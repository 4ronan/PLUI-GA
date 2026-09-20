import csv
import io
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

DATA_URL = "https://api.insee.fr/melodi/file/DS_RP_SERIE_HISTORIQUE/DS_RP_SERIE_HISTORIQUE_2023_CSV_FR"
PANEL = {
    "16015":"Angoulême","47001":"Agen","19031":"Brive-la-Gaillarde","24037":"Bergerac",
    "86066":"Châtellerault","16102":"Cognac","40088":"Dax","33243":"Libourne",
    "47157":"Marmande","40192":"Mont-de-Marsan","79191":"Niort","24322":"Périgueux",
    "17299":"Rochefort","17306":"Royan","17415":"Saintes","47323":"Villeneuve-sur-Lot"
}
YEARS = {"2017", "2023"}
TMP = Path("tmp_3j_snapshot")
OUT = Path("data")
TMP.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
raw = TMP / "rp_hist.zip"

# Téléchargement résilient : HTTP/1.1 + reprise. Plusieurs petites tentatives valent mieux
# qu'un unique transfert long et fragile sur HTTP/2.
for attempt in range(1, 13):
    cmd = [
        "curl", "--http1.1", "--fail", "--location", "--show-error",
        "--retry", "3", "--retry-all-errors", "--retry-delay", "2",
        "--connect-timeout", "30", "--max-time", "420",
        "--continue-at", "-", "--output", str(raw), DATA_URL,
    ]
    p = subprocess.run(cmd)
    if p.returncode == 0 and raw.exists() and zipfile.is_zipfile(raw):
        break
    if attempt == 12:
        raise RuntimeError(f"Téléchargement INSEE impossible après {attempt} tentatives; taille partielle={raw.stat().st_size if raw.exists() else 0}")
    time.sleep(3)

with zipfile.ZipFile(raw) as z:
    names = z.namelist()
    csvs = [n for n in names if n.lower().endswith('.csv')]
    data_candidates = [n for n in csvs if 'metadata' not in n.lower() and 'meta' not in n.lower()]
    if not data_candidates:
        raise RuntimeError(f"CSV de données introuvable: {names}")
    data_name = max(data_candidates, key=lambda n: z.getinfo(n).file_size)
    meta_name = next((n for n in csvs if 'metadata' in n.lower() or 'meta' in n.lower()), None)
    data_text = z.read(data_name).decode('utf-8-sig')
    meta_text = z.read(meta_name).decode('utf-8-sig') if meta_name else ''

labels = {}
if meta_text:
    rd = csv.DictReader(io.StringIO(meta_text), delimiter=';')
    for r in rd:
        cv=(r.get('COD_VAR') or '').strip(); cm=(r.get('COD_MOD') or '').strip(); lm=(r.get('LIB_MOD') or '').strip()
        if cv and cm and lm:
            labels[(cv,cm)] = lm

rd = csv.DictReader(io.StringIO(data_text), delimiter=';')
fields = rd.fieldnames or []
required = {'GEO','GEO_OBJECT','RP_MEASURE','OCS','TIME_PERIOD','OBS_VALUE'}
if not required.issubset(fields):
    raise RuntimeError(f"Schéma inattendu: {fields}")

kept = []
for r in rd:
    if (r.get('GEO') or '').strip() not in PANEL: continue
    if (r.get('GEO_OBJECT') or '').strip() != 'COM': continue
    if (r.get('TIME_PERIOD') or '').strip() not in YEARS: continue
    m=(r.get('RP_MEASURE') or '').strip()
    if m not in {'POP','DWELLINGS'}: continue
    kept.append(r)

if not kept:
    raise RuntimeError('Aucune ligne conservée')

# Contrôle de couverture minimale population 2017/2023.
for y in sorted(YEARS):
    geos={r['GEO'].strip() for r in kept if r['TIME_PERIOD'].strip()==y and r['RP_MEASURE'].strip()=='POP'}
    missing=[c for c in PANEL if c not in geos]
    if missing:
        raise RuntimeError(f"Population {y}: communes manquantes {missing}")

out_csv = OUT / 'insee-rp2023-panel-3j.csv'
with out_csv.open('w', newline='', encoding='utf-8') as f:
    w=csv.DictWriter(f, fieldnames=fields)
    w.writeheader(); w.writerows(kept)

meta = {
    'source_url': DATA_URL,
    'source_file': data_name,
    'years': sorted(YEARS),
    'panel_n': len(PANEL),
    'rows': len(kept),
    'occs': sorted({r['OCS'].strip() for r in kept if r['RP_MEASURE'].strip()=='DWELLINGS'}),
    'ocs_labels': {k[1]:v for k,v in labels.items() if k[0]=='OCS' and k[1] in {r['OCS'].strip() for r in kept}},
    'method_note': 'Snapshot réduit aux 16 communes du panel, années 2017/2023, mesures POP et DWELLINGS. Produit automatiquement depuis la diffusion officielle INSEE Melodi.'
}
(Path('data')/'insee-rp2023-panel-3j-meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(meta, ensure_ascii=False, indent=2))
