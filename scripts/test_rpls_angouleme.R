suppressPackageStartupMessages({
  library(dplyr)
  library(jsonlite)
})

dir.create("output", showWarnings = FALSE)

x <- propre.rpls::tab_result
stopifnot(all(c("DEPCOM", "millesime") %in% names(x)))

row <- x |>
  filter(as.character(DEPCOM) == "16015", as.integer(millesime) == 2025)

if (nrow(row) != 1) {
  stop(sprintf(
    "Attendu: exactement 1 ligne pour DEPCOM=16015, millesime=2025. Trouve: %s",
    nrow(row)
  ))
}

wanted <- c(
  "DEPCOM","millesime",
  "nb_ls_actif","nb_logt_total","nb_ls_loue","nb_ls_vacant","nb_ls_vacant_3",
  "num_mob","denom_mob",
  "nb_ls_age_0_5","nb_ls_age_5_10","nb_ls_age_10_20",
  "nb_ls_age_20_40","nb_ls_age_40_60","nb_ls_age_60_plus",
  "nb_ls_dpe_new_ener_A","nb_ls_dpe_new_ener_B","nb_ls_dpe_new_ener_C",
  "nb_ls_dpe_new_ener_D","nb_ls_dpe_new_ener_E","nb_ls_dpe_new_ener_F",
  "nb_ls_dpe_new_ener_G",
  "somme_loyer","somme_surface"
)

available <- intersect(wanted, names(row))
missing <- setdiff(wanted, names(row))

payload <- list(
  ok = TRUE,
  source = "propre.rpls::tab_result",
  package_version = as.character(utils::packageVersion("propre.rpls")),
  commune_code = "16015",
  millesime = 2025,
  n_rows = nrow(row),
  n_columns_total = ncol(row),
  selected_columns = available,
  missing_expected_columns = missing,
  values = as.list(row[1, available, drop = FALSE]),
  full_column_names = names(row)
)

write_json(
  payload,
  "output/rpls-2025-angouleme.json",
  pretty = TRUE,
  auto_unbox = TRUE,
  na = "null",
  dataframe = "rows"
)

cat("Extraction reussie.\n")
cat("Colonnes totales :", ncol(row), "\n")
cat("Colonnes selectionnees :", length(available), "\n")
cat("Colonnes attendues absentes :", length(missing), "\n")
