"""opentargets_clingen — P5 Slice 3 dosage-sensitivity classifier (pure, dict-fixture tested)."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.opentargets_clingen.read")


def _row(confidence, ar, disease="D"):
    return {"confidence": confidence, "allelicRequirements": ar, "diseaseFromSource": disease,
            "score": 1.0}


def test_any_high_confidence_AD_is_dominant_loss():
    # the BRCA1/MLH1 case: mixed AD+AR, AD present -> dominant_loss (haploinsufficiency safety)
    out = r.classify_dosage([_row("Definitive", ["AR"], "Fanconi"),
                             _row("Definitive", ["AD"], "Cancer predisp"),
                             _row("Definitive", ["AR"], "Fanconi")])
    assert out["dosage_sensitivity_class"] == "autosomal_dominant_loss"
    assert out["n_autosomal_dominant"] == 1 and out["n_autosomal_recessive"] == 2
    assert out["top_disease"] == "Cancer predisp"


def test_only_recessive_is_dosage_sufficient():
    out = r.classify_dosage([_row("Definitive", ["AR"]), _row("Strong", ["AR"])])
    assert out["dosage_sensitivity_class"] == "dosage_sufficient"


def test_disputed_AD_does_not_fire():
    # a Disputed dominant claim must NOT trigger the dominant-loss safety concern
    out = r.classify_dosage([_row("Disputed", ["AD"]), _row("Refuted", ["AD"])])
    assert out["dosage_sensitivity_class"] == "unresolved"   # rows exist, none high-confidence
    assert out["n_high_confidence"] == 0


def test_strong_confidence_counts():
    out = r.classify_dosage([_row("Strong", ["AD"])])
    assert out["dosage_sensitivity_class"] == "autosomal_dominant_loss"


def test_only_xlinked_is_unresolved():
    out = r.classify_dosage([_row("Definitive", ["XL"])])
    assert out["dosage_sensitivity_class"] == "unresolved"
    assert out["n_autosomal_dominant"] == 0 and out["n_autosomal_recessive"] == 0


def test_empty_is_no_clingen_entry():
    out = r.classify_dosage([])
    assert out["dosage_sensitivity_class"] == "no_clingen_entry"


def test_scalar_allelic_requirement_normalizes():
    # allelicRequirements may arrive as a scalar rather than a list
    out = r.classify_dosage([_row("Definitive", "AD")])
    assert out["dosage_sensitivity_class"] == "autosomal_dominant_loss"


def test_unresolvable_symbol_is_insufficient(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: None)
    assert r.read_clingen_dosage("NOTAGENE")["dosage_sensitivity_class"] == "insufficient"


def test_end_to_end_via_monkeypatch(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: "ENSG_TP53")
    df = pd.DataFrame([_row("Definitive", ["AD"], "Li-Fraumeni")])
    df["targetId"] = "ENSG_TP53"
    monkeypatch.setattr(r, "read_entity", lambda entity, columns=None: df)
    out = r.read_clingen_dosage("TP53")
    assert out["dosage_sensitivity_class"] == "autosomal_dominant_loss"
    assert out["ensembl_gene_id"] == "ENSG_TP53"
