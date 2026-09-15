import csv
import json
import re
import subprocess
import zipfile
from pathlib import Path

SOURCE_PAGE = "https://www.insee.fr/fr/statistiques/8735162"
ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/8735162/Filosofi2021_carreaux_200m_csv.zip"
COMMUNE = "16015"
TMP = Path("tmp_filosofi_grid")
OUT = Path("output")
TMP.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
zip_path = TMP / "Filosofi2021_carreaux_200m_csv.zip"

print("Téléchargement Filosofi 2021 carroyage 200 m officiel Insee...")
# wget est utilisé ici à la place du précédent curl interrompu ; reprise activée.
cmd = [
    "wget", "--quiet", "--show-progress", "--continue",
    "--tries=20", "--timeout=45", "--read-timeout=45",
    "--output-document", str(zip_path), ZIP_URL,
]
subprocess.run(cmd, check=True)

if not zip_path.exists() or zip_path.stat().st_size < 10_000_000:
    raise RuntimeError(f"Archive absente ou trop petite: {zip_path.stat().st_size if zip_path.exists() else 0}")
if not zipfile.is_zipfile(zip_path):
    raise RuntimeError("Archive Filosofi 200 m invalide")

with zipfile.ZipFile(zip_path) as z:
    csv_names = [n for n in z.namelist() if n.lower().endswith('.csv')]
    if not csv_names:
        raise RuntimeError(f"Aucun CSV: {z.namelist()}")
    # Angoulême est en métropole : le plus gros CSV est celui de métropole.
    csv_name = max(csv_names, key=lambda n: z.getinfo(n).file_size)
    z.extract(csv_name, TMP)

csv_path = TMP / csv_name
raw_head = csv_path.open('rb').read(65536)
encoding = 'utf-8-sig'
try:
    text_head = raw_head.decode(encoding)
except UnicodeDecodeError:
    encoding = 'latin-1'
    text_head = raw_head.decode(encoding)
try:
    delim = csv.Sniffer().sniff(text_head, delimiters=';,\t|').delimiter
except csv.Error:
    delim = ';'

with csv_path.open('r', encoding=encoding, newline='') as f:
    rd = csv.DictReader(f, delimiter=delim)
    fields = rd.fieldnames or []
    low = {c.lower(): c for c in fields}
    required = ['idcar_200m','i_est_200','lcog_geo','ind','men','men_pauv']
    missing = [k for k in required if k not in low]
    if missing:
        raise RuntimeError(f"Colonnes absentes: {missing}; schéma={fields}")

    selected = []
    overlap_only = 0
    for r in rd:
        geo = str(r.get(low['lcog_geo'],'') or '')
        codes = re.findall(r'(?<!\d)(?:2A|2B|\d{2})\d{3}(?!\d)', geo)
        if not codes:
            # secours pour les chaînes du type 16015,16113 sans séparateur clair
            codes = re.findall(r'\d{5}', geo)
        if COMMUNE in codes:
            if codes[0] == COMMUNE:
                selected.append(r)
            else:
                overlap_only += 1

if not selected:
    raise RuntimeError("Aucun carreau dont Angoulême est la commune principale dans lcog_geo")

def number(v):
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s or s.lower() in {'na','nan','nd','s'}:
        return 0.0
    try:
        return float(s.replace(' ','').replace(',','.'))
    except ValueError:
        return 0.0

n = len(selected)
imputed = sum(1 for r in selected if int(number(r.get(low['i_est_200']))) == 1)
ind = sum(number(r.get(low['ind'])) for r in selected)
men = sum(number(r.get(low['men'])) for r in selected)
men_pauv = sum(number(r.get(low['men_pauv'])) for r in selected)

# Descriptif spatial uniquement : distribution des carreaux, sans causalité et sans rattachement à des logements vacants.
poverty_rates = []
for r in selected:
    m = number(r.get(low['men']))
    p = number(r.get(low['men_pauv']))
    if m > 0:
        poverty_rates.append(100*p/m)
poverty_rates.sort()
def quantile(a,p):
    if not a: return None
    h=(len(a)-1)*p; i=int(h); f=h-i
    return a[i] + (a[min(i+1,len(a)-1)]-a[i])*f

result = {
    'ok': True,
    'source_page': SOURCE_PAGE,
    'download_url': ZIP_URL,
    'source_file': csv_name,
    'archive_bytes': zip_path.stat().st_size,
    'commune_code': COMMUNE,
    'selection_rule': 'Angoulême doit être le premier code de lcog_geo (commune principale par surface d’intersection)',
    'carreaux_selected': n,
    'carreaux_overlap_where_angouleme_not_primary': overlap_only,
    'carreaux_imputes': imputed,
    'part_carreaux_imputes_pct': 100*imputed/n,
    'sum_ind': ind,
    'sum_men': men,
    'sum_men_pauv': men_pauv,
    'poverty_rate_grid_weighted_pct': (100*men_pauv/men) if men else None,
    'poverty_rate_cell_q1_pct': quantile(poverty_rates,.25),
    'poverty_rate_cell_median_pct': quantile(poverty_rates,.5),
    'poverty_rate_cell_q3_pct': quantile(poverty_rates,.75),
    'n_fields': len(fields),
    'fields': fields,
    'method_note': "Étape 3I-B technique. Les carreaux servent à décrire l’hétérogénéité socio-économique infracommunale. Ils ne sont jamais affectés à un logement vacant individuel et les carreaux i_est_200=1 restent explicitement signalés comme imputés."
}

out = OUT / 'filosofi-2021-carroyage-angouleme.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
