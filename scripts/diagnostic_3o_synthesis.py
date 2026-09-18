import json
from pathlib import Path
from diagnostic_runtime import target, runtime_metadata

P3L=Path('output/diagnostic-3l-interpretation.json')
P3M2=Path('output/diagnostic-3m2-discriminants.json')
P3N=Path('output/diagnostic-3n-hypotheses.json')
OUT=Path('output/diagnostic-3o-synthesis.json')
TARGET=target()

for p in (P3L,P3M2,P3N):
    if not p.exists() or p.stat().st_size==0:
        raise RuntimeError(f'Entrée absente ou vide: {p}')

s3l=json.loads(P3L.read_text(encoding='utf-8'))
s3m=json.loads(P3M2.read_text(encoding='utf-8'))
s3n=json.loads(P3N.read_text(encoding='utf-8'))

if s3l.get('stage')!='3L' or s3m.get('stage')!='3M-2' or s3n.get('stage')!='3N':
    raise RuntimeError('Étapes amont inattendues')
if any(str(x.get('territory'))!=TARGET for x in (s3l,s3m,s3n)):
    raise RuntimeError('Territoire inattendu')
if any(x.get('quality',{}).get('status')!='ok' for x in (s3l,s3m,s3n)):
    raise RuntimeError('Une étape amont n’est pas validée')

sections={x['id']:x for x in s3l['sections']}
factors={x['id']:x for x in s3m['discriminant_factors']+s3m['non_discriminant_comparators']}
hypotheses={x['id']:x for x in s3n['hypotheses']}
guards={x['id']:x for x in s3n['guardrails']}

required_sections={'vacancy_private','vacant_stock_profile','real_estate_market','demography_housing','socioeconomic_context','construction','social_housing'}
if set(sections)!=required_sections:
    raise RuntimeError(f'Sections 3L inattendues: {sorted(sections)}')

# 3O n'invente aucun texte analytique libre: il assemble uniquement des constats,
# facteurs et hypothèses déjà matérialisés aux étapes amont selon une structure fixe.

def texts(section_id,kinds=None):
    rows=sections[section_id]['statements']
    if kinds is None:
        return [r['text'] for r in rows]
    return [r['text'] for r in rows if r['kind'] in kinds]


def factor_view(fid):
    x=factors[fid]
    return {
        'id':x['id'],'label':x['label'],'value':x['value'],'panel_median':x['panel_median'],
        'percentile':x['percentile'],'direction':x['direction'],'strength':x['strength'],
        'is_discriminant':x['is_discriminant'],'domain':x['domain'],'universe':x['universe'],
        'reference_panel_n':x.get('reference_panel_n'),
        'minimum_reference_panel_n':x.get('minimum_reference_panel_n'),
        'comparison_sufficient':x.get('comparison_sufficient', True)
    }

synthesis={
    'vacancy_status':{
        'title':'Niveau et nature de la vacance privée',
        'constats':texts('vacancy_private',{'constat'}),
        'comparison':[
            factor_view('private_vacancy_rate'),
            factor_view('private_structural_vacancy_rate'),
        ],
        'reading':'vacance privée discriminante dans le panel' if (factors['private_vacancy_rate']['is_discriminant'] or factors['private_structural_vacancy_rate']['is_discriminant']) else 'vacance privée non discriminante dans le panel',
        'guardrail':guards.get('G1_no_relative_excess_private_vacancy',{}).get('statement'),
    },
    'vacant_stock_profile':{
        'title':'Profil des logements vacants',
        'constats':texts('vacant_stock_profile',{'constat'}),
        'comparison':[
            factor_view('vacant_apartment_share'),
            factor_view('vacant_1946_1990_share'),
        ],
        'reading':(
            'profil des logements vacants indisponible ou non comparable'
            if factors['vacant_apartment_share'].get('percentile') is None or factors['vacant_1946_1990_share'].get('percentile') is None
            else ('profil des logements vacants discriminant dans le panel'
                  if (factors['vacant_apartment_share']['is_discriminant'] or factors['vacant_1946_1990_share']['is_discriminant'])
                  else 'profil des logements vacants non discriminant dans le panel')
        ),
        'guardrail':guards.get('G2_no_atypical_vacant_profile',{}).get('statement'),
    },
    'market_context':{
        'title':'Contexte immobilier',
        'constats':texts('real_estate_market',{'constat'}),
        'discriminants':[factor_view('dvf_median_price_m2')],
    },
    'demographic_residential_context':{
        'title':'Dynamique démographique et résidentielle',
        'constats':texts('demography_housing',{'constat','comparaison'}),
        'comparators':[
            factor_view('population_change'),factor_view('households_change'),factor_view('secondary_homes_share')
        ],
    },
    'socioeconomic_context':{
        'title':'Contexte socio-économique',
        'constats':texts('socioeconomic_context',{'comparaison'}),
        'discriminants':[factor_view('median_income'),factor_view('poverty_rate')],
    },
    'construction_context':{
        'title':'Dynamique de construction',
        'constats':texts('construction',{'constat'}),
        'comparators':[factor_view('sitadel_authorized_intensity'),factor_view('sitadel_started_intensity')],
    },
    'social_housing_context':{
        'title':'Parc locatif social',
        'constats':texts('social_housing',{'comparaison'}),
        'discriminants':[factor_view('social_mobility'),factor_view('social_qpv_share')],
        'comparators':[factor_view('social_vacancy'),factor_view('social_age_40_plus')],
    },
}

