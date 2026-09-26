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
        # axis must be a real retrieval axis so rl.retrieve_axis can resolve its query terms
        import retrieval_lanes as rl

        assert c["axis"] in rl.AXIS_PUBMED_TERMS, c["axis"]


def test_critical_signal_present_regex_over_dicts_and_objs():
    abs_dicts = [{"title": "Ocular keratopathy observed", "abstract": ""}, {"title": "unrelated", "abstract": ""}]
    assert ev.critical_signal_present(abs_dicts, "ocular|keratopath") is True
    assert ev.critical_signal_present(abs_dicts, "cardiotoxicity") is False
    assert ev.critical_signal_present([], "ocular") is False
    assert ev.critical_signal_present(abs_dicts, "") is False


def test_on_axis_precision_removed():
    # #1618: on_axis_precision was circular with the Stage-2 gate → removed as an eval metric.
    assert not hasattr(ev, "on_axis_precision")


def test_score_case_fields():
    case = {"target": "FOLR1", "indication": "ovarian cancer", "axis": "safety", "critical_signal": "ocular"}
    kept = [{"title": "ocular toxicity", "abstract": ""}]
    row = ev.score_case(case, kept, dropped=[{"pmid": "9"}])
    assert row["critical_signal_recall"] is True
    assert "on_axis_precision" not in row  # #1618: circular metric removed
    assert row["n_kept"] == 1 and row["n_dropped"] == 1
    assert row["target"] == "FOLR1" and row["axis"] == "safety"


# ---- gate_retrieval: the #1618 pass/fail teeth ----
def _row(target, axis, recall):
    return {"target": target, "axis": axis, "critical_signal_recall": recall, "n_kept": 1, "n_dropped": 0}


def test_gate_passes_when_all_recall():
    g = ev.gate_retrieval([_row("A", "safety", True), _row("B", "safety", True)], min_recall=1.0)
    assert g["passed"] is True and g["recall"] == 1.0 and g["n_hit"] == 2 and g["n_total"] == 2


def test_gate_fails_on_a_recall_miss():
    # TEETH: a single critical-signal miss reds the gate at min_recall=1.0.
    g = ev.gate_retrieval([_row("A", "safety", True), _row("B", "safety", False)], min_recall=1.0)
    assert g["passed"] is False and g["recall"] == 0.5
    assert any("recall MISS" in f for f in g["failures"])


def test_gate_counts_errors_as_failures_not_shrinking_denominator():
    # TEETH: an errored case must FAIL (denominator = ALL rows), not vanish from the denominator.
    rows = [_row("A", "safety", True), {"target": "B", "axis": "safety", "error": "network down"}]
    g = ev.gate_retrieval(rows, min_recall=1.0)
    assert g["n_total"] == 2 and g["n_error"] == 1 and g["recall"] == 0.5 and g["passed"] is False
    assert any("ERROR" in f for f in g["failures"])


def test_gate_fails_vacuous_empty_rows():
    # NON-VACUITY: an eval that scored nothing must not pass.
    g = ev.gate_retrieval([], min_recall=1.0)
    assert g["passed"] is False and g["n_total"] == 0


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


# ---- end-to-end teeth over the REAL committed gold file (hermetic, injected retrieve) ----
def _abstract_for(case):
    """A kept abstract whose text matches this real gold case's critical_signal regex (on-topic)."""
    exemplar = {"safety": {"FOLR1": "ocular keratopathy", "ERBB2": "cardiac LVEF decline"}}
    # derive a matching phrase from the regex's first literal alternative
    import re

    first = re.split(r"[|(]", case["critical_signal"])[0].strip()
    text = exemplar.get(case["axis"], {}).get(case["target"], first or "resistance reactivation bypass")
    return {"title": text, "abstract": ""}


def test_real_gold_file_gate_passes_when_signal_surfaced_and_fails_when_not():
    import json

    gold = json.loads(_GOLD.read_text())
    assert gold, "gold file must be non-empty (non-vacuity)"

    # GOOD: every case surfaces an on-topic abstract → recall 1.0 → gate PASSES.
    good_rows = ev.evaluate(
        gold, retrieve=lambda t, i, a, **k: {"kept": [_abstract_for(_case(gold, t, a))], "dropped": []}
    )
    g_good = ev.gate_retrieval(good_rows, min_recall=1.0)
    assert g_good["passed"] is True and g_good["n_total"] == len(gold) and g_good["n_hit"] == len(gold)

    # DEGRADED: retrieval returns only off-topic noise → recall 0 → gate FAILS (teeth).
    bad_rows = ev.evaluate(
        gold,
        retrieve=lambda t, i, a, **k: {"kept": [{"title": "unrelated methods paper", "abstract": ""}], "dropped": []},
    )
    g_bad = ev.gate_retrieval(bad_rows, min_recall=1.0)
    assert g_bad["passed"] is False and g_bad["n_hit"] == 0

    # OUTAGE: every case errors → gate FAILS (denominator NOT shrunk to 0/0).
    def _boom(t, i, a, **k):
        raise RuntimeError("network down")

    err_rows = ev.evaluate(gold, retrieve=_boom)
    g_err = ev.gate_retrieval(err_rows, min_recall=1.0)
    assert g_err["passed"] is False and g_err["n_error"] == len(gold) and g_err["recall"] == 0.0


def _case(gold, target, axis):
    for c in gold:
        if c["target"] == target and c["axis"] == axis:
            return c
    raise KeyError((target, axis))
