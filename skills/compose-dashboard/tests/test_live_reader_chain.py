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

import os
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from _live_readers import CARD_DISPATCHERS, read_live_summary  # noqa: E402

_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
))


def _is_wired(card_id: str) -> bool:
    """A card is WIRED if it has a bespoke CARD_DISPATCHERS entry OR its card_spec declares a
    methods[].entrypoint (routed by _generic_dispatch — the T11 collapse). Either resolves a live
    reader; only a card with NEITHER is genuinely unwired."""
    if card_id in CARD_DISPATCHERS:
        return True
    p = _CONTRACTS / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return False
    spec = yaml.safe_load(p.read_text()) or {}
    return any(isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or []))


# === Per-card chain-trace assertions ===
# Each tuple: (card_id, target, indication) — known to be WIRED (bespoke dispatcher OR generic).

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
    """Every card listed above must be WIRED — a bespoke CARD_DISPATCHERS entry OR a card_spec
    methods[].entrypoint routed by _generic_dispatch (T11 collapse). A card with neither is a
    genuine wiring defect."""
    assert _is_wired(card_id), (
        f"card_id {card_id!r} is not wired: no _live_readers.CARD_DISPATCHERS entry AND no "
        f"methods[].entrypoint in its card_spec. If you added a card, either add a bespoke dispatcher "
        f"or declare module+entrypoint in the card_spec (generic dispatch)."
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

    Pass criterion in unauthenticated environments (e.g. CI with no S3 creds): result dict carries a
    structured `_live_read_error` — the chain executed all the way to the S3 read and returned a
    structured error rather than throwing. Pass criterion in authenticated environments: result dict
    contains `n_cell_lines_evaluated` (real data flowed back).
    """
    result = read_live_summary("pan-cancer-crispr-dependency-distribution", "KRAS", "COADREAD")
    assert isinstance(result, dict)

    # One of two passing states — the assertion is about the CHAIN EXECUTING and returning a STRUCTURED
    # result, not the exact error string (the live-read seam emits `_live_read_error: str(e)`, whose value
    # varies by the underlying boto/creds error; the old test pinned a specific "s3_read_failed" sentinel
    # that the seam does not actually produce, so it only ever passed via the real-data branch).
    real_data_present = "n_cell_lines_evaluated" in result
    chain_errored = bool(result.get("_live_read_error"))

    assert real_data_present or chain_errored, (
        f"Card 1 chain trace produced unexpected result. Expected either a real summary "
        f"(n_cell_lines_evaluated key) or a structured _live_read_error (chain executed to the S3 read). "
        f"Got: {list(result.keys())}"
    )


# Regression: tumor-rna-vs-adjacent must work for indications BEYOND COADREAD.
# Prior bug: the dispatcher hardcoded {COADREAD: coadread-dge-df06320} and returned
# only a _data_note for every other indication (26 of 27) — despite the catalog
# having {ind}-dge-tumor-vs-normal-sensitivity-v1 products the reader can read.
from _live_readers import _dispatch_expression_tumor_vs_adjacent  # noqa: E402
from conftest import skip_if_no_data  # noqa: E402  (T10: live-S3 skip guard)


@pytest.mark.parametrize("target,indication", [("EGFR", "LUAD"), ("ERBB2", "BRCA")])
def test_tumor_vs_adjacent_covers_non_coadread(target, indication):
    # T10 (2026-08-11 engineering review): reading the sensitivity product needs live object-read
    # access to s3://onc-compbio. Where that's denied (CI / restricted creds) the read either
    # raises OSError(ACCESS_DENIED) OR degrades to a {_data_note: "no ... product ..."} dict —
    # both previously produced a HARD FAIL indistinguishable from a regression. skip_if_no_data
    # converts either of those env-limitation signals into a skip while letting a genuine
    # wiring/logic failure (a dict with real fields but wrong values) still fail.
    r = skip_if_no_data(lambda: _dispatch_expression_tumor_vs_adjacent(target, indication))
    assert r is not None
    # a real, non-None log2_fc from the sensitivity product's cell A (tumor-vs-adjacent)
    assert r.get("log2_fc") is not None, f"{target}/{indication} still returns n/a (dispatcher gate?)"
    assert "sensitivity-v1" in (r.get("_data_source") or "")


def test_tumor_vs_adjacent_coadread_uses_legacy_manifest():
    """COADREAD must stay on the legacy manifest (byte-stable verdict value)."""
    r = skip_if_no_data(lambda: _dispatch_expression_tumor_vs_adjacent("KRAS", "COADREAD"))
    # legacy path carries no _data_source key (read_dge_gene_row); the sensitivity
    # path would set _data_source=...sensitivity-v1. Assert we did NOT take that path.
    assert "sensitivity-v1" not in (r.get("_data_source") or "")
    assert r.get("log2_fc") is not None


# === N2 regression (2026-08-11 code review): expression_call_class emit-parity off-COADREAD ===
#
# Prior bug: the non-COADREAD branch returned only log2_fc/q_value, NOT expression_call_class —
# the field ALL 6 tumor-rna-vs-adjacent interpretation rules key on. So those rules could never
# fire for 26/27 indications (silent driving_rule_id drift + dropped degrader-killer rules).
# These are HERMETIC (mock the dge module) so they run without S3.
import unittest.mock as _mock  # noqa: E402
import _live_readers as _lr  # noqa: E402


@pytest.mark.parametrize("log2fc,q,expected", [
    (2.1, 1e-4, "strong_upregulation"),     # rank #2 rule expression-strong-upregulation-supportive
    (0.8, 1e-3, "modest_upregulation"),
    (-2.0, 1e-4, "strong_downregulation"),  # degrader-killer rule — was silently dropped off-COADREAD
    (0.1, 0.9, "not_informative"),
])
def test_non_coadread_emits_expression_call_class(log2fc, q, expected):
    """The non-COADREAD path must emit expression_call_class classified by the SAME function the
    COADREAD path uses, so the 6 tumor-rna-vs-adjacent rules can fire off-COADREAD."""
    fake_dge = _mock.MagicMock()
    # the dispatcher calls read_tumor_vs_normal_sensitivity_gene_row at the PACKAGE level ...
    fake_dge.read_tumor_vs_normal_sensitivity_gene_row.return_value = {
        "log2fc_cell_a": log2fc, "q_value_cell_a": q, "cells_ran": 4,
        "dominant_direction": "up" if log2fc > 0 else "down",
        "_data_source": "luad-dge-tumor-vs-normal-sensitivity-v1",
    }
    # ... and reaches the classifier via the .read submodule. Wire the REAL classifier (a pure
    # function of log2_fc/q_value) so the test exercises the actual classification, not a stub.
    real_read = _lr._import_method("dge_deseq2").read
    fake_dge.read._classify_expression_call = real_read._classify_expression_call
    with _mock.patch.object(_lr, "_import_method", return_value=fake_dge):
        r = _lr._dispatch_expression_tumor_vs_adjacent("EGFR", "LUAD")
    assert r["expression_call_class"] == expected
    assert r["log2_fc"] == log2fc


# === Drift guard: every card a shipped skill lists in its CARDS roster must have a dispatcher ===
#
# The bug this catches (2026-08-07, PR #267): sc-normal-celltype-expression was added to the
# CARDS list of BOTH tumor-presence and surface-modality-fit, and its method module + card spec
# existed — but no CARD_DISPATCHERS entry was ever added here. read_live_summary therefore hit its
# `dispatcher is None: return None` branch, resolve_cards tagged the card _missing, and run_health
# reported `degraded` on EVERY run of both skills (even for COADREAD, which has a colon shard).
#
# The pre-existing per-card tests above assert the FORWARD direction (a hand-listed card has a
# working chain). This asserts the far more important INVERSE: nothing a skill actually consumes
# is missing a dispatcher. It reads each skill's real CARDS list from run.py by AST (no import /
# no S3), so a newly-added-but-unwired card fails here the moment it lands — at the true drift
# source, not a list someone must remember to update.
import ast  # noqa: E402

_SKILLS_ROOT = SKILL_DIR.parent  # .../skills

# Buckets legitimately absent from CARD_DISPATCHERS: panorama cards are routed via the SEPARATE
# PANORAMA_DISPATCHERS table (subgroup-aware), not CARD_DISPATCHERS.
from _live_readers import PANORAMA_DISPATCHERS  # noqa: E402


def _skill_cards(run_py: Path) -> list[str]:
    """Extract the top-level module CARDS = [...] string literals from a skill's run.py via AST.
    Returns [] if the skill defines no such list (skills that don't use run_wired_skill)."""
    try:
        tree = ast.parse(run_py.read_text())
    except (OSError, SyntaxError):
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CARDS" and isinstance(node.value, (ast.List, ast.Tuple)):
                    return [el.value for el in node.value.elts
                            if isinstance(el, ast.Constant) and isinstance(el.value, str)]
    return []


def _iter_skill_card_pairs():
    for run_py in sorted(_SKILLS_ROOT.glob("*/scripts/run.py")):
        skill = run_py.parent.parent.name
        for card in _skill_cards(run_py):
            yield skill, card


import os  # noqa: E402
import yaml  # noqa: E402

_CONTRACTS_ROOT = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
))


