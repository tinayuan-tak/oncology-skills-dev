"""opentargets_gene_burden — P5 Slice 2 (first verdict-moving card).

The classifier is PURE (classify_burden takes assembled rows), so all direction-resolution
branches are pinned with dict fixtures — no S3. Plus the read_gene_burden data_unavailable
paths via monkeypatched opentargets_common. The guardrail under test: only risk-only fires
lof_risk_phenotype; risk+protect conflict -> direction_unresolved (never a false hold).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.opentargets_gene_burden.read")


def _row(direction, p, disease="D"):
    # split p into mantissa/exponent (p = mantissa * 10^exponent)
    import math
    exp = math.floor(math.log10(p)) if p > 0 else 0
    man = p / (10.0 ** exp)
    return {"directionOnTrait": direction, "pValueMantissa": man, "pValueExponent": exp,
            "beta": None, "diseaseFromSource": disease, "oddsRatio": None,
            "ancestry": None, "statisticalMethod": None}


def test_risk_only_is_lof_risk_phenotype():
    out = r.classify_burden([_row("risk", 1e-10, "Leukemia"), _row("risk", 1e-8)])
    assert out["burden_safety_class"] == "lof_risk_phenotype"
    assert out["n_significant"] == 2
    assert out["top_disease"] == "Leukemia"     # most-significant risk row
    assert out["direction_on_target"] == "LoF"


def test_protect_only_is_protective():
    out = r.classify_burden([_row("protect", 1e-12, "SomeTrait")])
    assert out["burden_safety_class"] == "protective"
    assert out["top_disease"] == "SomeTrait"


def test_risk_and_protect_conflict_is_unresolved():
    # the ATM/PTEN real case — both significant directions -> never a false hold
    out = r.classify_burden([_row("risk", 1e-20), _row("protect", 1e-15)])
    assert out["burden_safety_class"] == "direction_unresolved"
    assert out["n_risk"] == 1 and out["n_protect"] == 1


def test_below_significance_is_no_burden_signal():
    # p above the 1e-6 cutoff -> not counted
    out = r.classify_burden([_row("risk", 1e-3), _row("risk", 5e-4)])
    assert out["burden_safety_class"] == "no_burden_signal"
    assert out["n_significant"] == 0
    assert out["n_total_rows"] == 2


def test_null_direction_significant_is_unresolved():
    out = r.classify_burden([_row(None, 1e-10)])
    assert out["burden_safety_class"] == "direction_unresolved"


def test_empty_rows_is_no_burden_signal():
    out = r.classify_burden([])
    assert out["burden_safety_class"] == "no_burden_signal"


def test_unresolvable_symbol_is_insufficient(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: None)
    out = r.read_gene_burden("NOTAGENE")
    assert out["burden_safety_class"] == "insufficient"


def test_resolved_but_no_rows_is_no_burden_signal(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: "ENSG_ORPHAN")
    monkeypatch.setattr(r, "read_entity",
                        lambda entity, columns=None: pd.DataFrame(columns=r._FIELDS))
    # entity present but empty -> insufficient (entity unavailable path)
    out = r.read_gene_burden("ORPHAN")
    assert out["burden_safety_class"] in ("insufficient", "no_burden_signal")


def test_end_to_end_risk_via_monkeypatch(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: "ENSG_TP53")
    df = pd.DataFrame([_row("risk", 1e-25, "Leukemia"), _row("risk", 1e-19)])
    df["targetId"] = "ENSG_TP53"
    monkeypatch.setattr(r, "read_entity", lambda entity, columns=None: df)
    out = r.read_gene_burden("TP53")
    assert out["burden_safety_class"] == "lof_risk_phenotype"
    assert out["ensembl_gene_id"] == "ENSG_TP53"
