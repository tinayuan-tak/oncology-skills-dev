"""immune-context skill — verdict resolution from fired immune-context rules (no S3).

Pins the class-rule → effector-verdict mapping + the honest insufficient when no rule fires.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

ic = load_run_py(Path(__file__).resolve().parent.parent, "ic_run")


def _v(rule_id):
    return ic._verdict([{"rule_id": rule_id}])


def test_hot_rule_resolves_immune_hot():
    assert _v("immune-context-hot-tce-supportive") == ("immune_hot", "immune-context-hot-tce-supportive")


def test_intermediate_rule_resolves_intermediate():
    assert _v("immune-context-intermediate-tce-neutral")[0] == "immune_intermediate"


def test_cold_rule_resolves_cold():
    assert _v("immune-context-cold-tce-opposing")[0] == "immune_cold"


def test_no_immune_rule_fired_is_insufficient():
    # data_unavailable fires no immune-context rule → honest insufficient (never a false 'cold')
    assert ic._verdict([]) == ("insufficient", None)
    # an unrelated surface rule firing must not be mistaken for an immune verdict
    assert ic._verdict([{"rule_id": "single-pass-type1-adc-supportive"}]) == ("insufficient", None)


def test_cards_list_includes_immune_context_and_tme_display_cards():
    # immune-context (the verdict-bearing CD8 effector card) + the 3 VERDICT-INERT TME/immune display
    # cards wired 2026-08-25. The verdict is a direct read of immune_context_class (see _verdict), so
    # the display cards fire no rule and leave the effector-context verdict byte-stable.
    assert ic.CARDS[0] == "immune-context"
    assert set(ic.CARDS) == {
        "immune-context",
        "myeloid-compartment-expression-cheng",
        "caf-compartment-expression-luo",
        "ici-response-association",
        "tcga-til-fraction-saltz",  # 2026-08-28 — absolute H&E-DL TIL corroborator (verdict-inert)
        "ici-response-imvigor210",  # 2026-08-28 — urothelial ICI-response + immune phenotype (verdict-inert)
        "spatial-tumor-normal-colocalization",  # 2026-09-10 T0-4 — spatial inflamed/excluded phenotype (verdict-inert)
    }
