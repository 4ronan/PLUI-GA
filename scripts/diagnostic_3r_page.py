import json, html
from pathlib import Path
from diagnostic_runtime import target, commune_name, panel_peers, runtime_metadata

P3O=Path('output/diagnostic-3o-synthesis.json')
P3P=Path('output/diagnostic-3p-levers.json')
P3Q=Path('output/diagnostic-3q-priorities.json')
OUT_JSON=Path('output/diagnostic-3r-page.json')
OUT_HTML=Path('output/diagnostic-3r-page.html')
TARGET=target()
COMMUNE_NAME=commune_name()
PANEL_CODES=panel_peers()
REFERENCE_N=len(PANEL_CODES)
RUNTIME=runtime_metadata()

panel_members=[{'code':c,'name':None} for c in PANEL_CODES]
panel_effective_scale=RUNTIME.get('comparison_scale')
panel_algorithm=RUNTIME.get('panel_source')
panel_meta_path=Path('output/diagnostic-3v-panel.json')
if panel_meta_path.exists() and panel_meta_path.stat().st_size>0:
    try:
        panel_meta=json.loads(panel_meta_path.read_text(encoding='utf-8'))
        if (
            str(panel_meta.get('territory'))==TARGET
            and panel_meta.get('panel_codes')==PANEL_CODES
            and panel_meta.get('algorithm')==RUNTIME.get('panel_source')
        ):
            panel_effective_scale=panel_meta.get('effective_scale') or panel_effective_scale
            panel_algorithm=panel_meta.get('algorithm') or panel_algorithm
            panel_members=[
                {
                    'code':x.get('code'),
                    'name':x.get('name'),
                    'rank':x.get('rank'),
                    'density7':x.get('density7'),
                    'density7_label':x.get('density7_label'),
                    'aav_category':x.get('aav_category'),
                    'aav_name':x.get('aav_name'),
                    'aav_size':x.get('aav_size'),
                    'population_ratio':x.get('population_ratio'),
                }
                for x in panel_meta.get('selected',[])
            ]
    except Exception:
        pass

for p in (P3O,P3P,P3Q):
    if not p.exists() or p.stat().st_size==0:
        raise RuntimeError(f'Entrée absente ou vide: {p}')
o=json.loads(P3O.read_text(encoding='utf-8'))
p=json.loads(P3P.read_text(encoding='utf-8'))
q=json.loads(P3Q.read_text(encoding='utf-8'))

if o.get('stage')!='3O' or p.get('stage')!='3P' or q.get('stage')!='3Q':
    raise RuntimeError('Étapes amont inattendues')
if any(str(x.get('territory'))!=TARGET for x in (o,p,q)):
    raise RuntimeError('Territoire inattendu')
if any(x.get('quality',{}).get('status')!='ok' for x in (o,p,q)):
    raise RuntimeError('Une étape amont n’est pas validée')
if any(x.get('generation',{}).get('llm_used') is not False for x in (o,p,q)):
    raise RuntimeError('Les étapes amont doivent être déterministes')

factors={x['id']:x for x in o.get('discriminant_factors',[])}
synth=o['synthesis']

def fnum(v, digits=1, suffix=''):
    if v is None: return 'Indisponible'
    return f"{float(v):.{digits}f}".replace('.',',')+suffix

def esc(x):
    return html.escape(str(x), quote=True)

def comparison_detail(x, median_digits=2, suffix=''):
    if x.get('comparison_sufficient') is False:
        n=x.get('reference_panel_n')
        m=x.get('minimum_reference_panel_n')
        return f"Panel insuffisant (n={n if n is not None else 'Indisponible'} ; minimum {m if m is not None else 'Indisponible'})"
    return f"Panel médian {fnum(x.get('panel_median'),median_digits,suffix)} · percentile {fnum(x.get('percentile'),1)}"

def factor_card(fid):
    x=factors[fid]
    direction={
      'faible':'Faible','tres_faible':'Très faible',
      'eleve':'Élevé','tres_eleve':'Très élevé','typique':'Proche du panel'
    }.get(x.get('direction'),x.get('direction',''))
    return {
      'id':fid,'label':x['label'],'value':x['value'],
      'panel_median':x['panel_median'],'percentile':x['percentile'],
      'direction':direction,'strength':x.get('strength'),
      'universe':x['universe'],'reference_panel_n':x.get('reference_panel_n'),
      'minimum_reference_panel_n':x.get('minimum_reference_panel_n'),
      'comparison_sufficient':x.get('comparison_sufficient', True)
    }

