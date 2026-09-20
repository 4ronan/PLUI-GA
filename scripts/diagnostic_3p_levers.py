import json
from pathlib import Path
from diagnostic_runtime import target, runtime_metadata

IN=Path('output/diagnostic-3o-synthesis.json')
OUT=Path('output/diagnostic-3p-levers.json')
TARGET=target()

if not IN.exists() or IN.stat().st_size==0:
    raise RuntimeError('Entrée 3O absente ou vide')

d=json.loads(IN.read_text(encoding='utf-8'))
if d.get('stage')!='3O':
    raise RuntimeError('Entrée attendue: 3O')
if str(d.get('territory'))!=TARGET:
    raise RuntimeError('Territoire inattendu')
if d.get('quality',{}).get('status')!='ok':
    raise RuntimeError('3O non validé')
if d.get('generation',{}).get('llm_used') is not False:
    raise RuntimeError('3O doit être déterministe')

factors={x['id']:x for x in d.get('discriminant_factors',[])}
hypotheses={x['id']:x for x in d.get('hypotheses',[])}

# Les comparateurs non discriminants sont conservés dans les blocs de synthèse.
comparators={}
for block in d.get('synthesis',{}).values():
    for key in ('comparison','comparators','discriminants'):
        for x in block.get(key,[]) or []:
            if isinstance(x,dict) and x.get('id'):
                comparators[x['id']]=x

def has_factor(fid):
    return fid in factors

def has_hypothesis(hid):
    return hid in hypotheses

def lever(lid,title,family,trigger_type,trigger_ids,objective,actions,limits):
    return {
        'id':lid,
        'title':title,
        'family':family,
        'trigger_type':trigger_type,
        'trigger_ids':trigger_ids,
        'objective':objective,
        'actions':actions,
        'limits':limits,
        'priority_assigned':False,
        'causal_effect_claimed':False,
        'effectiveness_claimed':False,
    }

levers=[]

# L1 — Vacance privée non atypique : pas de stratégie de réduction massive déclenchée automatiquement.
pv=comparators.get('private_vacancy_rate')
ps=comparators.get('private_structural_vacancy_rate')
if pv and ps and pv.get('comparison_sufficient', True) and ps.get('comparison_sufficient', True) and not pv.get('is_discriminant') and not ps.get('is_discriminant'):
    levers.append(lever(
        'L1_private_vacancy_monitoring',
        'Qualifier et localiser la vacance privée avant toute intervention ciblée',
        'observation_et_qualification',
        'guardrail',
        ['private_vacancy_rate','private_structural_vacancy_rate'],
        "Éviter de déduire d'un taux communal non atypique qu'une intervention générale est nécessaire; concentrer l'étape suivante sur la localisation et la qualification de la vacance durable.",
        [
            'suivre séparément vacance totale et vacance de plus de deux ans',
            'localiser les concentrations infra-communales si une donnée compatible est disponible',
            'vérifier les situations individuelles ou micro-territoriales avant de choisir un outil opérationnel',
        ],
        [
            'Le diagnostic communal ne montre pas de sur-vacance relative par rapport au panel.',
            'Ce levier est un levier de connaissance, pas une mesure de remise sur le marché.',
        ]
    ))

# L2 — Convergence socio-économique / marché : vérifier la faisabilité économique locale.
if has_hypothesis('H1_socioeconomic_market_convergence'):
    levers.append(lever(
        'L2_market_feasibility_check',
        'Tester la faisabilité économique de la remise sur le marché',
        'qualification_economique',
        'hypothesis',
        ['H1_socioeconomic_market_convergence','median_income','poverty_rate','dvf_median_price_m2'],
        "Documenter si les conditions locales de revenus et de prix peuvent limiter certaines opérations de remise sur le marché, sans présumer que ce contexte cause la vacance.",
        [
            'comparer coûts prévisionnels de remise en état et valeurs de marché locales',
            'identifier les segments de logements pour lesquels l’écart économique est le plus important',
            'documenter les besoins éventuels d’accompagnement avant de sélectionner un dispositif',
        ],
        [
            'Filosofi ne décrit pas les propriétaires de logements vacants.',
            'DVF ne décrit que les mutations observées.',
            'Le diagnostic ne démontre aucun lien causal avec la vacance privée.',
        ]
    ))

# L3 — Décalage autorisations / commencements : vérification de chaîne de production.
if has_hypothesis('H2_construction_pipeline_gap'):
    levers.append(lever(
        'L3_construction_pipeline_review',
        'Analyser le passage des autorisations aux mises en chantier',
        'suivi_de_la_production',
        'hypothesis',
        ['H2_construction_pipeline_gap','sitadel_authorized_intensity','sitadel_started_intensity'],
        "Vérifier le décalage observé entre autorisations et mises en chantier avant toute interprétation de la dynamique de production.",
        [
            'examiner les opérations autorisées non encore commencées sur les millésimes disponibles',
            'distinguer décalage temporel, abandon, report et retard de déclaration lorsque ces informations sont disponibles',
            'mettre à jour l’analyse quand un millésime Sitadel plus complet devient disponible',
        ],
        [
            'Les autorisations et les commencements comparés ne portent pas sur le même millésime.',
            'Les séries communales Sitadel non estimées peuvent être incomplètes.',
        ]
    ))

