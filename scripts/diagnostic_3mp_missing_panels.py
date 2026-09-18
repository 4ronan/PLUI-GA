import csv, io, json, math, statistics, subprocess, re
import urllib.parse, urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlencode
from diagnostic_runtime import target, commune_name, panel_peers, department_code, runtime_metadata

TARGET=target()
COMMUNE_NAME=commune_name()
PEERS=panel_peers()
PANEL={TARGET:COMMUNE_NAME, **{c:c for c in PEERS}}
OUT=Path('output/diagnostic-3mp-panels.json')
TMP=Path('tmp_3mp_panels'); TMP.mkdir(exist_ok=True)

LOVAC_URL='https://www.data.gouv.fr/api/1/datasets/r/2e0417b4-902d-4c60-90e7-bf5df148cb87'
DVF_BASE='https://files.data.gouv.fr/geo-dvf/latest/csv/2025/communes'
SITADEL_RID='9c90a880-4ba0-49b4-b99d-d7dd6c810dd0'
SITADEL_BASE='https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1'
LOG1_DATASET='DS_RP_TD_LOGEMENT_CARACT_PRINC'
LOG1_BASE='https://api.insee.fr/melodi/data'
POP_SNAPSHOT=Path('data/insee-rp2023-panel-3j.csv')


def curl(url,path):
    subprocess.run(['curl','--http1.1','--fail','--location','--show-error','--silent','--retry','5','--retry-all-errors','--retry-delay','2','--connect-timeout','30','--max-time','180','--output',str(path),url],check=True)


def num(v):
    if v is None: return None
    s=str(v).strip().replace('\u202f','').replace(' ','').replace(',','.')
    if not s or s.lower() in {'s','secret','na','nan','null'}: return None
    try:
        x=float(s); return x if math.isfinite(x) else None
    except Exception: return None


def percentile(t,xs):
    vals=[x for x in xs if x is not None]
    return None if t is None or not vals else sum(1 for x in vals if x<=t)/len(vals)*100


def qlin(xs,q):
    vals=sorted(x for x in xs if x is not None)
    if not vals: return None
    pos=(len(vals)-1)*q; lo=int(pos); hi=min(lo+1,len(vals)-1); f=pos-lo
    return vals[lo]*(1-f)+vals[hi]*f


def stats(rows,key):
    t=next(r[key] for r in rows if r['code']==TARGET)
    peers=[r[key] for r in rows if r['code']!=TARGET and r[key] is not None]
    return {
        'target':t,
        'panel_n':len(peers),
        'panel_median':statistics.median(peers) if peers else None,
        'panel_q1':qlin(peers,.25),
        'panel_q3':qlin(peers,.75),
        'percentile':percentile(t,peers)
    }

# Population 2023, utilisée uniquement pour normaliser Sitadel sur un dénominateur commun.
# Le snapshot historique accélère le panel initial; une commune absente est récupérée
# ponctuellement via Melodi au lieu d'être rejetée.
with POP_SNAPSHOT.open(encoding='utf-8-sig',newline='') as f:
    poprows=list(csv.DictReader(f))

def melodi_population_2023(code):
    params=urllib.parse.urlencode({'GEO':f'COM-{code}','TIME_PERIOD':'2023','RP_MEASURE':'POP','maxResult':100})
    req=urllib.request.Request(
        f'https://api.insee.fr/melodi/data/DS_RP_SERIE_HISTORIQUE?{params}',
        headers={'Accept':'application/json','User-Agent':'PLUI-GA-diagnostic/3MP'}
    )
    with urllib.request.urlopen(req,timeout=60) as response:
        payload=json.load(response)
    vals=[]
    for obs in payload.get('observations') or []:
        d=obs.get('dimensions') or {}
        geo=str(d.get('GEO') or '')
        geo_code=geo.split('-')[-1] if '-' in geo else geo
        if geo_code!=code or str(d.get('TIME_PERIOD'))!='2023' or str(d.get('RP_MEASURE'))!='POP':
            continue
        if str(d.get('OCS') or '_T')!='_T':
            continue
        measures=obs.get('measures') or {}
        raw=measures.get('OBS_VALUE_NIVEAU',measures.get('OBS_VALUE'))
        if isinstance(raw,dict): raw=raw.get('value')
        v=num(raw)
        if v is not None: vals.append(v)
    if len(vals)!=1:
        raise RuntimeError(f'Population 2023 Melodi non unique {code}: {len(vals)}')
    return vals[0]

