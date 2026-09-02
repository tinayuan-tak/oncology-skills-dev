"""H1 regression: a SUPPLIED but unmapped indication must NOT leak another cohort's contrast (no S3).

CPTAC is a per-cohort tumor-vs-normal differential. INDICATION_TO_CPTAC omits many common queries
(NSCLC, PRAD, SKCM, ...). The old fallback returned max(|effect_size|) across ALL cohorts for an
unmapped indication — so e.g. an NSCLC query could return OV/BRCA's contrast labeled as NSCLC. The
fix: a supplied-but-unmapped indication returns data_unavailable; the cross-cohort aggregate is
reserved for the indication-FREE (target-only) call. Monkeypatches the loader so no S3 is touched."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

RD = importlib.import_module("methods.cptac_protein_deg.read")


def _fake_indexed():
    # EPCAM exists in the OV cohort with a large effect — the OLD code would have leaked THIS row for
    # any unmapped indication via the cross-cohort max(|effect|) fallback. LUAD carries a modest EPCAM
    # effect so the NSCLC umbrella (→ LUAD+LSCC) has a real leaf to report.
    df = pd.DataFrame([{"cohort": "OV", "gene_symbol": "EPCAM", "protein_effect_size": 9.9},
                       {"cohort": "LUAD", "gene_symbol": "EPCAM", "protein_effect_size": 1.2}])
    gene_idx = {"EPCAM": [0, 1]}
    cohort_gene_idx = {("OV", "EPCAM"): 0, ("LUAD", "EPCAM"): 1}
    return df, cohort_gene_idx, gene_idx


def test_supplied_unmapped_indication_is_data_unavailable(monkeypatch):
    # PRAD is genuinely absent from INDICATION_TO_CPTAC (and is not an umbrella) → must abstain, never
    # leak OV's contrast via the target-only pan-cancer fallback.
    monkeypatch.setattr(RD, "_load_indexed", _fake_indexed)
    out = RD.read_target_summary("EPCAM", "PRAD")
    assert out["protein_expression_class"] == "data_unavailable", (
        f"unmapped indication must abstain, not leak OV's contrast; got {out!r}")
    assert "indication_not_in_cptac" in str(out.get("_data_note", "")), (
        f"expected an honest indication_not_in_cptac reason; got {out.get('_data_note')!r}")
    assert out["protein_effect_size"] is None   # must NOT have returned OV's effect (the leak)


def test_nsclc_umbrella_reports_leaf_not_leak(monkeypatch):
    # NSCLC is now a MAPPED umbrella → LUAD+LSCC. It must report EPCAM's LUAD row (its own leaf),
    # NEVER OV's larger effect (that would be the cross-indication leak the max(|effect|) pick avoids
    # by being restricted to the umbrella's own leaves).
    monkeypatch.setattr(RD, "_load_indexed", _fake_indexed)
    out = RD.read_target_summary("EPCAM", "NSCLC")
    assert out["protein_effect_size"] == 1.2, f"must report LUAD (1.2), not OV (9.9); got {out!r}"
    assert str(out.get("cohort", "")).upper() == "LUAD"


def test_nsclc_umbrella_absent_in_leaves_abstains_no_leak(monkeypatch):
    # A gene present ONLY in OV (not in LUAD/LSCC) → NSCLC umbrella abstains data_unavailable with a
    # leaf-scoped reason, and does NOT leak OV's contrast.
    def _ov_only():
        df = pd.DataFrame([{"cohort": "OV", "gene_symbol": "MUC16", "protein_effect_size": 9.9}])
        return df, {("OV", "MUC16"): 0}, {"MUC16": [0]}
    monkeypatch.setattr(RD, "_load_indexed", _ov_only)
    out = RD.read_target_summary("MUC16", "NSCLC")
    assert out["protein_expression_class"] == "data_unavailable"
    assert "target_not_in_cptac_cohort" in str(out.get("_data_note", ""))
    assert out["protein_effect_size"] is None