# L4 — Parc social : contexte distinct, non transposable à LOVAC.
if has_hypothesis('H3_social_housing_configuration'):
    levers.append(lever(
        'L4_social_housing_context_coordination',
        'Traiter le parc social comme un contexte distinct dans l’analyse territoriale',
        'coordination_contextuelle',
        'hypothesis',
        ['H3_social_housing_configuration','social_mobility','social_qpv_share'],
        "Intégrer la configuration spécifique du parc social dans la lecture territoriale sans l’utiliser comme explication automatique de la vacance privée.",
        [
            'maintenir des indicateurs séparés entre RPLS et LOVAC',
            'croiser les constats territoriaux uniquement à des échelles compatibles',
            'réserver les actions sur le parc social à son propre diagnostic opérationnel',
        ],
        [
            'RPLS et LOVAC décrivent des univers différents.',
            'Aucune transposition vers les propriétaires ou logements vacants privés n’est autorisée.',
        ]
    ))

# Garde-fou : aucun levier de ciblage par type/âge de logement n'est généré si LOG1 n'est pas discriminant.
profile=d.get('synthesis',{}).get('vacant_stock_profile',{})
profile_reading=profile.get('reading')
profile_non_discriminant = profile_reading=='profil des logements vacants non discriminant dans le panel'
profile_unavailable = profile_reading=='profil des logements vacants indisponible ou non comparable'

suppressed_levers=[]
if pv and ps and pv.get('comparison_sufficient', True) and ps.get('comparison_sufficient', True) and not pv.get('is_discriminant') and not ps.get('is_discriminant'):
    suppressed_levers.append({
        'id':'S1_mass_private_vacancy_reduction',
        'reason':'non déclenché car vacance privée et vacance >2 ans non discriminantes dans un panel suffisamment renseigné'
    })
elif pv and ps and (not pv.get('comparison_sufficient', True) or not ps.get('comparison_sufficient', True)):
    suppressed_levers.append({
        'id':'S1_mass_private_vacancy_reduction',
        'reason':'non déclenché car la comparaison de la vacance privée au panel est insuffisante'
    })
if profile_non_discriminant:
    suppressed_levers.append({
        'id':'S2_target_by_vacant_dwelling_profile',
        'reason':'non déclenché car profil INSEE des logements vacants non discriminant dans le panel'
    })
elif profile_unavailable:
    suppressed_levers.append({
        'id':'S2_target_by_vacant_dwelling_profile',
        'reason':'non déclenché car profil INSEE des logements vacants indisponible ou non comparable'
    })

out={
    'stage':'3P',
    'territory':TARGET,
    'source_stage':'3O',
    'purpose':'associer des familles de leviers explicites aux constats et hypothèses du diagnostic sans IA, sans priorisation et sans promesse d’efficacité',
    'generation':{
        'mode':'deterministic_rule_engine',
        'llm_used':False,
        'external_knowledge_lookup_used':False,
        'web_used':False,
        'network_calls':False,
        'free_text_generation':False,
        'input_scope':'uniquement output/diagnostic-3o-synthesis.json',
        'catalogue':'règles et familles de leviers codées statiquement dans le script',
    },
    'rules':{
        'lever_requires_diagnostic_trigger':True,
        'causal_claims_allowed':False,
        'effectiveness_claims_allowed':False,
        'priority_assignment_allowed':False,
        'automatic_prescription_allowed':False,
        'no_mass_private_vacancy_action_if_not_discriminant':True,
        'no_normality_guardrail_if_panel_insufficient':True,
        'no_stock_profile_targeting_if_profile_not_discriminant':True,
        'universe_separation_rule':'LOVAC, INSEE RP et RPLS restent distincts',
    },
    'levers':levers,
    'suppressed_levers':suppressed_levers,
    'runtime':runtime_metadata(),
    'quality':{
        'lever_count':len(levers),
        'all_levers_have_triggers':all(bool(x['trigger_ids']) for x in levers),
        'all_levers_unprioritized':all(x['priority_assigned'] is False for x in levers),
        'causal_claims_included':False,
        'effectiveness_claims_included':False,
        'automatic_prescriptions_included':False,
        'llm_used':False,
        'external_knowledge_lookup_used':False,
        'profile_guardrail_respected':(
            ((profile_non_discriminant or profile_unavailable) and any(x['id']=='S2_target_by_vacant_dwelling_profile' for x in suppressed_levers))
            or ((not profile_non_discriminant and not profile_unavailable) and not any(x['id']=='S2_target_by_vacant_dwelling_profile' for x in suppressed_levers))
        ),
        'status':'ok'
    }
}

if not out['quality']['all_levers_have_triggers']:
    raise RuntimeError('Levier sans déclencheur diagnostique')
if not out['quality']['profile_guardrail_respected']:
    raise RuntimeError('Garde-fou profil vacant non respecté')

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({
    'quality':out['quality'],
    'lever_ids':[x['id'] for x in levers],
    'suppressed_ids':[x['id'] for x in out['suppressed_levers']]
},ensure_ascii=False,indent=2))
