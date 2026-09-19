"""Stage 5 — CROSS-LAYER SUBTYPE CONCORDANCE. `_subtype_layer_concordance` joins the three by-subtype
arms (tumor RNA / cell-line RNA / tumor protein) on stratum name and reports, per stratum, whether the
MEASURED arms agree, disagree, or only one arm measured it. Verdict-INERT (never-lift): it may flag a
directional discordance and raise/flag confidence only — it must NEVER move presence_verdict.

The disagreement test is the one that matters: it is written so the guard CAN fail (a synthetic stratum
where the arms genuinely disagree), because an all-`agree`/all-`single_arm` corpus is the vacuity
signature the plan calls out. The anti-vacuity test pins the facet non-empty for the COADREAD fixture.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
tp = load_run_py(SKILL_DIR, "tp_run_concordance")
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread.yaml"


def _arm(card_id: str, axis_quality: str, rows: list, stratum_key: str = "stratum_id") -> dict:
    """A by-subtype arm card. The RNA arm keys its stratum as `stratum_id`, the cell-line/protein arms
    as `stratum` — the helper must tolerate both, so let the caller pick which key to emit."""
    return {
        "card_id": card_id,
        "summary": {
            "subtype_axis_quality": axis_quality,
            "per_subgroup_metrics": [{stratum_key: sid, "subtype_signal": sig} for sid, sig in rows],
        },
    }


def test_detects_disagreement():
    """CAN-FAIL: a stratum where two measured arms carry DIFFERENT subtype_signal must read `disagree`
    and flip the whole facet to `discordant`. If the join or the set-comparison broke, this reds."""
    cards = [
        _arm(
            "tumor-rna-distribution-by-subtype", "powered", [("MSI_H", "subtype_enriched"), ("MSS", "subtype_uniform")]
        ),
        _arm(
            "cellline-rna-distribution-by-subtype",
            "exploratory",
            [("MSI_H", "subtype_uniform"), ("MSS", "subtype_uniform")],
            stratum_key="stratum",
        ),
        _arm(
            "tumor-protein-distribution-by-subtype", "exploratory", [("MSS", "subtype_uniform")], stratum_key="stratum"
        ),
    ]
    c = tp._subtype_layer_concordance(cards)
    assert c is not None
    assert c["by_stratum"]["MSI_H"]["status"] == "disagree"  # enriched (RNA) vs uniform (cell-line)
    assert c["by_stratum"]["MSS"]["status"] == "agree"  # all three uniform
    assert c["n_disagree"] == 1 and c["n_agree"] == 1
    assert c["concordance_class"] == "discordant"  # any disagreement dominates


def test_underpowered_null_is_excluded_and_single_arm():
    """A null subtype_signal (underpowered / unevaluable stratum) is NOT a measurement: it is dropped,
    so a stratum only one arm measured reads `single_arm`, never a spurious agree/disagree."""
    cards = [
        _arm("tumor-rna-distribution-by-subtype", "powered", [("MSS", "subtype_uniform"), ("CMS1", "subtype_uniform")]),
        _arm(
            "cellline-rna-distribution-by-subtype",
            "exploratory",
            [("MSS", "subtype_uniform"), ("CMS1", None)],  # CMS1 underpowered → excluded
            stratum_key="stratum",
        ),
        _arm("tumor-protein-distribution-by-subtype", "exploratory", [], stratum_key="stratum"),
    ]
    c = tp._subtype_layer_concordance(cards)
    assert c["by_stratum"]["MSS"]["status"] == "agree"  # RNA + cell-line both measured, agree
    assert c["by_stratum"]["CMS1"]["status"] == "single_arm"  # cell-line CMS1 null → only RNA counts
    assert set(c["by_stratum"]["CMS1"]["signals"]) == {"rna_tumor"}
    assert c["n_single_arm"] == 1 and c["concordance_class"] == "concordant"


def test_only_single_arm_is_insufficient():
    """When no stratum is cross-checked (every measured stratum has exactly one arm), the class is
    `insufficient` — concordance was never actually tested, and must not read as `concordant`."""
    cards = [
        _arm("tumor-rna-distribution-by-subtype", "powered", [("MSS", "subtype_uniform")]),
        _arm("cellline-rna-distribution-by-subtype", "unevaluable", [], stratum_key="stratum"),
        _arm("tumor-protein-distribution-by-subtype", "unavailable", [], stratum_key="stratum"),
    ]
    c = tp._subtype_layer_concordance(cards)
    assert c["n_agree"] == 0 and c["n_disagree"] == 0 and c["n_single_arm"] == 1
    assert c["concordance_class"] == "insufficient"


def test_none_when_nothing_measured():
    """No arm has a single measured stratum → nothing to reconcile → None (not an empty dict that would
    read as a positive-but-empty facet)."""
    cards = [
        _arm("tumor-rna-distribution-by-subtype", "unevaluable", [("MSS", None)]),
        _arm("cellline-rna-distribution-by-subtype", "unavailable", [], stratum_key="stratum"),
    ]
    assert tp._subtype_layer_concordance(cards) is None


def test_never_lift_and_verdict_inert():
    """The facet carries the never-lift stamp and emits NO verdict spine key — it can never move
    presence_verdict."""
    cards = [
        _arm("tumor-rna-distribution-by-subtype", "powered", [("MSS", "subtype_uniform")]),
        _arm(
            "cellline-rna-distribution-by-subtype", "exploratory", [("MSS", "subtype_uniform")], stratum_key="stratum"
        ),
    ]
    c = tp._subtype_layer_concordance(cards)
    assert "presence_verdict" not in c and "driving_rule_id" not in c
    assert "verdict-INERT" in c["_never_lift"] and "never" in c["_never_lift"]
    assert c["arm_axis_quality"]["rna_tumor"] == "powered"


def test_tolerates_non_dict_rows():
    """Frozen/simplified fixtures can carry non-dict rows in per_subgroup_metrics — the helper must skip
    them, not crash (the drift that AttributeError'd the frozen replay before the guard)."""
    cards = [
        {
            "card_id": "tumor-rna-distribution-by-subtype",
            "summary": {
                "subtype_axis_quality": "powered",
                "per_subgroup_metrics": ["MSS", {"stratum_id": "MSI_H", "subtype_signal": "subtype_uniform"}],
            },
        }
    ]
    c = tp._subtype_layer_concordance(cards)
    assert c is not None and set(c["by_stratum"]) == {"MSI_H"}


def test_arm_subtype_layer_graceful_on_missing_card():
    """_arm_subtype_layer returns the axis grade + per-stratum signal roll-up, and degrades to a
    null-filled layer (never raises) when the arm card is absent from the resolved set."""
    cards = [
        _arm(
            "tumor-rna-distribution-by-subtype", "powered", [("MSS", "subtype_uniform"), ("MSI_H", "subtype_enriched")]
        ),
    ]
    layer = tp._arm_subtype_layer(cards, "tumor-rna-distribution-by-subtype")
    assert layer["subtype_axis_quality"] == "powered"
    assert layer["per_stratum_signal"] == {"MSS": "subtype_uniform", "MSI_H": "subtype_enriched"}
    missing = tp._arm_subtype_layer(cards, "tumor-protein-distribution-by-subtype")
    assert missing["subtype_axis_quality"] is None and missing["per_stratum_signal"] == {}


def test_concordance_nonempty_for_coadread_fixture():
    """ANTI-VACUITY (the plan's guard against an empty parametrize reading green): the concordance facet
    is NON-EMPTY for the frozen COADREAD fixture. Built from the real frozen reader summaries so a future
    refreeze that empties the by-subtype arms reds here rather than silently going vacuous."""
    if not FIXTURE.exists():
        import pytest

        pytest.skip("no frozen fixture")
    frozen = yaml.safe_load(FIXTURE.read_text()) or {}
    cards = [
        {"card_id": cid, "summary": frozen[cid]}
        for cid in (
            "tumor-rna-distribution-by-subtype",
            "cellline-rna-distribution-by-subtype",
            "tumor-protein-distribution-by-subtype",
        )
        if isinstance(frozen.get(cid), dict)
    ]
    c = tp._subtype_layer_concordance(cards)
    assert c is not None, "concordance facet is None for the COADREAD fixture — the join found no measured stratum"
    assert c["n_strata_joined"] >= 1, "concordance facet is empty for the COADREAD fixture (vacuous)"
