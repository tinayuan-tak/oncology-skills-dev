"""Hermetic (no Bedrock, no network) tests for build_discordance_ledger.

Runs via: pixi run pytest eval/tests/test_discordance_ledger.py -q   (from the home checkout).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import build_discordance_ledger as bdl  # noqa: E402


def _record(**over):
    rec = {
        "target": "KRAS",
        "indication": "COADREAD",
        "skill": "functional-requirement",
        "sub_verdict": {
            "gate": "dependency",
            "verdict": "lineage_selective",
            "driving_rule_id": "lineage-selective-supportive",
            "fired_rule_ids": [],
        },
        "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high"}},
        "literature_synthesis": {
            "overall_consistency": "partially_concordant",
            "key_divergence": "literature reports pan-essentiality the panel calls selective",
            "axes": [],
            "blind_spots": [],
            "_model_id": "us.anthropic.claude-opus-4-8",
            "_prompt_hash": "abc123",
        },
    }
    rec.update(over)
    return rec


def _axis(agreement, verified=True, read="supports"):
    return {
        "axis_key": "A",
        "literature_read": read,
        "assertion": "X drives Y.",
        "agreement_vs_omics": agreement,
        "confidence": "moderate",
        "citations": [{"label": "Smith 2020", "pmid": "111", "verified": verified}],
    }


def test_verified_contradicts_is_verdict_rule_gap():
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("contradicts", verified=True)]
    rows = bdl.build_rows(rec)
    assert len(rows) == 1
    assert rows[0]["gap_class"] == bdl.GAP_VERDICT_RULE
    assert rows[0]["confabulation_risk"] is False


def test_unverified_contradicts_is_confabulation():
    """Containment guard: contradicts with no VERIFIED citation must NOT be a real-gap candidate."""
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("contradicts", verified=False)]
    rows = bdl.build_rows(rec)
    assert len(rows) == 1
    assert rows[0]["gap_class"] == bdl.GAP_CONFABULATION
    assert rows[0]["confabulation_risk"] is True


def test_calibration_target_escalates_verified_contradicts():
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("contradicts", verified=True)]
    rows = bdl.build_rows(rec, calibration_targets={"KRAS"})
    assert rows[0]["gap_class"] == bdl.GAP_CALIBRATION
    assert rows[0]["severity"] > bdl._SEVERITY[bdl.GAP_VERDICT_RULE]


def test_omics_blind_is_blind_spot():
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("omics_blind")]
    rows = bdl.build_rows(rec)
    assert rows[0]["gap_class"] == bdl.GAP_BLIND_SPOT


def test_atlas_excluded_skill_routes_to_staleness():
    rec = _record(skill="translational-readiness")
    rec["literature_synthesis"]["axes"] = [_axis("omics_blind")]
    rows = bdl.build_rows(rec)
    assert rows[0]["gap_class"] == bdl.GAP_STALENESS


def test_blind_spots_list_projected():
    rec = _record()
    rec["literature_synthesis"]["blind_spots"] = [
        {
            "signal": "invasive-front antigen loss",
            "why_omics_blind": "bulk cannot resolve",
            "citations": [{"label": "Jones 2019", "verified": True}],
        }
    ]
    rows = bdl.build_rows(rec)
    assert any(r["gap_class"] == bdl.GAP_BLIND_SPOT and r["axis_key"] == "blind_spot" for r in rows)


def test_concordant_axes_yield_no_rows():
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("agree"), _axis("extends")]
    assert bdl.build_rows(rec) == []


def test_skipped_or_errored_lane_yields_no_rows():
    assert bdl.build_rows(_record(literature_synthesis={"_literature_skipped": "x"})) == []
    assert bdl.build_rows(_record(literature_synthesis={"_literature_error": "x"})) == []


def test_covered_scope_includes_concordant_pairs_and_excludes_failed_lanes():
    """`covered` is the RUN'S SCOPE — what a diff may call resolved. A concordant pair emitted no
    row but WAS examined (so it belongs); a skipped/errored lane examined nothing (so it does not).
    Getting the second half wrong would let a lane FAILURE read as a fix."""
    concordant = _record(target="CLEAN")
    concordant["literature_synthesis"]["axes"] = [_axis("agree")]
    with_gap = _record(target="GAPPY")
    with_gap["literature_synthesis"]["axes"] = [_axis("contradicts")]
    records = [
        concordant,
        with_gap,
        _record(target="SKIPPED", literature_synthesis={"_literature_skipped": "x"}),
        _record(target="ERRORED", literature_synthesis={"_literature_error": "x"}),
    ]
    covered = bdl.covered_scope(records)
    assert covered == [
        ["functional-requirement", "CLEAN", "COADREAD"],
        ["functional-requirement", "GAPPY", "COADREAD"],
    ]


def test_covered_scope_predicate_is_shared_with_build_rows():
    """One predicate, so the two cannot drift: anything build_rows refuses to project rows for must
    also be absent from `covered`."""
    for bad in ({"_literature_skipped": "x"}, {"_literature_error": "x"}, None, "not-a-dict"):
        rec = _record(literature_synthesis=bad)
        assert bdl.lane_produced_a_comparison(rec) is False
        assert bdl.build_rows(rec) == []
        assert bdl.covered_scope([rec]) == []


def test_build_ledger_records_its_covered_scope(tmp_path):
    corpus = [_record(target="A"), _record(target="B", literature_synthesis={"_literature_skipped": "x"})]
    corpus[0]["literature_synthesis"]["axes"] = [_axis("contradicts")]
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(corpus))
    ledger = bdl.build_ledger(p)
    assert ledger["n_records"] == 2  # both records were loaded...
    assert ledger["n_covered"] == 1  # ...but only one was actually compared
    assert ledger["covered"] == [["functional-requirement", "A", "COADREAD"]]
    assert ledger["schema"] == "discordance_ledger/v2.1"


def test_input_record_is_never_mutated():
    """The aggregator is pure: it must not touch the verdict, cards, or any input field."""
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("contradicts")]
    before = copy.deepcopy(rec)
    bdl.build_rows(rec, calibration_targets={"KRAS"})
    assert rec == before


def test_build_ledger_ranks_and_summarizes(tmp_path):
    corpus = [
        _record(skill="functional-requirement"),
        _record(skill="on-target-safety-liability"),
    ]
    corpus[0]["literature_synthesis"]["axes"] = [_axis("contradicts", verified=True)]
    corpus[1]["literature_synthesis"]["axes"] = [_axis("omics_blind")]
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps(corpus))
    ledger = bdl.build_ledger(p, calibration_targets={"KRAS"})
    assert ledger["n_records"] == 2
    assert ledger["n_rows"] == 2
    # calibration_gap (sev 5) ranks above blind_spot (sev 3)
    assert ledger["rows"][0]["gap_class"] == bdl.GAP_CALIBRATION
    assert ledger["summary"]["by_gap_class"][bdl.GAP_CALIBRATION] == 1
    assert set(ledger["summary"]["by_skill"]) == {"functional-requirement", "on-target-safety-liability"}
    assert ledger["corpus_fingerprint"]  # deterministic content hash present


def test_load_calibration_targets_dict_keyed(tmp_path):
    """Ground-truth sections are DICTS keyed by target symbol (incl. known_gap_watchlist)."""
    cal = tmp_path / "cal.yaml"
    cal.write_text(
        "reference_profiles:\n  PARP1:\n    indication: OV\n  DLL3:\n    indication: SCLC\n"
        "known_gap_watchlist:\n  MET:\n    indication: LUAD\n  SMARCA2:\n    indication: LUAD\n"
        "positive_controls:\n  KRAS:\n    indication: COADREAD\n"
    )
    got = bdl._load_calibration_targets(cal)
    assert {"PARP1", "DLL3", "MET", "SMARCA2", "KRAS"} <= got


# ── claim-vector-axis alignment (v2) ────────────────────────────────────────────────────────────
def _rec_with_claim(axis_signal):
    """A contradicts row on axis 'A' with a claim_vector whose atom A has the given signal."""
    rec = _record()
    rec["claim_vector"] = {"A": {"signal": axis_signal, "corroboration": "high"}}
    rec["literature_synthesis"]["axes"] = [_axis("contradicts", verified=True)]  # axis_key='A'
    return rec


def test_measured_claim_axis_contradicts_is_verdict_rule_gap():
    rows = bdl.build_rows(_rec_with_claim("strong"))
    assert rows[0]["gap_class"] == bdl.GAP_VERDICT_RULE
    assert rows[0]["claim_signal"] == "strong" and rows[0]["claim_measured"] is True


def test_absent_is_still_measured_contradiction():
    # a measured floor 'absent' still counts as MEASURED (omics measured no-signal; lit says there is one)
    rows = bdl.build_rows(_rec_with_claim("absent"))
    assert rows[0]["gap_class"] == bdl.GAP_VERDICT_RULE and rows[0]["claim_measured"] is True


def test_unmeasured_claim_axis_downgrades_contradicts_to_blind_spot():
    # positively UNMEASURED claim axis → literature cannot contradict an absent signal → blind_spot
    rows = bdl.build_rows(_rec_with_claim("unmeasured"))
    assert rows[0]["gap_class"] == bdl.GAP_BLIND_SPOT and rows[0]["claim_measured"] is False


def test_no_claim_vector_preserves_prior_behavior():
    # record without a claim_vector → cannot check → trust the lane (contradicts stays verdict_rule)
    rec = _record()
    rec["literature_synthesis"]["axes"] = [_axis("contradicts", verified=True)]
    rows = bdl.build_rows(rec)  # no claim_vector key
    assert rows[0]["gap_class"] == bdl.GAP_VERDICT_RULE and rows[0]["claim_measured"] is None


def test_nested_claim_vector_shape_is_unwrapped():
    rec = _record()
    rec["claim_vector"] = {"claim_vector": {"A": {"signal": "unmeasured"}}}
    rec["literature_synthesis"]["axes"] = [_axis("contradicts", verified=True)]
    rows = bdl.build_rows(rec)
    assert rows[0]["claim_measured"] is False and rows[0]["gap_class"] == bdl.GAP_BLIND_SPOT


# ── concordant-over-flag cross-check (guard-tightening) ──────────────────────────────────────────
def test_overall_concordant_demotes_axis_contradicts():
    """A lane whose OWN overall_consistency=='concordant' but with a lone axis 'contradicts' is an
    internal over-flag → demote out of the sharp/actionable set (the dominant dismissed_concordant noise)."""
    rec = _rec_with_claim("strong")  # a MEASURED axis (would be a verdict_rule gap)
    rec["literature_synthesis"]["overall_consistency"] = "concordant"
    rows = bdl.build_rows(rec, calibration_targets={"KRAS"})
    assert rows[0]["gap_class"] == bdl.GAP_CONCORDANT_OVERFLAG
    assert rows[0]["severity"] == 1  # discard tier
    assert rows[0]["overall_consistency"] == "concordant"


def test_partially_concordant_does_not_demote():
    """The demotion keys ONLY off the lane's own 'concordant' summary — a partially_concordant lane
    (where the axis contradiction is plausibly the real divergence) is untouched (MET/COMUT, PARP1/COND)."""
    rec = _rec_with_claim("strong")
    rec["literature_synthesis"]["overall_consistency"] = "partially_concordant"
    rows = bdl.build_rows(rec, calibration_targets={"KRAS"})
    assert rows[0]["gap_class"] == bdl.GAP_CALIBRATION  # unchanged from prior behavior


def test_concordant_summary_does_not_hijack_unmeasured_coverage_gap():
    """Placement guard: a positively-UNMEASURED axis must still route to blind_spot even under a
    'concordant' lane summary — a coverage gap is not a concordant over-flag."""
    rec = _rec_with_claim("unmeasured")
    rec["literature_synthesis"]["overall_consistency"] = "concordant"
    rows = bdl.build_rows(rec)
    assert rows[0]["gap_class"] == bdl.GAP_BLIND_SPOT


def test_concordant_over_flag_is_non_actionable_and_non_sharp(tmp_path):
    """The demoted class is excluded from the actionable set and from the diff-monitor SHARP keys."""
    import diff_discordance_ledger as ddl

    rec = _rec_with_claim("strong")
    rec["literature_synthesis"]["overall_consistency"] = "concordant"
    p = tmp_path / "corpus.json"
    p.write_text(json.dumps([rec]))
    ledger = bdl.build_ledger(p, calibration_targets={"KRAS"})
    assert ledger["n_actionable"] == 0
    assert ddl.sharp_keys(ledger) == set()
