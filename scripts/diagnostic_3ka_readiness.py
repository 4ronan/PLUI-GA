import json
from pathlib import Path

# 3K-A — audit de préparation à l'assemblage du moteur de diagnostic.
# Principe : ne pas réinterpréter les blocs déjà validés ; vérifier seulement
# qu'ils disposent d'une sortie machine stable/reproductible sur la branche.

ROOT = Path('.')
OUT = ROOT / 'output' / 'diagnostic-3ka-readiness.json'
OUT.parent.mkdir(exist_ok=True)

blocks = [
    {
        'id': 'lovac',
        'label': 'Vacance privée LOVAC',
        'validated': True,
        'role': 'coeur_du_diagnostic',
        'machine_contract': None,
        'status': 'contract_to_materialize',
    },
    {
        'id': 'insee_vacant_profile',
        'label': 'Profil des logements vacants INSEE LOG1',
        'validated': True,
        'role': 'qualification_du_parc_vacant',
        'machine_contract': None,
        'status': 'contract_to_materialize',
    },
    {
        'id': 'dvf',
        'label': 'Contexte de marché DVF',
        'validated': True,
        'role': 'contexte_immobilier',
        'machine_contract': None,
        'status': 'contract_to_materialize',
    },
    {
        'id': 'sitadel',
        'label': 'Dynamique de construction Sitadel',
        'validated': True,
        'role': 'dynamique_de_construction',
        'machine_contract': None,
        'status': 'contract_to_materialize',
    },
    {
        'id': 'rpls',
        'label': 'Contexte parc social RPLS',
        'validated': True,
        'role': 'contexte_parc_social',
        'machine_contract': None,
        'support_files': [
            'data/rpls-2025-communes.csv',
            'data/rpls-2025-checks.json',
        ],
        'status': 'contract_to_materialize',
    },
    {
        'id': 'filosofi',
        'label': 'Contexte socio-économique Filosofi',
        'validated': True,
        'role': 'contexte_socio_economique',
        'machine_contract': 'scripts/filosofi_panel_contract_3icde.py',
        'status': 'reproducible_contract',
    },
    {
        'id': 'demography_housing',
        'label': 'Dynamique démographique et résidentielle INSEE',
        'validated': True,
        'role': 'contexte_demographique_residentiel',
        'machine_contract': 'scripts/insee_3jc_contract.py',
        'support_files': [
            'data/insee-rp2023-panel-3j.csv',
            'data/insee-rp2023-panel-3j-meta.json',
        ],
        'status': 'reproducible_contract',
    },
]

for b in blocks:
    contract = b.get('machine_contract')
    b['contract_exists'] = bool(contract and (ROOT / contract).exists())
    support = b.get('support_files', [])
    b['support_files_status'] = {
        p: (ROOT / p).exists() for p in support
    }
    if contract and not b['contract_exists']:
        b['status'] = 'missing_contract_file'
    if support and not all(b['support_files_status'].values()):
        b['status'] = 'missing_support_file'

ready = [b for b in blocks if b['status'] == 'reproducible_contract' and b['contract_exists']]
blockers = [b for b in blocks if b not in ready]

result = {
    'stage': '3K-A',
    'purpose': 'inventaire technique avant assemblage du moteur',
    'validated_blocks_n': sum(1 for b in blocks if b['validated']),
    'reproducible_contracts_n': len(ready),
    'blocks_n': len(blocks),
    'ready_for_full_assembly': len(blockers) == 0,
    'blocks': blocks,
    'blockers': [
        {
            'id': b['id'],
            'label': b['label'],
            'reason': b['status'],
        }
        for b in blockers
    ],
    'rule': (
        'Un bloc validé méthodologiquement n’est assemblé au moteur que lorsqu’il '
        'dispose d’un contrat machine stable/reproductible. Aucun chiffre validé '
        'n’est recalculé ni réinterprété pendant 3K-A.'
    ),
}

OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))

# 3K-A est un audit : il doit réussir même si l'assemblage complet n'est pas encore prêt.
assert result['validated_blocks_n'] == 7
assert result['reproducible_contracts_n'] >= 2
