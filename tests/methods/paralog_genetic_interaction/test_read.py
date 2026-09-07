"""paralog_genetic_interaction.read — hermetic tests (injected summary rows, no S3).

Pins the combinatorial_dependency_class precedence (constitutive > context > suppressive >
no_interaction), the coverage-gap default (absent -> no_paralog_screened, NOT interaction-negative),
the data_unavailable-vs-no_paralog distinction, and partner ranking by mean_gi.

The reader is AUTHORITATIVE over classification: it re-thresholds each partner from raw effect fields
(mean_gi + frac_lines_strong_gi), NOT the product's baked `interaction_class` column. A CONSTITUTIVE
(broad) buffering call requires a strong per-line effect in a majority-ish of lines
(frac_lines_strong_gi >= 0.4), not merely a small mean shift — see test_frac_strong_gate_* and the
real-data regression at the bottom.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.paralog_genetic_interaction.read import (  # noqa: E402
    combinatorial_dependency_for_gene,
)


def _pair(partner, mean_gi, frac_strong=0.05, min_gi=None, iclass=None, **kw):
    """Build a summary row. frac_strong + mean_gi are the fields the reader re-thresholds on.
    `iclass` sets the product's BAKED convenience label (interaction_class) only — the reader does
    NOT trust it (except as a fallback when mean_gi is absent); it exists so tests can assert the
    reclassification. min_gi defaults to mean_gi (no per-line spread) to isolate the frac gate."""
    base = {
        "target_gene": "GENEA",
        "partner_gene": partner,
        "pair_id": f"GENEA_{partner}",
        "n_lines": 278,
        "mean_gi": mean_gi,
        "median_gi": mean_gi,
        "gi_ttest_pvalue": 1e-10,
        "frac_lines_strong_gi": frac_strong,
        "min_gi": mean_gi if min_gi is None else min_gi,
        "min_gi_model_id": "ACH-000001",
        "min_gi_lineage": "Lung",
        "n_lineages_strong": 3,
        "interaction_class": iclass,
    }
    base.update(kw)
    return base


def test_constitutive_wins_precedence():
    rows = (
        _pair("P1", -0.10, frac_strong=0.12),  # context
        _pair("P2", -0.60, frac_strong=0.50),  # constitutive (mean<=-0.25 AND frac>=0.4)
        _pair("P3", 0.30, frac_strong=0.02),  # suppressive
    )
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "strong_synthetic_lethal"
    # strongest partner = most-negative mean_gi
    assert r["strongest_partner"] == "P2"
    assert r["n_interacting_partners"] == 3


def test_context_when_no_constitutive():
    rows = (_pair("P1", -0.15, frac_strong=0.15), _pair("P2", -0.05, frac_strong=0.02))
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "context_synthetic_lethal"
    assert r["strongest_partner"] == "P1"


def test_suppressive_when_only_positive():
    rows = (_pair("P1", 0.40, frac_strong=0.02), _pair("P2", 0.05, frac_strong=0.01))
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "suppressive_interaction"


def test_no_interaction_when_all_neutral():
    rows = (_pair("P1", -0.05, frac_strong=0.02), _pair("P2", 0.02, frac_strong=0.01))
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "no_interaction"
    assert r["n_interacting_partners"] == 0


def test_absent_gene_is_coverage_gap_not_negative():
    # empty tuple = gene not in the paralog library
    r = combinatorial_dependency_for_gene("NOTINLIB", summary_rows=tuple())
    assert r["combinatorial_dependency_class"] == "no_paralog_screened"
    assert "coverage gap" in r["combinatorial_context"]


def test_read_failure_is_data_unavailable_not_negative(monkeypatch):
    # GENUINE absence: the reader returns None on NoSuchKey/404 -> data_unavailable (NOT a negative
    # interaction; distinct from empty = screened-but-absent -> no_paralog_screened). A transient/creds
    # read failure now RE-RAISES instead of masking — see test_absence_discipline.py. summary_rows=None
    # means "read live", so monkeypatch the reader to the genuine-absence result to stay hermetic.
    import methods.paralog_genetic_interaction.read as _m

    monkeypatch.setattr(_m, "_read_summary_rows", lambda target: None)
    r = combinatorial_dependency_for_gene("SOMEGENE", summary_rows=None)
    assert r["combinatorial_dependency_class"] == "data_unavailable"


def test_partner_ranking_ascending_by_mean_gi():
    rows = (
        _pair("HI", -0.10, frac_strong=0.12),
        _pair("LO", -0.70, frac_strong=0.50),
        _pair("MID", -0.40, frac_strong=0.45),
    )
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    order = [p["partner_gene"] for p in r["top_partners"]]
    assert order == ["LO", "MID", "HI"]


# --- frac_strong constitutive gate (the D2 fix) --------------------------------------------------


def test_frac_strong_gate_demotes_weak_mean_only_constitutive():
    """A partner with a qualifying mean_gi but only a MINORITY of strong lines is NOT constitutive —
    it is context (conditional). This is the core of the over-call fix."""
    rows = (_pair("WEAK", -0.35, frac_strong=0.25, iclass="constitutive_buffering"),)
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "context_synthetic_lethal"
    # the product BAKED constitutive_buffering; the reader re-thresholds to context and keeps the
    # original label for audit.
    assert r["top_partners"][0]["interaction_class"] == "context_buffering"
    assert r["top_partners"][0]["interaction_class_product"] == "constitutive_buffering"


def test_frac_strong_gate_keeps_broad_constitutive():
    """A majority-of-lines strong effect IS constitutive."""
    rows = (_pair("BROAD", -0.55, frac_strong=0.58, iclass="constitutive_buffering"),)
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "strong_synthetic_lethal"
    assert r["top_partners"][0]["interaction_class"] == "constitutive_buffering"


def test_falls_back_to_baked_label_when_raw_fields_absent():
    """Older product build without raw effect fields: trust the baked interaction_class."""
    row = {
        "target_gene": "GENEA",
        "partner_gene": "OLD",
        "pair_id": "GENEA_OLD",
        "n_lines": 200,
        "mean_gi": None,
        "frac_lines_strong_gi": None,
        "min_gi": None,
        "interaction_class": "constitutive_buffering",
    }
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=(row,))
    assert r["combinatorial_dependency_class"] == "strong_synthetic_lethal"


# --- real-data regression: the 4 calibration targets from the 2026-08-15 Takeda review -----------
# Numbers are the ACTUAL per-partner summary stats from the deployed
# depmap-paralog-genetic-interaction-per-pair-v1 product (verified 2026-08-15). Only MARK2/MARK3 is a
# true reciprocal-paralog constitutive SL (frac_strong 0.58). EGFR/ERBB2/FLT3 were over-called
# `constitutive_combinatorial_dependency` by the baked column on weak family-wide GI against
# non-paralog partners (ZAP70 for both ERBB targets; a flat RTK plateau for FLT3) — they must demote
# to context.


def test_regression_MARK2_stays_constitutive():
    rows = (
        _pair("MARK3", -0.5651, frac_strong=0.5827, iclass="constitutive_buffering"),
        _pair("MARK1", -0.2289, frac_strong=0.1367, iclass="context_buffering"),
        _pair("SIK2", -0.1454, frac_strong=0.0719, iclass="no_interaction"),
    )
    r = combinatorial_dependency_for_gene("MARK2", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "strong_synthetic_lethal"
    assert r["strongest_partner"] == "MARK3"


def test_regression_FLT3_demotes_to_context():
    rows = (
        _pair("FGFR1", -0.3355, frac_strong=0.2590, iclass="constitutive_buffering"),
        _pair("FGFR3", -0.3292, frac_strong=0.2230, iclass="constitutive_buffering"),
        _pair("PDGFRA", -0.3205, frac_strong=0.2302, iclass="constitutive_buffering"),
        _pair("RET", -0.3106, frac_strong=0.2194, iclass="constitutive_buffering"),
    )
    r = combinatorial_dependency_for_gene("FLT3", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "context_synthetic_lethal"
    # every partner the product baked as constitutive is re-thresholded to context
    assert all(p["interaction_class"] == "context_buffering" for p in r["top_partners"])


def test_regression_EGFR_demotes_to_context():
    rows = (
        _pair("ZAP70", -0.3729, frac_strong=0.2914, iclass="constitutive_buffering"),
        _pair("TNK1", -0.3121, frac_strong=0.2590, iclass="constitutive_buffering"),
        _pair("ERBB3", -0.2473, frac_strong=0.2086, iclass="context_buffering"),
    )
    r = combinatorial_dependency_for_gene("EGFR", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "context_synthetic_lethal"
    # ZAP70 (a SYK-family T/NK kinase, not an ErbB paralog) no longer mints a constitutive call
    zap = next(p for p in r["top_partners"] if p["partner_gene"] == "ZAP70")
    assert zap["interaction_class"] == "context_buffering"
    assert zap["interaction_class_product"] == "constitutive_buffering"


def test_regression_ERBB2_demotes_to_context():
    rows = (
        _pair("ZAP70", -0.3096, frac_strong=0.1906, iclass="constitutive_buffering"),
        _pair("ERBB3", -0.2299, frac_strong=0.1835, iclass="context_buffering"),
        _pair("TNK2", -0.2009, frac_strong=0.1115, iclass="context_buffering"),
    )
    r = combinatorial_dependency_for_gene("ERBB2", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "context_synthetic_lethal"