pop2023={}
for code in PANEL:
    m=[r for r in poprows if r['GEO']==code and r['TIME_PERIOD']=='2023' and r['RP_MEASURE']=='POP' and r['OCS']=='_T']
    if len(m)==1:
        pop2023[code]=float(m[0]['OBS_VALUE'])
    elif len(m)==0:
        pop2023[code]=melodi_population_2023(code)
    else:
        raise RuntimeError(f'Population 2023 non unique {code}: {len(m)}')

# 1. LOVAC : même fichier national, même millésime et même dénominateur pour les 16 communes.
lp=TMP/'lovac.csv'; curl(LOVAC_URL,lp); raw=lp.read_bytes()
text=None
for enc in ('utf-8-sig','cp1252','latin-1'):
    try: text=raw.decode(enc); break
    except UnicodeDecodeError: pass
if text is None: raise RuntimeError('LOVAC encodage')
dialect=csv.Sniffer().sniff(text[:20000],delimiters=';,\t,')
lrows=list(csv.DictReader(io.StringIO(text),dialect=dialect))
lookup={str(r.get('CODGEO_26','')).strip():r for r in lrows}
lovac=[]
for code,name in PANEL.items():
    r=lookup.get(code)
    if not r: raise RuntimeError(f'LOVAC commune absente {code}')
    stock=num(r.get('ff_pp_total_25')); vac=num(r.get('pp_vacant_25')); gt2=num(r.get('pp_vacant_plus_2ans_25'))
    if stock in (None,0) or vac is None or gt2 is None: raise RuntimeError(f'LOVAC 2025 incomplet {code}')
    lovac.append({'code':code,'name':name,'vacancy_rate_pct':vac/stock*100,'structural_vacancy_rate_pct':gt2/stock*100})

# 2. DVF 2025 : prix médian au m² des ventes résidentielles simples, même méthode que 3K-D.
def dvf_summary(code):
    dep=department_code(code)
    p=TMP/f'dvf-{code}.csv'; curl(f'{DVF_BASE}/{dep}/{code}.csv',p)
    groups=defaultdict(list)
    with p.open(encoding='utf-8-sig',newline='') as f:
        rd=csv.DictReader(f)
        for r in rd:
            if str(r.get('code_commune','')).strip()==code and str(r.get('id_mutation','')).strip():
                groups[str(r['id_mutation']).strip()].append(r)
    simple=[]; residential=0
    for mid,rows in groups.items():
        if 'Vente' not in {str(r.get('nature_mutation','')).strip() for r in rows}: continue
        res=[]; seen=set()
        for r in rows:
            typ=str(r.get('code_type_local','')).strip()
            if typ not in {'1','2'}: continue
            lid=str(r.get('id_local') or '').strip()
            key=lid if lid else ('row',str(r.get('adresse_numero','')),str(r.get('adresse_nom_voie','')),str(r.get('surface_reelle_bati','')),typ)
            if key in seen: continue
            seen.add(key); res.append(r)
        if not res: continue
        vals=[num(r.get('valeur_fonciere')) for r in rows]; vals=[x for x in vals if x and x>0]
        if not vals: continue
        residential+=1
        if len(res)!=1: continue
        area=num(res[0].get('surface_reelle_bati'))
        if area and area>0: simple.append(vals[0]/area)
    return residential, (statistics.median(simple) if simple else None), len(simple)

