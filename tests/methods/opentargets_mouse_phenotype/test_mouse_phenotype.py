"""opentargets_mouse_phenotype — P5 Slice 4 KO-phenotype classifier (pure, dict-fixture tested).

The developmental-vs-adult guardrail is the property under test: adult/postnatal lethality ->
lethal_ko; embryonic/preweaning -> developmental_only (NEVER the adult killer)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.opentargets_mouse_phenotype.read")


def _row(label, classes=None):
    return {"modelPhenotypeLabel": label, "modelPhenotypeClasses": [{"id": "x", "label": c} for c in (classes or [])]}


def test_adult_lethal_is_lethal_ko():
    out = r.classify_ko_phenotype([_row("postnatal lethality, complete penetrance")])
    assert out["ko_phenotype_class"] == "lethal_ko"
    assert out["n_adult_lethal"] == 1


def test_embryonic_lethal_is_developmental_only():
    # the KRAS/MYC/BRCA1 case — embryonic lethal must NOT fire the adult killer
    out = r.classify_ko_phenotype([_row("embryonic lethality during organogenesis, complete penetrance")])
    assert out["ko_phenotype_class"] == "developmental_only"
    assert out["n_developmental_lethal"] == 1


def test_preweaning_is_developmental_only():
    out = r.classify_ko_phenotype([_row("preweaning lethality, complete penetrance")])
    assert out["ko_phenotype_class"] == "developmental_only"


def test_adult_wins_over_developmental():
    # TP53 case: both stages present -> adult escalates to lethal_ko
    out = r.classify_ko_phenotype(
        [_row("embryonic lethality, complete penetrance"), _row("postnatal lethality, incomplete penetrance")]
    )
    assert out["ko_phenotype_class"] == "lethal_ko"
    assert set(out["lethal_stages"]) >= {"adult", "developmental"}


def test_severe_organ_phenotype_when_no_lethal():
    out = r.classify_ko_phenotype([_row("some finding", classes=["cardiovascular system phenotype"])])
    assert out["ko_phenotype_class"] == "severe_organ_phenotype"
    assert "cardiovascular system phenotype" in out["organ_classes"]


def test_mild_phenotype_when_rows_but_nothing_severe():
    out = r.classify_ko_phenotype([_row("abnormal coat color", classes=["pigmentation phenotype"])])
    assert out["ko_phenotype_class"] == "mild_phenotype"


def test_no_rows_is_no_phenotype():
    assert r.classify_ko_phenotype([])["ko_phenotype_class"] == "no_phenotype"


def test_unstaged_lethal_is_developmental_only_not_adult():
    # bare "lethality" with no stage -> conservatively NOT an adult killer
    out = r.classify_ko_phenotype([_row("lethality, complete penetrance")])
    assert out["ko_phenotype_class"] == "developmental_only"


def test_inferred_evidence_tier_surfaced(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: "ENSG_X")
    df = pd.DataFrame([_row("postnatal lethality")])
    df["targetFromSourceId"] = "ENSG_X"
    monkeypatch.setattr(r, "read_entity", lambda entity, columns=None, **_kw: df)
    out = r.read_mouse_ko_phenotype("X")
    assert out["evidence_tier"] == "inferred"  # mouse is a MODEL, never a measured killer
    assert out["ko_phenotype_class"] == "lethal_ko"


def test_unresolvable_symbol_is_insufficient(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: None)
    assert r.read_mouse_ko_phenotype("NOTAGENE")["ko_phenotype_class"] == "insufficient"
