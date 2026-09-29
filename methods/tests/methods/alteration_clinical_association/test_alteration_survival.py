"""alteration_clinical_association (Q11-alteration) — pure classifier + monkeypatched end-to-end. No S3."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.alteration_clinical_association import read as _R  # noqa: E402
from methods.alteration_clinical_association.read import (  # noqa: E402
    MIN_EVENTS,
    MIN_PER_ARM,
    classify_alteration_survival_association,
)
from methods.expression_clinical_association import read as _eca  # noqa: E402

pytest.importorskip("numpy")
pytest.importorskip("pandas")


# ── pure classifier ───────────────────────────────────────────────────────────
def test_significant_mutated_worse():
    assert classify_alteration_survival_association(0.01, 1, 50, 20, 40) == "alteration_mutated_worse_survival"


def test_significant_mutated_better():
    assert classify_alteration_survival_association(0.01, -1, 50, 20, 40) == "alteration_mutated_better_survival"


def test_insignificant_is_no_association():
    assert classify_alteration_survival_association(0.4, 1, 50, 20, 40) == "no_survival_association"


def test_too_few_events_insufficient():
    assert classify_alteration_survival_association(0.001, 1, MIN_EVENTS - 1, 20, 40) == "insufficient_survival_data"


def test_small_mutated_arm_insufficient():
    # a rare mutation (few mutated patients) is honestly INSUFFICIENT, never a claim
    assert classify_alteration_survival_association(0.001, 1, 50, MIN_PER_ARM - 1, 40) == "insufficient_survival_data"


def test_none_p_is_data_unavailable():
    assert classify_alteration_survival_association(None, 1, 50, 20, 40) == "data_unavailable"


# ── monkeypatched end-to-end (synthetic MAF + CDR; exercises cohort/altered split + log-rank) ──
def _write_maf(tmp_path, cohort, mutated_frac_gene="TARGETX", n_mut=20):
    import pandas as pd

    rows = []
    for i, c in enumerate(cohort):
        rows.append({"sample_id": c, "gene_symbol": "OTHERGENE"})  # every patient is MC3-profiled
        if i < n_mut:
            rows.append({"sample_id": c, "gene_symbol": mutated_frac_gene})
    p = tmp_path / "coadread-mc3.parquet"
    pd.DataFrame(rows).to_parquet(p)
    return p


def test_end_to_end_mutated_worse(tmp_path, monkeypatch):
    cohort = [f"TCGA-AA-{i:04d}" for i in range(60)]  # 20 mutated, 40 WT
    p = _write_maf(tmp_path, cohort, n_mut=20)
    monkeypatch.setattr(_R, "_mc3_maf_path", lambda indication: p)
    # mutated (first 20) die early; WT (next 40) die late → mutated arm worse (+1)
    cdr = {c: (1, (100.0 + i) if i < 20 else (2000.0 + i)) for i, c in enumerate(cohort)}
    monkeypatch.setattr(_eca, "_load_cdr", lambda: cdr)
    out = _R.read_alteration_clinical_association("TARGETX", "COADREAD")
    assert out["alteration_survival_association_class"] == "alteration_mutated_worse_survival"
    assert out["n_mutated"] == 20 and out["n_wildtype"] == 40
    assert out["mutated_hazard_direction"] == 1
    assert out["mutated_frequency"] == round(20 / 60, 4)


def test_end_to_end_rare_mutation_insufficient(tmp_path, monkeypatch):
    # only 5 mutated patients → below MIN_PER_ARM → insufficient, not a spurious claim
    cohort = [f"TCGA-BB-{i:04d}" for i in range(60)]
    p = _write_maf(tmp_path, cohort, n_mut=5)
    monkeypatch.setattr(_R, "_mc3_maf_path", lambda indication: p)
    cdr = {c: (1, 100.0 + i) for i, c in enumerate(cohort)}
    monkeypatch.setattr(_eca, "_load_cdr", lambda: cdr)
    out = _R.read_alteration_clinical_association("TARGETX", "COADREAD")
    assert out["alteration_survival_association_class"] == "insufficient_survival_data"
    assert out["n_mutated"] == 5


def test_end_to_end_no_maf_is_data_unavailable(tmp_path, monkeypatch):
    # no local MAF and no S3 product → graceful data_unavailable (not a crash)
    monkeypatch.setattr(_R, "_mc3_maf_path", lambda indication: tmp_path / "absent.parquet")
    monkeypatch.setattr(_R, "_read_product_table", lambda *a, **k: None)
    out = _R.read_alteration_clinical_association("TARGETX", "COADREAD")
    assert out["alteration_survival_association_class"] == "data_unavailable"
