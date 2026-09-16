import json, subprocess, zipfile
from pathlib import Path
from openpyxl import load_workbook

URL='https://www.insee.fr/fr/statistiques/fichier/8998387/TD_LOGEMENT_CARACT_PRINC_2023_xlsx.zip'
TARGET='16015'
OUT=Path('output/insee-log1-3kc-audit.json')
TMP=Path('tmp_3kc')
TMP.mkdir(exist_ok=True)
zip_path=TMP/'TD_LOGEMENT_CARACT_PRINC_2023_xlsx.zip'

subprocess.run([
    'curl','--http1.1','--fail','--location','--show-error','--silent',
    '--retry','5','--retry-all-errors','--retry-delay','2',
    '--connect-timeout','30','--max-time','900',
    '--output',str(zip_path),URL
], check=True)

if not zipfile.is_zipfile(zip_path):
    raise RuntimeError('La ressource INSEE XLSX n’est pas une archive ZIP valide')

with zipfile.ZipFile(zip_path) as z:
    xlsx_names=[n for n in z.namelist() if n.lower().endswith('.xlsx')]
    if not xlsx_names:
        raise RuntimeError('Aucun fichier XLSX dans l’archive INSEE')
    xlsx_name=max(xlsx_names,key=lambda n:z.getinfo(n).file_size)
    xlsx_path=TMP/Path(xlsx_name).name
    xlsx_path.write_bytes(z.read(xlsx_name))

wb=load_workbook(xlsx_path,read_only=True,data_only=True)

sheet_audit=[]
target_sheet=None
headers=None
target_values=None
header_row_num=None

for ws in wb.worksheets:
    found_header=None
    found_header_row=None
    # Les feuilles de données peuvent comporter quelques lignes de titre avant l'en-tête.
    for row_idx,row in enumerate(ws.iter_rows(min_row=1,max_row=min(ws.max_row,25),values_only=True),start=1):
        vals=[str(v).strip() if v is not None else '' for v in row]
        if 'CODGEO' in vals or 'GEO' in vals:
            found_header=vals
            found_header_row=row_idx
            break
    sheet_info={'sheet':ws.title,'max_row':ws.max_row,'max_column':ws.max_column,'header_row':found_header_row}
    sheet_audit.append(sheet_info)
    if not found_header:
        continue
    try:
        geo_idx=found_header.index('CODGEO') if 'CODGEO' in found_header else found_header.index('GEO')
    except ValueError:
        continue
    for row in ws.iter_rows(min_row=found_header_row+1,values_only=True):
        if geo_idx < len(row) and str(row[geo_idx]).strip()==TARGET:
            target_sheet=ws.title
            headers=found_header
            target_values=[None if v is None else v for v in row]
            header_row_num=found_header_row
            break
    if target_values is not None:
        break

if target_values is None:
    raise RuntimeError(f'Aucune ligne trouvée pour {TARGET}; feuilles={sheet_audit}')

record={}
for i,h in enumerate(headers):
    if not h:
        continue
    record[h]=target_values[i] if i < len(target_values) else None

# Audit sémantique par noms de colonnes : aucune interprétation n'est encore figée ici.
def cols_matching(tokens):
    return [h for h in headers if h and any(t.lower() in h.lower() for t in tokens)]

vacancy_cols=cols_matching(['VAC','DW_VAC'])
construction_cols=cols_matching(['LT1919','1919','1946','1971','1991','2006','ACH','PERACH'])
dwelling_type_cols=cols_matching(['MAISON','APPART','HOUSE','APART','TYPL','TYPE'])
# NOR est volontairement audité mais ne sera jamais retenu pour le profil des logements vacants.
nor_cols=cols_matching(['NOR'])

result={
    'source':'Insee RP2023 - LOG1 / DS_RP_TD_LOGEMENT_CARACT_PRINC',
    'url':URL,
    'territory':TARGET,
    'format':'xlsx_zip',
    'xlsx_file':xlsx_name,
    'sheet':target_sheet,
    'header_row':header_row_num,
    'fields_n':len([h for h in headers if h]),
    'fields':[h for h in headers if h],
    'target_rows':1,
    'target_rows_2023':1,
    'target_record':record,
    'sheet_audit':sheet_audit,
    'detected':{
        'vacancy_columns':vacancy_cols,
        'construction_period_columns':construction_cols,
        'dwelling_type_columns':dwelling_type_cols,
        'nor_columns_excluded_from_vacant_profile':nor_cols
    },
    'quality':{
        'year':2023,
        'geography':'commune',
        'note':'Audit du tableau détaillé LOG1 officiel; aucune fusion avec LOVAC et aucun calcul causal.',
        'nor_rule':'NOR appartient aux résidences principales et ne doit pas être utilisé pour le profil des logements vacants.'
    }
}

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
