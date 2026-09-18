import json
from pathlib import Path

INP=Path('output/diagnostic-3p-levers.json')
OUT=Path('output/diagnostic-3q-priorities.json')
TARGET='16015'

if not INP.exists() or INP.stat().st_size==0:
    raise RuntimeError('Entrée 3P absente ou vide')
d=json.loads(INP.read_text(encoding='utf-8'))
if d.get('stage')!='3P' or str(d.get('territory'))!=TARGET:
    raise RuntimeError('Entrée 3P inattendue')
if d.get('quality',{}).get('status')!='ok':
    raise RuntimeError('3P non validé')
if d.get('generation',{}).get('llm_used') is not False:
    raise RuntimeError('3P doit être déterministe')

levers={x['id']:x for x in d.get('levers',[])}
required={
 'L1_private_vacancy_monitoring',
 'L2_market_feasibility_check',
 'L3_construction_pipeline_review',
 'L4_social_housing_context_coordination',
}
if set(levers)!=required:
    raise RuntimeError(f'Leviers 3P inattendus: {sorted(levers)}')

# 3Q ne calcule aucun score composite. Il classe seulement les sujets selon
# leur rôle opérationnel déjà explicite dans 3P et leur proximité avec
# l'objet principal du diagnostic: la vacance privée.
RULES={
 'L1_private_vacancy_monitoring':{
   'priority_class':'prealable',
   'order':1,
   'reason':'qualification nécessaire avant toute intervention ciblée sur la vacance privée',
   'decision_gate':'ne pas choisir un outil opérationnel tant que la localisation et la nature de la vacance durable ne sont pas suffisamment qualifiées',
   'local_data_to_verify':[
      'localisation infra-communale des logements vacants durables',
      'statut et état apparent des logements ciblés lorsque disponible',
      'ancienneté réelle de la vacance à l’échelle du logement lorsque disponible',
      'existence d’opérations ou dispositifs déjà engagés sur les secteurs concernés'
   ]
 },
 'L2_market_feasibility_check':{
   'priority_class':'approfondissement_direct',
   'order':2,
   'reason':'hypothèse de contexte à confiance moyenne directement utile pour apprécier la faisabilité de remise sur le marché',
   'decision_gate':'ne pas déduire qu’un soutien économique est nécessaire avant comparaison locale entre coûts, valeurs et caractéristiques du parc',
   'local_data_to_verify':[
      'coûts estimatifs de remise en état ou réhabilitation',
      'valeurs de vente et loyers observables à proximité',
      'typologie, surface et état des logements concernés',
      'écart entre coût de remise sur le marché et valeur économique locale'
   ]
 },
 'L3_construction_pipeline_review':{
   'priority_class':'verification_contextuelle',
   'order':3,
   'reason':'hypothèse à confiance faible portant sur la dynamique de production et non sur une cause démontrée de vacance',
   'decision_gate':'vérifier le décalage autorisations/mises en chantier avant toute interprétation territoriale',
   'local_data_to_verify':[
      'opérations autorisées non commencées',
      'date d’autorisation et date réelle de démarrage',
      'abandons, reports ou retards connus',
      'actualisation Sitadel lorsque les millésimes deviennent plus complets'
   ]
 },
 'L4_social_housing_context_coordination':{
   'priority_class':'contexte_separe',
   'order':4,
   'reason':'élément de contexte territorial à faible confiance pour l’objet vacance privée et relevant d’un univers statistique distinct',
   'decision_gate':'ne pas transposer les constats RPLS au parc privé',
   'local_data_to_verify':[
      'évolution propre de la vacance et de la mobilité du parc social',
      'répartition spatiale du parc social et des QPV',
      'diagnostics habitat ou politique de la ville déjà disponibles'
   ]
 }
}

priorities=[]
for lid in sorted(levers, key=lambda x:RULES[x]['order']):
    l=levers[lid]
    r=RULES[lid]
    priorities.append({
      'lever_id':lid,
      'title':l['title'],
      'priority_class':r['priority_class'],
      'order':r['order'],
      'reason':r['reason'],
      'decision_gate':r['decision_gate'],
      'local_data_to_verify':r['local_data_to_verify'],
      'trigger_type':l['trigger_type'],
      'trigger_ids':l['trigger_ids'],
      'objective':l['objective'],
      'actions_from_3p':l['actions'],
      'limits_from_3p':l['limits'],
      'effectiveness_claimed':False
    })

out={
 'stage':'3Q',
 'territory':TARGET,
 'source_stage':'3P',
 'purpose':'ordonner les sujets à examiner et les vérifications locales préalables à partir des seuls leviers diagnostiques de 3P',
 'generation':{
   'mode':'deterministic_operational_ordering',
   'llm_used':False,
   'external_knowledge_lookup_used':False,
   'web_used':False,
   'network_calls':False,
   'free_text_generation':False,
   'input_scope':'uniquement output/diagnostic-3p-levers.json',
   'scoring_used':False,
   'rule_basis':'rôle du levier, proximité avec la vacance privée et niveau de confiance déjà matérialisés dans les étapes amont'
 },
 'rules':{
   'global_score_allowed':False,
   'effectiveness_ranking_allowed':False,
   'automatic_prescription_allowed':False,
   'priority_meaning':'ordre d’examen et de vérification, pas classement d’efficacité',
   'missing_local_data_blocks_prescription':True,
   'universe_separation_rule':'LOVAC, INSEE RP et RPLS restent distincts'
 },
 'priorities':priorities,
 'suppressed_levers':d.get('suppressed_levers',[]),
 'quality':{
   'priority_count':len(priorities),
   'orders_unique':len({x['order'] for x in priorities})==len(priorities),
   'all_priorities_traceable_to_3p':all(x['lever_id'] in levers for x in priorities),
   'all_have_local_verification':all(bool(x['local_data_to_verify']) for x in priorities),
   'llm_used':False,
   'external_knowledge_lookup_used':False,
   'global_score_included':False,
   'effectiveness_ranking_included':False,
   'automatic_prescriptions_included':False,
   'status':'ok'
 }
}

if not out['quality']['orders_unique']:
    raise RuntimeError('Ordres 3Q non uniques')
if not out['quality']['all_priorities_traceable_to_3p']:
    raise RuntimeError('Priorité non traçable vers 3P')

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'quality':out['quality'],'priorities':[(x['order'],x['lever_id'],x['priority_class']) for x in priorities]},ensure_ascii=False,indent=2))
