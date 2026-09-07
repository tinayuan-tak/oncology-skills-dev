"""opentargets_clinvar — P5 ClinVar germline-pathogenic classifier (pure, dict-fixture tested).

Under test: pathogenicity gate + germline guardrail (somatic excluded) + review-status tiering."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.opentargets_clinvar.read")


def _row(sigs, origins, confidence="criteria provided, single submitter", disease="D"):
    return {
        "clinicalSignificances": sigs,
        "alleleOrigins": origins,
        "confidence": confidence,
        "diseaseFromSource": disease,
        "variantRsId": "rs1",
        "variantFunctionalConsequenceId": None,
    }


def test_germline_pathogenic_fires():
    out = r.classify_clinvar([_row(["pathogenic"], ["germline"], disease="Li-Fraumeni")])
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic"
    assert out["n_pathogenic_germline_confident"] == 1
    assert out["top_disease"] == "Li-Fraumeni"


def test_somatic_pathogenic_is_guardrailed_out():
    # a SOMATIC pathogenic ClinVar entry is a cancer-driver signal, NOT germline safety
    out = r.classify_clinvar([_row(["pathogenic"], ["somatic"])])
    assert out["clinvar_pathogenic_class"] == "somatic_only"
    assert out["n_pathogenic_somatic"] == 1
    assert out["n_pathogenic_germline"] == 0


def test_uncertain_and_benign_do_not_fire():
    out = r.classify_clinvar(
        [
            _row(["uncertain significance"], ["germline"]),
            _row(["likely benign"], ["germline"]),
            _row(["benign"], ["germline"]),
        ]
    )
    assert out["clinvar_pathogenic_class"] == "no_pathogenic_signal"


def test_weak_review_only_is_low_review_tier():
    out = r.classify_clinvar([_row(["pathogenic"], ["germline"], confidence="no assertion criteria provided")])
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic_low_review"


def test_conflicting_review_is_weak():
    out = r.classify_clinvar([_row(["pathogenic"], ["germline"], confidence="conflicting classifications")])
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic_low_review"


def test_confident_wins_over_weak():
    out = r.classify_clinvar(
        [
            _row(["pathogenic"], ["germline"], confidence="no assertion criteria provided"),
            _row(["likely_pathogenic"], ["inherited"], confidence="reviewed by expert panel"),
        ]
    )
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic"
    assert out["n_pathogenic_germline_confident"] == 1
    assert out["n_pathogenic_germline"] == 2


def test_pathogenic_unknown_origin_counts_as_weak_germline():
    out = r.classify_clinvar([_row(["pathogenic"], None)])
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic_low_review"


def test_empty_is_no_clinvar_entry():
    assert r.classify_clinvar([])["clinvar_pathogenic_class"] == "no_clinvar_entry"


def test_scalar_fields_normalize():
    out = r.classify_clinvar([_row("pathogenic", "germline")])
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic"


def test_unresolvable_symbol_is_insufficient(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: None)
    assert r.read_clinvar_pathogenic("NOTAGENE")["clinvar_pathogenic_class"] == "insufficient"


def test_end_to_end(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: "ENSG_TP53")
    df = pd.DataFrame([_row(["pathogenic"], ["germline"], disease="Li-Fraumeni")])
    df["targetId"] = "ENSG_TP53"
    monkeypatch.setattr(r, "read_entity", lambda entity, columns=None, **_kw: df)
    out = r.read_clinvar_pathogenic("TP53")
    assert out["clinvar_pathogenic_class"] == "germline_pathogenic"
    assert out["ensembl_gene_id"] == "ENSG_TP53"
