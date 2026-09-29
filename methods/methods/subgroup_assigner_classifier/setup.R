#!/usr/bin/env Rscript
# Fail on hard errors (but not on deprecation warnings from install_github)
options(error = function() { traceback(3); quit(status = 1) })

# setup.R — idempotent installer for the CMScaller R dependency (CMS classifier, Phase 1 scaffold).
#
# Run ONCE per fresh pixi env (after `pixi install` provisions the base R + bioconductor deps).
# Installs:
#   - CMScaller (Eide et al. 2017, Sci Rep 7:16618) — nearest-template-prediction (NTP) classifier
#     for the four Consensus Molecular Subtypes of CRC (Guinney 2015). Ships its 787-gene CMS
#     templates as package data (no separate signature ingestion). Built to extend CMS to cell
#     lines / PDX / organoids (our DepMap use case). Deps: Biobase (bioconductor) + limma.
#     Install via remotes::install_github("Lothelab/CMScaller").
#
# Idempotent — a no-op for an already-installed package. Mirrors
# methods/cooccurrence_fisher_pancohort/setup.R (the established GitHub-install pattern).
#
# Uses remotes::install_github (not devtools::install_github, deprecated in devtools 2.5+).

# --- Dependency checks ---
if (!requireNamespace("remotes", quietly = TRUE)) {
  stop("remotes not available — check pixi.toml has r-remotes + re-run `pixi install`")
}
if (!requireNamespace("Biobase", quietly = TRUE)) {
  stop("Biobase not available — check pixi.toml has bioconductor-biobase + re-run `pixi install`")
}
if (!requireNamespace("limma", quietly = TRUE)) {
  stop("limma not available — check pixi.toml has bioconductor-limma + re-run `pixi install`")
}

# --- CMScaller installation ---
# REPRODUCIBILITY TODO (Phase 4, before production): pin CMSCALLER_REF to a commit SHA
# (`git ls-remote https://github.com/Lothelab/CMScaller`) rather than a moving branch — mirrors
# the SHA-pinned DISCOVER/SELECT installs in cooccurrence_fisher_pancohort/setup.R. Left as the
# default branch in this scaffold PR because the SHA cannot be verified offline here.
CMSCALLER_REF <- Sys.getenv("CMSCALLER_REF", unset = "master")

if (!requireNamespace("CMScaller", quietly = TRUE)) {
  message("[setup.R] installing CMScaller from Lothelab/CMScaller @ ", CMSCALLER_REF, " ...")
  remotes::install_github(
    paste0("Lothelab/CMScaller@", CMSCALLER_REF),
    upgrade = "never",
    quiet = FALSE
  )
} else {
  message("[setup.R] CMScaller already installed (skipping): ", packageVersion("CMScaller"))
}

# --- Version summary (provenance) ---
message("[setup.R] R dependency versions:")
for (pkg in c("CMScaller", "Biobase", "limma", "remotes")) {
  if (requireNamespace(pkg, quietly = TRUE)) {
    message("  ", pkg, ": ", as.character(packageVersion(pkg)))
  }
}
message("[setup.R] done.")
