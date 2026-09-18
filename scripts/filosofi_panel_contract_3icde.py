import csv
import json
import math
import statistics
import subprocess
import zipfile
from pathlib import Path
from diagnostic_runtime import target, commune_name, panel_peers, runtime_metadata

SOURCE_PAGE = "https://www.insee.fr/fr/statistiques/7756729"
ZIP_URL = "https://www.insee.fr/fr/statistiques/fichier/7756729/base-cc-filosofi-2021-geo2025_csv.zip"
TIME_PERIOD = "2021"
GEO_OBJECT = "COM"
TARGET = target()
COMMUNE_NAME = commune_name()
PEER_CODES = panel_peers()
PANEL = {c: c for c in PEER_CODES}
NAMES = {TARGET: COMMUNE_NAME, **PANEL}
MEASURES = {
    "MED_SL": "niveau_de_vie_median",
    "PR_MD60": "taux_pauvrete",
}
TMP = Path("tmp_filosofi_panel")
OUT = Path("output")
TMP.mkdir(exist_ok=True)
OUT.mkdir(exist_ok=True)
zip_path = TMP / "base-cc-filosofi-2021-geo2025_csv.zip"

subprocess.run([
    "curl", "--fail", "--location", "--show-error", "--silent",
    "--retry", "6", "--retry-all-errors", "--retry-delay", "3",
    "--connect-timeout", "30", "--max-time", "600",
    "--output", str(zip_path), ZIP_URL,
], check=True)

if not zipfile.is_zipfile(zip_path):
    raise RuntimeError("Archive Filosofi invalide")

wanted_codes = {TARGET, *PANEL.keys()}
rows = {code: {} for code in wanted_codes}
labels = {}
units = {}

with zipfile.ZipFile(zip_path) as z:
    names = z.namelist()
    data_name = next(n for n in names if n.endswith("DS_FILOSOFI_CC_data.csv"))
    meta_name = next((n for n in names if n.endswith("DS_FILOSOFI_CC_metadata.csv")), None)
    if meta_name:
        rd = csv.DictReader(z.read(meta_name).decode("utf-8-sig").splitlines(), delimiter=";")
        for r in rd:
            if r.get("COD_VAR") == "FILOSOFI_MEASURE" and r.get("COD_MOD"):
                labels[r["COD_MOD"]] = r.get("LIB_MOD")
    rd = csv.DictReader(z.read(data_name).decode("utf-8-sig").splitlines(), delimiter=";")
    for r in rd:
        code = str(r.get("GEO", "")).strip()
        measure = str(r.get("FILOSOFI_MEASURE", "")).strip()
        if code not in wanted_codes or measure not in MEASURES:
            continue
        if str(r.get("GEO_OBJECT", "")).strip() != GEO_OBJECT:
            continue
        if str(r.get("TIME_PERIOD", "")).strip() != TIME_PERIOD:
            continue
        raw = str(r.get("OBS_VALUE", "")).strip()
        if raw in ("", "s", "nd", "NA", "NaN"):
            value = None
        else:
            value = float(raw.replace(" ", "").replace(",", "."))
        if measure in rows[code]:
            raise RuntimeError(f"Doublon {code}/{measure}")
        rows[code][measure] = value
        units[measure] = r.get("UNIT_MEASURE")

missing = []
for code in wanted_codes:
    for m in MEASURES:
        if m not in rows[code]:
            rows[code][m] = None
            missing.append(f"{code}/{m}")

# Filosofi peut masquer certaines valeurs au titre du secret statistique.
# Une valeur absente reste None et n'est jamais transformée en zéro.

def q_linear(values, p):
    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return xs[0]
    h = (n - 1) * p
    lo = math.floor(h)
    hi = math.ceil(h)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (h - lo)

def stats_for(measure):
    panel_values = [rows[c][measure] for c in PANEL if rows[c][measure] is not None]
    target_value = rows[TARGET][measure]
    if not panel_values:
        return {
            "target": target_value,
            "panel_min": None, "panel_q1": None, "panel_median": None,
            "panel_q3": None, "panel_max": None, "percentile_empirique": None,
            "panel_n": 0,
        }
    percentile = None if target_value is None else 100.0 * sum(v <= target_value for v in panel_values) / len(panel_values)
    return {
        "target": target_value,
        "panel_min": min(panel_values),
        "panel_q1": q_linear(panel_values, 0.25),
        "panel_median": statistics.median(panel_values),
        "panel_q3": q_linear(panel_values, 0.75),
        "panel_max": max(panel_values),
        "percentile_empirique": percentile,
        "panel_n": len(panel_values),
    }

income = stats_for("MED_SL")
poverty = stats_for("PR_MD60")

def relative_label(p, low, mid, high):
    if p is None:
        return "Indisponible (secret statistique ou donnée non diffusée)"
    if p < 25:
        return low
    if p >= 75:
        return high
    return mid

