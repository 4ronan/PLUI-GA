import json
from pathlib import Path
from diagnostic_runtime import target, runtime_metadata

TARGET = target()
OUT = Path('output/diagnostic-3kg-assembly.json')

SOURCES = {
    'vacancy_private': ('output/lovac-3kb-contract.json', None),
    'vacant_stock_profile': ('output/insee-log1-3kc-contract.json', None),
    'real_estate_market': ('output/dvf-3kd-contract.json', None),
    'construction': ('output/sitadel-3ke-contract.json', None),
    'social_housing': ('output/rpls-3kf-contract.json', None),
    'demography_housing': ('output/insee-3jc-contract.json', None),
    'socioeconomic_context': ('output/filosofi-3icde-panel.json', 'contract'),
}


def load_contract(path, nested=None):
    p = Path(path)
    if not p.exists() or p.stat().st_size == 0:
        raise RuntimeError(f'Contrat absent ou vide: {path}')
    data = json.loads(p.read_text(encoding='utf-8'))
    if nested:
        data = data.get(nested)
        if not isinstance(data, dict):
            raise RuntimeError(f'Contrat imbriqué {nested!r} absent dans {path}')
    return data

blocks = {name: load_contract(path, nested) for name, (path, nested) in SOURCES.items()}

DATA_AVAILABILITY_POLICY = {
    'vacancy_private': 'required_core',
    'vacant_stock_profile': 'contextual',
    'real_estate_market': 'contextual_partial_allowed',
    'construction': 'contextual_partial_allowed',
    'social_housing': 'contextual',
    'demography_housing': 'contextual',
    'socioeconomic_context': 'contextual_missing_values_allowed',
}

checks = []
for name, block in blocks.items():
    territory = str(block.get('territory', ''))
    ok_territory = territory == TARGET
    if not ok_territory:
        raise RuntimeError(f'Territoire incohérent pour {name}: {territory}')

    # Tous les blocs contextuels doivent interdire la fusion sémantique avec LOVAC.
    if name != 'vacancy_private':
        if block.get('merge_with_lovac') is not False:
            raise RuntimeError(f'{name}: merge_with_lovac doit être false')
        if block.get('causal_interpretation') is not False:
            raise RuntimeError(f'{name}: causal_interpretation doit être false')

    checks.append({
        'block': name,
        'territory_ok': ok_territory,
        'source': block.get('source'),
        'scope': block.get('scope'),
        'role': block.get('role'),
        'quality_status': (block.get('quality') or {}).get('status'),
        'availability_policy': DATA_AVAILABILITY_POLICY[name],
    })

# Verrous minimaux des contrats déjà validés.
lovac = blocks['vacancy_private']
lovac_metrics = lovac.get('metrics', {})
if lovac_metrics.get('latest_compatible_rate_year') != 2025:
    raise RuntimeError('LOVAC: dernière année de taux compatible attendue = 2025')
required_lovac_metrics = {
    'vacancy_rate_pct': 'taux de vacance privée 2025',
    'structural_vacancy_rate_pct': 'taux de vacance privée >2 ans 2025',
    'vacant_all_count_2026': 'nombre de logements vacants 2026',
    'vacant_gt2y_count_2026': 'nombre de logements vacants >2 ans 2026',
}
missing_core = [label for key,label in required_lovac_metrics.items() if lovac_metrics.get(key) is None]
if missing_core:
    raise RuntimeError('LOVAC_CORE_UNAVAILABLE: ' + '; '.join(missing_core))

log1 = blocks['vacant_stock_profile']
if log1.get('year') != 2023:
    raise RuntimeError('INSEE LOG1: millésime attendu = 2023')
if log1.get('merge_with_lovac') is not False:
    raise RuntimeError('INSEE LOG1 ne doit pas être fusionné avec LOVAC')

dvf = blocks['real_estate_market']
if dvf.get('years') != [2021, 2022, 2023, 2024, 2025]:
    raise RuntimeError('DVF: fenêtre reproductible attendue 2021-2025')

sitadel = blocks['construction']
if sitadel.get('quality', {}).get('status') not in {'ok','partial'}:
    raise RuntimeError('Sitadel: qualité non validée')

rpls = blocks['social_housing']
if rpls.get('quality', {}).get('status') != 'ok':
    raise RuntimeError('RPLS: qualité non validée')

assembly = {
    'stage': '3K-G',
    'territory': TARGET,
    'purpose': 'assemblage machine des blocs validés avant interprétation diagnostique',
    'diagnostic_interpretation_included': False,
    'global_score_included': False,
    'causal_claims_included': False,
    'canonical_order': [
        'vacancy_private',
        'vacant_stock_profile',
        'real_estate_market',
        'demography_housing',
        'socioeconomic_context',
        'construction',
        'social_housing',
    ],
    'data_availability_policy': DATA_AVAILABILITY_POLICY,
    'methodological_boundaries': {
        'lovac_role': 'source principale pour la vacance privée et la vacance durable >2 ans',
        'insee_log1_role': 'profil du parc vacant au recensement; univers distinct de LOVAC',
        'dvf_role': 'contexte de marché immobilier; descriptif, non causal',
        'sitadel_role': 'dynamique de construction; descriptif, non causal',
        'rpls_role': 'contexte du parc locatif social; ne pas transposer à LOVAC',
        'filosofi_role': 'contexte socio-économique communal; aucune attribution individuelle aux logements vacants',
        'demography_role': 'dynamique démographique et résidentielle; descriptive, non causale',
        'missing_values': 'null/absence = indisponible; jamais converti automatiquement en 0',
    },
    'checks': checks,
    'blocks': blocks,
    'runtime': runtime_metadata(),
    'quality': {
        'expected_blocks': len(SOURCES),
        'loaded_blocks': len(blocks),
        'all_same_territory': all(c['territory_ok'] for c in checks),
        'ready_for_interpretation_layer': len(blocks) == len(SOURCES),
        'status': 'ok',
    },
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(assembly, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(assembly['quality'], ensure_ascii=False, indent=2))
