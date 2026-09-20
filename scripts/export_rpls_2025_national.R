suppressPackageStartupMessages({
  library(dplyr)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
root <- if (length(args)) args[[1]] else "vendor/propre-rpls"
dir.create("output", showWarnings = FALSE)

find_tab_result <- function(root) {
  files <- list.files(root, recursive = TRUE, full.names = TRUE,
                      pattern = "\\.(rda|RData|rds)$", ignore.case = TRUE)
  files <- unique(c(files[grepl("tab_result", basename(files), ignore.case = TRUE)], files))
  for (f in files) {
    if (grepl("\\.rds$", f, ignore.case = TRUE)) {
      obj <- tryCatch(readRDS(f), error = function(e) NULL)
      if (is.data.frame(obj) && all(c("DEPCOM", "millesime") %in% names(obj))) return(obj)
    } else {
      e <- new.env(parent = emptyenv())
      ok <- tryCatch({ load(f, envir = e); TRUE }, error = function(err) FALSE)
      if (ok) for (nm in ls(e, all.names = TRUE)) {
        obj <- get(nm, envir = e)
        if (is.data.frame(obj) && all(c("DEPCOM", "millesime") %in% names(obj))) return(obj)
      }
    }
  }
  stop("tab_result introuvable")
}

x <- find_tab_result(root) |>
  filter(as.integer(millesime) == 2025, !is.na(DEPCOM), nchar(as.character(DEPCOM)) == 5)

keep <- c(
  "DEPCOM","millesime",
  "nb_logt_total","nb_ls_actif","nb_ls_qpv","nb_ls_coll","nb_ls_ind","nb_ls_etu",
  "nb_ls_loue","nb_ls_vacant","nb_ls_vacant_3","nb_ls_vide","nb_ls_association","nb_ls_autre",
  "num_mob","denom_mob","nb_mes",
  "nb_ls_age_0_5","nb_ls_age_5_10","nb_ls_age_10_20","nb_ls_age_20_40","nb_ls_age_40_60","nb_ls_age_60_plus",
  "nb_ls_dpe_realise",
  "nb_ls_dpe_new_ener_A","nb_ls_dpe_new_ener_B","nb_ls_dpe_new_ener_C","nb_ls_dpe_new_ener_D","nb_ls_dpe_new_ener_E","nb_ls_dpe_new_ener_F","nb_ls_dpe_new_ener_G",
  "somme_loyer","somme_surface"
)

available <- intersect(keep, names(x))
out <- x |> select(all_of(available)) |> arrange(DEPCOM)

# Contrôles de cohérence non destructifs
checks <- list(
  rows = nrow(out),
  unique_communes = n_distinct(out$DEPCOM),
  duplicate_commune_rows = nrow(out) - n_distinct(out$DEPCOM),
  angouleme_rows = sum(as.character(out$DEPCOM) == "16015"),
  available_columns = available,
  missing_columns = setdiff(keep, names(x))
)

write.csv(out, "output/rpls-2025-communes.csv", row.names = FALSE, na = "")
write_json(checks, "output/rpls-2025-checks.json", pretty = TRUE, auto_unbox = TRUE, na = "null")

cat("Export RPLS 2025 termine\n")
cat("Lignes :", nrow(out), "\n")
cat("Communes uniques :", n_distinct(out$DEPCOM), "\n")
cat("Doublons :", nrow(out) - n_distinct(out$DEPCOM), "\n")
cat("Angouleme :", sum(as.character(out$DEPCOM) == "16015"), "ligne(s)\n")
