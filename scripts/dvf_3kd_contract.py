import csv, json, math, statistics, subprocess
from collections import defaultdict
from pathlib import Path

TARGET='16015'
DEPT='16'
YEARS=list(range(2020,2026))
LATEST='https://files.data.gouv.fr/geo-dvf/latest/csv'
ARCHIVE_2020='https://files.data.gouv.fr/geo-dvf/2024-12/csv'
OUT=Path('output/dvf-3kd-contract.json')
TMP=Path('tmp_3kd')
TMP.mkdir(exist_ok=True)


def fnum(v):
    if v is None: return None
    s=str(v).strip().replace(' ','').replace(',','.')
    if not s: return None
    try:
        x=float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def download(year):
    # Geo-DVF publie directement un CSV par commune : c'est la voie la plus légère
    # et la plus robuste pour le moteur territorial. Le millésime 2020 n'est plus
    # exposé dans latest ; on le lit dans l'archive officielle 2024-12.
    base=ARCHIVE_2020 if year==2020 else LATEST
    url=f'{base}/{year}/communes/{DEPT}/{TARGET}.csv'
    path=TMP/f'{year}-{TARGET}.csv'
    subprocess.run([
        'curl','--http1.1','--fail','--location','--show-error','--silent',
        '--retry','5','--retry-all-errors','--retry-delay','2',
        '--connect-timeout','30','--max-time','180',
        '--output',str(path),url
    ],check=True)
    return url,path


def mutation_rows(path):
    groups=defaultdict(list)
    with open(path,'rt',encoding='utf-8-sig',newline='') as fh:
        reader=csv.DictReader(fh)
        required={'id_mutation','date_mutation','nature_mutation','valeur_fonciere','code_commune','code_type_local','surface_reelle_bati'}
        missing=required-set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f'Colonnes DVF manquantes: {sorted(missing)}; colonnes={reader.fieldnames}')
        for r in reader:
            if str(r.get('code_commune','')).strip()!=TARGET:
                continue
            mid=str(r.get('id_mutation','')).strip()
            if mid:
                groups[mid].append(r)
    return groups


def summarize_year(year,groups):
    residential_sales=[]
    simple=[]
    simple_by_type={'1':[],'2':[]}
    for mid,rows in groups.items():
        natures={str(r.get('nature_mutation','')).strip() for r in rows}
        if 'Vente' not in natures:
            continue
        res=[]
        seen=set()
        for r in rows:
            code=str(r.get('code_type_local','')).strip()
            if code not in {'1','2'}:
                continue
            lid=str(r.get('id_local') or '').strip()
            key=lid if lid else ('row',str(r.get('adresse_numero','')),str(r.get('adresse_nom_voie','')),str(r.get('surface_reelle_bati','')),code)
            if key in seen:
                continue
            seen.add(key)
            res.append(r)
        if not res:
            continue
        vals=[fnum(r.get('valeur_fonciere')) for r in rows]
        vals=[x for x in vals if x and x>0]
        if not vals:
            continue
        price=vals[0]
        residential_sales.append({'id_mutation':mid,'price':price,'res_n':len(res)})
        if len(res)!=1:
            continue
        r=res[0]
        area=fnum(r.get('surface_reelle_bati'))
        code=str(r.get('code_type_local','')).strip()
        if not area or area<=0:
            continue
        ppm2=price/area
        if not math.isfinite(ppm2) or ppm2<=0:
            continue
        item={'id_mutation':mid,'price':price,'surface':area,'price_m2':ppm2,'type_code':code}
        simple.append(item)
        simple_by_type[code].append(item)

    def med(items,key):
        vals=[x[key] for x in items if x.get(key) is not None]
        return statistics.median(vals) if vals else None

    return {
        'year':year,
        'residential_sale_mutations_n':len(residential_sales),
        'simple_residential_sale_mutations_n':len(simple),
        'median_transaction_value_eur_simple':med(simple,'price'),
        'median_price_m2_eur_simple':med(simple,'price_m2'),
        'houses':{
            'n':len(simple_by_type['1']),
            'median_price_m2_eur':med(simple_by_type['1'],'price_m2')
        },
        'apartments':{
            'n':len(simple_by_type['2']),
            'median_price_m2_eur':med(simple_by_type['2'],'price_m2')
        }
    }

urls=[]
series=[]
for year in YEARS:
    url,path=download(year)
    urls.append(url)
    groups=mutation_rows(path)
    series.append(summarize_year(year,groups))

latest=max((x for x in series if x['residential_sale_mutations_n']>0),key=lambda x:x['year'])
contract={
    'source':'DVF géolocalisées (Etalab / data.gouv.fr)',
    'source_kind':'static_geo_dvf_commune_csv',
    'territory':TARGET,
    'department':DEPT,
    'scope':'contexte du marché immobilier résidentiel',
    'role':'contexte immobilier',
    'merge_with_lovac':False,
    'causal_interpretation':False,
    'years':YEARS,
    'urls':urls,
    'method':{
        'download_strategy':'CSV Geo-DVF communal 16015 ; 2020 depuis archive officielle 2024-12, 2021-2025 depuis latest',
        'mutation_filter':'code_commune=16015; nature_mutation=Vente; au moins un local Maison/Appartement',
        'transaction_count_unit':'id_mutation distinct',
        'price_m2_filter':'ventes résidentielles simples avec exactement un id_local Maison ou Appartement, valeur_fonciere>0, surface_reelle_bati>0',
        'price_m2_formula':'valeur_fonciere / surface_reelle_bati',
        'aggregation':'médiane annuelle',
        'warning':'Le prix au m² DVF est un indicateur de marché descriptif. Les mutations complexes sont exclues du calcul au m² et DVF ne prouve aucune cause de vacance.'
    },
    'series':series,
    'selected_metrics':{
        'latest_year':latest['year'],
        'residential_sale_mutations_n':latest['residential_sale_mutations_n'],
        'simple_residential_sale_mutations_n':latest['simple_residential_sale_mutations_n'],
        'median_price_m2_eur_simple':latest['median_price_m2_eur_simple'],
        'house_median_price_m2_eur':latest['houses']['median_price_m2_eur'],
        'apartment_median_price_m2_eur':latest['apartments']['median_price_m2_eur']
    },
    'quality':{
        'deduplicated_by_id_mutation':True,
        'complex_mutations_excluded_from_price_m2':True,
        'missing_semantics':'absence de valeur = null, jamais 0',
        'status':'ok' if all(x['residential_sale_mutations_n']>0 for x in series) else 'partial'
    }
}
if contract['quality']['status']!='ok':
    raise RuntimeError(json.dumps(contract['quality'],ensure_ascii=False))
OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
