import csv, json, statistics
from pathlib import Path

SOURCE_PAGE='https://www.insee.fr/fr/statistiques/9003931'
SNAPSHOT=Path('data/insee-rp2023-panel-3j.csv')
PANEL={
'16015':'Angoulême','47001':'Agen','19031':'Brive-la-Gaillarde','24037':'Bergerac','86066':'Châtellerault','16102':'Cognac','40088':'Dax','33243':'Libourne','47157':'Marmande','40192':'Mont-de-Marsan','79191':'Niort','24322':'Périgueux','17299':'Rochefort','17306':'Royan','17415':'Saintes','47323':'Villeneuve-sur-Lot'}

if not SNAPSHOT.exists():
    raise RuntimeError('Snapshot INSEE 3J absent')

with SNAPSHOT.open(encoding='utf-8-sig', newline='') as f:
    rows=list(csv.DictReader(f))

# Le snapshot est déjà réduit aux 16 communes, années 2017/2023, mesures POP/DWELLINGS.
ocs_codes=sorted({(r.get('OCS') or '').strip() for r in rows if (r.get('RP_MEASURE') or '').strip()=='DWELLINGS'})
expected={'DW_MAIN','DW_SEC_DW_OCC','DW_VAC','_T'}
if set(ocs_codes)!=expected:
    raise RuntimeError(f'Codes OCS inattendus: {ocs_codes}')

OCS_PR='DW_MAIN'
OCS_RS='DW_SEC_DW_OCC'
OCS_VAC='DW_VAC'
OCS_TOTAL='_T'

def val(code,year,measure,ocs=None):
    m=[r for r in rows if (r.get('GEO') or '').strip()==code and (r.get('TIME_PERIOD') or '').strip()==year and (r.get('RP_MEASURE') or '').strip()==measure and (ocs is None or (r.get('OCS') or '').strip()==ocs)]
    if len(m)!=1:
        raise RuntimeError(f'Valeur non unique {code} {year} {measure} {ocs}: {len(m)}')
    return float((m[0].get('OBS_VALUE') or '').replace(',','.'))

def pct_change(a,b):
    return (b/a-1)*100 if a else None

def percentile(target,panel):
    return sum(1 for x in panel if x<=target)/len(panel)*100

def quantile_linear(xs,q):
    xs=sorted(xs); n=len(xs); pos=(n-1)*q; lo=int(pos); hi=min(lo+1,n-1); f=pos-lo
    return xs[lo]*(1-f)+xs[hi]*f

communes=[]
for code,name in PANEL.items():
    p17=val(code,'2017','POP')
    p23=val(code,'2023','POP')
    rp17=val(code,'2017','DWELLINGS',OCS_PR)
    rp23=val(code,'2023','DWELLINGS',OCS_PR)
    rs23=val(code,'2023','DWELLINGS',OCS_RS)
    tot23=val(code,'2023','DWELLINGS',OCS_TOTAL)
    vac23=val(code,'2023','DWELLINGS',OCS_VAC)
    diff=abs((rp23+rs23+vac23)-tot23)
    if diff>0.01:
        raise RuntimeError(f'Identité parc incohérente {code}: écart {diff}')
    communes.append({
        'code':code,'name':name,'is_target':code=='16015',
        'population_2017':p17,'population_2023':p23,
        'evol_population_2017_2023_pct':pct_change(p17,p23),
        'menages_2017':rp17,'menages_2023':rp23,
        'evol_menages_2017_2023_pct':pct_change(rp17,rp23),
        'res_secondaires_2023':rs23,'logements_total_2023':tot23,
        'part_res_secondaires_2023_pct':rs23/tot23*100 if tot23 else None
    })

target=next(x for x in communes if x['is_target'])
peers=[x for x in communes if not x['is_target']]
metrics=['evol_population_2017_2023_pct','evol_menages_2017_2023_pct','part_res_secondaires_2023_pct']
stats={}
for m in metrics:
    xs=[x[m] for x in peers]
    t=target[m]
    stats[m]={
        'target':t,'panel_min':min(xs),'panel_q1':quantile_linear(xs,.25),
        'panel_median':statistics.median(xs),'panel_q3':quantile_linear(xs,.75),
        'panel_max':max(xs),'percentile_empirique':percentile(t,xs),'panel_n':len(xs)
    }

result={
    'ok':True,'stage':'3J-B','source_page':SOURCE_PAGE,
    'snapshot_file':str(SNAPSHOT),'years':['2017','2023'],
    'resolved_ocs':{'principal':OCS_PR,'secondary_or_occasional':OCS_RS,'vacant':OCS_VAC,'total':OCS_TOTAL},
    'communes':communes,'panel_stats':stats,
    'method_note':"Ménages = nombre de résidences principales : au recensement, un ménage correspond à une résidence principale occupée. Les évolutions 2017-2023 sont descriptives. La prudence INSEE autour du changement de questionnaire est rappelée pour la population. La part de résidences secondaires/logements occasionnels est un contexte résidentiel, pas une mesure de vacance."
}
Path('output').mkdir(exist_ok=True)
out=Path('output/insee-3jb-panel.json')
out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))