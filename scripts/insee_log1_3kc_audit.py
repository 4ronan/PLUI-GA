import json
import subprocess
from pathlib import Path
from urllib.parse import urlencode

DATASET = 'DS_RP_TD_LOGEMENT_CARACT_PRINC'
TARGET = '16015'
YEAR = '2023'
BASE = 'https://api.insee.fr/melodi'
RANGE_URL = f'{BASE}/range/{DATASET}'
DATA_URL = f'{BASE}/data/{DATASET}?{urlencode({"GEO": f"COM-{TARGET}", "TIME_PERIOD": YEAR, "maxResult": 5000})}'
OUT = Path('output/insee-log1-3kc-audit.json')
TMP = Path('tmp_3kc')
TMP.mkdir(exist_ok=True)


def fetch_json(url: str, name: str):
    path = TMP / name
    subprocess.run([
        'curl', '--http1.1', '--fail', '--location', '--show-error', '--silent',
        '--retry', '4', '--retry-all-errors', '--retry-delay', '2',
        '--connect-timeout', '20', '--max-time', '180',
        '--header', 'Accept: application/json',
        '--output', str(path), url
    ], check=True)
    raw = path.read_text(encoding='utf-8-sig')
    try:
        return json.loads(raw), len(raw.encode('utf-8'))
    except json.JSONDecodeError as exc:
        preview = raw[:500].replace('\n', ' ')
        raise RuntimeError(f'Réponse non JSON pour {url}: {preview}') from exc


def lists_of_dicts(obj, path='$'):
    found = []
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj):
            found.append((path, obj))
        for i, value in enumerate(obj[:20]):
            found.extend(lists_of_dicts(value, f'{path}[{i}]'))
    elif isinstance(obj, dict):
        for key, value in obj.items():
            found.extend(lists_of_dicts(value, f'{path}.{key}'))
    return found


def scalar_fields(row):
    return {
        k: v for k, v in row.items()
        if v is None or isinstance(v, (str, int, float, bool))
    }


def find_data_rows(payload):
    candidates = lists_of_dicts(payload)
    if not candidates:
        return None, []
    # Priorité à une liste dont les objets ressemblent à des observations Melodi.
    def score(item):
        path, rows = item
        keys = set()
        for row in rows[:10]:
            keys.update(row.keys())
        markers = {'GEO', 'GEO_OBJECT', 'TIME_PERIOD', 'OBS_VALUE', 'FREQ'}
        return (len(keys & markers), len(rows))
    return max(candidates, key=score)


def flatten_range(payload):
    """Extrait les couples dimension/modalité sans dépendre d'un schéma JSON précis."""
    out = []
    seen = set()
    for path, rows in lists_of_dicts(payload):
        for row in rows:
            flat = scalar_fields(row)
            # Les noms rencontrés dans Melodi peuvent différer légèrement selon l'endpoint.
            dim = next((flat.get(k) for k in ('DIM', 'dimension', 'dimensionCode', 'codeDimension') if flat.get(k) is not None), None)
            mod = next((flat.get(k) for k in ('MOD', 'modality', 'modalityCode', 'codeModalite', 'code') if flat.get(k) is not None), None)
            label = next((flat.get(k) for k in ('MOD_LABEL', 'label', 'modalityLabel', 'libelle', 'Libelle') if flat.get(k) is not None), None)
            if dim is not None or mod is not None or label is not None:
                key = (str(dim), str(mod), str(label))
                if key not in seen:
                    seen.add(key)
                    out.append({'path': path, 'dim': dim, 'mod': mod, 'label': label, 'raw': flat})
    return out


range_payload, range_bytes = fetch_json(RANGE_URL, 'range.json')
data_payload, data_bytes = fetch_json(DATA_URL, 'data-16015.json')
row_path, rows = find_data_rows(data_payload)
if not rows:
    raise RuntimeError(f'Aucune observation Melodi trouvée pour {TARGET}. Clés racine={list(data_payload) if isinstance(data_payload, dict) else type(data_payload).__name__}')

rows = [scalar_fields(r) for r in rows]
# Contrôle géographique défensif : si GEO est présent, seules les lignes 16015 sont retenues.
if any('GEO' in r for r in rows):
    geo_rows = [r for r in rows if str(r.get('GEO', '')).strip() == TARGET]
    if geo_rows:
        rows = geo_rows

# Même principe pour l'année demandée.
if any('TIME_PERIOD' in r for r in rows):
    year_rows = [r for r in rows if str(r.get('TIME_PERIOD', '')).strip() == YEAR]
    if year_rows:
        rows = year_rows

fields = sorted({k for r in rows for k in r.keys()})
unique = {}
for field in fields:
    vals = []
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        s = str(value)
        if s not in vals:
            vals.append(s)
        if len(vals) >= 100:
            break
    unique[field] = vals

range_items = flatten_range(range_payload)

def matching_modalities(tokens):
    tokens = [t.lower() for t in tokens]
    matches = []
    for item in range_items:
        hay = ' '.join(str(item.get(k) or '') for k in ('dim', 'mod', 'label')).lower()
        if any(t in hay for t in tokens):
            matches.append(item)
    return matches


def matching_values(tokens):
    tokens = [t.lower() for t in tokens]
    out = {}
    for field, vals in unique.items():
        selected = [v for v in vals if any(t in v.lower() for t in tokens)]
        if selected:
            out[field] = selected
    return out

period_tokens = ['y_lt1919', 'y1919t1945', 'y1946t1970', 'y1971t1990', 'y1991t2005', 'y2006taaaa', 'avant 1919', '1919', '1946', '1971', '1991', '2006']
result = {
    'source': 'Insee RP2023 - DS_RP_TD_LOGEMENT_CARACT_PRINC',
    'dataset': DATASET,
    'territory': TARGET,
    'year': 2023,
    'strategy': 'melodi_range_then_local_data',
    'urls': {'range': RANGE_URL, 'data': DATA_URL},
    'transport': {'range_bytes': range_bytes, 'data_bytes': data_bytes},
    'data_rows_path': row_path,
    'target_rows': len(rows),
    'target_rows_2023': len(rows),
    'fields': fields,
    'unique_values': unique,
    'sample_rows': rows[:20],
    'detected': {
        'vacancy_from_range': matching_modalities(['DW_VAC', 'vacant', 'vacance']),
        'construction_periods_from_range': matching_modalities(period_tokens),
        'dwelling_types_from_range': matching_modalities(['maison', 'appartement', 'house', 'apart']),
        'nor_from_range_for_exclusion': matching_modalities(['NOR', 'nombre de pièces']),
        'vacancy_in_data': matching_values(['DW_VAC', 'VAC']),
        'construction_periods_in_data': matching_values(period_tokens),
        'dwelling_types_in_data': matching_values(['HOUSE', 'APART', 'MAISON', 'APPART'])
    },
    'quality': {
        'geography': 'commune',
        'local_query_only': True,
        'merge_with_lovac': False,
        'causal_interpretation': False,
        'nor_rule': 'NOR ne doit pas être utilisé pour le profil des logements vacants.',
        'purpose': 'Audit de schéma et des modalités avant matérialisation du contrat machine 3K-C.'
    }
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
