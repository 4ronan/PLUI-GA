import json
import math
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from diagnostic_runtime import target, comparison_scale
from diagnostic_3vd_insee_zonings import load_insee_zonings

API_BASE='https://geo.api.gouv.fr'
FIELDS='nom,code,codeDepartement,codeRegion,population,surface'
OUT=Path('output/diagnostic-3v-panel.json')
PANEL_N=15
ALGORITHM='3V-D-insee-typology-v2'
FALLBACK_ALGORITHM='3V-A-structural-v1'


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


def _aav_role_distance(a,b):
    if not a or not b:
        return 9
    if a==b:
        return 0
    poles={'11','12','13'}
    if a in poles and b in poles:
        return 1
    if (a in poles and b=='20') or (b in poles and a=='20'):
        return 2
    if '30' in {a,b}:
        return 3
    return 2


def _ordinal_distance(a,b,missing=9):
    try:
        return abs(int(a)-int(b))
    except (TypeError,ValueError):
        return missing


def _candidate_rank(row,target_row,typology_enabled):
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

    structural_distance=0.65*pop_distance + 0.35*density_distance
    density7_distance=_ordinal_distance(row.get('density7'),target_row.get('density7'))
    aav_role_distance=_aav_role_distance(row.get('aav_category'),target_row.get('aav_category'))
    aav_size_distance=_ordinal_distance(row.get('aav_size'),target_row.get('aav_size'))

    if typology_enabled:
        rank_key=(
            population_band,
            density7_distance,
            aav_role_distance,
            aav_size_distance,
            structural_distance,
            pop_distance,
            density_distance,
            row['code'],
        )
    else:
        rank_key=(
            population_band,
            structural_distance,
            pop_distance,
            density_distance,
            row['code'],
        )

    return rank_key, {
        'population_ratio':pop_ratio,
        'population_log_distance':pop_distance,
        'density_log_distance':density_distance,
        'structural_distance':structural_distance,
        'population_band':population_band,
        'density7_distance':density7_distance if typology_enabled else None,
        'aav_role_distance':aav_role_distance if typology_enabled else None,
        'aav_size_distance':aav_size_distance if typology_enabled else None,
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

    zoning_status='unavailable'
    zoning_metadata={}
    disable_typology=str(os.getenv('DIAG_DISABLE_INSEE_PANEL_TYPOLOGY') or '').strip().lower() in {'1','true','yes','oui','on'}
    try:
        if disable_typology:
            raise RuntimeError('typologies Insee désactivées explicitement pour validation comparative')
        zoning=load_insee_zonings()
        zoning_by_code=zoning['by_code']
        zoning_metadata=zoning['metadata']
        for code,row in by_code.items():
            row.update(zoning_by_code.get(code,{}))
        zoning_status='available'
    except Exception as exc:
        zoning_metadata={'error':f'{type(exc).__name__}: {exc}'}

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

    typology_enabled=(
        zoning_status=='available'
        and bool(target_row.get('density7'))
        and bool(target_row.get('aav_category'))
        and bool(target_row.get('aav_size'))
    )

    ranked=[]
    candidate_band_counts={0:0,1:0,2:0}
    for row in candidates:
        key,metrics=_candidate_rank(row,target_row,typology_enabled)
        candidate_band_counts[metrics['population_band']]+=1
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
            'density7':row.get('density7'),
            'density7_label':row.get('density7_label'),
            'aav_category':row.get('aav_category'),
            'aav_code':row.get('aav_code'),
            'aav_name':row.get('aav_name'),
            'aav_size':row.get('aav_size'),
            'aav_detailed_size':row.get('aav_detailed_size'),
            **metrics,
        })

    selected_band_counts={0:0,1:0,2:0}
    for x in selected:
        selected_band_counts[x['population_band']]+=1

    effective_algorithm=ALGORITHM if typology_enabled else FALLBACK_ALGORITHM
    result={
        'stage':'3V-D' if typology_enabled else '3V-A',
        'algorithm':effective_algorithm,
        'source':{
            'administrative':{
                'name':'API Découpage administratif - communes',
                'producer':'DINUM / Etalab',
                'url':url,
                'fields':['nom','code','codeDepartement','codeRegion','population','surface'],
            },
            'insee_zonings':{
                'status':zoning_status,
                **zoning_metadata,
            },
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
            'structural_distance':'0.65 * abs(log(population_ratio)) + 0.35 * abs(log(density_ratio))',
            'typology_priority':(
                'bande de population, puis distance DENS7, rôle AAV, tranche de taille AAV et distance structurelle'
                if typology_enabled else
                'zonages Insee indisponibles: repli sur bande de population puis distance structurelle 3V-A'
            ),
            'tie_break':(
                'population_band, density7_distance, aav_role_distance, aav_size_distance, structural_distance, population_distance, density_distance, code INSEE'
                if typology_enabled else
                'population_band, structural_distance, population_distance, density_distance, code INSEE'
            ),
            'administrative_scope_fallback':'department -> region -> france; region -> france; france',
            'llm_used':False,
            'global_score_used':False,
            'selection_metric_note':'Les distances servent uniquement à choisir les communes de référence; elles n’évaluent ni ne classent la commune cible.',
            'insee_density_role':'DENS7/LIBDENS7 de la grille communale de densité Insee au 01/01/2026',
            'insee_aav_role':'CATEAAV2020 et TAAV2017 de la base AAV 2020 au 01/01/2026',
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
            'candidate_population_band_counts':{str(k):v for k,v in candidate_band_counts.items()},
            'selected_population_band_counts':{str(k):v for k,v in selected_band_counts.items()},
            'population_band_priority_respected':(
                (candidate_band_counts[0]>=PANEL_N and selected_band_counts[0]==PANEL_N)
                or (candidate_band_counts[0]<PANEL_N and selected_band_counts[0]==candidate_band_counts[0])
            ),
            'insee_typology_enabled':typology_enabled,
            'insee_typology_disabled_by_env':disable_typology,
            'algorithm':effective_algorithm,
            'status':'ok',
        },
    }
    return result