signals = [
    {
        "id": "income_median",
        "label": relative_label(income["percentile_empirique"], "Niveau de vie médian relativement faible", "Niveau de vie médian intermédiaire", "Niveau de vie médian relativement élevé"),
        "value": income["target"],
        "percentile": income["percentile_empirique"],
        "panel_median": income["panel_median"],
        "role": "contexte socio-économique",
    },
    {
        "id": "poverty_rate",
        "label": relative_label(poverty["percentile_empirique"], "Pauvreté relativement faible", "Pauvreté intermédiaire", "Pauvreté relativement élevée"),
        "value": poverty["target"],
        "percentile": poverty["percentile_empirique"],
        "panel_median": poverty["panel_median"],
        "role": "contexte socio-économique",
    },
]

def fmt_value(v, digits=1):
    return None if v is None else f"{v:.{digits}f}"

income_text = (
    f"À {COMMUNE_NAME}, le niveau de vie médian est de {income['target']:.0f} € par unité de consommation "
    f"(médiane du panel : {income['panel_median']:.0f} € ; percentile empirique : {income['percentile_empirique']:.1f} %). "
    if income['target'] is not None and income['panel_median'] is not None and income['percentile_empirique'] is not None
    else f"À {COMMUNE_NAME}, le niveau de vie médian n'est pas disponible avec un panel comparable suffisant. "
)
poverty_text = (
    f"Le taux de pauvreté atteint {poverty['target']:.1f} % "
    f"(médiane du panel : {poverty['panel_median']:.1f} % ; percentile empirique : {poverty['percentile_empirique']:.1f} %). "
    if poverty['target'] is not None and poverty['panel_median'] is not None and poverty['percentile_empirique'] is not None
    else "Le taux de pauvreté n'est pas diffusé pour la commune ou ne permet pas de comparaison robuste ; il est conservé comme indisponible et n'est pas assimilé à zéro. "
)
summary = (
    income_text + poverty_text +
    "Ces indicateurs décrivent le contexte socio-économique du territoire. Ils ne permettent pas d'expliquer directement la vacance privée ni d'attribuer une situation socio-économique aux logements vacants."
)

contract = {
    "source": "Filosofi 2021 - Insee",
    "territory": TARGET,
    "scope": "contexte socio-économique communal",
    "role": "contexte structurel",
    "merge_with_lovac": False,
    "causal_interpretation": False,
    "selected_indicators": ["MED_SL", "PR_MD60"],
    "signals": signals,
    "metrics": {
        "niveau_de_vie_median": income["target"],
        "taux_pauvrete": poverty["target"],
        "percentiles": {
            "revenu_median": income["percentile_empirique"],
            "pauvrete": poverty["percentile_empirique"],
        },
        "medians_panel": {
            "revenu_median": income["panel_median"],
            "pauvrete": poverty["panel_median"],
        },
    },
    "quality": {
        "panel_n_excluding_target": len(PANEL),
        "panel_n_by_indicator": {
            "MED_SL": income["panel_n"],
            "PR_MD60": poverty["panel_n"],
        },
        "target_missing_indicators": [
            code for code, stat in (("MED_SL", income), ("PR_MD60", poverty))
            if stat["target"] is None
        ],
        "missing_semantics": "secret statistique / absence = null et exclusion de la comparaison; jamais 0",
        "percentile_rule": f"count(panel <= target) / n_disponible * 100",
        "quartile_rule": "linear interpolation on available peers, target excluded",
        "year": 2021,
    },
    "summary": summary,
    "runtime": runtime_metadata(),
}

result = {
    "ok": True,
    "stage": "3I-C/D/E",
    "source_page": SOURCE_PAGE,
    "download_url": ZIP_URL,
    "source_file": data_name,
    "time_period": TIME_PERIOD,
    "indicator_choice": {
        "count": 2,
        "indicators": [
            {"code": "MED_SL", "label": labels.get("MED_SL"), "unit": units.get("MED_SL"), "use": "niveau de vie médian"},
            {"code": "PR_MD60", "label": labels.get("PR_MD60"), "unit": units.get("PR_MD60"), "use": "taux de pauvreté au seuil de 60 %"},
        ],
        "excluded_from_v1": ["D1_SL", "D9_SL", "IR_D9_D1_SL", "income_components"],
        "reason": "V1 volontairement parcimonieuse : deux indicateurs suffisent pour le contexte revenu/pauvreté sans surcharger le diagnostic.",
    },
    "communes": [
        {
            "code": c,
            "name": NAMES[c],
            "is_target": c == TARGET,
            "MED_SL": rows[c]["MED_SL"],
            "PR_MD60": rows[c]["PR_MD60"],
        }
        for c in [TARGET, *PANEL.keys()]
    ],
    "panel_stats": {
        "MED_SL": income,
        "PR_MD60": poverty,
    },
    "contract": contract,
}

out = OUT / "filosofi-3icde-panel.json"
payload = json.dumps(result, ensure_ascii=False, indent=2)
out.write_text(payload, encoding="utf-8")
# Alias temporaire pour les workflows de non-régression antérieurs.
(OUT / "filosofi-3icde-angouleme-panel.json").write_text(payload, encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