def _card_has_generic_wiring(card_id: str) -> bool:
    """T11: a card is routable WITHOUT a bespoke dispatcher if its card_spec declares a method with
    an `entrypoint` (the generic dispatcher resolves module+entrypoint and calls it directly)."""
    card_path = _CONTRACTS_ROOT / "cards" / f"{card_id}.card.yaml"
    if not card_path.exists():
        return False
    try:
        spec = yaml.safe_load(card_path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return False
    return any(isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or []))


@pytest.mark.parametrize("skill,card_id", list(_iter_skill_card_pairs()))
def test_every_skill_card_has_a_dispatcher(skill, card_id):
    """Every card_id in any shipped skill's CARDS roster must be routable — via a bespoke
    CARD_DISPATCHERS/PANORAMA_DISPATCHERS entry, OR (T11) via the generic dispatcher when the
    card_spec declares module+entrypoint. A card with none of these resolves to None → _missing →
    run_health degraded (the #267 bug)."""
    routable = (
        card_id in CARD_DISPATCHERS
        or card_id in PANORAMA_DISPATCHERS
        or _card_has_generic_wiring(card_id)
    )
    assert routable, (
        f"skill {skill!r} lists card {card_id!r} in its CARDS roster, but it is NOT routable: no "
        f"entry in CARD_DISPATCHERS / PANORAMA_DISPATCHERS, and its card_spec declares no method "
        f"`entrypoint` for the generic dispatcher. read_live_summary will return None → the card is "
        f"tagged _missing → run_health 'degraded' on every run (the PR #267 bug). Either add a "
        f"_dispatch_* wrapper + registry entry, or declare module+entrypoint in the card_spec."
    )