# Cartes KPI: uniquement des valeurs déjà matérialisées en 3O.
vac_cmp={x['id']:x for x in synth['vacancy_status']['comparison']}
market=synth['market_context']['discriminants'][0]
socio={x['id']:x for x in synth['socioeconomic_context']['discriminants']}
construction={x['id']:x for x in synth['construction_context']['comparators']}
social={x['id']:x for x in synth['social_housing_context']['discriminants']}

kpis=[
 {'label':'Vacance privée 2025','value':fnum(vac_cmp['private_vacancy_rate']['value'],2,'%'),'detail':comparison_detail(vac_cmp['private_vacancy_rate'],2,'%')},
 {'label':'Vacance > 2 ans 2025','value':fnum(vac_cmp['private_structural_vacancy_rate']['value'],2,'%'),'detail':comparison_detail(vac_cmp['private_structural_vacancy_rate'],2,'%')},
 {'label':'Prix médian DVF 2025','value':fnum(market['value'],0,' €/m²'),'detail':comparison_detail(market,0,' €/m²')},
 {'label':'Niveau de vie médian','value':fnum(socio['median_income']['value'],0,' €'),'detail':comparison_detail(socio['median_income'],0,' €')},
 {'label':'Taux de pauvreté','value':fnum(socio['poverty_rate']['value'],1,'%'),'detail':comparison_detail(socio['poverty_rate'],1,'%')},
 {'label':'Mises en chantier 2024','value':fnum(construction['sitadel_started_intensity']['value'],2,' / 1 000 hab.'),'detail':comparison_detail(construction['sitadel_started_intensity'],2)},
 {'label':'Mobilité du parc social','value':fnum(social['social_mobility']['value'],2,'%'),'detail':comparison_detail(social['social_mobility'],2,'%')},
 {'label':'Parc social en QPV','value':fnum(social['social_qpv_share']['value'],2,'%'),'detail':comparison_detail(social['social_qpv_share'],2,'%')},
]

page={
 'stage':'3R','territory':TARGET,
 'source_stages':['3O','3P','3Q'],
 'title':'Diagnostic territorial de la vacance des logements',
 'subtitle':f'{COMMUNE_NAME} · code INSEE {TARGET}',
 'headline':o['headline'],
 'kpis':kpis,
 'discriminant_factors':[factor_card(x['id']) for x in o['discriminant_factors']],
 'hypotheses':o['hypotheses'],
 'priorities':q['priorities'],
 'limits':o['limits'],
 'suppressed_levers':p.get('suppressed_levers',[]),
 'method':{
   'panel_reference_n':REFERENCE_N,
   'panel_codes':PANEL_CODES,
   'panel_members':panel_members,
   'panel_source':panel_algorithm,
   'comparison_scale_requested':RUNTIME.get('comparison_scale'),
   'comparison_scale_effective':panel_effective_scale,
   'comparison_rule':f'Le panel cible comprend {REFERENCE_N} communes comparables, cible exclue. L’effectif réellement disponible peut être inférieur selon la source et l’indicateur ; un facteur n’est classé discriminant que si au moins deux tiers du panel demandé sont disponibles. Les percentiles et la qualification discriminante sont conditionnels à la composition de ce panel : un autre panel admissible peut modifier certains facteurs sans que cela constitue une preuve causale.',
   'hypotheses_rule':'Les hypothèses sont générées par règles déterministes à partir du diagnostic; aucune IA n’intervient.',
   'priority_rule':'L’ordre 3Q est un ordre de vérification, pas un classement d’efficacité.',
   'universe_rule':'LOVAC, INSEE RP et RPLS restent des univers distincts.',
   'panel_typology_rule':'Les typologies Insee DENS7 et AAV servent uniquement à sélectionner les communes de référence. Elles ne sont ni des facteurs discriminants, ni des hypothèses, ni des leviers du diagnostic.'
 },
 'runtime':RUNTIME,
 'quality':{
   'kpi_count':len(kpis),
   'discriminant_factor_count':len(o['discriminant_factors']),
   'hypothesis_count':len(o['hypotheses']),
   'priority_count':len(q['priorities']),
   'llm_used':False,
   'external_knowledge_lookup_used':False,
   'free_text_generation':False,
   'status':'ok'
 }
}

def li(items):
    return ''.join(f'<li>{esc(x)}</li>' for x in items)

