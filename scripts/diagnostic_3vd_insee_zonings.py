import hashlib
import json
import os
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CACHE_DIR=Path(os.getenv('DIAG_REFERENCE_CACHE_DIR', str(ROOT/'output/reference-cache/3vd')))
DENSITY_URL='https://www.insee.fr/fr/statistiques/fichier/8571524/fichier_diffusion_2026.xlsx'
AAV_URL='https://www.insee.fr/fr/statistiques/fichier/4803954/AAV2020_au_01-01-2026.zip'
TTL_HOURS=float(os.getenv('DIAG_REFERENCE_CACHE_TTL_HOURS','168'))

NS={
    'm':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p':'http://schemas.openxmlformats.org/package/2006/relationships',
}


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _fresh(path):
    if not path.exists() or path.stat().st_size<=0:
        return False
    return (time.time()-path.stat().st_mtime)/3600 <= TTL_HOURS


def _download(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    last=None
    for attempt in range(1,5):
        try:
            req=urllib.request.Request(
                url,
                headers={
                    'Accept':'*/*',
                    'User-Agent':'PLUI-GA-vacants-panel-selector/3V-D',
                },
            )
            with urllib.request.urlopen(req,timeout=180) as response:
                data=response.read()
            if not data:
                raise RuntimeError('réponse vide')
            tmp=path.with_suffix(path.suffix+'.tmp')
            tmp.write_bytes(data)
            os.replace(tmp,path)
            return data
        except Exception as exc:
            last=exc
            if attempt<4:
                time.sleep(attempt*3)
    raise RuntimeError(f'Échec téléchargement {url}: {last}')


def _ensure_file(url,path):
    if _fresh(path):
        return path.read_bytes(), 'cache_fresh'
    try:
        return _download(url,path), 'download'
    except Exception:
        if path.exists() and path.stat().st_size>0:
            return path.read_bytes(), 'cache_stale_fallback'
        raise


def _col_index(ref):
    letters=''.join(ch for ch in str(ref) if ch.isalpha())
    n=0
    for ch in letters:
        n=n*26+ord(ch.upper())-64
    return n-1


def _xlsx_sheet_rows_from_bytes(data):
    with zipfile.ZipFile(Path('/dev/null') if False else __import__('io').BytesIO(data)) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            for si in root.findall('m:si',NS):
                shared.append(''.join(t.text or '' for t in si.iterfind('.//m:t',NS)))

        wb=ET.fromstring(z.read('xl/workbook.xml'))
        relroot=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rels={x.attrib['Id']:x.attrib['Target'] for x in relroot}

        out={}
        for sh in wb.find('m:sheets',NS):
            name=sh.attrib['name']
            rid=sh.attrib['{'+NS['r']+'}id']
            target=rels[rid].lstrip('/')
            if not target.startswith('xl/'):
                target='xl/'+target
            target=str(Path(target))
            root=ET.fromstring(z.read(target))
            rows=[]
            for row in root.findall('.//m:sheetData/m:row',NS):
                cells={}
                maxcol=-1
                for c in row.findall('m:c',NS):
                    idx=_col_index(c.attrib.get('r','A1'))
                    typ=c.attrib.get('t')
                    v=c.find('m:v',NS)
                    if typ=='inlineStr':
                        isel=c.find('m:is',NS)
                        value=''.join(t.text or '' for t in isel.iterfind('.//m:t',NS)) if isel is not None else ''
                    elif v is None:
                        value=''
                    elif typ=='s':
                        value=shared[int(v.text)] if v.text is not None else ''
                    else:
                        value=v.text or ''
                    cells[idx]=value
                    maxcol=max(maxcol,idx)
                rows.append([cells.get(i,'') for i in range(maxcol+1)] if maxcol>=0 else [])
            out[name]=rows
        return out


def _records_from_sheet(rows,required_header):
    header_index=None
    for i,row in enumerate(rows):
        if required_header in row:
            header_index=i
            break
    if header_index is None:
        raise RuntimeError(f'En-tête {required_header} introuvable')
    headers=[str(x).strip() for x in rows[header_index]]
    records=[]
    for row in rows[header_index+1:]:
        if not row or not any(str(x).strip() for x in row):
            continue
        rec={headers[i]:row[i] if i<len(row) else '' for i in range(len(headers)) if headers[i]}
        records.append(rec)
    return records


def _parse_density(data):
    sheets=_xlsx_sheet_rows_from_bytes(data)
    rows=sheets.get('Maille communale')
    if not rows:
        raise RuntimeError('Feuille Maille communale absente du fichier de densité')
    records=_records_from_sheet(rows,'CODGEO')
    out={}
    for r in records:
        code=str(r.get('CODGEO') or '').strip().upper()
        if len(code)!=5:
            continue
        out[code]={
            'density3':str(r.get('DENS') or '').strip() or None,
            'density3_label':str(r.get('LIBDENS') or '').strip() or None,
            'density_aav':str(r.get('DENS_AAV') or '').strip() or None,
            'density_aav_label':str(r.get('LIBDENS_AAV') or '').strip() or None,
            'density7':str(r.get('DENS7') or '').strip() or None,
            'density7_label':str(r.get('LIBDENS7') or '').strip() or None,
        }
    return out


def _parse_aav(zip_data):
    from io import BytesIO
    with zipfile.ZipFile(BytesIO(zip_data)) as z:
        members=[n for n in z.namelist() if n.lower().endswith('.xlsx')]
        if not members:
            raise RuntimeError('Aucun classeur XLSX dans le ZIP AAV')
        xlsx=z.read(members[0])
    sheets=_xlsx_sheet_rows_from_bytes(xlsx)

    area_rows=_records_from_sheet(sheets.get('AAV2020') or [],'AAV2020')
    area_by_code={}
    for r in area_rows:
        code=str(r.get('AAV2020') or '').strip()
        if not code:
            continue
        area_by_code[code]={
            'aav_size':str(r.get('TAAV2017') or '').strip() or None,
            'aav_detailed_size':str(r.get('TDAAV2017') or '').strip() or None,
        }

    commune_rows=_records_from_sheet(sheets.get('Composition_communale') or [],'CODGEO')
    out={}
    for r in commune_rows:
        code=str(r.get('CODGEO') or '').strip().upper()
        if len(code)!=5:
            continue
        aav_code=str(r.get('AAV2020') or '').strip() or None
        area=area_by_code.get(aav_code,{})
        out[code]={
            'aav_code':aav_code,
            'aav_name':str(r.get('LIBAAV2020') or '').strip() or None,
            'aav_category':str(r.get('CATEAAV2020') or '').strip() or None,
            'aav_size':area.get('aav_size'),
            'aav_detailed_size':area.get('aav_detailed_size'),
        }
    return out


def load_insee_zonings():
    CACHE_DIR.mkdir(parents=True,exist_ok=True)
    density_bytes,density_mode=_ensure_file(DENSITY_URL,CACHE_DIR/'fichier_diffusion_2026.xlsx')
    aav_bytes,aav_mode=_ensure_file(AAV_URL,CACHE_DIR/'AAV2020_au_01-01-2026.zip')
    density=_parse_density(density_bytes)
    aav=_parse_aav(aav_bytes)
    codes=set(density)|set(aav)
    joined={}
    for code in codes:
        joined[code]={**density.get(code,{}),**aav.get(code,{})}
    return {
        'by_code':joined,
        'metadata':{
            'density_url':DENSITY_URL,
            'aav_url':AAV_URL,
            'density_sha256':sha256_bytes(density_bytes),
            'aav_sha256':sha256_bytes(aav_bytes),
            'density_fetch_mode':density_mode,
            'aav_fetch_mode':aav_mode,
            'density_commune_n':len(density),
            'aav_commune_n':len(aav),
            'joined_commune_n':len(joined),
            'cache_ttl_hours':TTL_HOURS,
        },
    }


if __name__=='__main__':
    result=load_insee_zonings()
    print(json.dumps(result['metadata'],ensure_ascii=False,indent=2))