def ensure_runtime_panel():
    explicit=os.getenv('DIAG_PANEL_CODES')
    if explicit and explicit.strip():
        explicit_codes=[x.strip().upper() for x in explicit.split(',') if x.strip()]
        if os.getenv('DIAG_PANEL_SOURCE') in {ALGORITHM,FALLBACK_ALGORITHM} and OUT.exists() and OUT.stat().st_size>0:
            try:
                prior=json.loads(OUT.read_text(encoding='utf-8'))
                if (
                    prior.get('algorithm')==os.getenv('DIAG_PANEL_SOURCE')
                    and str(prior.get('territory'))==target()
                    and prior.get('panel_codes')==explicit_codes
                ):
                    return prior
            except Exception:
                pass
        return {
            'stage':'3V-A',
            'algorithm':'explicit_env_override',
            'territory':target(),
            'requested_scale':comparison_scale(),
            'effective_scale':'explicit',
            'panel_codes':explicit_codes,
            'quality':{'status':'explicit_override'},
        }

    scale_was_explicit=bool(os.getenv('DIAG_COMPARISON_SCALE'))
    result=select_panel()
    codes=result['panel_codes']
    os.environ['DIAG_PANEL_CODES']=','.join(codes)
    os.environ['DIAG_PANEL_SOURCE']=result['algorithm']
    if not os.getenv('DIAG_COMMUNE_NAME'):
        os.environ['DIAG_COMMUNE_NAME']=result['target']['name']
        os.environ['DIAG_COMMUNE_NAME_SOURCE']='geo_api_auto'
    os.environ['DIAG_COMPARISON_SCALE']=result['requested_scale']
    os.environ['DIAG_COMPARISON_SCALE_SOURCE']='env' if scale_was_explicit else 'transition_default'

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    result=ensure_runtime_panel()
    print(json.dumps(result,ensure_ascii=False,indent=2))