def badge(text, cls=''):
    return f'<span class="badge {cls}">{esc(text)}</span>'

kpi_html=''.join(
 f'<article class="kpi"><div class="kpi-label">{esc(x["label"])}</div><div class="kpi-value">{esc(x["value"])}</div><div class="muted">{esc(x["detail"])}</div></article>'
 for x in kpis)

disc_html=''
for x in page['discriminant_factors']:
    pct=max(0,min(100,float(x['percentile'])))
    disc_html+=f'''<article class="factor">
      <div class="factor-head"><strong>{esc(x['label'])}</strong>{badge(x['direction'])}</div>
      <div class="factor-value">{fnum(x['value'],2)}</div>
      <div class="bar"><span style="width:{pct}%"></span></div>
      <div class="muted">Percentile {fnum(x['percentile'],1)} · médiane panel {fnum(x['panel_median'],2)} · n={esc(x.get('reference_panel_n') if x.get('reference_panel_n') is not None else 'Indisponible')} · {esc(x['universe'])}</div>
    </article>'''

hyp_html=''
if not page['hypotheses']:
    hyp_html='<article class="panel"><p class="muted">Aucune hypothèse n’est déclenchée par les règles déterministes pour ce territoire.</p></article>'
for h in page['hypotheses']:
    hyp_html+=f'''<article class="panel">
      <div class="factor-head"><h3>{esc(h['title'])}</h3>{badge('Confiance '+h['confidence'])}</div>
      <p>{esc(h['statement'])}</p>
      <p class="muted">{esc(h['confidence_meaning'])}</p>
      <details><summary>Précautions</summary><ul>{li(h['cautions'])}</ul></details>
    </article>'''

prio_html=''
if not page['priorities']:
    prio_html='<article class="panel"><p class="muted">Aucun ordre d’examen supplémentaire n’est déclenché par les leviers disponibles.</p></article>'
for x in page['priorities']:
    prio_html+=f'''<article class="priority">
      <div class="priority-num">{x['order']}</div>
      <div><div class="factor-head"><h3>{esc(x['title'])}</h3>{badge(x['priority_class'].replace('_',' '))}</div>
      <p>{esc(x['reason'])}</p>
      <p><strong>Avant d’agir :</strong> {esc(x['decision_gate'])}</p>
      <details><summary>Données locales à vérifier</summary><ul>{li(x['local_data_to_verify'])}</ul></details></div>
    </article>'''

limits_html=li(page['limits'])
supp_reasons=[x['reason'] for x in page['suppressed_levers']]
supp_html=li(supp_reasons) if supp_reasons else '<li>Aucun levier n’est explicitement écarté par les garde-fous pour ce territoire.</li>'
aav_labels={
    '11':'commune-centre',
    '12':'autre commune du pôle principal',
    '13':'commune d’un pôle secondaire',
    '20':'commune de la couronne',
    '30':'hors attraction des villes',
}
def panel_member_text(x):
    base=f'{x.get("name") or "Commune"} · {x.get("code")}'
    details=[]
    if x.get('density7_label'):
        details.append(str(x['density7_label']))
    if x.get('aav_category'):
        role=aav_labels.get(str(x['aav_category']),f"AAV catégorie {x['aav_category']}")
        if x.get('aav_name') and str(x.get('aav_category'))!='30':
            role+=f" · {x['aav_name']}"
        details.append(role)
    return base + (f" — {' · '.join(details)}" if details else '')

panel_members_html=''.join(
    f'<li>{esc(panel_member_text(x))}</li>'
    for x in page['method']['panel_members']
)

