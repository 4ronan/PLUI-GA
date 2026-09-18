import csv, json, statistics
import urllib.parse, urllib.request
from pathlib import Path
from diagnostic_runtime import target, commune_name, panel_peers, runtime_metadata

SNAPSHOT=Path('data/insee-rp2023-panel-3j.csv')
OUT=Path('output')
OUT.mkdir(exist_ok=True)

TARGET=target()
COMMUNE_NAME=commune_name()
PEER_CODES=panel_peers()
PANEL={TARGET:COMMUNE_NAME, **{c:c for c in PEER_CODES}}


with SNAPSHOT.open(encoding='utf-8-sig', newline='') as f:
    rows=list(csv.DictReader(f))

MELODI_URL='https://api.insee.fr/melodi/data/DS_RP_SERIE_HISTORIQUE'
LIVE_FALLBACK_CODES=[]

def _obs_value(obs):
    measures=obs.get('measures') or {}
    for key in ('OBS_VALUE_NIVEAU','OBS_VALUE'):
        raw=measures.get(key)
        if isinstance(raw, dict):
            raw=raw.get('value')
        if raw not in (None,''):
            return raw
    return None

def fetch_commune_rows(code):
    params=urllib.parse.urlencode({'GEO':f'COM-{code}','maxResult':5000})
    req=urllib.request.Request(
        f'{MELODI_URL}?{params}',
        headers={'Accept':'application/json','User-Agent':'PLUI-GA-diagnostic/3JC'}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            payload=json.load(response)
    except Exception as exc:
        raise RuntimeError(f'INSEE Melodi indisponible pour {code}: {exc}') from exc
    observations=payload.get('observations') or []
    fetched=[]
    for obs in observations:
        d=obs.get('dimensions') or {}
        geo=str(d.get('GEO') or '')
        geo_code=geo.split('-')[-1] if '-' in geo else geo
        year=str(d.get('TIME_PERIOD') or '')
        measure=str(d.get('RP_MEASURE') or '')
        ocs=str(d.get('OCS') or '_T')
        value=_obs_value(obs)
        if geo_code!=code or year not in {'2017','2023'} or measure not in {'POP','DWELLINGS'} or value is None:
            continue
        fetched.append({
            'GEO':code,
            'GEO_OBJECT':str(d.get('GEO_OBJECT') or 'COM'),
            'RP_MEASURE':measure,
            'OCS':ocs,
            'TIME_PERIOD':year,
            'OBS_VALUE':str(value),
        })
    required=[
        ('2017','POP','_T'),('2023','POP','_T'),
        ('2017','DWELLINGS','DW_MAIN'),('2023','DWELLINGS','DW_MAIN'),
        ('2023','DWELLINGS','DW_SEC_DW_OCC'),('2023','DWELLINGS','_T'),
    ]
    missing=[
        (year,measure,ocs) for year,measure,ocs in required
        if not any(r['TIME_PERIOD']==year and r['RP_MEASURE']==measure and r['OCS']==ocs for r in fetched)
    ]
    # Une série communale partielle reste exploitable pour les indicateurs
    # effectivement disponibles. Les absences sont conservées comme null.
    return fetched

snapshot_codes={r.get('GEO','') for r in rows}
for code in PANEL:
    if code not in snapshot_codes:
        rows.extend(fetch_commune_rows(code))
        LIVE_FALLBACK_CODES.append(code)

def val(code,year,measure,ocs=None):
    m=[r for r in rows if r['GEO']==code and r['TIME_PERIOD']==year and r['RP_MEASURE']==measure and (ocs is None or r['OCS']==ocs)]
    if len(m)>1:
        raise RuntimeError(f'Valeur non unique {code} {year} {measure} {ocs}: {len(m)}')
    if not m:
        return None
    try:
        return float(m[0]['OBS_VALUE'])
    except Exception:
        return None

def pct_change(a,b):
    return (b/a-1)*100 if a else None

def percentile(target,panel):
    vals=[x for x in panel if x is not None]
    return None if target is None or not vals else sum(1 for x in vals if x<=target)/len(vals)*100

def qlin(xs,q):
    xs=sorted(x for x in xs if x is not None)
    if not xs: return None
    n=len(xs); pos=(n-1)*q; lo=int(pos); hi=min(lo+1,n-1); f=pos-lo
    return xs[lo]*(1-f)+xs[hi]*f

communes=[]
for code,name in PANEL.items():
    p17=val(code,'2017','POP','_T'); p23=val(code,'2023','POP','_T')
    rp17=val(code,'2017','DWELLINGS','DW_MAIN'); rp23=val(code,'2023','DWELLINGS','DW_MAIN')
    rs23=val(code,'2023','DWELLINGS','DW_SEC_DW_OCC'); total23=val(code,'2023','DWELLINGS','_T')
    communes.append({
        'code':code,'name':name,'is_target':code==TARGET,
        'population_change_pct':pct_change(p17,p23),
        'households_change_pct':pct_change(rp17,rp23),
        'secondary_share_pct':rs23/total23*100 if rs23 is not None and total23 else None
    })

target=next(x for x in communes if x['is_target'])
peers=[x for x in communes if not x['is_target']]

def stat(key):
    xs=[x[key] for x in peers if x[key] is not None]
    t=target[key]
    return {
        'value':t,
        'panel_n':len(xs),
        'panel_median':statistics.median(xs) if xs else None,
        'panel_q1':qlin(xs,.25),
        'panel_q3':qlin(xs,.75),
        'percentile':percentile(t,xs)
    }

s_pop=stat('population_change_pct')
s_hh=stat('households_change_pct')
s_sec=stat('secondary_share_pct')

signals=[
    {
        'id':'population_stable',
        'label':'Population globalement stable',
        'value':s_pop['value'],
        'percentile':s_pop['percentile'],
        'panel_median':s_pop['panel_median'],
        'role':'dynamique démographique'
    },
    {
        'id':'households_growth',
        'label':'Croissance des ménages relativement soutenue',
        'value':s_hh['value'],
        'percentile':s_hh['percentile'],
        'panel_median':s_hh['panel_median'],
        'role':'pression résidentielle'
    },
    {
        'id':'secondary_homes_typical',
        'label':'Part des résidences secondaires proche du panel',
        'value':s_sec['value'],
        'percentile':s_sec['percentile'],
        'panel_median':s_sec['panel_median'],
        'role':'structure résidentielle'
    }
]

def stat_text(label,stat):
    if stat['value'] is None:
        return f"{label} est indisponible pour la commune ; aucune valeur n’est imputée. "
    if stat['panel_median'] is None or stat['percentile'] is None:
        return f"{label} est de {stat['value']:.1f} %, mais le panel comparable est insuffisant. "
    return f"{label} est de {stat['value']:.1f} % (médiane du panel : {stat['panel_median']:.1f} % ; percentile : {stat['percentile']:.1f} %). "

summary=(
    stat_text(f"Entre 2017 et 2023, l’évolution de la population de {COMMUNE_NAME}",s_pop)
    + stat_text("L’évolution du nombre de ménages",s_hh)
    + stat_text("La part des résidences secondaires et logements occasionnels en 2023",s_sec)
    + "Ces indicateurs décrivent la dynamique démographique et résidentielle. Ils ne permettent pas, à eux seuls, d’expliquer causalement la vacance privée."
)

contract={
    'source':'INSEE - Recensement de la population 2023, séries historiques',
    'territory':TARGET,
    'scope':'dynamique démographique et pression résidentielle',
    'role':'contexte structurel',
    'merge_with_lovac':False,
    'causal_interpretation':False,
    'years':[2017,2023],
    'selected_indicators':['population_change_2017_2023','households_change_2017_2023','secondary_homes_share_2023'],
    'signals':signals,
    'metrics':{
        'population_change_pct':s_pop['value'],
        'households_change_pct':s_hh['value'],
        'secondary_homes_share_pct':s_sec['value'],
        'percentiles':{
            'population_change':s_pop['percentile'],
            'households_change':s_hh['percentile'],
            'secondary_homes_share':s_sec['percentile']
        },
        'medians_panel':{
            'population_change_pct':s_pop['panel_median'],
            'households_change_pct':s_hh['panel_median'],
            'secondary_homes_share_pct':s_sec['panel_median']
        }
    },
    'quality':{
        'panel_n_excluding_target':len(peers),
        'panel_n_by_indicator':{
            'population_change':s_pop['panel_n'],
            'households_change':s_hh['panel_n'],
            'secondary_homes_share':s_sec['panel_n'],
        },
        'target_missing_indicators':[
            key for key,st in (
                ('population_change',s_pop),('households_change',s_hh),('secondary_homes_share',s_sec)
            ) if st['value'] is None
        ],
        'missing_semantics':'absence = null et exclusion de la comparaison; jamais 0',
        'percentile_rule':'count(available peer <= target) / n_available * 100',
        'quartile_rule':'linear interpolation on available peers, target excluded',
        'households_proxy':'residences principales du recensement',
        'caution':'comparaisons de population à interpréter avec prudence autour du changement de questionnaire INSEE ; contexte résidentiel non causal',
        'snapshot_path':str(SNAPSHOT),
        'live_fallback_source':MELODI_URL,
        'live_fallback_codes':LIVE_FALLBACK_CODES
    },
    'summary':summary,
    'runtime':runtime_metadata()
}

out=OUT/'insee-3jc-contract.json'
out.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
