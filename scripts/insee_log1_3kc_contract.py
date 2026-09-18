import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode
from diagnostic_runtime import target, runtime_metadata

DATASET='DS_RP_TD_LOGEMENT_CARACT_PRINC'
TARGET=target()
YEAR='2023'
BASE='https://api.insee.fr/melodi'
DATA_URL=f'{BASE}/data/{DATASET}?{urlencode({"GEO":f"COM-{TARGET}","TIME_PERIOD":YEAR,"maxResult":5000})}'
OUT=Path('output/insee-log1-3kc-contract.json')
TMP=Path('tmp_3kc_contract')
TMP.mkdir(exist_ok=True)

PERIODS=[
 ('Y_LT1919','Avant 1919'),
 ('Y1919T1945','1919-1945'),
 ('Y1946T1970','1946-1970'),
 ('Y1971T1990','1971-1990'),
 ('Y1991T2005','1991-2005'),
 ('Y2006TAAAA','2006-2020'),
]
TYPES=[('1','Maison'),('2','Appartement'),('3T6','Autres logements')]
OTHER_DIMS=['dimensions.LIFT','dimensions.L_STAY','dimensions.NOC','dimensions.NOR','dimensions.TSH']

def fetch_json(url):
    p=TMP/'data.json'
    subprocess.run(['curl','--http1.1','--fail','--location','--show-error','--silent','--retry','4','--retry-all-errors','--retry-delay','2','--connect-timeout','20','--max-time','180','--header','Accept: application/json','--output',str(p),url],check=True)
    return json.loads(p.read_text(encoding='utf-8-sig'))

def lists_of_dicts(obj,path='$'):
    found=[]
    if isinstance(obj,list):
        if obj and all(isinstance(x,dict) for x in obj): found.append((path,obj))
        for i,v in enumerate(obj[:50]): found.extend(lists_of_dicts(v,f'{path}[{i}]'))
    elif isinstance(obj,dict):
        for k,v in obj.items(): found.extend(lists_of_dicts(v,f'{path}.{k}'))
    return found

def flatten_leafs(obj,prefix=''):
    out={}
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=f'{prefix}.{k}' if prefix else k
            if isinstance(v,dict): out.update(flatten_leafs(v,key))
            elif not isinstance(v,list): out[key]=v
    return out

def find_rows(payload):
    cands=lists_of_dicts(payload)
    if not cands: return None,[]
    def score(item):
        path,rows=item
        flat=[flatten_leafs(r) for r in rows[:10]]
        keys=set(k for r in flat for k in r)
        markers={'dimensions.GEO','dimensions.TIME_PERIOD','dimensions.OCS','measures.OBS_VALUE_NIVEAU.value'}
        return (len(keys&markers),len(rows))
    path,rows=max(cands,key=score)
    return path,[flatten_leafs(r) for r in rows]

def value(row):
    v=row.get('measures.OBS_VALUE_NIVEAU.value')
    return None if v is None else float(v)

def match_base(r):
    return (
      r.get('dimensions.GEO') in (TARGET,f'2026-COM-{TARGET}') and
      str(r.get('dimensions.TIME_PERIOD'))==YEAR and
      r.get('dimensions.RP_MEASURE')=='DWELLINGS' and
      r.get('dimensions.OCS')=='DW_VAC'
    )

def all_other_total(r):
    return all(r.get(d)=='_T' for d in OTHER_DIMS)

def select_exact(rows, *, build_end, tdw):
    matches=[r for r in rows if match_base(r) and all_other_total(r) and r.get('dimensions.BUILD_END')==build_end and r.get('dimensions.TDW')==tdw]
    if len(matches)!=1:
        diag=[{k:r.get(k) for k in ['dimensions.BUILD_END','dimensions.TDW',*OTHER_DIMS]} for r in rows if match_base(r) and all_other_total(r)][:30]
        raise RuntimeError(f'Attendu 1 ligne BUILD_END={build_end}, TDW={tdw}, trouvé {len(matches)}; candidats={diag}')
    return value(matches[0])

payload=fetch_json(DATA_URL)
row_path,rows=find_rows(payload)
if not rows: raise RuntimeError('Aucune observation Melodi')

# LOG1 2023 porte sur les logements construits avant 2021. Dans Melodi,
# l'agrégat de cette population est codé BUILD_END=Y_LT2021 (et non _T).
# Les profils par période et par type sont donc reconstruits dans ce même univers.
by_period=[]
for code,label in PERIODS:
    v=select_exact(rows,build_end=code,tdw='_T')
    by_period.append({'code':code,'label':label,'value':v})

by_type=[]
for code,label in TYPES:
    v=select_exact(rows,build_end='Y_LT2021',tdw=code)
    by_type.append({'code':code,'label':label,'value':v})

period_sum=sum(x['value'] for x in by_period if x['value'] is not None)
type_sum=sum(x['value'] for x in by_type if x['value'] is not None)

# Contrôle supplémentaire sur l'agrégat publié, lorsqu'il existe.
try:
    published_total=select_exact(rows,build_end='Y_LT2021',tdw='_T')
except RuntimeError:
    published_total=None

total=published_total if published_total is not None else period_sum
for x in by_period:
    x['share_pct']=None if total in (None,0) else x['value']/total*100
for x in by_type:
    x['share_pct']=None if total in (None,0) else x['value']/total*100

period_delta=period_sum-total
type_delta=type_sum-total
contract={
 'source':'Insee RP2023 - DS_RP_TD_LOGEMENT_CARACT_PRINC',
 'dataset':DATASET,
 'territory':TARGET,
 'year':2023,
 'scope':'profil des logements vacants au recensement',
 'role':'caractéristiques du parc vacant',
 'merge_with_lovac':False,
 'causal_interpretation':False,
 'query':{'url':DATA_URL,'rows_path':row_path,'local_query_only':True},
 'universe':{
   'occupancy_code':'DW_VAC',
   'measure':'DWELLINGS',
   'construction_universe_code':'Y_LT2021',
   'label':'Logements vacants INSEE construits avant 2021',
   'note':'Profil issu du recensement de la population 2023. Il ne correspond pas au champ LOVAC du parc privé et ne permet pas d’identifier la vacance de plus de 2 ans.'
 },
 'metrics':{
   'vacant_total':total,
   'published_total':published_total,
   'by_construction_period':by_period,
   'by_dwelling_type':by_type,
 },
 'runtime':runtime_metadata(),
 'quality':{
   'construction_codes':[c for c,_ in PERIODS],
   'dwelling_type_codes':[c for c,_ in TYPES],
   'nor_excluded':True,
   'nor_rule':'La dimension NOR n’est pas utilisée pour caractériser les logements vacants.',
   'period_sum':period_sum,
   'type_sum':type_sum,
   'period_sum_delta_vs_total':period_delta,
   'type_sum_delta_vs_total':type_delta,
   'tolerance_abs':0.05,
   'status':'ok' if abs(period_delta)<=0.05 and abs(type_delta)<=0.05 else 'inconsistent'
 }
}
if contract['quality']['status']!='ok':
    raise RuntimeError(json.dumps(contract['quality'],ensure_ascii=False))
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
