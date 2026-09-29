#!/usr/bin/env Rscript
# Fail on hard errors (but not on deprecation warnings from install_github)
options(error = function() { traceback(3); quit(status = 1) })

# setup.R — idempotent installer for DISCOVER + SELECT R dependencies.
#
# Run ONCE per fresh pixi env (after `pixi install` provisions the base
# R + bioconductor deps). Installs:
#   - DISCOVER (Canisius 2016 Genome Biology 17:261) — Poisson-binomial null
#     for mutual-exclusivity + co-occurrence. Install via
#     remotes::install_github("NKI-CCB/DISCOVER", subdir="r").
#     Repo: github.com/NKI-CCB/DISCOVER (unmaintained since 2019 but
#     still functional for the pairwise test).
#   - SELECT (Mina 2020 Nat Genet 52:1198) — subtype-conditional
#     evolutionary-dependency inference. Install via
#     remotes::install_github("CSOgroup/select", ref="v1.6.3"). Actively
#     maintained by the Ciriello CSO Lab (UNIL Lausanne), current stable
#     tag v1.6.3.
#
# Idempotent — if a package is already installed, this script is a no-op
# for that package.
#
# Uses remotes::install_github directly (not devtools::install_github,
# which is deprecated in devtools 2.5+ and now delegates to remotes anyway).

# --- Dependency checks ---
if (!requireNamespace("remotes", quietly = TRUE)) {
  stop("remotes not available — check pixi.toml has r-remotes + re-run `pixi install`")
}

# --- DISCOVER installation ---
# Pinned to master@a46d99f9 (2026-07-10 HEAD SHA — see git ls-remote on
# github.com/NKI-CCB/DISCOVER). Note: repo's version tags are `py_v0.9.*`
# for the Python package; the R package under `R/` doesn't have its own
# tag, so we pin the commit SHA directly.
#
# IMPORTANT: subdir MUST be `R` (capital), NOT `r` (lowercase). ext4 is
# case-sensitive and the repo's R-package directory is capitalized. Case
# mismatch returns HTTP 404 from the GitHub API — silent failure mode
# that cost ~30 min of diagnostic time on 2026-07-10.
DISCOVER_COMMIT <- "a46d99f9a8a76dc6302f42c814650ca2a1568267"

if (!requireNamespace("discover", quietly = TRUE)) {
  message("[setup.R] installing DISCOVER from NKI-CCB/DISCOVER@", DISCOVER_COMMIT, " ...")
  remotes::install_github(
    paste0("NKI-CCB/DISCOVER@", DISCOVER_COMMIT),
    subdir = "R",  # capital R, not "r" — see comment above
    upgrade = "never",
    quiet = FALSE
  )
} else {
  message("[setup.R] DISCOVER already installed (skipping): ",
          packageVersion("discover"))
}

# --- SELECT installation ---
if (!requireNamespace("select", quietly = TRUE)) {
  message("[setup.R] installing SELECT from github.com/CSOgroup/select @ v1.6.3 ...")
  remotes::install_github(
    "CSOgroup/select",
    ref = "v1.6.3",       # pinned tag for reproducibility
    upgrade = "never",
    quiet = FALSE
  )
} else {
  message("[setup.R] SELECT already installed (skipping): ",
          packageVersion("select"))
}

# --- Verification ---
message("[setup.R] installed R packages summary:")
for (pkg in c("discover", "select", "data.table", "arrow", "optparse",
               "igraph", "Matrix", "matrixStats", "foreach", "doParallel",
               "BiRewire", "remotes")) {
  if (requireNamespace(pkg, quietly = TRUE)) {
    message("  ", pkg, ": ", packageVersion(pkg))
  } else {
    message("  ", pkg, ": NOT INSTALLED")
  }
}
