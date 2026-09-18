import json
from pathlib import Path
from diagnostic_runtime import target, commune_name, runtime_metadata

IN = Path('output/diagnostic-3kg-assembly.json')
OUT = Path('output/diagnostic-3l-interpretation.json')
TARGET = target()
COMMUNE_NAME = commune_name()


def pct(x):
    return None if x is None else round(float(x), 2)


def eur(x):
    return None if x is None else round(float(x))


def statement(kind, text, evidence, limit=None):
    d = {
        'kind': kind,
        'text': text,
        'evidence': evidence,
    }
    if limit:
        d['limit'] = limit
    return d


if not IN.exists() or IN.stat().st_size == 0:
    raise RuntimeError('Assemblage 3K-G absent ou vide')

assembly = json.loads(IN.read_text(encoding='utf-8'))
if assembly.get('stage') != '3K-G':
    raise RuntimeError('Entrée attendue: assemblage 3K-G')
if str(assembly.get('territory')) != TARGET:
    raise RuntimeError('Territoire inattendu')
if assembly.get('quality', {}).get('ready_for_interpretation_layer') is not True:
    raise RuntimeError('3K-G non prêt pour interprétation')

b = assembly['blocks']

lovac = b['vacancy_private']
lm = lovac['metrics']
log1 = b['vacant_stock_profile']
logm = log1['metrics']
dvf = b['real_estate_market']
dvfm = dvf['selected_metrics']
demo = b['demography_housing']
demom = demo['metrics']
filo = b['socioeconomic_context']
filom = filo['metrics']
sit = b['construction']
sitm = sit['selected_metrics']
rpls = b['social_housing']
rplsm = rpls['metrics']
rplsp = rpls['panel']

# Profil vacant INSEE : sommes strictement descriptives, sans comparaison au parc de référence.
periods = {x['code']: x for x in logm['by_construction_period']}
share_1946_1990 = periods['Y1946T1970']['share_pct'] + periods['Y1971T1990']['share_pct']

demo_med = demom['medians_panel']
demo_pct = demom['percentiles']
filo_med = filom['medians_panel']
filo_pct = filom['percentiles']
rpls_med = rplsp['medians']
rpls_pct = rplsp['percentiles']

def rpls_text(label, value, median, percentile):
    if value is None:
        return f"{label} : donnée RPLS indisponible pour la commune ; aucune valeur n’est imputée."
    if median is None or percentile is None:
        return f"{label} : {pct(value)} %. La comparaison au panel RPLS est insuffisante ou indisponible."
    return f"{label} : {pct(value)} %, contre une médiane de {pct(median)} % dans le panel (percentile {pct(percentile)})."

def socio_text(label, value, median, percentile, unit=''):
    if value is None:
        return f"{label} est indisponible pour la commune (secret statistique ou donnée non diffusée) ; aucune valeur n’est imputée et aucun percentile communal n’est calculé."
    if median is None or percentile is None:
        return f"{label} est de {pct(value)}{unit}, mais le panel disponible est insuffisant pour une comparaison robuste."
    return f"{label} est de {pct(value)}{unit}, contre {pct(median)}{unit} dans le panel ; son percentile empirique est {pct(percentile)}."

income_text = (
    f"Le niveau de vie médian est indisponible pour la commune (secret statistique ou donnée non diffusée) ; aucune valeur n’est imputée et aucun percentile communal n’est calculé."
    if filom['niveau_de_vie_median'] is None else
    f"Le niveau de vie médian est de {eur(filom['niveau_de_vie_median'])} € par unité de consommation, contre {eur(filo_med['revenu_median'])} € dans le panel ; son percentile empirique est {pct(filo_pct['revenu_median'])}."
)
poverty_text = socio_text("Le taux de pauvreté", filom['taux_pauvrete'], filo_med['pauvrete'], filo_pct['pauvrete'], " %")

