"""subtype_survival_association (Q2-subtype) — omnibus log-rank + classifier + monkeypatched e2e. No S3."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.subtype_survival_association.read import (  # noqa: E402
    classify_subtype_survival_association,
    multivariate_logrank,
    MIN_EVENTS,
)
from methods.subtype_survival_association import read as _R  # noqa: E402
from methods.expression_clinical_association import read as _eca  # noqa: E402

np = pytest.importorskip("numpy")
pytest.importorskip("pandas")
pytest.importorskip("scipy")


# ── omnibus (k-group) log-rank ────────────────────────────────────────────────
def test_multivariate_reduces_to_two_group():
    # k=2 separated groups → significant, df=1 (matches the 2-group log-rank behaviour)
    a = (np.arange(1, 9, dtype=float), np.ones(8, int))
    b = (np.arange(50, 58, dtype=float), np.ones(8, int))
    chi2, p, df = multivariate_logrank([a, b])
    assert df == 1 and p < 0.01 and chi2 > 6


def test_three_separated_groups_significant():
    a = (np.arange(1, 9, dtype=float), np.ones(8, int))  # early
    b = (np.arange(30, 38, dtype=float), np.ones(8, int))  # mid
    c = (np.arange(80, 88, dtype=float), np.ones(8, int))  # late
    chi2, p, df = multivariate_logrank([a, b, c])
    assert df == 2 and p < 0.01


def test_identical_groups_null():
    t = np.array([5, 10, 15, 20, 25, 30], dtype=float)
    e = np.ones(6, int)
    chi2, p, df = multivariate_logrank([(t, e), (t.copy(), e.copy()), (t.copy(), e.copy())])
    assert df == 2 and p > 0.5 and chi2 < 1.5


# ── classifier ────────────────────────────────────────────────────────────────
def test_significant_stratifies():
    assert classify_subtype_survival_association(0.001, 3, 60) == "subtype_stratifies_survival"


def test_insignificant_no_association():
    assert classify_subtype_survival_association(0.5, 3, 60) == "no_subtype_survival_association"


def test_one_admissible_stratum_insufficient():
    assert classify_subtype_survival_association(0.001, 1, 60) == "insufficient_survival_data"


def test_too_few_events_insufficient():
    assert classify_subtype_survival_association(0.001, 3, MIN_EVENTS - 1) == "insufficient_survival_data"


# ── monkeypatched end-to-end (synthetic assignment shard + CDR) ───────────────
def _assignments(strata_members):
    import pandas as pd

    rows = []
    for sid, ids in strata_members.items():
        for pid in ids:
            rows.append(
                {"sample_id": pid, "patient_id": pid, "source_native_id": pid, "stratum_id": sid, "is_member": True}
            )
    return pd.DataFrame(rows)


def test_end_to_end_subtype_stratifies(monkeypatch):
    # three subtypes of 20 patients each; A early deaths, B mid, C late → stratifies
    A = [f"TCGA-A{i:03d}-01" for i in range(20)]
    B = [f"TCGA-B{i:03d}-01" for i in range(20)]
    C = [f"TCGA-C{i:03d}-01" for i in range(20)]
    monkeypatch.setattr(
        _R, "load_assignments", lambda m, data_catalog_repo=None: _assignments({"CMS1": A, "CMS2": B, "CMS4": C})
    )
    cdr = {}
    for i, p in enumerate(A):
        cdr[_eca._tcga_case(p)] = (1, 100.0 + i)
    for i, p in enumerate(B):
        cdr[_eca._tcga_case(p)] = (1, 1000.0 + i)
    for i, p in enumerate(C):
        cdr[_eca._tcga_case(p)] = (1, 3000.0 + i)
    monkeypatch.setattr(_eca, "_load_cdr", lambda: cdr)
    out = _R.read_subtype_survival_association("COADREAD", "tcga-maf-subgroup-assignments-coadread-v1")
    assert out["subtype_survival_association_class"] == "subtype_stratifies_survival"
    assert out["n_admissible_strata"] == 3


def test_end_to_end_underpowered_strata_dropped(monkeypatch):
    # only one stratum clears the per-arm floor → insufficient (small strata reported, not claimed)
    big = [f"TCGA-D{i:03d}-01" for i in range(20)]
    tiny = [f"TCGA-E{i:03d}-01" for i in range(3)]
    monkeypatch.setattr(
        _R, "load_assignments", lambda m, data_catalog_repo=None: _assignments({"CMS2": big, "CMS3": tiny})
    )
    cdr = {_eca._tcga_case(p): (1, 100.0 + i) for i, p in enumerate(big + tiny)}
    monkeypatch.setattr(_eca, "_load_cdr", lambda: cdr)
    out = _R.read_subtype_survival_association("COADREAD", "tcga-maf-subgroup-assignments-coadread-v1")
    assert out["subtype_survival_association_class"] == "insufficient_survival_data"
    assert out["n_admissible_strata"] == 1
    assert any(d["stratum"] == "CMS3" for d in out.get("dropped_underpowered_strata", []))


# ── indication → shard resolution (2026-08-20 follow-up: card passes only {indication}) ──
def test_indication_resolves_shard_when_manifest_omitted(monkeypatch):
    import pandas as pd

    captured = {}

    def fake_load(m, data_catalog_repo=None):
        captured["m"] = m
        return pd.DataFrame(columns=["sample_id", "patient_id", "source_native_id", "stratum_id", "is_member"])

    monkeypatch.setattr(_R, "load_assignments", fake_load)
    _R.read_subtype_survival_association("COADREAD")  # no manifest passed
    assert captured["m"] == "tcga-subgroup-assignments-coadread-v1"


def test_unmapped_indication_is_data_unavailable():
    out = _R.read_subtype_survival_association("GLIOMA")  # no registered TCGA subtype shard
    assert out["subtype_survival_association_class"] == "data_unavailable"
    assert "no TCGA subtype" in out["_data_note"]
