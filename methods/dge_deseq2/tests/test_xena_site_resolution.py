"""R-side roster consolidation (analysis-methods#733, S1's deferred (b)-half).

`00_load_xena_toil.R` used to carry its own `SITE_BY_INDICATION` / `TCGA_STUDIES_BY_INDICATION`
R literals, independently of `config/indications.yaml` (the single source of truth the Python
side already projects from, S1 #693). `resolve_xena_site_and_studies()` in
`r/live/_four_cell_lib.R` replaces them with a lookup against the SAME YAML (via its new
`xena_primary_site` field). This is a PURE NO-OP: the frozen literals below were copied
verbatim from the pre-#733 `SITE_BY_INDICATION`/`TCGA_STUDIES_BY_INDICATION` R lists, and the
new function must reproduce them exactly for every indication those lists covered.

Run via `Rscript` since the function under test is R, not Python — mirrors the module's
pure-function R test style (test_xena_log2_to_counts.py, test_dedupe_one_aliquot_per_case.py).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
LIB_PATH = METHODS_REPO / "methods" / "dge_deseq2" / "r" / "live" / "_four_cell_lib.R"
CONFIG_PATH = METHODS_REPO / "methods" / "dge_deseq2" / "config" / "indications.yaml"


def _resolve_rscript() -> str | None:
    """Prefer the running interpreter's own pixi env; see test_xena_log2_to_counts's twin."""
    candidates = [
        Path(sys.executable).parent / "Rscript",
        METHODS_REPO / ".pixi" / "envs" / "default" / "bin" / "Rscript",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("Rscript")


RSCRIPT = _resolve_rscript()

pytestmark = pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the R site-resolution function",
)

# The frozen pre-#733 literals — copied verbatim from SITE_BY_INDICATION / TCGA_STUDIES_BY_INDICATION
# as they stood in r/live/00_load_xena_toil.R immediately before this consolidation. Do NOT edit
# these to match a code change: a diff here means the roster moved, which is out of scope.
R_SCRIPT = r"""
source(Sys.getenv("LIB_PATH"))
cfg <- yaml::read_yaml(Sys.getenv("CONFIG_PATH"))$indications

frozen_site <- list(
  brca     = list(tcga = "Breast",              gtex = "Breast"),
  paad     = list(tcga = "Pancreas",            gtex = "Pancreas"),
  luad     = list(tcga = "Lung",                gtex = "Lung"),
  lusc     = list(tcga = "Lung",                gtex = "Lung"),
  coad     = list(tcga = "Colon",               gtex = "Colon"),
  read     = list(tcga = "Rectum",              gtex = "Colon"),
  coadread = list(tcga = c("Colon", "Rectum"),  gtex = "Colon"),
  stad     = list(tcga = "Stomach",             gtex = "Stomach"),
  prad     = list(tcga = "Prostate",            gtex = "Prostate"),
  lihc     = list(tcga = "Liver",               gtex = "Liver"),
  blca     = list(tcga = "Bladder",             gtex = "Bladder"),
  kirc     = list(tcga = "Kidney",              gtex = "Kidney"),
  skcm     = list(tcga = "Skin",                gtex = "Skin"),
  cesc     = list(tcga = "Cervix Uteri",        gtex = "Cervix Uteri"),
  esca     = list(tcga = "Esophagus",           gtex = "Esophagus")
)
frozen_studies <- list(coadread = c("COAD", "READ"))

# 1. Every one of the 15 pre-#733 indications resolves to the EXACT frozen site + studies.
for (ind in names(frozen_site)) {
  got <- resolve_xena_site_and_studies(ind, cfg)
  if (is.null(got)) stop("no mapping for ", ind)
  want_tcga <- frozen_site[[ind]]$tcga
  want_gtex <- frozen_site[[ind]]$gtex
  want_studies <- frozen_studies[[ind]] %||% toupper(ind)
  if (!identical(got$tcga_sites, want_tcga)) stop("tcga_sites mismatch for ", ind)
  if (!identical(got$gtex_sites, want_gtex)) stop("gtex_sites mismatch for ", ind)
  if (!identical(got$tcga_studies, want_studies)) stop("tcga_studies mismatch for ", ind)
}
cat("all 15 frozen indications match exactly\n")

# 2. An indication NEVER in the xena_toil roster (e.g. a recount3-only one) returns NULL, the
# caller's cue to require --primary-site — never a fabricated/partial mapping.
stopifnot("HNSC (no xena_primary_site) resolves to NULL" = is.null(resolve_xena_site_and_studies("hnsc", cfg)))
stopifnot("an unknown indication resolves to NULL" = is.null(resolve_xena_site_and_studies("zzznotreal", cfg)))

# 3. Case-insensitivity: lowercase in, uppercase YAML key lookup.
stopifnot("uppercase-insensitive lookup" = identical(
  resolve_xena_site_and_studies("brca", cfg),
  resolve_xena_site_and_studies("BRCA", cfg)
))

cat("ALL R SITE-RESOLUTION CHECKS PASSED\n")
"""


def _run() -> subprocess.CompletedProcess:
    import os

    env = dict(os.environ)
    env["LIB_PATH"] = str(LIB_PATH)
    env["CONFIG_PATH"] = str(CONFIG_PATH)
    return subprocess.run(
        [RSCRIPT, "-e", R_SCRIPT],
        capture_output=True,
        text=True,
        env=env,
    )


def test_resolve_xena_site_and_studies_matches_frozen_literals():
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ALL R SITE-RESOLUTION CHECKS PASSED" in result.stdout


def test_config_carries_xena_primary_site_for_exactly_the_15_frozen_indications():
    import yaml

    data = yaml.safe_load(CONFIG_PATH.read_text())["indications"]
    have = {name for name, attrs in data.items() if attrs.get("xena_primary_site")}
    expected = {
        "BRCA",
        "PAAD",
        "LUAD",
        "LUSC",
        "COAD",
        "READ",
        "COADREAD",
        "STAD",
        "PRAD",
        "LIHC",
        "BLCA",
        "KIRC",
        "SKCM",
        "CESC",
        "ESCA",
    }
    assert have == expected
    assert len(expected) == 15
