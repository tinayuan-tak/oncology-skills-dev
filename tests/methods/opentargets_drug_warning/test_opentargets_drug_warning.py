"""opentargets_drug_warning — pharmacovigilance safety-context classifier (pure, dict-fixture tested).

Strongest-wins precedence (withdrawn > black_box > other > no_warning) + the coverage-gap /
no-targeted-drug path. VERDICT-INERT; these guards pin the class taxonomy, not a verdict."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.opentargets_drug_warning.read")


def _w(wtype, chembls=("CHEMBL1",), tox=None):
    return {"warningType": wtype, "chemblIds": list(chembls), "toxicityClass": tox}


def test_no_targeted_drug_is_coverage_gap():
    out = r.classify_drug_warning([], n_targeted_drugs=0)
    assert out["drug_warning_class"] == "no_targeted_drug"
    assert out["has_black_box"] is False and out["has_withdrawn"] is False
    assert out["n_targeted_drugs"] == 0  # declared summary_field must be present on this branch


def test_nan_toxicity_class_does_not_leak_nan_token():
    # regression: a NaN toxicityClass (float) is truthy, so a bare truthy check let str(NaN)=="nan"
    # leak into toxicity_classes. Real string labels only.
    nan = float("nan")
    out = r.classify_drug_warning(
        [_w("Black Box Warning", tox="hepatotoxicity"), _w("Black Box Warning", tox=nan)], n_targeted_drugs=2
    )
    assert out["toxicity_classes"] == ["hepatotoxicity"]
    assert "nan" not in out["toxicity_classes"]


def test_engaging_drug_no_warning_is_measured_negative():
    out = r.classify_drug_warning([], n_targeted_drugs=3)
    assert out["drug_warning_class"] == "no_warning"


def test_black_box_detected():
    out = r.classify_drug_warning([_w("Black Box Warning", tox="hepatotoxicity")], n_targeted_drugs=2)
    assert out["drug_warning_class"] == "black_box_warned"
    assert out["has_black_box"] is True
    assert out["toxicity_classes"] == ["hepatotoxicity"]


def test_withdrawn_wins_over_black_box():
    out = r.classify_drug_warning(
        [_w("Black Box Warning", ("CHEMBL1",)), _w("Withdrawn", ("CHEMBL2",))], n_targeted_drugs=2
    )
    assert out["drug_warning_class"] == "withdrawn_drug"
    assert out["has_withdrawn"] is True and out["has_black_box"] is True
    assert out["n_targeted_warned_drugs"] == 2


def test_other_warning_when_neither_flag():
    out = r.classify_drug_warning([_w("Some Other Warning")], n_targeted_drugs=1)
    assert out["drug_warning_class"] == "other_warning"


def test_unresolvable_target_is_insufficient(monkeypatch):
    monkeypatch.setattr(r, "symbol_to_ensembl", lambda t: None)
    out = r.read_drug_warning("NOTAGENE")
    assert out["drug_warning_class"] == "insufficient"
    assert out["evidence_tier"] == "inferred"
