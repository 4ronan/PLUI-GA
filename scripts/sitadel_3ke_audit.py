import json, subprocess
from pathlib import Path

RID='9c90a880-4ba0-49b4-b99d-d7dd6c810dd0'
TARGET='16015'
BASE='https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1'
URL=f'{BASE}/datafiles/{RID}/json?COMM=eq:{TARGET}'
OUT=Path('output/sitadel-3ke-audit.json')
TMP=Path('tmp_3ke')
TMP.mkdir(exist_ok=True)

p=TMP/'sitadel.json'
subprocess.run([
    'curl','--http1.1','--fail','--location','--show-error','--silent',
    '--retry','5','--retry-all-errors','--retry-delay','2',
    '--connect-timeout','30','--max-time','300',
    '--header','Accept: application/json',
    '--output',str(p),URL
],check=True)
payload=json.loads(p.read_text(encoding='utf-8-sig'))

def lists_of_dicts(obj,path='$'):
    found=[]
    if isinstance(obj,list):
        if obj and all(isinstance(x,dict) for x in obj):
            found.append((path,obj))
        for i,v in enumerate(obj[:20]):
            found.extend(lists_of_dicts(v,f'{path}[{i}]'))
    elif isinstance(obj,dict):
        for k,v in obj.items():
            found.extend(lists_of_dicts(v,f'{path}.{k}'))
    return found

cands=lists_of_dicts(payload)
if not cands:
    raise RuntimeError('Aucune liste de lignes détectée dans la réponse Dido')

def score(item):
    path,rows=item
    keys=set()
    for r in rows[:10]: keys.update(r.keys())
    s=0
    for token in ('COMM','ANNEE','MILL','AUT','COMMENC','LOG'):
        if any(token in str(k).upper() for k in keys): s+=1
    return (s,len(rows))

row_path,rows=max(cands,key=score)
keys=sorted({k for r in rows for k in r.keys()})
preview=[]
for r in rows[:12]:
    preview.append({k:r.get(k) for k in keys})

# Valeurs distinctes compactes pour les champs utiles à l'identification du schéma.
distinct={}
for k in keys:
    vals=[]
    seen=set()
    for r in rows:
        v=r.get(k)
        if v is None: continue
        sv=str(v)
        if sv not in seen:
            seen.add(sv); vals.append(v)
        if len(vals)>=25: break
    distinct[k]=vals

result={
    'source':'SDES - Sitadel, logements autorisés et commencés, séries annuelles non estimées',
    'dataset_id':'6513ee3a3b05e5cd969c270f',
    'datafile_rid':RID,
    'territory':TARGET,
    'query_url':URL,
    'rows_path':row_path,
    'rows_n':len(rows),
    'fields':keys,
    'distinct_sample':distinct,
    'preview':preview,
    'quality':{
        'local_query_only':True,
        'missing_semantics':'absence/null = indisponible, jamais 0',
        'note':'Audit de schéma uniquement; aucune interprétation causale.'
    }
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
