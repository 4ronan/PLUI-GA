import json
from pathlib import Path
import duckdb

PARQUET = "https://static.data.gouv.fr/resources/revenus-pauvrete-et-niveau-de-vie-donnees-carroyees-dispositif-fichier-localise-social-et-fiscal-filosofi/20260309-120901/carreaux-200m-met-3035-2021.parquet"
COMMUNE = "16015"

Path("output").mkdir(exist_ok=True)
con = duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs;")

schema = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{PARQUET}')").fetchall()
columns = [r[0] for r in schema]
print("Colonnes parquet:", columns)

# Correspondance insensible à la casse, car le parquet communautaire peut conserver
# la casse des colonnes du fichier source Insee.
by_lower = {c.lower(): c for c in columns}
geo_col = by_lower.get("lcog_geo")
if not geo_col:
    candidates_geo = [c for c in columns if "cog" in c.lower() or "comm" in c.lower()]
    raise RuntimeError(f"Colonne communale introuvable. Colonnes candidates: {candidates_geo}; schéma: {columns}")

where = f"strpos(CAST(\"{geo_col}\" AS VARCHAR), ?) > 0"
count = con.execute(f"SELECT COUNT(*) FROM read_parquet('{PARQUET}') WHERE {where}", [COMMUNE]).fetchone()[0]
if count == 0:
    raise RuntimeError("Aucun carreau Filosofi trouvé pour Angoulême 16015")

wanted_lower = [
    "idcar_200m","idcar_1km","id_car_nat","i_est_200","i_est_1km","lcog_geo",
    "ind","men","men_pauv","men_1ind","men_5ind","men_prop","men_fmp","men_coll","men_mais",
    "ind_0_3","ind_4_5","ind_6_10","ind_11_17","ind_18_24","ind_25_39","ind_40_54","ind_55_64","ind_65_79","ind_80p",
    "log_av45","log_45_70","log_70_90","log_ap90","revdisp","nivvie"
]
available = [by_lower[k] for k in wanted_lower if k in by_lower]

sum_lower = ["ind","men","men_pauv","men_1ind","men_5ind","men_prop","men_fmp","men_coll","men_mais"]
sum_vars = [by_lower[k] for k in sum_lower if k in by_lower]

selects = ["COUNT(*) AS carreaux"]
est_col = by_lower.get("i_est_200")
if est_col:
    selects.append(f'SUM(CASE WHEN CAST("{est_col}" AS INTEGER)=1 THEN 1 ELSE 0 END) AS carreaux_imputes')
else:
    selects.append("NULL AS carreaux_imputes")
for c in sum_vars:
    selects.append(f'SUM(COALESCE("{c}",0)) AS "{c}"')

agg = con.execute(
    f"SELECT {', '.join(selects)} FROM read_parquet('{PARQUET}') WHERE {where}",
    [COMMUNE],
).fetchdf().to_dict(orient="records")[0]

sample_cols = available[:20]
sample_select = ", ".join([f'"{c}"' for c in sample_cols])
sample = con.execute(
    f"SELECT {sample_select} FROM read_parquet('{PARQUET}') WHERE {where} LIMIT 5",
    [COMMUNE],
).fetchdf().to_dict(orient="records") if sample_cols else []

result = {
    "ok": True,
    "source": PARQUET,
    "commune_code": COMMUNE,
    "commune_field": geo_col,
    "rows": count,
    "n_columns": len(columns),
    "columns": columns,
    "candidate_columns_available": available,
    "aggregate": agg,
    "sample": sample,
    "method_note": "Étape 3I-A = validation technique de récupération. Les indicateurs de revenu et de pauvreté ne sont pas encore interprétés."
}

Path("output/filosofi-2021-angouleme.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
print(json.dumps({"rows": count, "n_columns": len(columns), "commune_field": geo_col, "aggregate": agg}, ensure_ascii=False, indent=2, default=str))
