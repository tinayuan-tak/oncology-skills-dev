"""Regression tests for run_scholareval markdown-extraction bugs C11 + C12.

C11 — fold-change merge sentinel collision:
    parse_idas_yaml defaulted tumor_vs_adjacent_fc to 1.0, and the merge guard
    fired on `== 1.0`. A genuine iDAS log2fc=0 also computes to linear FC 1.0,
    so the guard could not tell "iDAS supplied no FC" from "iDAS supplied a real
    log2fc=0" — and silently overwrote the genuine value with the markdown one.
    Fix: default to None; guard on `is None`; coerce leftover None to 1.0 after.

C12 — _capped_count counts regex matches, not distinct mentions:
    "CRISPR CRISPR CRISPR" in one clause yielded n_crispr_studies=3. Fix: dedupe
    by (line_index, lowercased match) so repeated identical hits on one line
    count once, then apply the cap. (True PMID dedup is impossible on free-form
    markdown — the facts.yaml path's _count_unique_pmids is the high-fidelity
    successor.)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from run_scholareval import _merge_report_fc, _capped_count  # noqa: E402


# ---------------------------------------------------------------------------
# C11 — fold-change merge preserves a genuine log2fc=0
# ---------------------------------------------------------------------------

def _omics(fc):
    return {"rna_expression": {"tumor_vs_adjacent_fc": fc}}


def test_C11_genuine_log2fc0_not_overwritten():
    """iDAS log2fc=0 → linear FC 1.0 must survive; the report value must NOT win.

    Before the fix, parse_idas_yaml stored 1.0 for a real log2fc=0 and the
    `== 1.0` guard treated it as 'missing', overwriting with the report's 5.0.
    """
    omics = _omics(1.0)  # genuine log2fc=0 → 2**0 = 1.0 (SUPPLIED, not absent)
    report = {"tumor_vs_adjacent_fc": 5.0}
    _merge_report_fc(omics, report)
    assert omics["rna_expression"]["tumor_vs_adjacent_fc"] == 1.0, (
        "C11 regression: genuine log2fc=0 (FC 1.0) was overwritten by the report value"
    )


def test_C11_absent_fc_filled_from_report():
    """When iDAS supplied no FC (None), the report value fills it."""
    omics = _omics(None)
    report = {"tumor_vs_adjacent_fc": 5.0}
    _merge_report_fc(omics, report)
    assert omics["rna_expression"]["tumor_vs_adjacent_fc"] == 5.0


def test_C11_absent_fc_no_report_defaults_to_one():
    """Absent in both iDAS and report → coerced to numeric 1.0 (scorer contract)."""
    omics = _omics(None)
    report = {}  # report has no FC either
    _merge_report_fc(omics, report)
    fc = omics["rna_expression"]["tumor_vs_adjacent_fc"]
    assert fc == 1.0 and fc is not None, (
        "leftover None must coerce to 1.0 so the scorer's >= comparison is safe"
    )


def test_C11_real_idas_fc_beats_report():
    """A genuine non-trivial iDAS FC (e.g. 3.2) is preserved over the report."""
    omics = _omics(3.2)
    report = {"tumor_vs_adjacent_fc": 5.0}
    _merge_report_fc(omics, report)
    assert omics["rna_expression"]["tumor_vs_adjacent_fc"] == 3.2


# ---------------------------------------------------------------------------
# C12 — _capped_count dedupes repeated same-line mentions
# ---------------------------------------------------------------------------

CRISPR = r'\b(CRISPR|knockout|KO mice|sgRNA)\b'


def test_C12_repeated_same_line_counts_once():
    """Same keyword 3× on one line → 1 distinct mention, not 3."""
    text = "CRISPR screening confirmed the target via CRISPR knockout; CRISPR again."
    # "CRISPR" appears 3× + "knockout" 1× on ONE line → 2 distinct tokens.
    assert _capped_count(text, CRISPR) == 2, (
        f"expected 2 distinct tokens on one line, got {_capped_count(text, CRISPR)}"
    )


def test_C12_distinct_lines_count_separately():
    """The same keyword on 3 different lines → 3 (each line is its own mention)."""
    text = "CRISPR study one.\nCRISPR study two.\nCRISPR study three."
    assert _capped_count(text, CRISPR) == 3


def test_C12_cap_still_applies():
    """The cap bounds the total even across many distinct lines."""
    text = "\n".join(f"CRISPR line {i}" for i in range(10))
    assert _capped_count(text, CRISPR, cap=5) == 5


def test_C12_no_match_is_zero():
    text = "No functional genomics evidence in this section."
    assert _capped_count(text, CRISPR) == 0


def test_C12_single_mention_is_one():
    text = "One CRISPR knockout study (sgRNA library) reported the phenotype."
    # CRISPR, knockout, sgRNA — 3 distinct tokens on one line.
    assert _capped_count(text, CRISPR) == 3
