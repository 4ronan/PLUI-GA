import csv, io, json, subprocess, zipfile, statistics
from pathlib import Path

SOURCE_PAGE='https://www.insee.fr/fr/statistiques/9003931'
DATA_URL='https://api.insee.fr/melodi/file/DS_RP_SERIE_HISTORIQUE/DS_RP_SERIE_HISTORIQUE_2023_CSV_FR'
PANEL={
'16015':'Angoulême','47001':'Agen','19031':'Brive-la-Gaillarde','24037':'Bergerac','86066':'Châtellerault','16102':'Cognac','40088':'Dax','33243':'Libourne','47157':'Marmande','40192':'Mont-de-Marsan','79191':'Niort','24322':'Périgueux','17299':'Rochefort','17306':'Royan','17415':'Saintes','47323':'Villeneuve-sur-Lot'}
YEARS={'2017','2023'}
TMP=Path('tmp_3jb'); OUT=Path('output'); TMP.mkdir(exist_ok=True); OUT.mkdir(exist_ok=True)
raw=TMP/'rp_hist.zip'
subprocess.run(['curl','--fail','--location','--show-error','--silent','--retry','6','--retry-all-errors','--retry-delay','3','--connect-timeout','30','--max-time','600','--output',str(raw),DATA_URL],check=True)
if not zipfile.is_zipfile(raw): raise RuntimeError('Archive Melodi invalide')
with zipfile.ZipFile(raw) as z:
    files=[(n,z.getinfo(n).file_size) for n in z.namelist() if n.lower().endswith('.csv')]
    data_name=max([x for x in files if 'metadata' not in x[0].lower() and 'meta' not in x[0].lower()],key=lambda x:x[1])[0]
    meta_name=max([x for x in files if 'metadata' in x[0].lower() or 'meta' in x[0].lower()],key=lambda x:x[1])[0]
    data_text=z.read(data_name).decode('utf-8-sig')
    meta_text=z.read(meta_name).decode('utf-8-sig')

labels={}
for r in csv.DictReader(meta_text.splitlines(),delimiter=';'):
    cv=(r.get('COD_VAR') or '').strip(); cm=(r.get('COD_MOD') or '').strip(); lm=(r.get('LIB_MOD') or '').strip()
    if cv and cm: labels[(cv,cm)]=lm

rd=csv.DictReader(io.StringIO(data_text),delimiter=';')
rows=[]
for r in rd:
    if (r.get('GEO') or '').strip() not in PANEL: continue
    if (r.get('GEO_OBJECT') or '').strip()!='COM': continue
    if (r.get('TIME_PERIOD') or '').strip() not in YEARS: continue
    rows.append(r)

ocs_codes=sorted({(r.get('OCS') or '').strip() for r in rows if (r.get('RP_MEASURE') or '').strip()=='DWELLINGS'})
ocs_labels={c:labels.get(('OCS',c)) for c in ocs_codes}

def find_code(words):
    hits=[]
    for c,l in ocs_labels.items():
        text=(c+' '+(l or '')).lower()
        if all(w in text for w in words): hits.append(c)
    return hits

principal=find_code(['princip'])
secondary=[c for c,l in ocs_labels.items() if any(k in (c+' '+(l or '')).lower() for k in ['second','occasion'])]
vacant=find_code(['vac'])
all_codes=[c for c,l in ocs_labels.items() if any(k in (c+' '+(l or '')).lower() for k in ['ensemble','total','all'])]
if len(principal)!=1 or len(secondary)!=1:
    raise RuntimeError(f'OCS non identifiés de façon unique: labels={ocs_labels}, principal={principal}, secondary={secondary}')
OCS_PR=principal[0]; OCS_RS=secondary[0]

def val(code,year,measure,ocs=None):
    m=[r for r in rows if (r.get('GEO') or '').strip()==code and (r.get('TIME_PERIOD') or '').strip()==year and (r.get('RP_MEASURE') or '').strip()==measure and (ocs is None or (r.get('OCS') or '').strip()==ocs)]
    if len(m)!=1: raise RuntimeError(f'Valeur non unique {code} {year} {measure} {ocs}: {len(m)}')
    return float((m[0].get('OBS_VALUE') or '').replace(',','.'))

def total_dwellings(code,year):
    if len(all_codes)==1:
        return val(code,year,'DWELLINGS',all_codes[0])
    vals={c:val(code,year,'DWELLINGS',c) for c in ocs_codes}
    if len(vacant)==1:
        return vals[OCS_PR]+vals[OCS_RS]+vals[vacant[0]]
    return sum(vals.values())

def pct_change(a,b): return (b/a-1)*100 if a else None

def percentile(target,panel): return sum(1 for x in panel if x<=target)/len(panel)*100

def quantile_linear(xs,q):
    xs=sorted(xs); n=len(xs); pos=(n-1)*q; lo=int(pos); hi=min(lo+1,n-1); f=pos-lo
    return xs[lo]*(1-f)+xs[hi]*f

communes=[]
for code,name in PANEL.items():
    p17=val(code,'2017','POP'); p23=val(code,'2023','POP')
    rp17=val(code,'2017','DWELLINGS',OCS_PR); rp23=val(code,'2023','DWELLINGS',OCS_PR)
    rs23=val(code,'2023','DWELLINGS',OCS_RS); tot23=total_dwellings(code,'2023')
    communes.append({'code':code,'name':name,'is_target':code=='16015','population_2017':p17,'population_2023':p23,'evol_population_2017_2023_pct':pct_change(p17,p23),'menages_2017':rp17,'menages_2023':rp23,'evol_menages_2017_2023_pct':pct_change(rp17,rp23),'res_secondaires_2023':rs23,'logements_total_2023':tot23,'part_res_secondaires_2023_pct':rs23/tot23*100 if tot23 else None})

target=next(x for x in communes if x['is_target']); peers=[x for x in communes if not x['is_target']]
metrics=['evol_population_2017_2023_pct','evol_menages_2017_2023_pct','part_res_secondaires_2023_pct']
stats={}
for m in metrics:
    xs=[x[m] for x in peers]; t=target[m]
    stats[m]={'target':t,'panel_min':min(xs),'panel_q1':quantile_linear(xs,.25),'panel_median':statistics.median(xs),'panel_q3':quantile_linear(xs,.75),'panel_max':max(xs),'percentile_empirique':percentile(t,xs),'panel_n':len(xs)}

result={'ok':True,'stage':'3J-B','source_page':SOURCE_PAGE,'download_url':DATA_URL,'source_file':data_name,'years':['2017','2023'],'ocs_labels':ocs_labels,'resolved_ocs':{'principal':OCS_PR,'secondary_or_occasional':OCS_RS,'vacant':vacant[0] if len(vacant)==1 else None,'total':all_codes[0] if len(all_codes)==1 else None},'communes':communes,'panel_stats':stats,'method_note':"Ménages = nombre de résidences principales, relation usuelle du recensement : un ménage occupe une résidence principale. Les évolutions 2017-2023 sont descriptives. La prudence INSEE autour du changement de questionnaire est rappelée pour la population. La part de résidences secondaires/logements occasionnels est un contexte résidentiel, pas une mesure de vacance."}
out=OUT/'insee-3jb-panel.json'; out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(result,ensure_ascii=False,indent=2))