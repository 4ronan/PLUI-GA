import json
import os
from pathlib import Path

TARGET=os.environ["DIAG_TERRITORY"].strip().upper()
NAME=os.environ["DIAG_COMMUNE_NAME"].strip()
JSON_PATH=Path("output/diagnostic-3r-page.json")
HTML_PATH=Path("output/diagnostic-3r-page.html")

if not JSON_PATH.exists() or JSON_PATH.stat().st_size == 0:
    raise AssertionError("Sortie JSON 3R absente ou vide")
if not HTML_PATH.exists() or HTML_PATH.stat().st_size == 0:
    raise AssertionError("Sortie HTML 3R absente ou vide")

d=json.loads(JSON_PATH.read_text(encoding="utf-8"))
h=HTML_PATH.read_text(encoding="utf-8")

assert d["stage"] == "3R"
assert d["territory"] == TARGET
assert d["subtitle"] == f"{NAME} · code INSEE {TARGET}"
assert d["source_stages"] == ["3O","3P","3Q"]

runtime=d["runtime"]
assert runtime["territory_source"] == "env"
assert runtime["commune_name_source"] == "env"
assert runtime["panel_source"] == "env"

method=d["method"]
assert method["panel_reference_n"] == 15
assert "15 communes comparables" in method["comparison_rule"]

quality=d["quality"]
assert quality["status"] == "ok"
assert quality["llm_used"] is False
assert quality["external_knowledge_lookup_used"] is False
assert quality["free_text_generation"] is False
assert quality["kpi_count"] == len(d["kpis"]) == 8
assert quality["discriminant_factor_count"] == len(d["discriminant_factors"])
assert quality["hypothesis_count"] == len(d["hypotheses"])
assert quality["priority_count"] == len(d["priorities"])
assert all(isinstance(quality[k], int) and quality[k] >= 0 for k in (
    "kpi_count","discriminant_factor_count","hypothesis_count","priority_count"
))

assert d["headline"].get("interpretation")
assert isinstance(d["limits"], list) and d["limits"]
assert isinstance(d["suppressed_levers"], list)
assert all(k.get("label") and isinstance(k.get("value"), str) and isinstance(k.get("detail"), str) for k in d["kpis"])

for factor in d["discriminant_factors"]:
    assert factor.get("comparison_sufficient") is True
    assert isinstance(factor.get("reference_panel_n"), int)
    assert isinstance(factor.get("minimum_reference_panel_n"), int)
    assert factor["minimum_reference_panel_n"] == 10
    assert factor["reference_panel_n"] >= factor["minimum_reference_panel_n"]

needle=f"<strong>{NAME}</strong> · code INSEE {TARGET}."
assert needle in h
assert f"<title>{d['title']} — {NAME}</title>" in h
assert "Diagnostic déterministe · Étape 3R" in h
assert "Aucune IA ni connaissance externe n’intervient" in h

# Détection des reliquats les plus dangereux de la phase mono-territoire.
if TARGET != "16015":
    assert "<strong>Angoulême</strong> · code INSEE 16015." not in h
    assert d["subtitle"] != "Angoulême · code INSEE 16015"

print(json.dumps({
    "status":"3T_OK",
    "territory":TARGET,
    "commune":NAME,
    "kpis":quality["kpi_count"],
    "discriminants":quality["discriminant_factor_count"],
    "hypotheses":quality["hypothesis_count"],
    "priorities":quality["priority_count"],
    "panel_sufficiency_validated":True
}, ensure_ascii=False))