html_doc=f'''<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(page['title'])} — {esc(COMMUNE_NAME)}</title>
<style>
:root{{--bg:#f6f8fb;--card:#fff;--text:#172033;--muted:#667085;--line:#e5e7eb;--blue:#236fc1;--accent:#ffcb4a;}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}}
main{{max-width:1180px;margin:auto;padding:28px 18px 64px}} h1{{font-size:clamp(2rem,4vw,3.6rem);line-height:1.05;margin:.2em 0}} h2{{margin-top:38px}} h3{{margin:.1em 0;font-size:1.05rem}}
.hero{{background:linear-gradient(135deg,#fff,#eef5fd);border:1px solid var(--line);border-radius:24px;padding:28px}} .eyebrow{{color:var(--blue);font-weight:800;text-transform:uppercase;letter-spacing:.08em;font-size:.78rem}}
.summary{{max-width:850px;font-size:1.05rem}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.kpi,.factor,.panel,.priority,.method{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}} .kpi-value{{font-size:1.7rem;font-weight:800;margin:4px 0}} .kpi-label{{font-weight:700}}
.factor-head{{display:flex;gap:10px;justify-content:space-between;align-items:flex-start}} .factor-value{{font-size:1.4rem;font-weight:800;margin:.5rem 0}}
.badge{{background:#eef4fb;color:#164f8d;border-radius:999px;padding:4px 9px;font-size:.74rem;font-weight:800;white-space:nowrap}} .muted{{color:var(--muted);font-size:.9rem}}
.bar{{height:8px;background:#edf0f4;border-radius:999px;overflow:hidden;margin:8px 0}} .bar span{{display:block;height:100%;background:var(--blue)}}
.priority{{display:grid;grid-template-columns:44px 1fr;gap:14px;margin:12px 0}} .priority-num{{width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:var(--accent);font-weight:900}}
.notice{{border-left:4px solid var(--accent);padding:12px 16px;background:#fff8d8;border-radius:8px}} details{{margin-top:10px}} summary{{cursor:pointer;font-weight:700}}
footer{{margin-top:40px;color:var(--muted);font-size:.85rem}} ul{{padding-left:1.2rem}} @media(max-width:600px){{main{{padding:14px 12px 42px}}.hero{{padding:20px}}}}
</style>
</head>
<body><main>
<section class="hero">
<div class="eyebrow">Diagnostic déterministe · Étape 3R</div>
<h1>{esc(page['title'])}</h1>
<p class="summary"><strong>{esc(COMMUNE_NAME)}</strong> · code INSEE {esc(TARGET)}. {esc(o['headline']['interpretation'])}</p>
<p>{badge('Sans IA dans le moteur')} {badge(f'Panel de {REFERENCE_N} communes')} {badge('Traçabilité complète')}</p>
</section>

<h2>Indicateurs clés</h2><section class="grid">{kpi_html}</section>

<h2>Facteurs discriminants</h2>
<p class="muted">Un facteur est signalé lorsque sa position dans le panel est ≤ 25e percentile ou ≥ 75e percentile.</p>
<section class="grid">{disc_html}</section>

<h2>Hypothèses issues du diagnostic</h2>
<div class="notice">Ces hypothèses ne constituent pas des causes démontrées. Elles sont déclenchées automatiquement par des combinaisons d’indicateurs du diagnostic.</div>
<section>{hyp_html}</section>

<h2>Ordre d’examen opérationnel</h2>
<p class="muted">L’ordre ci-dessous indique ce qu’il faut vérifier en premier. Il ne classe pas l’efficacité des politiques publiques.</p>
<section>{prio_html}</section>

<h2>Ce que le diagnostic ne permet pas de conclure</h2>
<section class="panel"><ul>{supp_html}</ul></section>

<h2>Limites méthodologiques</h2>
<section class="panel"><ul>{limits_html}</ul></section>

<h2>Méthode</h2>
<section class="method">
<p><strong>Comparaison :</strong> {esc(page['method']['comparison_rule'])}</p>
<p><strong>Échelle demandée :</strong> {esc(page['method']['comparison_scale_requested'])} · <strong>échelle effective :</strong> {esc(page['method']['comparison_scale_effective'])} · <strong>source du panel :</strong> {esc(page['method']['panel_source'])}</p>
<details><summary>Communes du panel de référence</summary><ul>{panel_members_html}</ul></details>
<p><strong>Hypothèses :</strong> {esc(page['method']['hypotheses_rule'])}</p>
<p><strong>Priorités :</strong> {esc(page['method']['priority_rule'])}</p>
<p><strong>Univers statistiques :</strong> {esc(page['method']['universe_rule'])}</p>
<p><strong>Typologies du panel :</strong> {esc(page['method']['panel_typology_rule'])}</p>
</section>

<footer>Page générée automatiquement à partir des sorties validées 3O, 3P et 3Q. Aucune IA ni connaissance externe n’intervient dans la génération du diagnostic.</footer>
</main></body></html>'''

OUT_JSON.parent.mkdir(exist_ok=True)
OUT_JSON.write_text(json.dumps(page,ensure_ascii=False,indent=2),encoding='utf-8')
OUT_HTML.write_text(html_doc,encoding='utf-8')
print(json.dumps(page['quality'],ensure_ascii=False,indent=2))
