import csv
import io
import json
import subprocess
import zipfile
from pathlib import Path

SOURCE_PAGE = "https://www.insee.fr/fr/statistiques/9003931"
DATA_URL = "https://api.insee.fr/melodi/file/DS_RP_SERIE_HISTORIQUE/DS_RP_SERIE_HISTORIQUE_2023_CSV_FR"
PANEL = {
    "16015":"Angoulême","47001":"Agen","19031":"Brive-la-Gaillarde","24037":"Bergerac",
    "86066":"Châtellerault","16102":"Cognac","40088":"Dax","33243":"Libourne",
    "47157":"Marmande","40192":"Mont-de-Marsan","79191":"Niort","24322":"Périgueux",
    "17299":"Rochefort","17306":"Royan","17415":"Saintes","47323":"Villeneuve-sur-Lot"
}
YEARS = {"2012","2017","2023"}
TMP = Path("tmp_3ja")
OUT = Path("output")
TMP.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
raw_path = TMP / "serie_historique_2023_download"

subprocess.run([
    "curl","--fail","--location","--show-error","--silent",
    "--retry","6","--retry-all-errors","--retry-delay","3",
    "--connect-timeout","30","--max-time","600",
    "--output",str(raw_path),DATA_URL
], check=True)

if not raw_path.exists() or raw_path.stat().st_size < 1000:
    raise RuntimeError("Téléchargement INSEE absent ou anormalement petit")

labels = {}
archive_files = []
if zipfile.is_zipfile(raw_path):
    with zipfile.ZipFile(raw_path) as z:
        names = z.namelist()
        csv_names = [n for n in names if n.lower().endswith('.csv')]
        if not csv_names:
            raise RuntimeError(f"Aucun CSV dans l'archive: {names}")
        meta_candidates = [n for n in csv_names if 'metadata' in n.lower() or 'meta' in n.lower()]
        meta_name = meta_candidates[0] if meta_candidates else None
        data_candidates = [n for n in csv_names if n != meta_name and 'metadata' not in n.lower() and 'meta' not in n.lower()]
        if not data_candidates:
            raise RuntimeError(f"Aucun CSV de données distinct des métadonnées. Archive: {names}")
        # Le fichier de données est de loin le plus volumineux ; ne jamais prendre le CSV de métadonnées par défaut.
        data_name = max(data_candidates, key=lambda n: z.getinfo(n).file_size)
        archive_files = [{"name":n,"bytes":z.getinfo(n).file_size} for n in csv_names]
        data_text = z.read(data_name).decode('utf-8-sig')
        if meta_name:
            meta_text = z.read(meta_name).decode('utf-8-sig')
            mrd = csv.DictReader(meta_text.splitlines(), delimiter=';')
            for r in mrd:
                cod_var = (r.get('COD_VAR') or '').strip()
                cod_mod = (r.get('COD_MOD') or '').strip()
                lib_mod = (r.get('LIB_MOD') or '').strip()
                if cod_mod and lib_mod:
                    labels[(cod_var,cod_mod)] = lib_mod
else:
    data_name = raw_path.name
    data_text = raw_path.read_text(encoding='utf-8-sig')

sample = data_text[:5000]
delim = ';' if sample.count(';') >= sample.count(',') else ','
rd = csv.DictReader(io.StringIO(data_text), delimiter=delim)
fields = rd.fieldnames or []

geo_field = 'GEO' if 'GEO' in fields else ('CODGEO' if 'CODGEO' in fields else None)
geo_object_field = 'GEO_OBJECT' if 'GEO_OBJECT' in fields else None
time_field = 'TIME_PERIOD' if 'TIME_PERIOD' in fields else None
value_field = 'OBS_VALUE' if 'OBS_VALUE' in fields else None

if not geo_field:
    raise RuntimeError(f"Champ géographique absent du fichier de données {data_name}. Champs: {fields}; archive: {archive_files}")

