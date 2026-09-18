import json
from pathlib import Path
from diagnostic_runtime import target, runtime_metadata

BASE=Path('output/diagnostic-3m-discriminants.json')
PANELS=Path('output/diagnostic-3mp-panels.json')
OUT=Path('output/diagnostic-3m2-discriminants.json')
TARGET=target()


def band(p):
    if p is None:
        return 'indisponible',None
    p=float(p)
    if p<=10: return 'tres_faible','très marqué'
    if p<=25: return 'faible','marqué'
    if p>=90: return 'tres_eleve','très marqué'
    if p>=75: return 'eleve','marqué'
    return 'typique',None


def mk(fid,label,domain,stat,universe,evidence):
    direction,strength=band(stat['percentile'])
    return {
        'id':fid,'label':label,'domain':domain,
        'value':stat['target'],'panel_median':stat['panel_median'],
        'percentile':stat['percentile'],'direction':direction,
        'strength':strength,'is_discriminant':strength is not None,
        'reference_panel_n':stat['panel_n'],'universe':universe,
        'evidence':evidence,
    }

if not BASE.exists() or not PANELS.exists():
    raise RuntimeError('Entrées 3M / 3M-P absentes')
base=json.loads(BASE.read_text(encoding='utf-8'))
pan=json.loads(PANELS.read_text(encoding='utf-8'))
if base.get('stage')!='3M' or pan.get('stage')!='3M-P':
    raise RuntimeError('Étapes amont inattendues')
if str(base.get('territory'))!=TARGET or str(pan.get('territory'))!=TARGET:
    raise RuntimeError('Territoire inattendu')
if pan.get('quality',{}).get('status') not in {'ok','partial'}:
    raise RuntimeError('3M-P non validé')

candidates=list(base['discriminant_factors'])+list(base['non_discriminant_comparators'])
B=pan['blocks']
candidates += [
    mk('private_vacancy_rate','Taux de vacance privée 2025','vacancy_private',B['lovac']['stats']['vacancy_rate_pct'],'parc privé LOVAC 2025',['3M-P.blocks.lovac.stats.vacancy_rate_pct']),
    mk('private_structural_vacancy_rate','Taux de vacance privée >2 ans 2025','vacancy_private',B['lovac']['stats']['structural_vacancy_rate_pct'],'parc privé LOVAC 2025',['3M-P.blocks.lovac.stats.structural_vacancy_rate_pct']),
    mk('dvf_median_price_m2','Prix médian DVF 2025 des ventes résidentielles simples','real_estate_market',B['dvf']['stats']['median_price_m2_eur_simple'],'mutations résidentielles simples DVF 2025',['3M-P.blocks.dvf.stats.median_price_m2_eur_simple']),
    mk('sitadel_authorized_intensity','Logements autorisés 2025 pour 1 000 habitants','construction',B['sitadel']['stats']['authorized_2025_per_1000_pop2023'],'Sitadel autorisations 2025 normalisées par population 2023',['3M-P.blocks.sitadel.stats.authorized_2025_per_1000_pop2023']),
    mk('sitadel_started_intensity','Logements commencés 2024 pour 1 000 habitants','construction',B['sitadel']['stats']['started_2024_per_1000_pop2023'],'Sitadel mises en chantier 2024 normalisées par population 2023',['3M-P.blocks.sitadel.stats.started_2024_per_1000_pop2023']),
    mk('vacant_apartment_share','Part des appartements parmi les logements vacants INSEE','vacant_stock_profile',B['insee_log1_vacant_profile']['stats']['vacant_apartment_share_pct'],'profil INSEE 2023 des logements vacants construits avant 2021',['3M-P.blocks.insee_log1_vacant_profile.stats.vacant_apartment_share_pct']),
    mk('vacant_1946_1990_share','Part des logements vacants construits entre 1946 et 1990','vacant_stock_profile',B['insee_log1_vacant_profile']['stats']['vacant_1946_1990_share_pct'],'profil INSEE 2023 des logements vacants construits avant 2021',['3M-P.blocks.insee_log1_vacant_profile.stats.vacant_1946_1990_share_pct']),
]

# Déduplication défensive par identifiant.
by_id={x['id']:x for x in candidates}
candidates=list(by_id.values())
discriminants=[x for x in candidates if x['is_discriminant']]
non_discriminants=[x for x in candidates if not x['is_discriminant']]

out={
    'stage':'3M-2','territory':TARGET,
    'source_stages':['3M','3M-P'],
    'purpose':'étendre la détection des facteurs discriminants après matérialisation des panels LOVAC, DVF, Sitadel et LOG1',
    'rules':{
        'discriminant_if_percentile_lte':25,
        'discriminant_if_percentile_gte':75,
        'very_marked_if_percentile_lte':10,
        'very_marked_if_percentile_gte':90,
        'ranking_allowed':False,
        'global_score_allowed':False,
        'causal_claims_allowed':False,
        'recommendations_allowed':False,
        'comparison_required':True,
        'profile_caution':'LOG1 compare les profils de logements vacants entre communes; il ne mesure pas une surreprésentation par rapport au parc occupé local.'
    },
    'discriminant_factors':discriminants,
    'non_discriminant_comparators':non_discriminants,
    'runtime':runtime_metadata(),
    'quality':{
        'candidate_count':len(candidates),
        'discriminant_count':len(discriminants),
        'all_candidates_have_panel':all(x.get('reference_panel_n',0)>0 for x in candidates if x.get('percentile') is not None),
        'unavailable_candidate_count':sum(1 for x in candidates if x.get('percentile') is None),
        'all_discriminants_have_panel':all(x.get('reference_panel_n',0)>0 for x in discriminants),
        'causal_claims_included':False,
        'recommendations_included':False,
        'global_score_included':False,
        'ranking_included':False,
        'status':'ok'
    }
}
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'quality':out['quality'],'discriminants':[(x['id'],x['percentile']) for x in discriminants]},ensure_ascii=False,indent=2))
