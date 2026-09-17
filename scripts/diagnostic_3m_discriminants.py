import json
from pathlib import Path

ASSEMBLY = Path('output/diagnostic-3kg-assembly.json')
INTERP = Path('output/diagnostic-3l-interpretation.json')
OUT = Path('output/diagnostic-3m-discriminants.json')
TARGET = '16015'


def band(percentile):
    p = float(percentile)
    if p <= 10:
        return 'tres_faible', 'très marqué'
    if p <= 25:
        return 'faible', 'marqué'
    if p >= 90:
        return 'tres_eleve', 'très marqué'
    if p >= 75:
        return 'eleve', 'marqué'
    return 'typique', None


def factor(fid, label, domain, value, median, percentile, evidence, universe, panel_n=15):
    direction, strength = band(percentile)
    return {
        'id': fid,
        'label': label,
        'domain': domain,
        'value': value,
        'panel_median': median,
        'percentile': percentile,
        'direction': direction,
        'strength': strength,
        'is_discriminant': strength is not None,
        'reference_panel_n': panel_n,
        'universe': universe,
        'evidence': evidence,
    }


if not ASSEMBLY.exists() or not INTERP.exists():
    raise RuntimeError('Entrées 3K-G / 3L absentes')
assembly = json.loads(ASSEMBLY.read_text(encoding='utf-8'))
interp = json.loads(INTERP.read_text(encoding='utf-8'))
if assembly.get('stage') != '3K-G' or interp.get('stage') != '3L':
    raise RuntimeError('Étapes amont inattendues')
if str(assembly.get('territory')) != TARGET or str(interp.get('territory')) != TARGET:
    raise RuntimeError('Territoire inattendu')
if interp.get('quality', {}).get('status') != 'ok':
    raise RuntimeError('3L non validé')

b = assembly['blocks']
demo = b['demography_housing']['metrics']
filo = b['socioeconomic_context']['metrics']
rpls = b['social_housing']
rm = rpls['metrics']
rp = rpls['panel']

candidates = [
    factor('population_change', 'Évolution de la population 2017-2023', 'demography_housing', demo['population_change_pct'], demo['medians_panel']['population_change_pct'], demo['percentiles']['population_change'], ['blocks.demography_housing.metrics.population_change_pct','blocks.demography_housing.metrics.medians_panel.population_change_pct','blocks.demography_housing.metrics.percentiles.population_change'], 'population communale'),
    factor('households_change', 'Évolution des ménages 2017-2023', 'demography_housing', demo['households_change_pct'], demo['medians_panel']['households_change_pct'], demo['percentiles']['households_change'], ['blocks.demography_housing.metrics.households_change_pct','blocks.demography_housing.metrics.medians_panel.households_change_pct','blocks.demography_housing.metrics.percentiles.households_change'], 'ménages / résidences principales'),
    factor('secondary_homes_share', 'Part des résidences secondaires et logements occasionnels', 'demography_housing', demo['secondary_homes_share_pct'], demo['medians_panel']['secondary_homes_share_pct'], demo['percentiles']['secondary_homes_share'], ['blocks.demography_housing.metrics.secondary_homes_share_pct','blocks.demography_housing.metrics.medians_panel.secondary_homes_share_pct','blocks.demography_housing.metrics.percentiles.secondary_homes_share'], 'ensemble des logements du recensement'),
    factor('median_income', 'Niveau de vie médian', 'socioeconomic_context', filo['niveau_de_vie_median'], filo['medians_panel']['revenu_median'], filo['percentiles']['revenu_median'], ['blocks.socioeconomic_context.metrics.niveau_de_vie_median','blocks.socioeconomic_context.metrics.medians_panel.revenu_median','blocks.socioeconomic_context.metrics.percentiles.revenu_median'], 'population fiscale communale'),
    factor('poverty_rate', 'Taux de pauvreté', 'socioeconomic_context', filo['taux_pauvrete'], filo['medians_panel']['pauvrete'], filo['percentiles']['pauvrete'], ['blocks.socioeconomic_context.metrics.taux_pauvrete','blocks.socioeconomic_context.metrics.medians_panel.pauvrete','blocks.socioeconomic_context.metrics.percentiles.pauvrete'], 'population fiscale communale'),
    factor('social_vacancy', 'Vacance du parc social', 'social_housing', rm['vacance_sociale_pct'], rp['medians']['vacance_sociale_pct'], rp['percentiles']['vacance_sociale_pct'], ['blocks.social_housing.metrics.vacance_sociale_pct','blocks.social_housing.panel.medians.vacance_sociale_pct','blocks.social_housing.panel.percentiles.vacance_sociale_pct'], 'parc locatif social RPLS'),
    factor('social_mobility', 'Mobilité du parc social', 'social_housing', rm['mobilite_pct'], rp['medians']['mobilite_pct'], rp['percentiles']['mobilite_pct'], ['blocks.social_housing.metrics.mobilite_pct','blocks.social_housing.panel.medians.mobilite_pct','blocks.social_housing.panel.percentiles.mobilite_pct'], 'parc locatif social RPLS'),
    factor('social_qpv_share', 'Part du parc social en QPV', 'social_housing', rm['part_qpv_pct'], rp['medians']['part_qpv_pct'], rp['percentiles']['part_qpv_pct'], ['blocks.social_housing.metrics.part_qpv_pct','blocks.social_housing.panel.medians.part_qpv_pct','blocks.social_housing.panel.percentiles.part_qpv_pct'], 'parc locatif social RPLS'),
    factor('social_age_40_plus', 'Part du parc social âgé de 40 ans ou plus', 'social_housing', rm['part_age_40_plus_pct'], rp['medians']['part_age_40_plus_pct'], rp['percentiles']['part_age_40_plus_pct'], ['blocks.social_housing.metrics.part_age_40_plus_pct','blocks.social_housing.panel.medians.part_age_40_plus_pct','blocks.social_housing.panel.percentiles.part_age_40_plus_pct'], 'parc locatif social RPLS'),
]

discriminants = [x for x in candidates if x['is_discriminant']]
non_discriminants = [x for x in candidates if not x['is_discriminant']]

out = {
    'stage': '3M',
    'territory': TARGET,
    'source_stage': '3L',
    'purpose': 'détecter les écarts objectivement atypiques par rapport aux panels disponibles, sans causalité ni recommandation',
    'rules': {
        'discriminant_if_percentile_lte': 25,
        'discriminant_if_percentile_gte': 75,
        'very_marked_if_percentile_lte': 10,
        'very_marked_if_percentile_gte': 90,
        'ranking_allowed': False,
        'global_score_allowed': False,
        'causal_claims_allowed': False,
        'recommendations_allowed': False,
        'comparison_required': True,
        'no_panel_rule': 'un indicateur sans panel comparable n’est pas classé comme discriminant en 3M',
    },
    'discriminant_factors': discriminants,
    'non_discriminant_comparators': non_discriminants,
    'not_assessed_without_comparable_panel': [
        'vacance privée LOVAC',
        'profil INSEE des logements vacants',
        'prix et volumes DVF',
        'dynamique Sitadel',
    ],
    'quality': {
        'candidate_count': len(candidates),
        'discriminant_count': len(discriminants),
        'all_discriminants_have_panel': all(x['reference_panel_n'] > 0 for x in discriminants),
        'causal_claims_included': False,
        'recommendations_included': False,
        'global_score_included': False,
        'ranking_included': False,
        'status': 'ok',
    },
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out['quality'], ensure_ascii=False, indent=2))