rows = []
for r in rd:
    code = str(r.get(geo_field,'')).strip()
    if code not in PANEL:
        continue
    if geo_object_field and str(r.get(geo_object_field,'')).strip() != 'COM':
        continue
    if time_field and str(r.get(time_field,'')).strip() not in YEARS:
        continue
    rows.append(r)

if not rows:
    raise RuntimeError(f"Aucune ligne panel trouvée dans {data_name}. Champs: {fields}; archive: {archive_files}")

measure_candidates = [f for f in fields if any(k in f.upper() for k in ('MEASURE','INDICATOR','SERIE','VARIABLE'))]
measure_field = measure_candidates[0] if measure_candidates else None
if not measure_field:
    excluded = {geo_field, geo_object_field, time_field, value_field, 'UNIT_MEASURE','UNIT_MULT','OBS_STATUS','CONF_STATUS'}
    candidates = []
    for f in fields:
        if f in excluded or f is None:
            continue
        vals = {str(r.get(f,'')).strip() for r in rows if str(r.get(f,'')).strip()}
        if 2 <= len(vals) <= 200:
            candidates.append((len(vals), f))
    if candidates:
        measure_field = sorted(candidates)[0][1]

measures = {}
if measure_field:
    for r in rows:
        m = str(r.get(measure_field,'')).strip()
        if not m:
            continue
        measures.setdefault(m, {'count':0,'years':set(),'geos':set(),'label':None,'unit':None})
        measures[m]['count'] += 1
        if time_field:
            measures[m]['years'].add(str(r.get(time_field,'')).strip())
        measures[m]['geos'].add(str(r.get(geo_field,'')).strip())
        measures[m]['unit'] = r.get('UNIT_MEASURE')
        for key in ((measure_field,m), ('SERIE_HISTORIQUE_MEASURE',m), ('RP_SERIE_HISTORIQUE_MEASURE',m)):
            if key in labels:
                measures[m]['label'] = labels[key]
                break

keywords = ('population','ménage','menage','résidence principale','residence principale','résidence secondaire','residence secondaire','logement occasionnel')
candidate_measures = []
for code, info in sorted(measures.items()):
    text = (code + ' ' + (info['label'] or '')).lower()
    if any(k in text for k in keywords):
        candidate_measures.append({
            'code':code,'label':info['label'],'unit':info['unit'],'count':info['count'],
            'years':sorted(info['years']),'geos_n':len(info['geos'])
        })

coverage = {}
for y in sorted(YEARS):
    geos = {str(r.get(geo_field,'')).strip() for r in rows if (not time_field or str(r.get(time_field,'')).strip()==y)}
    coverage[y] = {'n':len(geos),'missing':[c for c in PANEL if c not in geos]}

result = {
    'ok': True,
    'stage': '3J-A',
    'source_page': SOURCE_PAGE,
    'download_url': DATA_URL,
    'download_bytes': raw_path.stat().st_size,
    'source_file': data_name,
    'archive_files': archive_files,
    'fields': fields,
    'geo_field': geo_field,
    'geo_object_field': geo_object_field,
    'time_field': time_field,
    'value_field': value_field,
    'measure_field': measure_field,
    'rows_panel_2012_2017_2023': len(rows),
    'panel_n': len(PANEL),
    'coverage': coverage,
    'measure_count': len(measures),
    'candidate_measures': candidate_measures,
    'all_measure_codes': sorted(measures),
    'method_note': "3J-A contrôle seulement la disponibilité et la comparabilité des données INSEE en géographie 2026. Aucun percentile ni diagnostic n'est produit à ce stade. Les évolutions 2017-2023 seront privilégiées ; la prudence méthodologique INSEE sur les comparaisons de population autour du changement de questionnaire sera rappelée."
}

out = OUT / 'insee-3ja-demography-housing.json'
out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(result, ensure_ascii=False, indent=2))
