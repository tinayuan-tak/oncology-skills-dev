"""Indication-scoped co-occurrence verdict — B8-01 / B8-02 regression suite.

The verdict-driving `cooccurrence_class` used to be pooled across ALL ~53 cohorts, so a
SINGLE partner appearing co-occurring in one cancer and mutually-exclusive in another
(e.g. KRAS×TP53: +2.86 Pancreatic, -1.35 NSCLC, both q≈0) manufactured a spurious
`both_patterns_present`. These tests pin the two guards that close that hole:
  * the verdict is scoped to the indication's cohort(s), and
  * within a scope each partner is collapsed to one sign, so `both_patterns_present`
    requires TWO DISTINCT partners.
Tests monkeypatch `_read_target_rows` — no S3.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.cooccurrence_fisher_pancohort.read")


def _row(partner, cohort, source, log2_or, bh_q, pooled_eligible=True):
    return {
        "target_gene_symbol": "KRAS",
        "partner_gene_symbol": partner,
        "cohort": cohort,
        "source": source,
        "log2_odds_ratio": log2_or,
        "bh_q_value": bh_q,
        "pooled_eligible": pooled_eligible,
        "ranking_score": None,
    }


def _patch(monkeypatch, rows):
    monkeypatch.setattr(r, "_read_target_rows", lambda sym: rows)


def test_same_partner_opposite_signs_two_cohorts_not_both_patterns(monkeypatch):
    """THE bug: one partner, opposite significant signs in two cohorts of ONE indication.
    Must NOT resolve to both_patterns_present (a single partner cannot be both)."""
    rows = [
        # TP53 strongly CO-OCCURRING in one COADREAD cohort ...
        _row("TP53", "COAD", "tcga_mc3", log2_or=2.5, bh_q=1e-30),
        # ... and strongly MUTUALLY-EXCLUSIVE in another COADREAD cohort.
        _row("TP53", "Colorectal Cancer", "genie_v19", log2_or=-2.5, bh_q=1e-30),
    ]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", "COADREAD")
    assert d["cooccurrence_scope"] == "indication"
    assert d["cooccurrence_class"] != "both_patterns_present"
    # TP53's most-significant sign wins ONE rung only (here both q equal → first-seen co-occurring).
    assert d["cooccurrence_class"] in {"strong_cooccurring", "strong_mutually_exclusive"}
    # A single partner cannot satisfy both driver flags.
    assert not (d["has_cooccurring_driver"] and d["has_mutually_exclusive_driver"])


def test_two_distinct_partners_do_yield_both_patterns(monkeypatch):
    """Legitimate both_patterns_present: DIFFERENT partners drive cooc vs mutex in-scope."""
    rows = [
        _row("APC", "Colorectal Cancer", "genie_v19", log2_or=1.6, bh_q=1e-40),  # co-occurring
        _row("BRAF", "Colorectal Cancer", "genie_v19", log2_or=-3.0, bh_q=1e-40),  # mutually exclusive
    ]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", "COADREAD")
    assert d["cooccurrence_class"] == "both_patterns_present"
    assert d["has_cooccurring_driver"] and d["has_mutually_exclusive_driver"]


def test_out_of_scope_cohorts_excluded_from_verdict(monkeypatch):
    """A strong mutex partner living ONLY in an out-of-indication cohort must not leak in."""
    rows = [
        _row("APC", "Colorectal Cancer", "genie_v19", log2_or=1.6, bh_q=1e-40),  # in COADREAD
        _row("EGFR", "Non-Small Cell Lung Cancer", "genie_v19", log2_or=-3.0, bh_q=1e-40),  # NSCLC only
    ]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", "COADREAD")
    # Only APC (in-scope) drives the verdict → strong_cooccurring, NOT both_patterns_present.
    assert d["cooccurrence_class"] == "strong_cooccurring"
    assert d["scoped_cohorts"] == ["Colorectal Cancer"]


def test_mapped_indication_with_no_scope_rows_abstains(monkeypatch):
    """Indication maps to real cohort labels but the target has no row there → data_unavailable,
    while the pan-cohort DISPLAY landscape is still populated."""
    rows = [
        _row("EGFR", "Non-Small Cell Lung Cancer", "genie_v19", log2_or=-3.0, bh_q=1e-40),
    ]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", "COADREAD")
    assert d["cooccurrence_class"] == "data_unavailable"
    assert d["cooccurrence_scope"] == "unavailable"
    assert not d["has_cooccurring_driver"] and not d["has_mutually_exclusive_driver"]
    # DISPLAY landscape retained (pan-cohort) even though the verdict abstains.
    assert d["top_mutually_exclusive"][0]["partner_gene_symbol"] == "EGFR"


def test_no_indication_uses_pancohort(monkeypatch):
    """No indication → pan_cohort scope on the single PANCAN cohort."""
    rows = [
        _row("APC", "PANCAN", "genie_v19", log2_or=1.6, bh_q=1e-40),
        _row("BRAF", "Colorectal Cancer", "genie_v19", log2_or=-3.0, bh_q=1e-40),  # not PANCAN
    ]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", None)
    assert d["cooccurrence_scope"] == "pan_cohort"
    assert d["scoped_cohorts"] == ["PANCAN"]
    # Only the PANCAN row scopes the verdict → strong_cooccurring (BRAF mutex is out of PANCAN scope).
    assert d["cooccurrence_class"] == "strong_cooccurring"


def test_multiplicity_bonferroni_across_families(monkeypatch):
    """A borderline q that clears 0.05 in ONE cohort must NOT clear it after Bonferroni
    across several scoped (cohort, source) families."""
    # q = 0.03 alone is modest_cooc; with 3 families → 0.09, no longer < 0.05.
    rows = [
        _row("PARTNER_A", "COAD", "tcga_mc3", log2_or=0.8, bh_q=0.03),
        _row("PARTNER_B", "READ", "tcga_mc3", log2_or=0.7, bh_q=0.30),
        _row("PARTNER_C", "Colorectal Cancer", "genie_v19", log2_or=0.7, bh_q=0.30),
    ]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", "COADREAD")
    assert d["cooccurrence_class"] == "ns"


def test_unmapped_indication_falls_back_to_pancohort(monkeypatch):
    rows = [_row("APC", "PANCAN", "genie_v19", log2_or=1.6, bh_q=1e-40)]
    _patch(monkeypatch, rows)
    d = r.read_target_summary("KRAS", "SOME_UNMAPPED_INDICATION")
    assert d["cooccurrence_scope"] == "pan_cohort"
    assert d["cooccurrence_class"] == "strong_cooccurring"


# ── TCGA-WES-only passenger floor (panel-absent, GENIE-absent → demote to ns) ─────────────────────
def test_tcga_wes_only_passenger_demoted_to_ns(monkeypatch):
    """A gene sequenced ONLY in TCGA whole-exome — no panel-eligible pair AND no GENIE-source
    significant pair — is a large/passenger gene whose per-source co-occurrence is a TMB/gene-length
    artifact (live: PCLO/COADREAD read strong_cooccurring off 3961 tcga_mc3-only pairs). The verdict is
    demoted to `ns`; the raw call is preserved in cooccurrence_class_prefloor."""
    _patch(
        monkeypatch,
        [
            _row("DNAH5", "Colorectal Cancer", "tcga_mc3", log2_or=2.9, bh_q=1e-190, pooled_eligible=False),
            _row("LRP1B", "Colorectal Cancer", "tcga_mc3", log2_or=2.7, bh_q=1e-180, pooled_eligible=False),
        ],
    )
    d = r.read_target_summary("PCLO", "COADREAD")
    assert d["cooccurrence_class"] == "ns", "TCGA-WES-only passenger must be demoted"
    assert d["cooccurrence_class_prefloor"] == "strong_cooccurring", "prefloor audit must keep the raw call"
    assert d["has_cooccurring_driver"] is False and d["has_mutually_exclusive_driver"] is False


def test_off_intersect_but_genie_present_driver_not_demoted(monkeypatch):
    """A real driver OFF the restrictive 166-gene panel-intersect (pooled_eligible=False) but sequenced
    on GENIE panels (a GENIE-source significant pair) — e.g. KEAP1/LUAD — must NOT be demoted: GENIE
    presence, not panel-INTERSECT membership, is the gate. Class == prefloor (byte-identical)."""
    _patch(
        monkeypatch,
        [
            _row("STK11", "Colorectal Cancer", "genie_v19", log2_or=1.8, bh_q=1e-40, pooled_eligible=False),
            _row("EGFR", "Colorectal Cancer", "genie_v19", log2_or=-2.8, bh_q=1e-40, pooled_eligible=False),
        ],
    )
    d = r.read_target_summary("KEAP1", "COADREAD")
    assert d["cooccurrence_class"] == "both_patterns_present", "GENIE-present off-intersect driver must be spared"
    assert d["cooccurrence_class_prefloor"] == d["cooccurrence_class"]


def test_panel_eligible_target_byte_identical_prefloor(monkeypatch):
    """A panel-eligible target (pooled_eligible=True) is untouched by the floor: class == prefloor."""
    _patch(
        monkeypatch,
        [
            _row("APC", "Colorectal Cancer", "genie_v19", log2_or=1.6, bh_q=1e-40, pooled_eligible=True),
            _row("BRAF", "Colorectal Cancer", "genie_v19", log2_or=-3.0, bh_q=1e-40, pooled_eligible=True),
        ],
    )
    d = r.read_target_summary("KRAS", "COADREAD")
    assert d["cooccurrence_class"] == "both_patterns_present"
    assert d["cooccurrence_class_prefloor"] == "both_patterns_present"
