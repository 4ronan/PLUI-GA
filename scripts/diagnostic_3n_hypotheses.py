import json
from pathlib import Path
from diagnostic_runtime import target, runtime_metadata

IN = Path('output/diagnostic-3m2-discriminants.json')
OUT = Path('output/diagnostic-3n-hypotheses.json')
TARGET = target()

if not IN.exists() or IN.stat().st_size == 0:
    raise RuntimeError('Entrée 3M-2 absente ou vide')

d = json.loads(IN.read_text(encoding='utf-8'))
if d.get('stage') != '3M-2':
    raise RuntimeError('Entrée attendue: 3M-2')
if str(d.get('territory')) != TARGET:
    raise RuntimeError('Territoire inattendu')
if d.get('quality', {}).get('status') != 'ok':
    raise RuntimeError('3M-2 non validé')

all_factors = {}
for x in d.get('discriminant_factors', []) + d.get('non_discriminant_comparators', []):
    all_factors[x['id']] = x


def require(*ids):
    missing = [i for i in ids if i not in all_factors]
    if missing:
        raise RuntimeError(f'Indicateurs 3M-2 manquants: {missing}')
    return [all_factors[i] for i in ids]


def independent_domains(factors):
    return sorted({x['domain'] for x in factors})


def confidence_from_domains(domains):
    # Niveau de confiance = convergence diagnostique, jamais probabilité causale.
    n = len(set(domains))
    if n >= 3:
        return 'eleve'
    if n == 2:
        return 'moyen'
    return 'faible'


def hypothesis(hid, title, statement, factor_ids, applicability, cautions):
    factors = require(*factor_ids)
    domains = independent_domains(factors)
    return {
        'id': hid,
        'title': title,
        'statement': statement,
        'supporting_factor_ids': factor_ids,
        'supporting_domains': domains,
        'supporting_factors': [
            {
                'id': x['id'],
                'label': x['label'],
                'value': x['value'],
                'panel_median': x['panel_median'],
                'percentile': x['percentile'],
                'direction': x['direction'],
                'is_discriminant': x['is_discriminant'],
                'universe': x['universe'],
            }
            for x in factors
        ],
        'confidence': confidence_from_domains(domains),
        'confidence_meaning': 'niveau de convergence entre dimensions du diagnostic; ne mesure pas une probabilité causale',
        'applicability': applicability,
        'cautions': cautions,
    }

hypotheses = []

# Règle H1 — convergence socio-économique + marché immobilier.
# Déclenchement uniquement si les trois constats sont réellement présents dans 3M-2
# avec les directions attendues. Aucun savoir externe n'est consulté.
mi, pov, price = require('median_income', 'poverty_rate', 'dvf_median_price_m2')
if mi['direction'] in {'faible', 'tres_faible'} and pov['direction'] in {'eleve', 'tres_eleve'} and price['direction'] in {'faible', 'tres_faible'}:
    hypotheses.append(hypothesis(
        'H1_socioeconomic_market_convergence',
        'Convergence entre fragilité socio-économique et faible niveau de prix immobiliers',
        "Le diagnostic fait apparaître simultanément un niveau de vie médian relativement faible, un taux de pauvreté élevé et un prix médian DVF relativement faible par rapport au panel. Cette convergence constitue une hypothèse de contexte à examiner pour comprendre les conditions locales de remise sur le marché, sans permettre d'établir un lien causal avec la vacance privée.",
        ['median_income', 'poverty_rate', 'dvf_median_price_m2'],
        'contexte_general; pas une cause démontrée de vacance privée',
        [
            'Filosofi décrit la population fiscale communale, pas les propriétaires de logements vacants.',
            'DVF décrit les mutations observées, pas la valeur de tout le parc.',
            'La vacance privée LOVAC n’est pas atypique dans le panel.'
        ]
    ))

# Règle H2 — autorisations / mises en chantier.
aut, started = require('sitadel_authorized_intensity', 'sitadel_started_intensity')
if started['direction'] in {'faible', 'tres_faible'} and aut['percentile'] is not None and 25 < float(aut['percentile']) < 75:
    hypotheses.append(hypothesis(
        'H2_construction_pipeline_gap',
        'Décalage diagnostique entre autorisations et mises en chantier',
        "Le diagnostic combine une intensité d'autorisations située dans la zone centrale du panel et une intensité de mises en chantier très faible. Le script signale donc un décalage à vérifier dans la transformation des autorisations en démarrages, sans en attribuer la cause.",
        ['sitadel_authorized_intensity', 'sitadel_started_intensity'],
        'dynamique_de_construction; hypothèse de vérification',
        [
            'Les autorisations et les mises en chantier portent sur des millésimes différents.',
            'Sitadel est utilisé ici en série communale non estimée.',
            'Le diagnostic ne permet pas d’identifier la cause du décalage.'
        ]
    ))

