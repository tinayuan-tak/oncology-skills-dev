"""Public-API import guard for the S0 reorg (analysis-methods#692).

S0 moved `read.py` into a `read/` package (so a future secondary-substrate reader, S1b #694,
has somewhere to live alongside it) and split `steps/` into `r/live/` (production) vs
`r/legacy/` (quarantined). Neither move is supposed to change what a consumer can import.

Structural on purpose, not just "does `import methods.dge_deseq2` work": several OTHER
methods' tests reach into `dge_deseq2.read`'s private helpers directly (e.g.
tests/methods/dge_deseq2/test_comparator_independence.py, test_expression_call_classifier.py,
test_substrate_provenance.py all do `from methods.dge_deseq2 import read as r` then touch an
underscore-prefixed attribute), so "the public names still resolve" is not the whole
contract — this pins that `dge_deseq2.read` keeps behaving like the flat module it replaces,
private helpers included, rather than a package that only re-exports what `__all__` names.
"""

from __future__ import annotations

from pathlib import Path

import methods.dge_deseq2 as dge_deseq2
from methods.dge_deseq2 import read as dge_read

METHOD_DIR = Path(__file__).resolve().parents[1]

# A representative sample of PRIVATE helpers other tests/methods reach into directly (not the
# full ~40-name surface of read/__init__.py — this is an anti-vacuity spot check, not a mirror
# of every call site; if one of these is ever legitimately removed, drop it here too).
_PRIVATE_HELPERS_USED_EXTERNALLY = (
    "_classify_expression_call",
    "_classify_selectivity_from_sensitivity",
    "_comparator_concordance",
    "_family_direction",
    "_family_ran",
    "_independence_fields",
    "_substrate_provenance",
)


def test_dunder_all_names_resolve_and_are_callable():
    assert dge_deseq2.__all__, "dge_deseq2.__all__ must not be empty"
    for name in dge_deseq2.__all__:
        assert hasattr(dge_deseq2, name), f"{name} declared in __all__ but not importable"
        assert callable(getattr(dge_deseq2, name))


def test_dge_deseq2_read_is_a_package_that_still_resolves_every_name():
    # dge_deseq2.read is now a package (read/__init__.py), not a module (read.py) — this is the
    # literal thing S0 changed. `from methods.dge_deseq2 import read as r; r.something` must
    # keep working identically either way.
    assert dge_read.__file__.endswith("read/__init__.py"), (
        f"expected read to be a package (.../read/__init__.py), got {dge_read.__file__}"
    )
    for name in _PRIVATE_HELPERS_USED_EXTERNALLY:
        assert hasattr(dge_read, name), f"external consumers reach into dge_deseq2.read.{name}"


def test_r_live_and_r_legacy_layout():
    """Pins the S0 directory split so a future accidental misplacement fails loudly rather
    than silently changing which scripts run_pipeline.R / cli.py can reach."""
    live = METHOD_DIR / "r" / "live"
    legacy = METHOD_DIR / "r" / "legacy"
    assert {p.name for p in live.glob("*.R")} == {
        "00_load_recount3.R",
        "00_load_xena_toil.R",  # promoted from r/legacy in S1b (#694): secondary/diagnostic substrate
        "06_four_cell_driver.R",
        "07_stratified_four_cell_driver.R",
        "_four_cell_lib.R",
        "run_pipeline.R",
    }
    assert {p.name for p in legacy.glob("*.R")} == {
        "00_load_counts.R",
        "01_build_design.R",
        "02_combat_seq.R",
        "03_deseq2.R",
        "04_write_parquet.R",
        "05_provenance.R",
    }
    assert not (METHOD_DIR / "steps").exists(), "steps/ should be gone, replaced by r/live + r/legacy"


def test_cli_run_pipeline_path_exists():
    from methods.dge_deseq2 import cli

    assert cli.RUN_PIPELINE.is_file()
    assert cli.RUN_PIPELINE == METHOD_DIR / "r" / "live" / "run_pipeline.R"
