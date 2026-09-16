import csv, io, json, subprocess, zipfile
from pathlib import Path

URL='https://api.insee.fr/melodi/file/DS_RP_TD_LOGEMENT_CARACT_PRINC/DS_RP_TD_LOGEMENT_CARACT_PRINC_2023_CSV_FR'
TARGET='16015'
OUT=Path('output/insee-log1-3kc-audit.json')
TMP=Path('tmp_3kc')
TMP.mkdir(exist_ok=True)
archive=TMP/'insee-logement-caract-princ-2023.zip'

subprocess.run([
    'curl','--fail','--location','--show-error','--silent',
    '--retry','5','--retry-all-errors','--retry-delay','2',
    '--connect-timeout','30','--max-time','600',
    '--output',str(archive),URL
], check=True)

if not zipfile.is_zipfile(archive):
    raise RuntimeError('La ressource INSEE téléchargée n’est pas une archive ZIP valide')

with zipfile.ZipFile(archive) as z:
    names=[n for n in z.namelist() if n.lower().endswith('.csv')]
    if not names:
        raise RuntimeError('Aucun CSV dans l’archive INSEE')
    infos={n:z.getinfo(n).file_size for n in names}
    data_candidates=[n for n in names if 'meta' not in n.lower()]
    if not data_candidates:
        data_candidates=names
    data_name=max(data_candidates,key=lambda n: infos[n])
    raw=z.read(data_name)

text=None
encoding=None
for enc in ('utf-8-sig','utf-8','cp1252','latin-1'):
    try:
        text=raw.decode(enc)
        encoding=enc
        break
    except UnicodeDecodeError:
        pass
if text is None:
    raise RuntimeError('Encodage du CSV INSEE indétectable')

sample=text[:30000]
dialect=csv.Sniffer().sniff(sample,delimiters=';,\t,')
reader=csv.DictReader(io.StringIO(text),dialect=dialect)
fields=reader.fieldnames or []
rows=[]
for r in reader:
    geo=(r.get('GEO') or r.get('CODGEO') or '').strip()
    obj=(r.get('GEO_OBJECT') or '').strip()
    if geo==TARGET and (not obj or obj in {'COM','COMMUNE'}):
        rows.append(r)

if not rows:
    raise RuntimeError(f'Aucune ligne trouvée pour {TARGET}; champs={fields}')

# Profil des dimensions présentes pour la commune cible, sans présumer du schéma.
unique={}
for f in fields:
    vals=[]
    seen=set()
    for r in rows:
        v=(r.get(f) or '').strip()
        if v and v not in seen:
            seen.add(v); vals.append(v)
        if len(vals)>=50:
            break
    unique[f]=vals

# Sous-ensemble utile : uniquement 2023 lorsqu’une dimension temporelle existe.
rows_2023=[r for r in rows if not r.get('TIME_PERIOD') or str(r.get('TIME_PERIOD')).strip()=='2023']

# Recherche descriptive des modalités LOG1 attendues, sans les utiliser encore pour calculer.
def matching_values(tokens):
    out={}
    for f,vals in unique.items():
        m=[v for v in vals if any(t.lower() in v.lower() for t in tokens)]
        if m: out[f]=m
    return out

result={
    'source':'Insee RP2023 - DS_RP_TD_LOGEMENT_CARACT_PRINC',
    'url':URL,
    'territory':TARGET,
    'data_file':data_name,
    'encoding':encoding,
    'delimiter':dialect.delimiter,
    'fields':fields,
    'target_rows':len(rows),
    'target_rows_2023':len(rows_2023),
    'unique_values':unique,
    'detected':{
        'vacancy_candidates':matching_values(['DW_VAC','VAC']),
        'construction_period_candidates':matching_values(['Y_LT1919','Y1919T1945','Y1946T1970','Y1971T1990','Y1991T2005','Y2006']),
        'dwelling_type_candidates':matching_values(['HOUSE','APART','MAISON','APPART'])
    }
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