# Règle H3 — configuration du parc social; explicitement non transférable au parc privé.
mob, qpv, svac = require('social_mobility', 'social_qpv_share', 'social_vacancy')
if mob['direction'] in {'eleve', 'tres_eleve'} and qpv['direction'] in {'eleve', 'tres_eleve'} and not svac['is_discriminant']:
    hypotheses.append(hypothesis(
        'H3_social_housing_configuration',
        'Configuration spécifique du parc social',
        "Le parc social se distingue par une mobilité élevée et une forte concentration en QPV, tandis que sa vacance n’est pas atypique dans le panel. Le script retient cette configuration comme élément de contexte territorial distinct, sans la transposer à la vacance du parc privé.",
        ['social_mobility', 'social_qpv_share', 'social_vacancy'],
        'contexte_parc_social_uniquement',
        [
            'RPLS et LOVAC décrivent des univers différents.',
            'Aucune inférence vers les propriétaires ou logements vacants privés n’est autorisée.'
        ]
    ))

# Garde-fous issus directement des comparateurs 3M-2.
priv, structural, apt, age = require(
    'private_vacancy_rate',
    'private_structural_vacancy_rate',
    'vacant_apartment_share',
    'vacant_1946_1990_share',
)

guardrails = []
if not priv['is_discriminant'] and not structural['is_discriminant']:
    guardrails.append({
        'id': 'G1_no_relative_excess_private_vacancy',
        'statement': "Le script ne génère aucune hypothèse de sur-vacance privée relative : ni le taux de vacance privée ni le taux de vacance de plus de deux ans ne sont discriminants dans le panel.",
        'evidence_factor_ids': ['private_vacancy_rate', 'private_structural_vacancy_rate']
    })
if not apt['is_discriminant'] and not age['is_discriminant']:
    guardrails.append({
        'id': 'G2_no_atypical_vacant_profile',
        'statement': "Le script ne génère aucune hypothèse fondée sur un profil atypique des logements vacants : la part des appartements et la part des logements construits entre 1946 et 1990 ne sont pas discriminantes dans le panel.",
        'evidence_factor_ids': ['vacant_apartment_share', 'vacant_1946_1990_share']
    })

out = {
    'stage': '3N',
    'territory': TARGET,
    'source_stage': '3M-2',
    'purpose': 'formuler uniquement des hypothèses déterministes dérivées du diagnostic, sans IA ni connaissance externe',
    'generation': {
        'mode': 'deterministic_rule_engine',
        'llm_used': False,
        'external_knowledge_used': False,
        'web_used': False,
        'network_calls': False,
        'free_text_generation': False,
        'input_scope': 'uniquement output/diagnostic-3m2-discriminants.json',
        'rule_principle': 'une hypothèse n’est émise que lorsqu’une combinaison explicitement codée d’indicateurs du diagnostic est satisfaite',
    },
    'rules': {
        'causality_allowed': False,
        'recommendations_allowed': False,
        'global_score_allowed': False,
        'confidence_definition': 'faible=1 domaine diagnostique; moyen=2; élevé=3 ou plus; mesure la convergence, pas la causalité',
        'missing_data_rule': 'une règle dont un indicateur requis est absent ne doit pas être évaluée comme vraie',
        'universe_separation_rule': 'LOVAC, INSEE RP et RPLS restent des univers distincts',
    },
    'hypotheses': hypotheses,
    'guardrails': guardrails,
    'runtime': runtime_metadata(),
    'quality': {
        'hypothesis_count': len(hypotheses),
        'guardrail_count': len(guardrails),
        'all_hypotheses_traceable_to_3m2': all(all(fid in all_factors for fid in h['supporting_factor_ids']) for h in hypotheses),
        'llm_used': False,
        'external_knowledge_used': False,
        'causal_claims_included': False,
        'recommendations_included': False,
        'global_score_included': False,
        'status': 'ok',
    },
}

if not out['quality']['all_hypotheses_traceable_to_3m2']:
    raise RuntimeError('Hypothèse non traçable vers 3M-2')

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'quality': out['quality'], 'hypothesis_ids': [h['id'] for h in hypotheses], 'guardrail_ids': [g['id'] for g in guardrails]}, ensure_ascii=False, indent=2))