dvf=[]
for code,name in PANEL.items():
    try:
        n,med,ns=dvf_summary(code)
    except Exception:
        n,med,ns=0,None,0
    dvf.append({'code':code,'name':name,'residential_sale_mutations_n':n,'simple_sales_n':ns,'median_price_m2_eur_simple':med})

# 3. Sitadel : années fixes pour rendre les comparaisons homogènes.
def rows_from_payload(payload):
    if isinstance(payload,list): return [r for r in payload if isinstance(r,dict)]
    if isinstance(payload,dict):
        for k in ('data','results','records','observations'):
            v=payload.get(k)
            if isinstance(v,list): return [r for r in v if isinstance(r,dict)]
    raise RuntimeError('Sitadel structure inconnue')

sitadel=[]
for code,name in PANEL.items():
    p=TMP/f'sitadel-{code}.json'; curl(f'{SITADEL_BASE}/datafiles/{SITADEL_RID}/json?COMM=eq:{code}',p)
    rr=rows_from_payload(json.loads(p.read_text(encoding='utf-8-sig')))
    totals=[r for r in rr if str(r.get('COMM'))==code and str(r.get('TYPE_LGT'))=='Tous Logements']
    def exact(year,field):
        m=[r for r in totals if int(r['ANNEE'])==year]
        if len(m)!=1: return None
        return num(m[0].get(field))
    aut25=exact(2025,'LOG_AUT'); com24=exact(2024,'LOG_COM'); pop=pop2023[code]
    sitadel.append({
        'code':code,'name':name,
        'authorized_2025_n':aut25,
        'authorized_2025_per_1000_pop2023':(aut25/pop*1000 if aut25 is not None and pop>0 else None),
        'started_2024_n':com24,
        'started_2024_per_1000_pop2023':(com24/pop*1000 if com24 is not None and pop>0 else None)
    })

# 4. LOG1 : profil des logements vacants comparé entre communes du même panel.
def flatten(obj,prefix=''):
    out={}
    if isinstance(obj,dict):
        for k,v in obj.items():
            kk=f'{prefix}.{k}' if prefix else k
            if isinstance(v,dict): out.update(flatten(v,kk))
            elif not isinstance(v,list): out[kk]=v
    return out

def listdicts(obj):
    found=[]
    if isinstance(obj,list):
        if obj and all(isinstance(x,dict) for x in obj): found.append(obj)
        for v in obj[:50]: found.extend(listdicts(v))
    elif isinstance(obj,dict):
        for v in obj.values(): found.extend(listdicts(v))
    return found

def log1_profile(code):
    url=f'{LOG1_BASE}/{LOG1_DATASET}?{urlencode({"GEO":f"COM-{code}","TIME_PERIOD":"2023","maxResult":5000})}'
    p=TMP/f'log1-{code}.json'; curl(url,p); payload=json.loads(p.read_text(encoding='utf-8-sig'))
    cands=listdicts(payload)
    if not cands: raise RuntimeError(f'LOG1 aucune observation {code}')
    def score(rows):
        fs=[flatten(r) for r in rows[:10]]; keys={k for r in fs for k in r}
        return (len(keys & {'dimensions.GEO','dimensions.TIME_PERIOD','dimensions.OCS','measures.OBS_VALUE_NIVEAU.value'}),len(rows))
    rows=[flatten(r) for r in max(cands,key=score)]
    def val(build,tdw):
        m=[]
        for r in rows:
            geo=str(r.get('dimensions.GEO',''))
            if geo not in {code,f'2026-COM-{code}'}: continue
            if str(r.get('dimensions.TIME_PERIOD'))!='2023' or r.get('dimensions.RP_MEASURE')!='DWELLINGS' or r.get('dimensions.OCS')!='DW_VAC': continue
            if r.get('dimensions.BUILD_END')!=build or r.get('dimensions.TDW')!=tdw: continue
            if not all(r.get(d)=='_T' for d in ['dimensions.LIFT','dimensions.L_STAY','dimensions.NOC','dimensions.NOR','dimensions.TSH']): continue
            m.append(r)
        if len(m)!=1: raise RuntimeError(f'LOG1 select {code} {build} {tdw}: {len(m)}')
        return num(m[0].get('measures.OBS_VALUE_NIVEAU.value'))
    total=val('Y_LT2021','_T'); apt=val('Y_LT2021','2'); p1=val('Y1946T1970','_T'); p2=val('Y1971T1990','_T')
    if total in (None,0) or None in (apt,p1,p2): raise RuntimeError(f'LOG1 incomplet {code}')
    return apt/total*100,(p1+p2)/total*100

