"""Chain-trace tests for live-reader dispatchers.

For each card with a registered live-reader dispatcher, verify the full call chain
works end-to-end:

  orchestrator → _live_readers.read_live_summary(card_id, ...) → dispatcher function →
  methods/<module>/__init__.py imports → methods/<module>/read.py function call → return

A PASSING test means one of:
  1. The function returned a real summary dict (live data accessible — e.g., local cache)
  2. The function returned a structured `_live_read_error` (data unreachable but
     framework's graceful-degradation contract is honored)

A FAILING test means one of:
  - ImportError (the method module doesn't import — __init__.py missing export)
  - AttributeError (the dispatcher tries to call a function the module doesn't export)
  - Unhandled exception (analysis logic crashes instead of returning structured error)

The framework's wiring defect of 2026-06-27 (forgot to `from .read import read_pan_cancer_distribution`
in methods/depmap_chronos_distribution/__init__.py) would have been caught by this test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from _live_readers import CARD_DISPATCHERS, read_live_summary  # noqa: E402


# === Per-card chain-trace assertions ===
# Each tuple: (card_id, target, indication) — known to be in CARD_DISPATCHERS.

CARDS_WITH_DISPATCHERS = [
    ("target-identity-summary", "KRAS", "COADREAD"),
    ("pan-cancer-crispr-dependency-distribution", "KRAS", "COADREAD"),
    ("pan-cancer-rnai-dependency-distribution", "KRAS", "COADREAD"),
    ("crispr-rnai-dependency-concordance", "KRAS", "COADREAD"),
    ("cellline-rna-distribution", "KRAS", "COADREAD"),
    ("expression-dependency-correlation", "KRAS", "COADREAD"),
    ("dependency-predictability", "KRAS", "COADREAD"),
    ("prism-compound-activity", "KRAS", "COADREAD"),
    ("prism-crispr-concordance", "KRAS", "COADREAD"),
    ("tumor-vs-normal-selectivity", "KRAS", "COADREAD"),
    ("dependency-lineage-selectivity", "KRAS", "COADREAD"),
    ("copy-number-distribution", "KRAS", "COADREAD"),
    ("mutation-type-counts", "KRAS", "COADREAD"),
    ("mutation-stratified-dependency", "KRAS", "COADREAD"),
    ("mutation-hotspot-frequency", "KRAS", "COADREAD"),
    ("tumor-rna-vs-adjacent", "KRAS", "COADREAD"),
    ("protein-surface-evidence", "EGFR", "COADREAD"),   # CSPA surface_confirmation live provider
]


@pytest.mark.parametrize("card_id,target,indication", CARDS_WITH_DISPATCHERS)
def test_dispatcher_registered(card_id, target, indication):
    """Every card listed above must have a registered dispatcher in CARD_DISPATCHERS."""
    assert card_id in CARD_DISPATCHERS, (
        f"card_id {card_id!r} has no dispatcher registered in _live_readers.CARD_DISPATCHERS. "
        f"If you added a card, also add its dispatcher entry."
    )


@pytest.mark.parametrize("card_id,target,indication", CARDS_WITH_DISPATCHERS)
def test_chain_trace_returns_structured(card_id, target, indication):
    """Calling read_live_summary must return a dict — either a real summary OR a
    structured _live_read_error. It must NOT raise Python exceptions for import
    failures, attribute errors, or analysis crashes."""
    try:
        result = read_live_summary(card_id, target, indication)
    except (ImportError, AttributeError) as e:
        pytest.fail(
            f"chain trace for {card_id!r} raised {type(e).__name__}: {e}\n"
            f"This indicates a WIRING DEFECT — either the method module doesn't import, "
            f"OR __init__.py doesn't export the read function. Check:\n"
            f"  - methods/<module>/__init__.py exports the public read function\n"
            f"  - methods/<module>/read.py contains the function the dispatcher calls\n"
            f"  - _live_readers.py dispatcher references the correct function name"
        )
    except Exception as e:
        pytest.fail(
            f"chain trace for {card_id!r} raised unexpected {type(e).__name__}: {e}\n"
            f"Analysis logic should return a structured _live_read_error, not crash."
        )

    assert result is not None, (
        f"Dispatcher for {card_id!r} returned None — should return a summary dict "
        f"or a dict with _live_read_error key, never None."
    )
    assert isinstance(result, dict), (
        f"Dispatcher for {card_id!r} returned {type(result).__name__}, expected dict."
    )

    # Either real summary OR structured error
    has_error = "_live_read_error" in result
    has_summary_or_note = bool(set(result.keys()) - {"_live_read_error", "errors", "_remediation"})

    assert has_error or has_summary_or_note, (
        f"Dispatcher for {card_id!r} returned a dict that contains neither a summary nor "
        f"a structured _live_read_error. Got keys: {list(result.keys())}"
    )

    # WIRING-BUG GUARD: if the dispatcher returned _live_read_error, its content must
    # NOT look like a Python import/attribute error. Those are wiring defects (missing
    # __init__.py re-export, wrong dispatcher function name), NOT legitimate data-
    # availability errors. This is exactly the class of bug the top-level try/except in
    # read_live_summary swallowed prior to 2026-07-01 (E5 dispatcher silently emitted
    # empty summaries for weeks). Explicit assertion here surfaces it.
    if has_error:
        err_str = str(result.get("_live_read_error", ""))
        WIRING_BUG_SIGNATURES = [
            "has no attribute",           # AttributeError from a missing re-export
            "cannot import",              # ImportError from a missing module
            "No module named",            # ModuleNotFoundError from bad sys.path
            "is not a package",           # bad submodule qualification
        ]
        for sig in WIRING_BUG_SIGNATURES:
            assert sig not in err_str, (
                f"Dispatcher for {card_id!r} returned _live_read_error containing wiring-bug "
                f"signature {sig!r}: {err_str!r}\n"
                f"This is NOT a legitimate data-availability error — it means the dispatcher's "
                f"import chain is broken. Fix:\n"
                f"  - methods/<module>/__init__.py should `from .read import <fn>` and __all__\n"
                f"  - _live_readers dispatcher should call the correct function name\n"
                f"  - method module should be reachable on sys.path"
            )


def test_card1_pan_cancer_distribution_chain_specifically():
    """Additional specific test for Card 1: verify the wiring matches the architectural
    claim that orchestrator → dispatcher → methods/depmap_chronos_distribution/read.py →
    methods/depmap_chronos_distribution/cli._load_depmap_files actually executes.

    Pass criterion in unauthenticated environments: result dict contains
    `_live_read_error: s3_read_failed` (AccessDenied on the bucket = expected unauth path).
    Pass criterion in authenticated environments: result dict contains
    `n_cell_lines_evaluated` field (real data flowed back).
    """
    result = read_live_summary("pan-cancer-crispr-dependency-distribution", "KRAS", "COADREAD")
    assert isinstance(result, dict)

    # One of two passing states:
    real_data_present = "n_cell_lines_evaluated" in result
    s3_denied = result.get("_live_read_error") == "s3_read_failed"

    assert real_data_present or s3_denied, (
        f"Card 1 chain trace produced unexpected result. Expected either "
        f"real summary (n_cell_lines_evaluated key) or structured s3_read_failed error. "
        f"Got: {list(result.keys())}"
    )


# Regression: tumor-rna-vs-adjacent must work for indications BEYOND COADREAD.
# Prior bug: the dispatcher hardcoded {COADREAD: coadread-dge-df06320} and returned
# only a _data_note for every other indication (26 of 27) — despite the catalog
# having {ind}-dge-tumor-vs-normal-sensitivity-v1 products the reader can read.
from _live_readers import _dispatch_expression_tumor_vs_adjacent  # noqa: E402


@pytest.mark.parametrize("target,indication", [("EGFR", "LUAD"), ("ERBB2", "BRCA")])
def test_tumor_vs_adjacent_covers_non_coadread(target, indication):
    r = _dispatch_expression_tumor_vs_adjacent(target, indication)
    assert r is not None
    # a real, non-None log2_fc from the sensitivity product's cell A (tumor-vs-adjacent)
    assert r.get("log2_fc") is not None, f"{target}/{indication} still returns n/a (dispatcher gate?)"
    assert "sensitivity-v1" in (r.get("_data_source") or "")


def test_tumor_vs_adjacent_coadread_uses_legacy_manifest():
    """COADREAD must stay on the legacy manifest (byte-stable verdict value)."""
    r = _dispatch_expression_tumor_vs_adjacent("KRAS", "COADREAD")
    # legacy path carries no _data_source key (read_dge_gene_row); the sensitivity
    # path would set _data_source=...sensitivity-v1. Assert we did NOT take that path.
    assert "sensitivity-v1" not in (r.get("_data_source") or "")
    assert r.get("log2_fc") is not None