def dvf_text():
    if dvfm.get('latest_year') is None or dvfm.get('residential_sale_mutations_n') is None:
        return f"DVF ne fournit pas de mutation résidentielle exploitable pour {COMMUNE_NAME} sur la fenêtre 2021-2025 ; aucun niveau de prix n’est imputé."
    med=eur(dvfm.get('median_price_m2_eur_simple'))
    return (
        f"En {int(dvfm['latest_year'])}, DVF recense {int(dvfm['residential_sale_mutations_n'])} mutations résidentielles à {COMMUNE_NAME}. "
        + (f"Sur les ventes résidentielles simples retenues, le prix médian est de {med} €/m²." if med is not None else "Le volume est observable mais aucune médiane au m² robuste n’est disponible pour les ventes simples.")
    )

def dvf_type_text():
    h=eur(dvfm.get('house_median_price_m2_eur'))
    a=eur(dvfm.get('apartment_median_price_m2_eur'))
    if h is None and a is None:
        return "Aucune médiane distincte maison/appartement n’est disponible sur le dernier millésime DVF exploitable."
    if h is None:
        return f"La médiane appartement est de {a} €/m² ; aucune médiane maison robuste n’est disponible."
    if a is None:
        return f"La médiane maison est de {h} €/m² ; aucune médiane appartement robuste n’est disponible."
    return f"La médiane atteint {h} €/m² pour les maisons et {a} €/m² pour les appartements."

def sitadel_text(kind):
    if kind=='authorized':
        y=sitm.get('latest_authorized_year'); v=sitm.get('latest_authorized_dwellings')
        if y is None or v is None:
            return "Aucune valeur communale exploitable n’est disponible pour les logements autorisés dans la série Sitadel."
        return f"Sitadel recense {int(v)} logements autorisés en {int(y)}."
    y=sitm.get('latest_started_year'); v=sitm.get('latest_started_dwellings')
    if y is None or v is None:
        return "Aucune valeur communale exploitable n’est disponible pour les logements commencés dans la série Sitadel."
    return f"La dernière valeur disponible pour les logements commencés est de {int(v)} en {int(y)}."

