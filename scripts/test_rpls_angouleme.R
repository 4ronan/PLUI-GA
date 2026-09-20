suppressPackageStartupMessages({
  library(dplyr)
  library(jsonlite)
})

`%||%` <- function(x, y) if (is.null(x)) y else x

dir.create("output", showWarnings = FALSE)

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args)) args[[1]] else "vendor/propre-rpls"

find_tab_result <- function(root) {
  candidates <- list.files(root, recursive = TRUE, full.names = TRUE,
                           pattern = "\\.(rda|RData|rds)$", ignore.case = TRUE)
  preferred <- candidates[grepl("tab_result", basename(candidates), ignore.case = TRUE)]
  candidates <- unique(c(preferred, candidates))

  for (f in candidates) {
    if (grepl("\\.rds$", f, ignore.case = TRUE)) {
      obj <- tryCatch(readRDS(f), error = function(e) NULL)
      if (is.data.frame(obj) && all(c("DEPCOM", "millesime") %in% names(obj))) {
        return(list(data = obj, file = f, object = basename(f)))
      }
    } else {
      e <- new.env(parent = emptyenv())
      ok <- tryCatch({ load(f, envir = e); TRUE }, error = function(err) FALSE)
      if (ok) {
        for (nm in ls(e, all.names = TRUE)) {
          obj <- get(nm, envir = e)
          if (is.data.frame(obj) && all(c("DEPCOM", "millesime") %in% names(obj))) {
            return(list(data = obj, file = f, object = nm))
          }
        }
      }
    }
  }
  stop("Aucun objet communal tab_result compatible trouve dans les sources propre.rpls")
}

found <- find_tab_result(root)
x <- found$data

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
  "nb_ls_dpe_ener_new_A","nb_ls_dpe_ener_new_B","nb_ls_dpe_ener_new_C",
  "nb_ls_dpe_ener_new_D","nb_ls_dpe_ener_new_E","nb_ls_dpe_ener_new_F",
  "nb_ls_dpe_ener_new_G",
  "nb_ls_dpe_realise",
  "somme_loyer","somme_surface"
)

available <- intersect(wanted, names(row))
missing <- setdiff(wanted, names(row))

description <- file.path(root, "DESCRIPTION")
version <- NA_character_
if (file.exists(description)) {
  desc <- read.dcf(description)
  if ("Version" %in% colnames(desc)) version <- unname(desc[1, "Version"])
}

payload <- list(
  ok = TRUE,
  source = "propre.rpls source data / tab_result",
  source_file = found$file,
  source_object = found$object %||% NA_character_,
  package_version = version,
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
cat("Source :", found$file, "\n")
cat("Colonnes totales :", ncol(row), "\n")
cat("Colonnes selectionnees :", length(available), "\n")
cat("Colonnes attendues absentes :", length(missing), "\n")
