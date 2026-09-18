import json, subprocess
from pathlib import Path
from diagnostic_runtime import target, runtime_metadata

DATASET_ID='6513ee3a3b05e5cd969c270f'
RID='9c90a880-4ba0-49b4-b99d-d7dd6c810dd0'
TARGET=target()
BASE='https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1'
URL=f'{BASE}/datafiles/{RID}/json?COMM=eq:{TARGET}'
OUT=Path('output/sitadel-3ke-contract.json')
TMP=Path('tmp_3ke_contract')
TMP.mkdir(exist_ok=True)


def fetch_json(url):
    p=TMP/'sitadel.json'
    subprocess.run([
        'curl','--http1.1','--fail','--location','--show-error','--silent',
        '--retry','4','--retry-all-errors','--retry-delay','2',
        '--connect-timeout','20','--max-time','180',
        '--header','Accept: application/json','--output',str(p),url
    ],check=True)
    return json.loads(p.read_text(encoding='utf-8-sig'))


def rows_from_payload(payload):
    if isinstance(payload,list):
        return [r for r in payload if isinstance(r,dict)]
    if isinstance(payload,dict):
        for key in ('data','results','records','observations'):
            v=payload.get(key)
            if isinstance(v,list) and all(isinstance(x,dict) for x in v):
                return v
    raise RuntimeError('Structure JSON Sitadel non reconnue')


def norm(v):
    return None if v is None else v

payload=fetch_json(URL)
rows=rows_from_payload(payload)
required={'ANNEE','COMM','LOG_AUT','LOG_COM','SDP_AUT','SDP_COM','TYPE_LGT'}
if not rows:
    raise RuntimeError('Aucune ligne Sitadel')
missing=required-set(rows[0].keys())
if missing:
    raise RuntimeError(f'Colonnes Sitadel manquantes: {sorted(missing)}')
rows=[r for r in rows if str(r.get('COMM'))==TARGET]
if not rows:
    raise RuntimeError('Aucune ligne pour la commune cible')

total_rows=[]
by_type={}
for r in rows:
    year=int(r['ANNEE'])
    typ=str(r['TYPE_LGT'])
    item={
        'year':year,
        'authorized_dwellings':norm(r.get('LOG_AUT')),
        'started_dwellings':norm(r.get('LOG_COM')),
        'authorized_floor_area_m2':norm(r.get('SDP_AUT')),
        'started_floor_area_m2':norm(r.get('SDP_COM')),
    }
    if typ=='Tous Logements':
        total_rows.append(item)
    else:
        by_type.setdefault(str(year),{})[typ]=item

total_rows=sorted(total_rows,key=lambda x:x['year'])
years=[x['year'] for x in total_rows]
expected=list(range(2013,2026))
if years!=expected:
    raise RuntimeError(f'Millésimes inattendus: {years}')

latest_authorized=max((x for x in total_rows if x['authorized_dwellings'] is not None),key=lambda x:x['year'])
latest_started=max((x for x in total_rows if x['started_dwellings'] is not None),key=lambda x:x['year'])

# Contrôle de cohérence des sous-types seulement lorsque toutes les valeurs sont publiées.
reconciliation=[]
for t in total_rows:
    year=str(t['year'])
    types=by_type.get(year,{})
    vals_aut=[v['authorized_dwellings'] for v in types.values()]
    vals_com=[v['started_dwellings'] for v in types.values()]
    rec={
        'year':t['year'],
        'authorized_types_complete':len(vals_aut)==4 and all(v is not None for v in vals_aut),
        'started_types_complete':len(vals_com)==4 and all(v is not None for v in vals_com),
        'authorized_types_sum':sum(vals_aut) if len(vals_aut)==4 and all(v is not None for v in vals_aut) else None,
        'started_types_sum':sum(vals_com) if len(vals_com)==4 and all(v is not None for v in vals_com) else None,
        'authorized_total':t['authorized_dwellings'],
        'started_total':t['started_dwellings'],
    }
    rec['authorized_reconciles']=None if rec['authorized_types_sum'] is None or t['authorized_dwellings'] is None else rec['authorized_types_sum']==t['authorized_dwellings']
    rec['started_reconciles']=None if rec['started_types_sum'] is None or t['started_dwellings'] is None else rec['started_types_sum']==t['started_dwellings']
    reconciliation.append(rec)

bad=[r for r in reconciliation if r['authorized_reconciles'] is False or r['started_reconciles'] is False]
if bad:
    raise RuntimeError(f'Incohérence total/sous-types Sitadel: {bad}')

contract={
    'source':'SDES - Sitadel, logements autorisés et commencés, séries annuelles non estimées',
    'dataset_id':DATASET_ID,
    'datafile_rid':RID,
    'territory':TARGET,
    'scope':'dynamique de construction de logements',
    'role':'dynamique territoriale',
    'merge_with_lovac':False,
    'causal_interpretation':False,
    'query':{'url':URL,'local_query_only':True},
    'series':total_rows,
    'by_type':by_type,
    'selected_metrics':{
        'latest_authorized_year':latest_authorized['year'],
        'latest_authorized_dwellings':latest_authorized['authorized_dwellings'],
        'latest_started_year':latest_started['year'],
        'latest_started_dwellings':latest_started['started_dwellings'],
    },
    'method':{
        'type_filter_for_main_series':'TYPE_LGT = Tous Logements',
        'authorized_field':'LOG_AUT',
        'started_field':'LOG_COM',
        'floor_area_fields':['SDP_AUT','SDP_COM'],
        'warning':'Séries annuelles communales non estimées. Une valeur absente signifie indisponible et n’est jamais convertie en zéro. Les données récentes peuvent être incomplètes lorsque les déclarations ne sont pas encore toutes reçues.',
        'sitadel3_transition_note':'Le changement de système Sitadel2 vers Sitadel3 doit être traité comme une vigilance méthodologique pour les comparaisons temporelles récentes.'
    },
    'runtime':runtime_metadata(),
    'quality':{
        'years':years,
        'expected_years':expected,
        'reconciliation':reconciliation,
        'missing_semantics':'absence/null = indisponible, jamais 0',
        'latest_started_lags_latest_authorized':latest_started['year']<latest_authorized['year'],
        'status':'ok'
    }
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
