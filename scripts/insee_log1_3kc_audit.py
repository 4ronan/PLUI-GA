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
    return json.loads(raw), len(raw.encode('utf-8'))


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


def flatten_scalars(obj, prefix=''):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f'{prefix}.{k}' if prefix else str(k)
            out.update(flatten_scalars(v, p))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f'{prefix}[{i}]'
            out.update(flatten_scalars(v, p))
    elif obj is None or isinstance(obj, (str, int, float, bool)):
        out[prefix] = obj
    return out


def find_data_rows(payload):
    candidates = lists_of_dicts(payload)
    if not candidates:
        return None, []
    for path, rows in candidates:
        if path.endswith('.observations'):
            return path, rows
    return max(candidates, key=lambda x: len(x[1]))


def flatten_range(payload):
    out = []
    seen = set()
    for path, rows in lists_of_dicts(payload):
        for row in rows:
            flat = flatten_scalars(row)
            mod = next((v for k, v in flat.items() if k.endswith('.code') or k == 'code'), None)
            if mod is None:
                continue
            key = (path, str(mod))
            if key in seen:
                continue
            seen.add(key)
            out.append({'path': path, 'mod': mod, 'raw': flat})
    return out


range_payload, range_bytes = fetch_json(RANGE_URL, 'range.json')
data_payload, data_bytes = fetch_json(DATA_URL, 'data-16015.json')
row_path, raw_rows = find_data_rows(data_payload)
if not raw_rows:
    raise RuntimeError('Aucune observation Melodi trouvée')

rows = [flatten_scalars(r) for r in raw_rows]
fields = sorted({k for r in rows for k in r})
unique = {}
for field in fields:
    vals = []
    for row in rows:
        v = row.get(field)
        if v is None:
            continue
        s = str(v)
        if s not in vals:
            vals.append(s)
        if len(vals) >= 100:
            break
    unique[field] = vals

range_items = flatten_range(range_payload)

def matching_modalities(tokens):
    tokens = [t.lower() for t in tokens]
    out = []
    for item in range_items:
        hay = json.dumps(item, ensure_ascii=False).lower()
        if any(t in hay for t in tokens):
            out.append(item)
    return out


def matching_values(tokens):
    tokens = [t.lower() for t in tokens]
    out = {}
    for field, vals in unique.items():
        m = [v for v in vals if any(t in v.lower() for t in tokens)]
        if m:
            out[field] = m
    return out

period_tokens = ['y_lt1919','y1919t1945','y1946t1970','y1971t1990','y1991t2005','y2006taaaa']
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
    'sample_rows': rows[:5],
    'detected': {
        'vacancy_from_range': matching_modalities(['DW_VAC']),
        'construction_periods_from_range': matching_modalities(period_tokens),
        'dwelling_types_from_range': matching_modalities(['HOUSE','APART','MAISON','APPART']),
        'nor_from_range_for_exclusion': matching_modalities(['NOR']),
        'vacancy_in_data': matching_values(['DW_VAC']),
        'construction_periods_in_data': matching_values(period_tokens),
        'dwelling_types_in_data': matching_values(['HOUSE','APART','MAISON','APPART'])
    },
    'quality': {
        'geography': 'commune',
        'local_query_only': True,
        'merge_with_lovac': False,
        'causal_interpretation': False,
        'nor_rule': 'NOR ne doit pas être utilisé pour le profil des logements vacants.'
    }
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
