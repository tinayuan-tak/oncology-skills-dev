"""eval_retrieval: pure-metric + wiring tests (no network) for the retrieval eval harness."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import eval_retrieval as ev  # noqa: E402

_GOLD = Path(__file__).resolve().parent.parent / "validation" / "retrieval_gold_v0.json"


def test_gold_seed_is_wellformed():
    import json

    gold = json.loads(_GOLD.read_text())
    assert isinstance(gold, list) and gold
    for c in gold:
        assert {"target", "indication", "axis", "critical_signal"} <= set(c)
        # axis must be a real retrieval axis so on_axis_precision resolves its terms
        import retrieval_lanes as rl

        assert c["axis"] in rl.AXIS_PUBMED_TERMS, c["axis"]


def test_critical_signal_present_regex_over_dicts_and_objs():
    abs_dicts = [{"title": "Ocular keratopathy observed", "abstract": ""}, {"title": "unrelated", "abstract": ""}]
    assert ev.critical_signal_present(abs_dicts, "ocular|keratopath") is True
    assert ev.critical_signal_present(abs_dicts, "cardiotoxicity") is False
    assert ev.critical_signal_present([], "ocular") is False
    assert ev.critical_signal_present(abs_dicts, "") is False


def test_on_axis_precision_fraction_and_none_on_empty():
    # safety axis: "toxicity"/"adverse event"/... ; 1 of 2 abstracts on-axis
    abs_ = [{"title": "hepatic toxicity", "abstract": ""}, {"title": "unrelated method", "abstract": ""}]
    assert ev.on_axis_precision(abs_, "safety") == 0.5
    assert ev.on_axis_precision([], "safety") is None  # 0/0 → N/A, never 0.0


def test_score_case_fields():
    case = {"target": "FOLR1", "indication": "ovarian cancer", "axis": "safety", "critical_signal": "ocular"}
    kept = [{"title": "ocular toxicity", "abstract": ""}]
    row = ev.score_case(case, kept, dropped=[{"pmid": "9"}])
    assert row["critical_signal_recall"] is True
    assert row["on_axis_precision"] == 1.0  # "toxicity" is on the safety axis
    assert row["n_kept"] == 1 and row["n_dropped"] == 1
    assert row["target"] == "FOLR1" and row["axis"] == "safety"


def test_evaluate_with_injected_retrieve_offline():
    gold = [
        {"target": "FOLR1", "indication": "ovarian cancer", "axis": "safety", "critical_signal": "ocular"},
        {"target": "X", "indication": "y", "axis": "safety", "critical_signal": "zzz"},
    ]

    def fake_retrieve(target, indication, axis, **k):
        if target == "FOLR1":
            return {"kept": [{"title": "ocular toxicity", "abstract": ""}], "dropped": []}
        raise RuntimeError("network down")

    rows = ev.evaluate(gold, retrieve=fake_retrieve)
    assert rows[0]["critical_signal_recall"] is True
    assert "error" in rows[1]  # a per-case failure is captured, not fatal
