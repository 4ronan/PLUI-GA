import json, re
from pathlib import Path

ROOT=Path('scripts')
OUT=Path('output/diagnostic-3s-generalization-audit.json')

PIPELINE=[
 'lovac_3kb_contract.py',
 'insee_log1_3kc_contract.py',
 'dvf_3kd_contract.py',
 'sitadel_3ke_contract.py',
 'rpls_3kf_contract.py',
 'insee_3jc_contract.py',
 'filosofi_panel_contract_3icde.py',
 'diagnostic_3kg_assembly.py',
 'diagnostic_3l_interpretation.py',
 'diagnostic_3m_discriminants.py',
 'diagnostic_3mp_missing_panels.py',
 'diagnostic_3m2_discriminants_extended.py',
 'diagnostic_3n_hypotheses.py',
 'diagnostic_3o_synthesis.py',
 'diagnostic_3p_levers.py',
 'diagnostic_3q_prioritization.py',
 'diagnostic_3r_page.py',
]

patterns={
 'hardcoded_target_code': re.compile(r"['\"]16015['\"]"),
 'hardcoded_angouleme_label': re.compile(r'Angoul[eê]me',re.I),
 'target_assignment': re.compile(r'^\s*TARGET\s*=',re.M),
 'panel_codes_assignment': re.compile(r'^\s*PANEL_CODES\s*=',re.M),
 'hardcoded_target_assertion': re.compile(r"territory[^\n]{0,80}16015|16015[^\n]{0,80}territory",re.I),
}

rows=[]
for name in PIPELINE:
    p=ROOT/name
    if not p.exists():
        rows.append({'file':str(p),'exists':False,'blockers':['missing_file']})
        continue
    text=p.read_text(encoding='utf-8')
    hits={k:len(rx.findall(text)) for k,rx in patterns.items()}
    blockers=[k for k,v in hits.items() if v]
    rows.append({
      'file':str(p),
      'exists':True,
      'hits':hits,
      'blockers':blockers,
      'generalized':len(blockers)==0,
    })

blocking=[r for r in rows if r.get('blockers')]
target_files=[r['file'] for r in blocking if 'hardcoded_target_code' in r.get('blockers',[]) or 'target_assignment' in r.get('blockers',[])]
label_files=[r['file'] for r in blocking if 'hardcoded_angouleme_label' in r.get('blockers',[])]
panel_files=[r['file'] for r in blocking if 'panel_codes_assignment' in r.get('blockers',[])]

out={
 'stage':'3S-A',
 'purpose':'auditer les dépendances codées en dur empêchant l’exécution du pipeline pour une commune arbitraire',
 'runtime_contract_target':{
   'territory_env':'DIAG_TERRITORY',
   'commune_name_env':'DIAG_COMMUNE_NAME',
   'panel_codes_env':'DIAG_PANEL_CODES',
   'default_allowed_for_tests':'16015 uniquement dans les tests de non-régression, jamais comme valeur métier implicite',
 },
 'rules':{
   'no_runtime_llm':True,
   'territory_must_be_parameterized':True,
   'commune_label_must_be_parameterized':True,
   'comparison_panel_must_be_parameterized_or_generated':True,
   'angouleme_may_remain_only_in_regression_tests':True,
 },
 'files':rows,
 'summary':{
   'pipeline_file_count':len(rows),
   'blocking_file_count':len(blocking),
   'target_hardcoding_file_count':len(target_files),
   'label_hardcoding_file_count':len(label_files),
   'panel_hardcoding_file_count':len(panel_files),
   'ready_for_any_commune':len(blocking)==0,
 },
 'next_refactor_order':[
   'source contracts: LOVAC, INSEE LOG1, DVF, Sitadel, RPLS, INSEE démographie, Filosofi',
   'panel materialization and comparison contracts',
   'assembly and interpretation layers 3K-G to 3Q',
   'final page 3R and commune label',
 ],
 'quality':{
   'all_pipeline_files_present':all(r.get('exists') for r in rows),
   'audit_deterministic':True,
   'llm_used':False,
   'status':'ok',
 }
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'summary':out['summary'],'blocking_files':[r['file'] for r in blocking]},ensure_ascii=False,indent=2))
