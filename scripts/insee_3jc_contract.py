import csv, json, statistics
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

def val(code,year,measure,ocs=None):
    m=[r for r in rows if r['GEO']==code and r['TIME_PERIOD']==year and r['RP_MEASURE']==measure and (ocs is None or r['OCS']==ocs)]
    if len(m)!=1:
        raise RuntimeError(f'Valeur non unique {code} {year} {measure} {ocs}: {len(m)}')
    return float(m[0]['OBS_VALUE'])

def pct_change(a,b):
    return (b/a-1)*100 if a else None

def percentile(target,panel):
    return sum(1 for x in panel if x<=target)/len(panel)*100

def qlin(xs,q):
    xs=sorted(xs); n=len(xs); pos=(n-1)*q; lo=int(pos); hi=min(lo+1,n-1); f=pos-lo
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
        'secondary_share_pct':rs23/total23*100 if total23 else None
    })

target=next(x for x in communes if x['is_target'])
peers=[x for x in communes if not x['is_target']]

def stat(key):
    xs=[x[key] for x in peers]; t=target[key]
    return {
        'value':t,
        'panel_median':statistics.median(xs),
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

summary=(
    f"Entre 2017 et 2023, la population de {COMMUNE_NAME} évolue de {s_pop['value']:.1f} % "
    f"(médiane du panel : {s_pop['panel_median']:.1f} % ; percentile : {s_pop['percentile']:.1f} %). "
    f"Le nombre de ménages progresse de {s_hh['value']:.1f} % "
    f"(médiane du panel : {s_hh['panel_median']:.1f} % ; percentile : {s_hh['percentile']:.1f} %). "
    f"Les résidences secondaires et logements occasionnels représentent {s_sec['value']:.1f} % du parc en 2023 "
    f"(médiane du panel : {s_sec['panel_median']:.1f} % ; percentile : {s_sec['percentile']:.1f} %). "
    "Ces indicateurs décrivent la dynamique démographique et résidentielle. Ils ne permettent pas, à eux seuls, d’expliquer causalement la vacance privée."
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
        'percentile_rule':f'count(panel <= target) / {len(peers)} * 100',
        'quartile_rule':f'linear interpolation on the {len(peers)} peers, target excluded',
        'households_proxy':'residences principales du recensement',
        'caution':'comparaisons de population à interpréter avec prudence autour du changement de questionnaire INSEE ; contexte résidentiel non causal'
    },
    'summary':summary,
    'runtime':runtime_metadata()
}

out=OUT/'insee-3jc-contract.json'
out.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