log1=[]
for code,name in PANEL.items():
    apt,mid=log1_profile(code)
    log1.append({'code':code,'name':name,'vacant_apartment_share_pct':apt,'vacant_1946_1990_share_pct':mid})

blocks={
 'lovac':{'year':2025,'rows':lovac,'stats':{'vacancy_rate_pct':stats(lovac,'vacancy_rate_pct'),'structural_vacancy_rate_pct':stats(lovac,'structural_vacancy_rate_pct')},'limit':'Comparaison du parc privé LOVAC sur un même millésime; ne pas fusionner avec les univers INSEE ou RPLS.'},
 'dvf':{'year':2025,'rows':dvf,'stats':{'median_price_m2_eur_simple':stats(dvf,'median_price_m2_eur_simple')},'limit':'Le prix médian DVF décrit les mutations simples observées; le volume brut de mutations est conservé à titre descriptif mais non utilisé comme facteur discriminant sans normalisation dédiée.'},
 'sitadel':{'years':{'authorized':2025,'started':2024,'population_denominator':2023},'rows':sitadel,'stats':{'authorized_2025_per_1000_pop2023':stats(sitadel,'authorized_2025_per_1000_pop2023'),'started_2024_per_1000_pop2023':stats(sitadel,'started_2024_per_1000_pop2023')},'limit':'Séries communales non estimées; normalisation par population 2023 uniquement pour comparer des intensités de construction, sans causalité.'},
 'insee_log1_vacant_profile':{'year':2023,'rows':log1,'stats':{'vacant_apartment_share_pct':stats(log1,'vacant_apartment_share_pct'),'vacant_1946_1990_share_pct':stats(log1,'vacant_1946_1990_share_pct')},'limit':'Comparaison du profil des logements vacants entre communes. Elle ne mesure pas une surreprésentation par rapport au parc occupé local; cette dernière exige un dénominateur de référence construit sur le même univers.'}
}

all_stats=[s for b in blocks.values() for s in b['stats'].values()]
quality={
 'panel_codes':list(PANEL),
 'target_excluded_from_reference':True,
 'reference_n':len(PEERS),
 'same_panel_as_filosofi_demography_rpls':True,
 'percentile_rule':f'count(peer <= target) / {len(PEERS)} * 100',
 'all_panel_stats_complete':all(s['panel_n']==len(PEERS) for s in all_stats),
 'partial_panel_stats':[k for k,b in blocks.items() for k2,s in b['stats'].items() if s['panel_n']<len(PEERS) for k in [f'{k}.{k2}']],
 'missing_semantics':'absence/secret = null ou exclusion; jamais 0',
 'causal_claims_included':False,
 'status':'ok' if all(s['panel_n']==len(PEERS) for s in all_stats) else 'partial'
}
out={'stage':'3M-P','territory':TARGET,'runtime':runtime_metadata(),'purpose':'matérialiser les panels manquants avant extension de la détection des facteurs discriminants','blocks':blocks,'quality':quality}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'quality':quality,'target_stats':{k:v['stats'] for k,v in blocks.items()}},ensure_ascii=False,indent=2))
