import csv, io, json, re, subprocess
from pathlib import Path

DATASET_PAGE='https://www.data.gouv.fr/datasets/logements-vacants-du-parc-prive-par-commune-departement-region-france-de-2020-a-2026'
RESOURCE_URL='https://www.data.gouv.fr/api/1/datasets/r/2e0417b4-902d-4c60-90e7-bf5df148cb87'
TARGET='16015'

Path('tmp_3kb').mkdir(exist_ok=True)
raw_path=Path('tmp_3kb/lovac.csv')
subprocess.run(['curl','--fail','--location','--retry','4','--output',str(raw_path),RESOURCE_URL],check=True)
raw=raw_path.read_bytes()
text=None
encoding_used=None
for enc in ('utf-8-sig','cp1252','latin-1'):
    try:
        text=raw.decode(enc)
        encoding_used=enc
        break
    except UnicodeDecodeError:
        pass
if text is None:
    raise RuntimeError('Encodage LOVAC indétectable')

dialect=csv.Sniffer().sniff(text[:20000], delimiters=';,\t,')
rows=list(csv.DictReader(io.StringIO(text), dialect=dialect))
if not rows: raise RuntimeError('CSV LOVAC vide')
fields=list(rows[0].keys())

def norm(s): return re.sub(r'[^a-z0-9]+','', (s or '').lower())
code_candidates=[f for f in fields if norm(f) in {'codgeo','codecommune','com','insee','codeinsee','codgeo2026'}]
if not code_candidates: code_candidates=[f for f in fields if 'com' in norm(f) and ('code' in norm(f) or 'insee' in norm(f))]
if not code_candidates: raise RuntimeError(f'Champ code commune introuvable. Champs={fields}')
code_field=code_candidates[0]
matches=[r for r in rows if str(r.get(code_field,'')).strip()==TARGET]
if len(matches)!=1: raise RuntimeError(f'Angoulême non unique avec {code_field}: {len(matches)}')
r=matches[0]

def to_num(v):
    s=str(v or '').strip()
    if not s or s.lower() in {'s','secret','na','nan','null'}: return None
    s=s.replace('\u202f','').replace(' ','').replace(',','.')
    try: return float(s)
    except: return None

def year_of(f):
    m=re.search(r'(20(?:20|21|22|23|24|25|26))', f)
    return int(m.group(1)) if m else None

def family(f):
    n=norm(f)
    if any(k in n for k in ['plus2','plusde2','2ans','struct','filtre','fil']): return 'vacant_gt2y'
    if any(k in n for k in ['parcprive','nbpp','logpriv','prive']) and not any(k in n for k in ['vac','lv']): return 'private_stock'
    if any(k in n for k in ['vac','lv','exh']): return 'vacant_all'
    return None

classified={}
for f in fields:
    y=year_of(f); fam=family(f)
    if y and fam: classified.setdefault((fam,y),[]).append(f)

def get(fam,y):
    fs=classified.get((fam,y),[])
    if len(fs)!=1: return {'value':None,'status':'ambiguous_or_missing','fields':fs}
    v=to_num(r.get(fs[0]))
    return {'value':v,'status':'ok' if v is not None else 'secret_or_missing','field':fs[0]}

series={}
for y in range(2020,2027):
    stock=get('private_stock',y) if y<=2025 else {'value':None,'status':'not_available_by_design'}
    vac=get('vacant_all',y); gt2=get('vacant_gt2y',y)
    rate=gt2rate=None
    if y<=2025 and stock.get('value') not in (None,0):
        if vac.get('value') is not None: rate=vac['value']/stock['value']*100
        if gt2.get('value') is not None: gt2rate=gt2['value']/stock['value']*100
    short=(vac['value']-gt2['value']) if vac.get('value') is not None and gt2.get('value') is not None else None
    series[str(y)]={'private_stock':stock,'vacant_all':vac,'vacant_gt2y':gt2,'vacant_le2y_derived_count':short,'vacancy_rate_pct':rate,'structural_vacancy_rate_pct':gt2rate,'rate_status':'compatible_denominator' if y<=2025 and stock.get('value') not in (None,0) else ('counts_only_no_compatible_denominator' if y==2026 else 'unavailable')}

contract={'source':'LOVAC open data - Ministère de la Transition écologique','dataset_page':DATASET_PAGE,'resource_url':RESOURCE_URL,'territory':TARGET,'scope':'vacance du parc privé','role':'coeur_du_diagnostic','merge_with_other_vacancy_universes':False,'causal_interpretation':False,'code_field':code_field,'series':series,'selected_indicators':['private_vacancy_rate_latest_compatible','private_structural_vacancy_rate_latest_compatible','private_vacancy_counts_2026'],'metrics':{'latest_compatible_rate_year':2025,'vacancy_rate_pct':series['2025']['vacancy_rate_pct'],'structural_vacancy_rate_pct':series['2025']['structural_vacancy_rate_pct'],'vacant_all_count_2026':series['2026']['vacant_all']['value'],'vacant_gt2y_count_2026':series['2026']['vacant_gt2y']['value']},'quality':{'encoding_used':encoding_used,'secret_rule':'s/secret => null, jamais 0','rate_rule':'aucun taux 2026 sans dénominateur parc privé 2026 compatible','breaks_in_series':['GMBI autour de 2023','1767Biscom en 2025'],'short_vacancy_rule':'<=2 ans = vacants totaux - vacants >2 ans si les deux sont disponibles'},'schema_audit':{'fields':fields,'classified_fields':{f'{fam}_{y}':fs for (fam,y),fs in classified.items()}}}
if contract['metrics']['vacancy_rate_pct'] is None or contract['metrics']['structural_vacancy_rate_pct'] is None: raise RuntimeError('LOVAC 2025 non matérialisable avec le schéma détecté')
if contract['metrics']['vacant_all_count_2026'] is None or contract['metrics']['vacant_gt2y_count_2026'] is None: raise RuntimeError('LOVAC 2026 non matérialisable avec le schéma détecté')
Path('output').mkdir(exist_ok=True)
Path('output/lovac-3kb-contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
