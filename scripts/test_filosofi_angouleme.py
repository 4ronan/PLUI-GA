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
    csv_names = [n for n in z.namelist() if n.lower().endswith('.csv')]
    if not csv_names:
        raise RuntimeError(f"Aucun CSV dans l'archive: {z.namelist()}")
    found = []
    inspected = []
    for name in csv_names:
        with z.open(name) as f:
            raw = f.read()
        text = None
        enc = None
        for candidate in ('utf-8-sig','latin-1','cp1252'):
            try:
                text = raw.decode(candidate)
                enc = candidate
                break
            except UnicodeDecodeError:
                pass
        if text is None:
            continue
        sample = text[:65536]
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=';,\t|').delimiter
        except csv.Error:
            delim = ';'
        reader = csv.DictReader(text.splitlines(), delimiter=delim)
        fields = reader.fieldnames or []
        inspected.append({'file': name, 'encoding': enc, 'delimiter': delim, 'fields': fields[:60]})
        by_lower = {c.lower(): c for c in fields}
        code_field = by_lower.get('codgeo') or by_lower.get('codegeo') or by_lower.get('code_geo')
        if not code_field:
            continue
        for row in reader:
            if str(row.get(code_field, '')).strip() == COMMUNE:
                found.append({'file': name, 'encoding': enc, 'delimiter': delim, 'row': row, 'fields': fields})

if not found:
    raise RuntimeError(f"Aucune ligne Filosofi trouvée pour {COMMUNE}. Fichiers inspectés: {inspected}")

# Il peut exister plusieurs CSV spécialisés ; on privilégie la ligne contenant les indicateurs principaux.
def score(item):
    fields = {c.upper() for c in item['fields']}
    wanted = {'MED21','TP6021','PIMP21','NBMENFISC21','NBPERSMENFISC21','D121','D921','RD21'}
    return len(fields & wanted)

best = max(found, key=score)
row = best['row']
by_upper = {k.upper(): k for k in row.keys()}

def val(code):
    k = by_upper.get(code.upper())
    if not k:
        return None
    v = row.get(k)
    if v is None or str(v).strip() in ('','s','nd','NA'):
        return None
    s = str(v).strip().replace(' ', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        return str(v).strip()

indicators = {
    'CODGEO': str(row.get(by_upper.get('CODGEO'), COMMUNE)).strip(),
    'LIBGEO': row.get(by_upper.get('LIBGEO')) if by_upper.get('LIBGEO') else None,
    'NBMENFISC21': val('NBMENFISC21'),
    'NBPERSMENFISC21': val('NBPERSMENFISC21'),
    'MED21': val('MED21'),
    'PIMP21': val('PIMP21'),
    'TP6021': val('TP6021'),
    'D121': val('D121'),
    'D921': val('D921'),
    'RD21': val('RD21'),
    'PACT21': val('PACT21'),
    'PCHO21': val('PCHO21'),
    'PPEN21': val('PPEN21'),
    'PPAT21': val('PPAT21'),
    'PPSOC21': val('PPSOC21'),
    'PPMINI21': val('PPMINI21'),
    'PPLOGT21': val('PPLOGT21'),
    'TP60TOL121': val('TP60TOL121'),
    'TP60TOL221': val('TP60TOL221'),
}

required = ['MED21','TP6021','NBMENFISC21']
missing_required = [k for k in required if indicators.get(k) is None]
if missing_required:
    raise RuntimeError(f"Ligne Angoulême trouvée mais indicateurs essentiels absents: {missing_required}; colonnes: {best['fields']}")

result = {
    'ok': True,
    'source_page': SOURCE_PAGE,
    'download_url': ZIP_URL,
    'archive_bytes': zip_path.stat().st_size,
    'commune_code': COMMUNE,
    'source_file': best['file'],
    'encoding': best['encoding'],
    'delimiter': best['delimiter'],
    'rows_found_for_commune': len(found),
    'n_columns_selected_file': len(best['fields']),
    'columns': best['fields'],
    'indicators': indicators,
    'missing_required': missing_required,
    'method_note': "Étape 3I-A : validation technique des indicateurs communaux officiels Filosofi 2021. Le carroyage 200 m sera traité séparément pour l'analyse infracommunale."
}

out = OUT / 'filosofi-2021-angouleme.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
