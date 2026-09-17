import csv, json, math, statistics
from pathlib import Path

TARGET='16015'
YEAR=2025
PANEL_CODES=['16015','19031','47001','24322','40192','79191','86066','33243','17299','40088','24037','17415','16102','17306','47323','47157']
CSV_PATH=Path('data/rpls-2025-communes.csv')
CHECKS_PATH=Path('data/rpls-2025-checks.json')
OUT=Path('output/rpls-3kf-contract.json')


def num(v):
    if v is None:
        return None
    s=str(v).strip().replace(' ','').replace(',','.')
    if not s:
        return None
    try:
        x=float(s)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def ratio100(n,d):
    return None if n is None or d in (None,0) else 100*n/d


def quantile_linear(vals,p):
    a=sorted(v for v in vals if v is not None and math.isfinite(v))
    if not a:
        return None
    h=(len(a)-1)*p
    i=math.floor(h)
    f=h-i
    return a[i]+(a[min(i+1,len(a)-1)]-a[i])*f


def percentile(panel_vals,target):
    vals=[v for v in panel_vals if v is not None and math.isfinite(v)]
    if target is None or not vals:
        return None
    return 100*sum(v <= target for v in vals)/len(vals)


def metrics(r):
    active=num(r.get('nb_ls_actif'))
    vacant=num(r.get('nb_ls_vacant'))
    vacant3=num(r.get('nb_ls_vacant_3'))
    age40_60=num(r.get('nb_ls_age_40_60'))
    age60=num(r.get('nb_ls_age_60_plus'))
    return {
        'stock_social_actif':active,
        'logements_vacants':vacant,
        'vacance_sociale_pct':ratio100(vacant,active),
        'vacance_plus_3_mois_n':vacant3,
        'vacance_plus_3_mois_pct_stock':ratio100(vacant3,active),
        'vacance_plus_3_mois_pct_vacants':ratio100(vacant3,vacant),
        'mobilite_pct':ratio100(num(r.get('num_mob')),num(r.get('denom_mob'))),
        'part_qpv_pct':ratio100(num(r.get('nb_ls_qpv')),active),
        'part_collectif_pct':ratio100(num(r.get('nb_ls_coll')),active),
        'part_age_40_plus_pct':ratio100((age40_60 or 0)+(age60 or 0),active) if active not in (None,0) else None,
        'part_age_60_plus_pct':ratio100(age60,active),
    }

checks=json.loads(CHECKS_PATH.read_text(encoding='utf-8'))
if checks.get('duplicate_commune_rows') != 0 or checks.get('angouleme_rows') != 1:
    raise RuntimeError(f'Précontrôles RPLS invalides: {checks}')

rows={}
with CSV_PATH.open('r',encoding='utf-8-sig',newline='') as fh:
    reader=csv.DictReader(fh)
    for r in reader:
        code=str(r.get('DEPCOM','')).strip()
        if code in PANEL_CODES:
            if code in rows:
                raise RuntimeError(f'Doublon commune {code}')
            rows[code]=r

missing=sorted(set(PANEL_CODES)-set(rows))
if missing:
    raise RuntimeError(f'Panel RPLS incomplet: {missing}')

panel={code:metrics(r) for code,r in rows.items()}
t=panel[TARGET]
peers=[panel[c] for c in PANEL_CODES if c != TARGET]

keys=['vacance_sociale_pct','mobilite_pct','part_qpv_pct','part_age_40_plus_pct']
medians={k:quantile_linear([x[k] for x in peers],.5) for k in keys}
percentiles={k:percentile([x[k] for x in peers],t[k]) for k in keys}

signals=[
    {
        'id':'social_vacancy',
        'label':'Vacance sociale plutôt contenue',
        'value':t['vacance_sociale_pct'],
        'panel_median':medians['vacance_sociale_pct'],
        'percentile':percentiles['vacance_sociale_pct'],
        'role':'contexte du fonctionnement du parc social',
        'interpretation_limit':'Ne pas transposer à LOVAC.'
    },
    {
        'id':'social_mobility',
        'label':'Mobilité relativement élevée',
        'value':t['mobilite_pct'],
        'panel_median':medians['mobilite_pct'],
        'percentile':percentiles['mobilite_pct'],
        'role':'contexte de mobilité du parc social',
        'interpretation_limit':'Indicateur descriptif du parc social.'
    },
    {
        'id':'social_qpv',
        'label':'Forte concentration du parc social en QPV',
        'value':t['part_qpv_pct'],
        'panel_median':medians['part_qpv_pct'],
        'percentile':percentiles['part_qpv_pct'],
        'role':'contexte spatial du parc social',
        'interpretation_limit':'Ne constitue pas une cause prouvée de vacance privée.'
    },
    {
        'id':'social_age',
        'label':'Parc social relativement ancien',
        'value':t['part_age_40_plus_pct'],
        'panel_median':medians['part_age_40_plus_pct'],
        'percentile':percentiles['part_age_40_plus_pct'],
        'role':'contexte de structure et d’ancienneté du parc social',
        'interpretation_limit':'Ne constitue pas une cause prouvée de vacance privée.'
    },
]

contract={
    'source':'RPLS 2025 - SDES',
    'source_year':YEAR,
    'source_snapshot':'data/rpls-2025-communes.csv',
    'upstream_source':'https://www.statistiques.developpement-durable.gouv.fr/54-millions-de-logements-locatifs-sociaux-en-france-au-1er-janvier-2025',
    'territory':TARGET,
    'scope':'parc locatif social ordinaire des bailleurs sociaux',
    'role':'contexte structurel',
    'merge_with_lovac':False,
    'causal_interpretation':False,
    'universe_note':'RPLS décrit le parc locatif social. Il est distinct du champ LOVAC de la vacance du parc privé. Les foyers et résidences sociales ne relèvent pas du même champ de diffusion détaillée.',
    'metrics':t,
    'signals':signals,
    'panel':{
        'codes':PANEL_CODES,
        'target_excluded_from_reference':True,
        'reference_n':len(peers),
        'percentile_rule':'count(peer <= target) / 15 * 100',
        'quartile_rule':'linear interpolation on the 15 peers, target excluded',
        'medians':medians,
        'percentiles':percentiles,
    },
    'quality':{
        'snapshot_rows':checks.get('rows'),
        'snapshot_unique_communes':checks.get('unique_communes'),
        'snapshot_duplicate_commune_rows':checks.get('duplicate_commune_rows'),
        'panel_complete':len(rows)==len(PANEL_CODES),
        'missing_semantics':'valeur absente, supprimée ou secrète = null/exclue, jamais 0',
        'vacance_plus_3_mois_rule':'nb_ls_vacant_3 décrit la vacance sociale de plus de 3 mois; ne pas l’assimiler à la vacance LOVAC de plus de 2 ans',
        'status':'ok'
    }
}

# Verrous sur les valeurs déjà validées à l’étape 3H.
assert abs(t['vacance_sociale_pct']-1.703975944)<0.01
assert abs(t['mobilite_pct']-9.61)<0.02
assert abs(t['part_qpv_pct']-56.92)<0.02
assert abs(t['part_age_40_plus_pct']-66.84)<0.02
assert abs(t['part_collectif_pct']-90.98)<0.02
assert abs(percentiles['vacance_sociale_pct']-40.0)<0.01
assert abs(percentiles['mobilite_pct']-86.6666666667)<0.01
assert abs(percentiles['part_qpv_pct']-93.3333333333)<0.01
assert abs(percentiles['part_age_40_plus_pct']-73.3333333333)<0.01

OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(contract,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(contract,ensure_ascii=False,indent=2))
