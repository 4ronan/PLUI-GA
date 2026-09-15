import csv
import json
import zipfile
import subprocess
from pathlib import Path
import duckdb

SOURCE_PAGE = "https://www.insee.fr/fr/statistiques/8735162"
ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/8735162/Filosofi2021_carreaux_200m_csv.zip"
COMMUNE = "16015"
TMP = Path("tmp_filosofi")
OUT = Path("output")
TMP.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
zip_path = TMP / "Filosofi2021_carreaux_200m_csv.zip"

# Téléchargement robuste : curl reprend un fichier partiel et réessaie les erreurs
# réseau/HTTP. Cela évite les IncompleteRead observés avec urllib sur le runner GitHub.
print("Téléchargement de l'archive officielle Insee avec reprise...")
cmd = [
    "curl", "--fail", "--location", "--show-error", "--silent",
    "--retry", "8", "--retry-all-errors", "--retry-delay", "5",
    "--connect-timeout", "30", "--max-time", "1200",
    "--continue-at", "-", "--output", str(zip_path), ZIP_URL,
]
subprocess.run(cmd, check=True)

if not zip_path.exists() or zip_path.stat().st_size < 1_000_000:
    raise RuntimeError(f"Archive absente ou anormalement petite: {zip_path.stat().st_size if zip_path.exists() else 0} octets")

if not zipfile.is_zipfile(zip_path):
    raise RuntimeError("Le fichier téléchargé n'est pas une archive ZIP valide")

with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    print("Fichiers archive:", names)
    csv_names = [n for n in names if n.lower().endswith('.csv')]
    if not csv_names:
        raise RuntimeError(f"Aucun CSV dans l'archive. Fichiers: {names}")
    # Le fichier Métropole est le plus volumineux des CSV ; Angoulême est en métropole.
    csv_name = max(csv_names, key=lambda n: z.getinfo(n).file_size)
    z.extract(csv_name, TMP)

csv_path = TMP / csv_name
print("CSV retenu:", csv_path, "taille", csv_path.stat().st_size)

# Détection robuste séparateur/encodage sur l'en-tête uniquement.
raw = csv_path.open('rb').read(65536)
encoding = 'utf-8-sig'
try:
    text = raw.decode(encoding)
except UnicodeDecodeError:
    encoding = 'latin-1'
    text = raw.decode(encoding)
try:
    dialect = csv.Sniffer().sniff(text, delimiters=';,\t|')
    delim = dialect.delimiter
except csv.Error:
    delim = ';'
print("Encodage:", encoding, "séparateur:", repr(delim))

con = duckdb.connect()
rel = f"read_csv_auto('{csv_path.as_posix()}', delim='{delim}', header=true, all_varchar=false, ignore_errors=true)"
schema = con.execute(f"DESCRIBE SELECT * FROM {rel}").fetchall()
columns = [r[0] for r in schema]
by_lower = {c.lower(): c for c in columns}
print("Colonnes:", columns)

required = ['idcar_200m','i_est_200','lcog_geo','ind','men','men_pauv']
missing = [c for c in required if c not in by_lower]
if missing:
    raise RuntimeError(f"Colonnes officielles attendues absentes: {missing}; schéma: {columns}")

geo = by_lower['lcog_geo']
# lcog_geo contient un ou plusieurs codes COG concaténés ; le code 16015 doit être présent.
where = f"strpos(CAST(\"{geo}\" AS VARCHAR), ?) > 0"
count = con.execute(f"SELECT COUNT(*) FROM {rel} WHERE {where}", [COMMUNE]).fetchone()[0]
if count == 0:
    raise RuntimeError("Aucun carreau Filosofi officiel trouvé pour Angoulême 16015")

wanted = [
    'idcar_200m','idcar_1km','id_car_nat','i_est_200','i_est_1km','lcog_geo',
    'ind','men','men_pauv','men_1ind','men_5ind','men_prop','men_fmp','ind_snv','men_surf',
    'men_coll','men_mais','log_av45','log_45_70','log_70_90','log_ap90','log_inc','log_soc',
    'ind_0_3','ind_4_5','ind_6_10','ind_11_17','ind_18_24','ind_25_39','ind_40_54','ind_55_64','ind_65_79','ind_80p','ind_inc'
]
available = [by_lower[k] for k in wanted if k in by_lower]

sum_keys = [
    'ind','men','men_pauv','men_1ind','men_5ind','men_prop','men_fmp','ind_snv','men_surf',
    'men_coll','men_mais','log_av45','log_45_70','log_70_90','log_ap90','log_inc','log_soc'
]
selects = ["COUNT(*) AS carreaux"]
est = by_lower['i_est_200']
selects.append(f'SUM(CASE WHEN TRY_CAST(\"{est}\" AS INTEGER)=1 THEN 1 ELSE 0 END) AS carreaux_imputes')
for k in sum_keys:
    if k in by_lower:
        c = by_lower[k]
        selects.append(f'SUM(COALESCE(TRY_CAST(\"{c}\" AS DOUBLE),0)) AS \"{k}\"')

agg = con.execute(f"SELECT {', '.join(selects)} FROM {rel} WHERE {where}", [COMMUNE]).fetchdf().to_dict(orient='records')[0]

sample_cols = available[:18]
sample_select = ', '.join(f'"{c}"' for c in sample_cols)
sample = con.execute(f"SELECT {sample_select} FROM {rel} WHERE {where} LIMIT 5", [COMMUNE]).fetchdf().to_dict(orient='records')

result = {
    'ok': True,
    'source_page': SOURCE_PAGE,
    'download_url': ZIP_URL,
    'source_file': csv_name,
    'archive_bytes': zip_path.stat().st_size,
    'commune_code': COMMUNE,
    'commune_field': geo,
    'selection_method': 'lcog_geo contains commune code',
    'rows': count,
    'n_columns': len(columns),
    'columns': columns,
    'candidate_columns_available': available,
    'aggregate_exploratory': agg,
    'sample': sample,
    'method_note': "Étape 3I-A : validation technique de récupération depuis le fichier CSV officiel Insee. Les sommes sont exploratoires ; les indicateurs territoriaux et l'interprétation seront validés séparément."
}

(OUT / 'filosofi-2021-angouleme.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
print(json.dumps({
    'ok': True,
    'source_file': csv_name,
    'archive_bytes': zip_path.stat().st_size,
    'rows': count,
    'n_columns': len(columns),
    'carreaux_imputes': agg.get('carreaux_imputes'),
    'ind': agg.get('ind'),
    'men': agg.get('men'),
    'men_pauv': agg.get('men_pauv')
}, ensure_ascii=False, indent=2, default=str))
