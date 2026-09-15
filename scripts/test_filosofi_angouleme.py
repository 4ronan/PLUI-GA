import csv
import json
import zipfile
import subprocess
from pathlib import Path

SOURCE_PAGE = "https://www.insee.fr/fr/statistiques/7756729"
ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/7756729/base-cc-filosofi-2021-geo2025_csv.zip"
COMMUNE = "16015"
TMP = Path("tmp_filosofi")
OUT = Path("output")
TMP.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
zip_path = TMP / "base-cc-filosofi-2021-geo2025_csv.zip"

print("Téléchargement de la base communale officielle Filosofi 2021...")
cmd = [
    "curl", "--fail", "--location", "--show-error", "--silent",
    "--retry", "6", "--retry-all-errors", "--retry-delay", "3",
    "--connect-timeout", "30", "--max-time", "600",
    "--output", str(zip_path), ZIP_URL,
]
subprocess.run(cmd, check=True)

if not zip_path.exists() or zip_path.stat().st_size < 100_000:
    raise RuntimeError(f"Archive absente ou anormalement petite: {zip_path.stat().st_size if zip_path.exists() else 0} octets")
if not zipfile.is_zipfile(zip_path):
    raise RuntimeError("Le fichier téléchargé n'est pas une archive ZIP valide")

with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    data_name = next((n for n in names if n.endswith('DS_FILOSOFI_CC_data.csv')), None)
    meta_name = next((n for n in names if n.endswith('DS_FILOSOFI_CC_metadata.csv')), None)
    if not data_name:
        raise RuntimeError(f"Fichier de données Filosofi introuvable. Archive: {names}")

    # Lire les libellés de mesures depuis les métadonnées.
    labels = {}
    if meta_name:
        raw = z.read(meta_name).decode('utf-8-sig')
        rd = csv.DictReader(raw.splitlines(), delimiter=';')
        for r in rd:
            if r.get('COD_VAR') == 'FILOSOFI_MEASURE' and r.get('COD_MOD'):
                labels[r['COD_MOD']] = r.get('LIB_MOD')

    raw = z.read(data_name).decode('utf-8-sig')
    rd = csv.DictReader(raw.splitlines(), delimiter=';')
    fields = rd.fieldnames or []
    required_fields = {'GEO','GEO_OBJECT','FILOSOFI_MEASURE','OBS_VALUE'}
    if not required_fields.issubset(set(fields)):
        raise RuntimeError(f"Schéma long Filosofi inattendu: {fields}")

    matched = []
    for r in rd:
        geo = str(r.get('GEO','')).strip()
        # GEO est une clé SDMX, pas nécessairement le code commune brut.
        # On accepte 16015, COM-16015, 2021-COM-16015, etc., mais pas un simple sous-chaînage numérique ambigu.
        parts = [p for p in geo.replace('_','-').split('-') if p]
        is_target = geo == COMMUNE or (COMMUNE in parts)
        if is_target:
            matched.append(r)

if not matched:
    # Diagnostic compact : quelques exemples de clés GEO pour comprendre le format exact si l'Insee le change.
    with zipfile.ZipFile(zip_path) as z:
        raw = z.read(data_name).decode('utf-8-sig')
        rd = csv.DictReader(raw.splitlines(), delimiter=';')
        examples=[]
        for r in rd:
            g=str(r.get('GEO','')).strip()
            if g and g not in examples:
                examples.append(g)
            if len(examples)>=20: break
    raise RuntimeError(f"Aucune observation Filosofi trouvée pour {COMMUNE}. Exemples GEO: {examples}")

# Les données sont en format long : une observation par mesure.
# On ne suppose pas à l'avance les codes exacts ; on conserve tous ceux du territoire.
def parse_value(v):
    if v is None: return None
    s=str(v).strip()
    if s in ('','s','nd','NA','NaN'): return None
    s2=s.replace(' ','').replace(',','.')
    try: return float(s2)
    except ValueError: return s

obs = {}
meta_obs = {}
for r in matched:
    code = str(r.get('FILOSOFI_MEASURE','')).strip()
    if not code: continue
    obs[code] = parse_value(r.get('OBS_VALUE'))
    meta_obs[code] = {
        'label': labels.get(code),
        'unit': r.get('UNIT_MEASURE'),
        'unit_mult': r.get('UNIT_MULT'),
        'conf_status': r.get('CONF_STATUS'),
        'obs_status': r.get('OBS_STATUS'),
        'time_period': r.get('TIME_PERIOD'),
        'geo': r.get('GEO'),
        'geo_object': r.get('GEO_OBJECT'),
    }

# Codes attendus si présents dans la diffusion actuelle. Les absences sont signalées sans inventer.
wanted = ['MED21','TP6021','PIMP21','NBMENFISC21','NBPERSMENFISC21','D121','D921','RD21',
          'PACT21','PCHO21','PPEN21','PPAT21','PPSOC21','PPMINI21','PPLOGT21','TP60TOL121','TP60TOL221']
selected = {k: obs.get(k) for k in wanted if k in obs}

result = {
    'ok': True,
    'source_page': SOURCE_PAGE,
    'download_url': ZIP_URL,
    'archive_bytes': zip_path.stat().st_size,
    'commune_code': COMMUNE,
    'source_file': data_name,
    'format': 'long SDMX CSV',
    'rows_found_for_commune': len(matched),
    'geo_values': sorted({str(r.get('GEO','')) for r in matched}),
    'geo_objects': sorted({str(r.get('GEO_OBJECT','')) for r in matched}),
    'measure_count': len(obs),
    'selected_expected_codes': selected,
    'all_measures': [
        {'code': k, 'value': obs[k], **meta_obs[k]}
        for k in sorted(obs)
    ],
    'method_note': "Étape 3I-A : validation technique du format long officiel Filosofi 2021. Les codes réellement présents sont conservés tels quels ; aucune équivalence n'est inventée."
}

out = OUT / 'filosofi-2021-angouleme.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({
    'ok': True,
    'rows_found_for_commune': len(matched),
    'geo_values': result['geo_values'],
    'measure_count': len(obs),
    'selected_expected_codes': selected,
    'first_measures': result['all_measures'][:20]
}, ensure_ascii=False, indent=2))
