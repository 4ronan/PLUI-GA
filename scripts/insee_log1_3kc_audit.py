import json, subprocess
from pathlib import Path
import pyarrow.parquet as pq

URL='https://api.insee.fr/melodi/file/DS_RP_TD_LOGEMENT_CARACT_PRINC_2023/PARQUET'
TARGET='16015'
OUT=Path('output/insee-log1-3kc-audit.json')
TMP=Path('tmp_3kc')
TMP.mkdir(exist_ok=True)
parquet_path=TMP/'insee-logement-caract-princ-2023.parquet'

subprocess.run([
    'curl','--http1.1','--fail','--location','--show-error','--silent',
    '--retry','5','--retry-all-errors','--retry-delay','2',
    '--connect-timeout','30','--max-time','900',
    '--output',str(parquet_path),URL
], check=True)

pf=pq.ParquetFile(parquet_path)
fields=pf.schema.names

# Lecture filtrée par commune directement via pyarrow dataset quand possible.
import pyarrow.dataset as ds
dataset=ds.dataset(str(parquet_path),format='parquet')
filter_expr=(ds.field('GEO')==TARGET)
if 'GEO_OBJECT' in fields:
    filter_expr=filter_expr & (ds.field('GEO_OBJECT')=='COM')
table=dataset.to_table(filter=filter_expr)
if table.num_rows==0:
    # Certains exports utilisent CODGEO au lieu de GEO.
    if 'CODGEO' in fields:
        filter_expr=(ds.field('CODGEO')==TARGET)
        table=dataset.to_table(filter=filter_expr)
if table.num_rows==0:
    raise RuntimeError(f'Aucune ligne trouvée pour {TARGET}; champs={fields}')

df=table.to_pandas()
rows=df.to_dict(orient='records')

unique={}
for f in fields:
    vals=[]
    if f in df.columns:
        for v in df[f].dropna().astype(str):
            if v not in vals:
                vals.append(v)
            if len(vals)>=50:
                break
    unique[f]=vals

if 'TIME_PERIOD' in df.columns:
    rows_2023=df[df['TIME_PERIOD'].astype(str)=='2023']
else:
    rows_2023=df

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
    'format':'parquet',
    'fields':fields,
    'target_rows':len(rows),
    'target_rows_2023':int(len(rows_2023)),
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
