import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from diagnostic_runtime import target, comparison_scale

API_BASE='https://geo.api.gouv.fr'
FIELDS='nom,code,codeDepartement,codeRegion,population,surface'
OUT=Path('output/diagnostic-3v-panel.json')
PANEL_N=15
ALGORITHM='3V-A-structural-v1'


def _fetch_json(url):
    last=None
    for attempt in range(1,5):
        try:
            req=urllib.request.Request(
                url,
                headers={
                    'Accept':'application/json',
                    'User-Agent':'PLUI-GA-vacants-panel-selector/3V-A',
                },
            )
            with urllib.request.urlopen(req,timeout=120) as response:
                return json.load(response)
        except Exception as exc:
            last=exc
            if attempt<4:
                time.sleep(attempt*2)
    raise RuntimeError(f'geo.api.gouv.fr indisponible après 4 tentatives: {last}')


def _is_municipal_arrondissement(code):
    # L’API peut exposer les arrondissements municipaux avec les communes.
    # Ils ne constituent pas des communes LOVAC comparables.
    return (
        (code.startswith('751') and code[3:].isdigit() and 1<=int(code[3:])<=20)
        or (code.startswith('132') and code[3:].isdigit() and 1<=int(code[3:])<=16)
        or (code.startswith('6938') and code[-1].isdigit() and 1<=int(code[-1])<=9)
    )


def _clean(row):
    code=str(row.get('code') or '').strip().upper()
    try:
        population=float(row.get('population'))
        surface=float(row.get('surface'))
    except (TypeError,ValueError):
        return None
    if len(code)!=5 or population<=0 or surface<=0 or _is_municipal_arrondissement(code):
        return None
    return {
        'code':code,
        'name':str(row.get('nom') or code).strip(),
        'department':str(row.get('codeDepartement') or '').strip().upper(),
        'region':str(row.get('codeRegion') or '').strip().upper(),
        'population':population,
        'surface':surface,
        # Pour le classement, seule la proximité relative compte. Toute unité
        # homogène de surface produit le même écart logarithmique.
        'density_index':population/surface,
    }


def _scope_match(row,target_row,scope):
    if scope=='department':
        return row['department']==target_row['department']
    if scope=='region':
        return row['region']==target_row['region']
    if scope=='france':
        return True
    raise RuntimeError(f'Échelle inconnue: {scope}')


def _scope_sequence(requested):
    if requested=='department':
        return ['department','region','france']
    if requested=='region':
        return ['region','france']
    return ['france']


def _candidate_rank(row,target_row):
    pop_ratio=row['population']/target_row['population']
    density_ratio=row['density_index']/target_row['density_index']
    pop_distance=abs(math.log(pop_ratio))
    density_distance=abs(math.log(density_ratio))

    # La bande 70-130 % constitue la première préférence. On élargit ensuite
    # à 50-200 %, puis à l’ensemble de l’échelle si nécessaire.
    if 0.70<=pop_ratio<=1.30:
        population_band=0
    elif 0.50<=pop_ratio<=2.00:
        population_band=1
    else:
        population_band=2

    structural_score=0.65*pop_distance + 0.35*density_distance
    return (
        population_band,
        structural_score,
        pop_distance,
        density_distance,
        row['code'],
    ), {
        'population_ratio':pop_ratio,
        'population_log_distance':pop_distance,
        'density_log_distance':density_distance,
        'structural_score':structural_score,
        'population_band':population_band,
    }


