import csv
import json
import zipfile
import subprocess
from pathlib import Path

SOURCE_PAGE = "https://www.insee.fr/fr/statistiques/7756729"
ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/7756729/base-cc-filosofi-2021-geo2025_csv.zip"
COMMUNE = "16015"
GEO_OBJECT = "COM"
TIME_PERIOD = "2021"
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
    required_fields = {'GEO','GEO_OBJECT','FILOSOFI_MEASURE','OBS_VALUE','TIME_PERIOD'}
    if not required_fields.issubset(set(fields)):
        raise RuntimeError(f"Schéma long Filosofi inattendu: {fields}")

    matched = []
    for r in rd:
        if (
            str(r.get('GEO','')).strip() == COMMUNE
            and str(r.get('GEO_OBJECT','')).strip() == GEO_OBJECT
            and str(r.get('TIME_PERIOD','')).strip() == TIME_PERIOD
        ):
            matched.append(r)

if not matched:
    raise RuntimeError(f"Aucune observation communale Filosofi trouvée pour GEO={COMMUNE}, GEO_OBJECT={GEO_OBJECT}, TIME_PERIOD={TIME_PERIOD}")

def parse_value(v):
    if v is None:
        return None
    s = str(v).strip()
    if s in ('','s','nd','NA','NaN'):
        return None
    try:
        return float(s.replace(' ','').replace(',','.'))
    except ValueError:
        return s

# Contrôle strict d'unicité : une seule observation par mesure pour la commune et le millésime.
by_code = {}
for r in matched:
    code = str(r.get('FILOSOFI_MEASURE','')).strip()
    if not code:
        continue
    by_code.setdefault(code, []).append(r)

duplicates = {k: len(v) for k, v in by_code.items() if len(v) != 1}
if duplicates:
    raise RuntimeError(f"Mesures non uniques après filtre communal strict: {duplicates}")

obs = {}
meta_obs = {}
for code, rows in by_code.items():
    r = rows[0]
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

# Contrat basé sur les codes SDMX réellement observés dans la diffusion officielle.
wanted = ['D1_SL','D9_SL','IR_D9_D1_SL','MED_SL','NUM_CU','NUM_HH','NUM_PER','PR_MD60',
          'S_DIR_TAX_DI','S_EI_DI','S_EI_DI_N_SAL','S_EI_DI_SAL','S_EI_DI_UNE','S_HH_TAX',
          'S_INC_ASS_DI','S_RET_PEN_DI','S_SOC_BEN_DI','S_SOC_BEN_DI_FAM_BEN',
          'S_SOC_BEN_DI_HOU_BEN','S_SOC_BEN_DI_MIN_SOC']
selected = {k: obs.get(k) for k in wanted if k in obs}

required_measures = ['D1_SL','D9_SL','IR_D9_D1_SL','MED_SL','PR_MD60','NUM_HH','NUM_PER']
missing_required = [k for k in required_measures if k not in obs or obs[k] is None]
if missing_required:
    raise RuntimeError(f"Mesures communales essentielles absentes: {missing_required}; présentes: {sorted(obs)}")

result = {
    'ok': True,
    'source_page': SOURCE_PAGE,
    'download_url': ZIP_URL,
    'archive_bytes': zip_path.stat().st_size,
    'commune_code': COMMUNE,
    'geo_object': GEO_OBJECT,
    'time_period': TIME_PERIOD,
    'source_file': data_name,
    'format': 'long SDMX CSV',
    'rows_found_for_commune': len(matched),
    'measure_count': len(obs),
    'duplicates_after_strict_filter': duplicates,
    'missing_required': missing_required,
    'selected_measures': selected,
    'all_measures': [
        {'code': k, 'value': obs[k], **meta_obs[k]}
        for k in sorted(obs)
    ],
    'method_note': "Étape 3I-A : filtre strict GEO=16015, GEO_OBJECT=COM, TIME_PERIOD=2021. Une seule observation par mesure est exigée. Les codes SDMX sont conservés tels que diffusés par l'Insee."
}

out = OUT / 'filosofi-2021-angouleme.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({
    'ok': True,
    'rows_found_for_commune': len(matched),
    'measure_count': len(obs),
    'duplicates_after_strict_filter': duplicates,
    'missing_required': missing_required,
    'selected_measures': selected
}, ensure_ascii=False, indent=2))
