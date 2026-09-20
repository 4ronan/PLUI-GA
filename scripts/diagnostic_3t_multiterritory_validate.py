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
assert runtime["commune_name_source"] in {"env","geo_api_auto"}
assert runtime["panel_source"] in {"env","3V-A-structural-v1","3V-D-insee-typology-v2"}

method=d["method"]
assert method["panel_reference_n"] == 15
assert "15 communes comparables" in method["comparison_rule"]
assert "uniquement à sélectionner les communes de référence" in method["panel_typology_rule"]
assert all("aav" not in str(x.get("id","")).lower() and "dens7" not in str(x.get("id","")).lower() for x in d["discriminant_factors"])
assert all("aav" not in str(x.get("id","")).lower() and "dens7" not in str(x.get("id","")).lower() for x in d["hypotheses"])

expected_provenance={
    "vacancy_private":"required_core",
    "vacant_stock_profile":"contextual",
    "real_estate_market":"contextual_partial_allowed",
    "construction":"contextual_partial_allowed",
    "social_housing":"contextual",
    "demography_housing":"contextual",
    "socioeconomic_context":"contextual_missing_values_allowed",
}
provenance=d.get("source_provenance") or {}
assert set(provenance)==set(expected_provenance)
for block,policy in expected_provenance.items():
    meta=provenance[block]
    assert meta.get("source")
    assert meta.get("period_label")
    assert meta.get("availability_policy")==policy
    assert meta.get("quality_status") in {"ok","partial"}
assert "Sources et millésimes" in h
assert "Les millésimes diffèrent selon les producteurs" in h

quality=d["quality"]
assert quality["status"] == "ok"
assert quality["llm_used"] is False
assert quality["external_knowledge_lookup_used"] is False
assert quality["free_text_generation"] is False
assert quality["kpi_count"] == len(d["kpis"]) == 8
assert quality["discriminant_factor_count"] == len(d["discriminant_factors"])
assert quality["hypothesis_count"] == len(d["hypotheses"])
assert quality["priority_count"] == len(d["priorities"])
assert quality["source_provenance_count"] == len(provenance) == 7
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
    "panel_sufficiency_validated":True,
    "panel_source":runtime["panel_source"],
    "comparison_scale":runtime.get("comparison_scale"),
    "source_provenance_count":quality["source_provenance_count"]
}, ensure_ascii=False))