hypothesis_views=[]
for h in s3n['hypotheses']:
    hypothesis_views.append({
        'id':h['id'],'title':h['title'],'statement':h['statement'],'confidence':h['confidence'],
        'confidence_meaning':h['confidence_meaning'],'supporting_factor_ids':h['supporting_factor_ids'],
        'supporting_domains':h['supporting_domains'],'applicability':h['applicability'],'cautions':h['cautions']
    })

out={
    'stage':'3O',
    'territory':TARGET,
    'source_stages':['3L','3M-2','3N'],
    'purpose':'assembler un diagnostic synthétique hiérarchisé uniquement à partir des sorties validées du diagnostic',
    'generation':{
        'mode':'deterministic_assembly',
        'llm_used':False,
        'external_knowledge_used':False,
        'web_used':False,
        'network_calls':False,
        'free_text_generation':False,
        'input_scope':['output/diagnostic-3l-interpretation.json','output/diagnostic-3m2-discriminants.json','output/diagnostic-3n-hypotheses.json'],
    },
    'headline':{
        'private_vacancy_discriminant':factors['private_vacancy_rate']['is_discriminant'],
        'structural_private_vacancy_discriminant':factors['private_structural_vacancy_rate']['is_discriminant'],
        'discriminant_factor_count':len(s3m['discriminant_factors']),
        'hypothesis_count':len(s3n['hypotheses']),
        'interpretation':('la vacance privée présente un écart discriminant dans le panel; ce constat reste descriptif et sans causalité automatique' if (factors['private_vacancy_rate']['is_discriminant'] or factors['private_structural_vacancy_rate']['is_discriminant']) else 'la vacance privée n’est pas atypique dans le panel; le diagnostic met en évidence des contextes discriminants distincts à examiner sans causalité automatique'),
    },
    'synthesis':synthesis,
    'discriminant_factors':[factor_view(x['id']) for x in s3m['discriminant_factors']],
    'hypotheses':hypothesis_views,
    'limits':[
        *texts('vacancy_private',{'limite'}),
        *texts('vacant_stock_profile',{'limite'}),
        *texts('real_estate_market',{'limite'}),
        *texts('demography_housing',{'limite'}),
        *texts('socioeconomic_context',{'limite'}),
        *texts('construction',{'limite'}),
        *texts('social_housing',{'limite'}),
    ],
    'rules':{
        'causal_claims_allowed':False,
        'recommendations_allowed':False,
        'global_score_allowed':False,
        'ranking_allowed':False,
        'universe_separation_rule':'LOVAC, INSEE RP et RPLS restent distincts',
    },
    'runtime':runtime_metadata(),
    'quality':{
        'synthesis_block_count':len(synthesis),
        'all_7_domains_present':len(synthesis)==7,
        'discriminant_factor_count':len(s3m['discriminant_factors']),
        'hypothesis_count':len(hypothesis_views),
        'all_hypotheses_from_3n':all(h['id'] in hypotheses for h in hypothesis_views),
        'llm_used':False,
        'external_knowledge_used':False,
        'causal_claims_included':False,
        'recommendations_included':False,
        'global_score_included':False,
        'status':'ok',
    }
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'quality':out['quality'],'headline':out['headline']},ensure_ascii=False,indent=2))
