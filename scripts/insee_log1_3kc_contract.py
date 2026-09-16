import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode

DATASET='DS_RP_TD_LOGEMENT_CARACT_PRINC'
TARGET='16015'
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
CHAR_DIMS=['dimensions.BUILD_END','dimensions.LIFT','dimensions.L_STAY','dimensions.NOC','dimensions.NOR','dimensions.TDW','dimensions.TSH']

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

def select_one(rows, breakdown_dim=None, breakdown_value=None):
    matches=[]
    for r in rows:
        if not match_base(r): continue
        if breakdown_dim is not None and r.get(breakdown_dim)!=breakdown_value: continue
        ok=True
        for d in CHAR_DIMS:
            if d==breakdown_dim: continue
            if r.get(d)!='_T': ok=False; break
        if ok: matches.append(r)
    if len(matches)!=1:
        raise RuntimeError(f'Attendu 1 ligne pour {breakdown_dim}={breakdown_value}, trouvé {len(matches)}')
    return value(matches[0])

payload=fetch_json(DATA_URL)
row_path,rows=find_rows(payload)
if not rows: raise RuntimeError('Aucune observation Melodi')

total=select_one(rows)
by_period=[]
for code,label in PERIODS:
    v=select_one(rows,'dimensions.BUILD_END',code)
    by_period.append({'code':code,'label':label,'value':v,'share_pct':None if total in (None,0) else v/total*100})
by_type=[]
for code,label in TYPES:
    v=select_one(rows,'dimensions.TDW',code)
    by_type.append({'code':code,'label':label,'value':v,'share_pct':None if total in (None,0) else v/total*100})

period_sum=sum(x['value'] for x in by_period if x['value'] is not None)
type_sum=sum(x['value'] for x in by_type if x['value'] is not None)

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
   'label':'Logements vacants INSEE construits avant 2021',
   'note':'Profil issu du recensement de la population 2023. Il ne correspond pas au champ LOVAC du parc privé et ne permet pas d’identifier la vacance de plus de 2 ans.'
 },
 'metrics':{
   'vacant_total':total,
   'by_construction_period':by_period,
   'by_dwelling_type':by_type,
 },
 'quality':{
   'construction_codes':[c for c,_ in PERIODS],
   'dwelling_type_codes':[c for c,_ in TYPES],
   'nor_excluded':True,
   'nor_rule':'La dimension NOR concerne les résidences principales dans l’usage retenu ici et n’est pas utilisée pour caractériser les logements vacants.',
   'period_sum':period_sum,
   'type_sum':type_sum,
   'period_sum_delta_vs_total':period_sum-total,
   'type_sum_delta_vs_total':type_sum-total,
   'tolerance_abs':0.05,
   'status':'ok' if abs(period_sum-total)<=0.05 and abs(type_sum-total)<=0.05 else 'inconsistent'
 }
}
if contract['quality']['status']!='ok':
    raise RuntimeError(json.dumps(contract['quality'],ensure_ascii=False))
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