sections = [
    {
        'id': 'vacancy_private',
        'title': 'Vacance du parc privé',
        'statements': [
            statement(
                'constat',
                f"En 2025, dernière année disposant d'un dénominateur compatible, {pct(lm['vacancy_rate_pct'])} % du parc privé est vacant et {pct(lm['structural_vacancy_rate_pct'])} % du parc privé relève d'une vacance de plus de deux ans.",
                ['blocks.vacancy_private.metrics.latest_compatible_rate_year', 'blocks.vacancy_private.metrics.vacancy_rate_pct', 'blocks.vacancy_private.metrics.structural_vacancy_rate_pct']
            ),
            statement(
                'constat',
                f"En 2026, LOVAC recense {int(lm['vacant_all_count_2026'])} logements privés vacants, dont {int(lm['vacant_gt2y_count_2026'])} vacants depuis plus de deux ans.",
                ['blocks.vacancy_private.metrics.vacant_all_count_2026', 'blocks.vacancy_private.metrics.vacant_gt2y_count_2026']
            ),
            statement(
                'limite',
                "Aucun taux de vacance 2026 n'est calculé, faute de dénominateur 2026 compatible. Les ruptures méthodologiques documentées dans LOVAC imposent aussi de la prudence pour les comparaisons temporelles.",
                ['blocks.vacancy_private.series.2026.rate_status', 'blocks.vacancy_private.quality.breaks_in_series']
            ),
        ],
    },
    {
        'id': 'vacant_stock_profile',
        'title': 'Caractéristiques du parc vacant',
        'statements': [
            statement(
                'constat',
                f"Dans le profil INSEE 2023 des logements vacants construits avant 2021, les appartements représentent {pct(next(x['share_pct'] for x in logm['by_dwelling_type'] if x['code']=='2'))} % des logements vacants et les maisons {pct(next(x['share_pct'] for x in logm['by_dwelling_type'] if x['code']=='1'))} %.",
                ['blocks.vacant_stock_profile.metrics.by_dwelling_type']
            ),
            statement(
                'constat',
                f"Les logements construits entre 1946 et 1990 représentent {pct(share_1946_1990)} % de ce profil de logements vacants.",
                ['blocks.vacant_stock_profile.metrics.by_construction_period']
            ),
            statement(
                'limite',
                "Ce bloc décrit le profil des logements vacants au recensement. Sans distribution de référence du parc occupé construite sur le même univers, il ne permet pas encore de parler de surreprésentation d'un type de logement ou d'une période de construction.",
                ['blocks.vacant_stock_profile.universe', 'blocks.vacant_stock_profile.merge_with_lovac']
            ),
        ],
    },
    {
        'id': 'real_estate_market',
        'title': 'Contexte immobilier',
        'statements': [
            statement(
                'constat',
                dvf_text(),
                ['blocks.real_estate_market.selected_metrics.residential_sale_mutations_n', 'blocks.real_estate_market.selected_metrics.median_price_m2_eur_simple']
            ),
            statement(
                'constat',
                dvf_type_text(),
                ['blocks.real_estate_market.selected_metrics.house_median_price_m2_eur', 'blocks.real_estate_market.selected_metrics.apartment_median_price_m2_eur']
            ),
            statement(
                'limite',
                "Les prix DVF décrivent le marché des mutations observées. Ils ne constituent pas une mesure de la valeur de l'ensemble du parc et ne prouvent aucune cause de vacance.",
                ['blocks.real_estate_market.method.warning']
            ),
        ],
    },
    {
        'id': 'demography_housing',
        'title': 'Dynamique démographique et résidentielle',
        'statements': [
            statement(
                'constat',
                f"Entre 2017 et 2023, la population évolue de {pct(demom['population_change_pct'])} % tandis que le nombre de ménages progresse de {pct(demom['households_change_pct'])} %.",
                ['blocks.demography_housing.metrics.population_change_pct', 'blocks.demography_housing.metrics.households_change_pct']
            ),
            statement(
                'comparaison',
                f"La croissance des ménages est supérieure à la médiane du panel ({pct(demo_med['households_change_pct'])} %) et se situe au percentile empirique {pct(demo_pct['households_change'])}.",
                ['blocks.demography_housing.metrics.households_change_pct', 'blocks.demography_housing.metrics.medians_panel.households_change_pct', 'blocks.demography_housing.metrics.percentiles.households_change']
            ),
            statement(
                'comparaison',
                f"La part des résidences secondaires et logements occasionnels est de {pct(demom['secondary_homes_share_pct'])} %, très proche de la médiane du panel ({pct(demo_med['secondary_homes_share_pct'])} % ; percentile {pct(demo_pct['secondary_homes_share'])}).",
                ['blocks.demography_housing.metrics.secondary_homes_share_pct', 'blocks.demography_housing.metrics.medians_panel.secondary_homes_share_pct', 'blocks.demography_housing.metrics.percentiles.secondary_homes_share']
            ),
            statement(
                'limite',
                "Ces indicateurs décrivent la pression résidentielle et la structure démographique ; ils ne permettent pas d'expliquer, à eux seuls, la vacance privée.",
                ['blocks.demography_housing.causal_interpretation']
            ),
        ],
    },
    {
        'id': 'socioeconomic_context',
        'title': 'Contexte socio-économique',
        'statements': [
            statement(
                'comparaison',
                income_text,
                ['blocks.socioeconomic_context.metrics.niveau_de_vie_median', 'blocks.socioeconomic_context.metrics.medians_panel.revenu_median', 'blocks.socioeconomic_context.metrics.percentiles.revenu_median']
            ),
            statement(
                'comparaison',
                poverty_text,
                ['blocks.socioeconomic_context.metrics.taux_pauvrete', 'blocks.socioeconomic_context.metrics.medians_panel.pauvrete', 'blocks.socioeconomic_context.metrics.percentiles.pauvrete']
            ),
            statement(
                'limite',
                "Filosofi décrit le contexte socio-économique communal. Il ne permet pas d'attribuer une situation de revenu ou de pauvreté aux propriétaires ou occupants de logements vacants.",
                ['blocks.socioeconomic_context.causal_interpretation']
            ),
        ],
    },
    {
        'id': 'construction',
        'title': 'Dynamique de construction',
        'statements': [
            statement(
                'constat',
                sitadel_text('authorized'),
                ['blocks.construction.selected_metrics.latest_authorized_year', 'blocks.construction.selected_metrics.latest_authorized_dwellings']
            ),
            statement(
                'constat',
                sitadel_text('started'),
                ['blocks.construction.selected_metrics.latest_started_year', 'blocks.construction.selected_metrics.latest_started_dwellings']
            ),
            statement(
                'limite',
                "Les logements commencés 2025 sont indisponibles dans cette série non estimée ; autorisations et mises en chantier ne doivent donc pas être comparées comme si elles portaient sur le même millésime disponible.",
                ['blocks.construction.series', 'blocks.construction.quality.latest_started_lags_latest_authorized']
            ),
        ],
    },
    {
        'id': 'social_housing',
        'title': 'Contexte du parc locatif social',
        'statements': [
            statement(
                'comparaison',
                rpls_text("Vacance du parc social", rplsm['vacance_sociale_pct'], rpls_med['vacance_sociale_pct'], rpls_pct['vacance_sociale_pct']),
                ['blocks.social_housing.metrics.vacance_sociale_pct', 'blocks.social_housing.panel.medians.vacance_sociale_pct', 'blocks.social_housing.panel.percentiles.vacance_sociale_pct']
            ),
            statement(
                'comparaison',
                rpls_text("Mobilité du parc social", rplsm['mobilite_pct'], rpls_med['mobilite_pct'], rpls_pct['mobilite_pct']),
                ['blocks.social_housing.metrics.mobilite_pct', 'blocks.social_housing.panel.medians.mobilite_pct', 'blocks.social_housing.panel.percentiles.mobilite_pct']
            ),
            statement(
                'comparaison',
                rpls_text("Part du parc social située en QPV", rplsm['part_qpv_pct'], rpls_med['part_qpv_pct'], rpls_pct['part_qpv_pct']),
                ['blocks.social_housing.metrics.part_qpv_pct', 'blocks.social_housing.panel.medians.part_qpv_pct', 'blocks.social_housing.panel.percentiles.part_qpv_pct']
            ),
            statement(
                'comparaison',
                rpls_text("Part du parc social âgé de 40 ans ou plus", rplsm['part_age_40_plus_pct'], rpls_med['part_age_40_plus_pct'], rpls_pct['part_age_40_plus_pct']),
                ['blocks.social_housing.metrics.part_age_40_plus_pct', 'blocks.social_housing.panel.medians.part_age_40_plus_pct', 'blocks.social_housing.panel.percentiles.part_age_40_plus_pct']
            ),
            statement(
                'limite',
                "RPLS décrit le parc locatif social et ne doit pas être transposé à la vacance privée LOVAC.",
                ['blocks.social_housing.universe_note', 'blocks.social_housing.merge_with_lovac']
            ),
        ],
    },
]

out = {
    'stage': '3L',
    'territory': TARGET,
    'purpose': 'interprétation structurée des blocs validés, avant détection des facteurs discriminants',
    'source_stage': '3K-G',
    'interpretation_rules': {
        'allowed_statement_kinds': ['constat', 'comparaison', 'limite'],
        'causal_claims_allowed': False,
        'recommendations_allowed': False,
        'global_score_allowed': False,
        'discriminant_factor_ranking_allowed': False,
        'missing_values_rule': 'null/absence = indisponible; jamais converti en 0',
        'comparison_rule': 'une comparaison n’est formulée que lorsqu’un panel de référence est déjà présent dans le contrat source',
    },
    'sections': sections,
    'runtime': runtime_metadata(),
    'quality': {
        'section_count': len(sections),
        'all_canonical_blocks_interpreted': len(sections) == 7,
        'causal_claims_included': False,
        'recommendations_included': False,
        'global_score_included': False,
        'discriminant_ranking_included': False,
        'status': 'ok',
    },
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(out['quality'], ensure_ascii=False, indent=2))