def select_panel():
    target_code=target()
    requested_scale=comparison_scale()
    params=urllib.parse.urlencode({'fields':FIELDS,'format':'json'})
    url=f'{API_BASE}/communes?{params}'
    payload=_fetch_json(url)
    if not isinstance(payload,list):
        raise RuntimeError('Réponse geo.api.gouv.fr inattendue pour la liste des communes')

    rows=[]
    for raw in payload:
        if isinstance(raw,dict):
            clean=_clean(raw)
            if clean:
                rows.append(clean)

    by_code={r['code']:r for r in rows}
    target_row=by_code.get(target_code)
    if not target_row:
        raise RuntimeError(f'Commune cible {target_code} absente ou sans population/surface exploitable dans geo.api.gouv.fr')

    chosen_scope=None
    candidates=None
    expansion=[]
    for scope in _scope_sequence(requested_scale):
        scoped=[
            r for r in rows
            if r['code']!=target_code and _scope_match(r,target_row,scope)
        ]
        expansion.append({'scope':scope,'valid_candidate_n':len(scoped)})
        if len(scoped)>=PANEL_N:
            chosen_scope=scope
            candidates=scoped
            break

    if chosen_scope is None or candidates is None:
        raise RuntimeError(f'Moins de {PANEL_N} communes comparables valides, même après élargissement à la France')

    ranked=[]
    for row in candidates:
        key,metrics=_candidate_rank(row,target_row)
        ranked.append((key,row,metrics))
    ranked.sort(key=lambda x:x[0])

    selected=[]
    for rank,(_,row,metrics) in enumerate(ranked[:PANEL_N],start=1):
        selected.append({
            'rank':rank,
            'code':row['code'],
            'name':row['name'],
            'department':row['department'],
            'region':row['region'],
            'population':row['population'],
            'surface':row['surface'],
            'density_index':row['density_index'],
            **metrics,
        })

    result={
        'stage':'3V-A',
        'algorithm':ALGORITHM,
        'source':{
            'name':'API Découpage administratif - communes',
            'producer':'DINUM / Etalab',
            'url':url,
            'fields':['nom','code','codeDepartement','codeRegion','population','surface'],
        },
        'territory':target_code,
        'target':target_row,
        'requested_scale':requested_scale,
        'effective_scale':chosen_scope,
        'scope_expansion':expansion,
        'rules':{
            'panel_n':PANEL_N,
            'target_excluded':True,
            'population_preference':'70-130 % de la population cible, puis 50-200 %, puis reste de l’échelle',
            'structural_score':'0.65 * abs(log(population_ratio)) + 0.35 * abs(log(density_ratio))',
            'tie_break':'population_band, structural_score, population_distance, density_distance, code INSEE',
            'administrative_scope_fallback':'department -> region -> france; region -> france; france',
            'llm_used':False,
            'global_score_used':False,
        },
        'selected':selected,
        'panel_codes':[x['code'] for x in selected],
        'quality':{
            'selected_n':len(selected),
            'codes_unique':len({x['code'] for x in selected})==len(selected),
            'target_excluded':target_code not in {x['code'] for x in selected},
            'all_have_population':all(x['population']>0 for x in selected),
            'all_have_surface':all(x['surface']>0 for x in selected),
            'deterministic_sort':True,
            'status':'ok',
        },
    }
    return result


def ensure_runtime_panel():
    explicit=os.getenv('DIAG_PANEL_CODES')
    if explicit and explicit.strip():
        return {
            'stage':'3V-A',
            'algorithm':'explicit_env_override',
            'territory':target(),
            'requested_scale':comparison_scale(),
            'effective_scale':'explicit',
            'panel_codes':[x.strip().upper() for x in explicit.split(',') if x.strip()],
            'quality':{'status':'explicit_override'},
        }

    result=select_panel()
    codes=result['panel_codes']
    os.environ['DIAG_PANEL_CODES']=','.join(codes)
    os.environ['DIAG_PANEL_SOURCE']=ALGORITHM
    if not os.getenv('DIAG_COMMUNE_NAME'):
        os.environ['DIAG_COMMUNE_NAME']=result['target']['name']
        os.environ['DIAG_COMMUNE_NAME_SOURCE']='geo_api_auto'
    os.environ['DIAG_COMPARISON_SCALE']=result['requested_scale']

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    result=ensure_runtime_panel()
    print(json.dumps(result,ensure_ascii=False,indent=2))
