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
    # any unmapped indication via the cross-cohort max(|effect|) fallback.
    df = pd.DataFrame([{"cohort": "OV", "gene_symbol": "EPCAM", "protein_effect_size": 9.9}])
    gene_idx = {"EPCAM": [0]}
    cohort_gene_idx = {("OV", "EPCAM"): 0}
    return df, cohort_gene_idx, gene_idx


def test_supplied_unmapped_indication_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(RD, "_load_indexed", _fake_indexed)
    out = RD.read_target_summary("EPCAM", "NSCLC")   # NSCLC not in INDICATION_TO_CPTAC
    assert out["protein_expression_class"] == "data_unavailable", (
        f"unmapped indication must abstain, not leak OV's contrast; got {out!r}")
    assert "indication_not_in_cptac" in str(out.get("_data_note", "")), (
        f"expected an honest indication_not_in_cptac reason; got {out.get('_data_note')!r}")
    # and it must NOT have returned OV's effect size (the leak)
    assert out["protein_effect_size"] is None
