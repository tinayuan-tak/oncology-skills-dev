"""#790 blocker 1 — 00_load_xena_toil.R's config path resolves one level too shallow.

The S0 reorg (#692) moved this loader from `steps/` (one level under `methods/dge_deseq2/`)
to `r/live/` (two levels), but the `.here`-relative path to `config/indications.yaml` was
left at `file.path(.here, "..", "config", ...)` — resolving to `r/config` (does not exist)
instead of `methods/dge_deseq2/config` two levels up. Latent because the `xena_toil` substrate
is a dev/diagnostic path, never exercised in CI.

Hermetic (no S3, no DESeq2): runs the real script file directly via `Rscript`, exercising the
SAME `.here` self-location logic the pipeline uses — a copied literal path would not catch a
future reorg the way running the actual file does. The script's `CFG_INDICATIONS <-
yaml::read_yaml(...)` line executes before its own `parse_args()` argument validation, so
invoking it with `--indication` alone (still missing `--out`) reaches the config load and then
fails at the script's own `stopifnot(... !is.null(opts$out))` — a config-path failure instead
raises a distinct "cannot open"/"no such file" error from `yaml::read_yaml`, so the two failure
modes are never confused.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
LOADER_PATH = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "00_load_xena_toil.R"


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
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the loader script",
)


def _run() -> subprocess.CompletedProcess:
    # --indication alone: reaches CFG_INDICATIONS <- yaml::read_yaml(...) then dies at the
    # script's own stopifnot for the missing --out, NEVER at DESeq2/S3 (those come later).
    return subprocess.run(
        [RSCRIPT, str(LOADER_PATH), "--indication", "brca"],
        capture_output=True,
        text=True,
    )


def test_loader_resolves_config_indications_yaml_not_missing_out():
    result = _run()
    combined = result.stdout + result.stderr
    assert "cannot open" not in combined.lower(), (
        "config/indications.yaml failed to load — .here path depth is wrong again: " + combined
    )
    assert "no such file" not in combined.lower(), combined
    # The script must get PAST the config load and die on ITS OWN validation (missing --out),
    # proving CFG_INDICATIONS resolved successfully.
    assert result.returncode != 0
    assert "out" in combined.lower()
