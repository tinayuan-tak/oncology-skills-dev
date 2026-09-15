"""The headline PHRASE must not assert a modality arm the resolver has EXCLUDED (2026-09-15).

THE DEFECT, measured over the whole n=504 corpus at ~/dev/target-archetype-corpus-20260915: 108 rows
(21.4%) rendered a FAVOURABLE phrase for a token whose own arm projection carries a foreclosed or
caveated arm —

    87  fit_class=both_viable    surface_modality_verdict=adc_preferred_tce_unsafe     "ADC & TCE viable"
    18  fit_class=TCE_preferred  surface_modality_verdict=tce_unsafe_normal_liability  "TCE-favorable"
     2  fit_class=both_viable    surface_modality_verdict=adc_preferred_tce_escape_risk "ADC & TCE viable"
     1  fit_class=both_viable    surface_modality_verdict=surface_viable_density_caveated "ADC & TCE viable"

The 18 are the sharpest: `tce_unsafe_normal_liability` projects to {adc: not_preferred, bite_tce: unsafe,
antibody: not_preferred} — NO viable arm at all — while the badge read "TCE-favorable".

ON THE POPULATION: the corpus was first partitioned at the mid-run #1379 fast-forward (`fb66acee`, reflog
2026-09-14T20:24:49Z, inside the 19:51:38Z–00:46:54Z package window), which gives 87 of 451 post-FF rows
(19.3%) and 21 of 53 pre-FF (39.6%). The partition was then checked and is IMMATERIAL to THIS
measurement: it reads `sub_verdicts.<axis>.verdict` (untouched by #1379) and `evidence_graph.verdict.id`,
which is a fit_class token on 504/504 rows in BOTH partitions — so the whole corpus is one population
here. Hence 108/504 above. Do NOT reconcile the two 87s: one is the largest CELL corpus-wide, the other
was the affected COUNT in the post-FF partition. Two unrelated eighty-sevens.

WHY _FIT_CLASS_PHRASE COULD NOT FIX IT: that map is keyed on `fit_class`, and fit_class is blind to the
downgrade (which lives in `surface_modality_verdict`). So the phrase is rebuilt from the ARM PROJECTION,
which is a pure projection of the resolved token and therefore cannot disagree with it.

SCOPE: display only. `verdict.call` stays the fit_class token (#1384's invariant),
`evidence_graph.verdict.id` with it, the gate keeps the resolver vocabulary, and `verdict.polarity` still
comes from `_fit_class_polarity` — so the badge COLOUR is unchanged and remains keyed on fit_class. That
residual is deliberate and filed separately; this file pins the phrase, and pins that the spine did not
move with it.

All pure (no S3, no live data).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _skills_common.evidence_graph import build_evidence_graph
from _skills_common.headline_hero import _ARM_LABEL, _truncate
from _skills_common.skill_report import build_skill_report
from _test_support import load_run_py

_M = load_run_py(Path(__file__).resolve().parent.parent, "smf_run_downgrade_phrase")

# The hero badge truncation budget (headline_hero.render_headline_hero_png passes 38; the svg passes 40).
# The phrase MAY exceed it — but the excluded arm must still be legible after truncation.
_HERO_TRUNCATE = 38

# Every token whose pinned arm projection carries a downgraded state. DERIVED, never hand-listed: a
# hand-listed copy here would reproduce the very defect this file was written for (_SURFACE_DOWNGRADE_REASON
# was hand-maintained and silently 2 rows short for three weeks).
_DOWNGRADE_TOKENS = sorted(
    tok for tok, arms in _M._VERDICT_ARMS.items() if any(s in _M._ARM_DOWNGRADED for s in arms.values())
)
_POSITIVE_FIT = sorted(_M._FIT_CLASS_POSITIVE)


def _headline(token: str, fit_class: str) -> dict:
    """A minimal headline for _build_headline_block — the same shape test_verdict_by_modality.py uses."""
    return {
        "surface_modality_verdict": token,
        "fit_class": fit_class,
        "driving_rule_id": "sc-normal-high-liability-bite-killer",
        "claim_vector": {
            k: {"signal": "strong", "corroboration": "high"} for k in ("FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED")
        },
        "key_signals": {},
    }


# ── the population is real ────────────────────────────────────────────────────────────────────────
def test_the_downgrade_population_is_not_empty_and_is_derived():
    """Anti-vacuity for the whole file: if this collapsed to 0 tokens every test below would pass for
    free. 9 of the 16 pinned tokens carry a downgraded arm (the 4 safety/escape pairs + density-caveat,
    annotation-only and shed-opposed)."""
    assert len(_DOWNGRADE_TOKENS) == 9, f"downgrade tokens moved: {_DOWNGRADE_TOKENS}"
    assert _POSITIVE_FIT == ["ADC_preferred", "TCE_preferred", "both_viable"]


# ── the phrase names the excluded arm ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("token", _DOWNGRADE_TOKENS)
@pytest.mark.parametrize("fit_class", _POSITIVE_FIT)
def test_phrase_names_every_downgraded_arm_with_its_state(token, fit_class):
    arms = _M._surface_verdict_by_modality(token)
    phrase = _M._downgraded_arm_phrase(fit_class, arms)
    assert phrase, f"{fit_class}/{token} left the phrase on the fit_class map"
    for arm, state in arms.items():
        if state in _M._ARM_DOWNGRADED:
            assert _ARM_LABEL[arm] in phrase, f"{phrase!r} does not name the downgraded {arm} arm"
            assert state.replace("_", " ") in phrase, f"{phrase!r} does not carry the {state!r} state"


@pytest.mark.parametrize("token", _DOWNGRADE_TOKENS)
@pytest.mark.parametrize("fit_class", _POSITIVE_FIT)
def test_phrase_differs_from_the_favourable_fit_class_phrase(token, fit_class):
    """The point of the change. A builder that returned the fit_class phrase unchanged would satisfy
    every "contains the arm" assertion above only by accident, so state the inequality directly."""
    phrase = _M._downgraded_arm_phrase(fit_class, _M._surface_verdict_by_modality(token))
    assert phrase != _M._FIT_CLASS_PHRASE[fit_class]


@pytest.mark.parametrize("token", _DOWNGRADE_TOKENS)
@pytest.mark.parametrize("fit_class", _POSITIVE_FIT)
def test_no_downgraded_arm_is_called_viable_or_preferred(token, fit_class):
    """The defect in one assertion: the substring "<ARM> viable" / "<ARM> preferred" must not appear for
    an arm the resolver downgraded. Guards the phrase against a future re-ordering that reunites a
    downgraded arm with a positive word."""
    arms = _M._surface_verdict_by_modality(token)
    phrase = _M._downgraded_arm_phrase(fit_class, arms)
    for arm, state in arms.items():
        if state in _M._ARM_DOWNGRADED:
            label = _ARM_LABEL[arm]
            for positive in ("viable", "preferred", "supported"):
                assert f"{label} {positive}" not in phrase, f"{phrase!r} still calls {arm} {positive}"


def test_the_sharpest_row_reads_honestly():
    """The 15-row cell, spelled out: tce_unsafe_normal_liability has NO viable arm, and used to render
    "TCE-favorable"."""
    arms = _M._surface_verdict_by_modality("tce_unsafe_normal_liability")
    assert "viable" not in arms.values() and "preferred" not in arms.values()
    assert _M._downgraded_arm_phrase("TCE_preferred", arms) == "TCE unsafe; ADC & mAb not preferred"
    # and the 69-row cell
    assert (
        _M._downgraded_arm_phrase("both_viable", _M._surface_verdict_by_modality("adc_preferred_tce_unsafe"))
        == "TCE unsafe; ADC & mAb viable"
    )


# ── the rows that must NOT move ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("token", ["both_viable", "adc_preferred", "tce_preferred"])
def test_clean_positive_tokens_keep_the_fit_class_phrase(token):
    """No arm downgraded → no override → byte-identical to trunk. `not_preferred` (adc_preferred /
    tce_preferred) is the FIT'S OWN ranking of the arm it did not pick, not a resolver downgrade, so it
    must NOT trigger — otherwise 240+ untouched rows would churn."""
    assert _M._downgraded_arm_phrase("both_viable", _M._surface_verdict_by_modality(token)) is None


@pytest.mark.parametrize("token", sorted(_M._VERDICT_ARMS))
def test_non_positive_fit_classes_never_override(token):
    """The override exists because a FAVOURABLE phrase mis-asserts. A negative or gap fit_class already
    reads honestly (`neither_viable`, `Insufficient evidence`), so it keeps its phrase even when arms are
    downgraded — including pmhc_tce_supported, whose "Neither ADC nor TCE viable" badge is the correct
    read and whose pMHC route is surfaced as the top tension instead."""
    arms = _M._surface_verdict_by_modality(token)
    for fit_class in ("neither_viable", "insufficient", "modality_ambiguous", "data_unavailable", None):
        assert _M._downgraded_arm_phrase(fit_class, arms) is None


def test_malformed_arms_never_crash_the_headline():
    for arms in (None, {}, "not-a-dict", {"adc": None}):
        assert _M._downgraded_arm_phrase("both_viable", arms) is None


# ── the completeness guard that would have caught the two missing reason rows ─────────────────────
def test_every_downgraded_token_has_a_downgrade_reason_row():
    """_SURFACE_DOWNGRADE_REASON feeds the severity-3 top tension. `adc_preferred_tce_escape_risk` and
    `tce_escape_risk` were absent from it since they shipped (1.3.0, 2026-08-24), so those rows rendered
    a favourable phrase with severity=None AND text=None — no downgrade note on any surface. Two
    parallel inventories over one vocabulary drift; this makes the drift a red."""
    missing = [t for t in _DOWNGRADE_TOKENS if t not in _M._SURFACE_DOWNGRADE_REASON]
    assert not missing, f"downgraded tokens with no top-tension reason row: {missing}"


def test_no_reason_row_describes_a_token_without_a_downgraded_arm():
    """The reverse direction — a reason row for a token whose arms carry no downgraded state documents
    behaviour that cannot happen. Checked both ways because the two maps fail independently."""
    fictional = [
        t
        for t in _M._SURFACE_DOWNGRADE_REASON
        if not any(s in _M._ARM_DOWNGRADED for s in _M._VERDICT_ARMS.get(t, {}).values())
    ]
    assert not fictional, f"reason rows for tokens with no downgraded arm: {fictional}"


def test_the_escape_risk_reason_rows_fire_as_a_top_tension():
    """The added rows, exercised through the real tension builder rather than read off the map."""
    for token in ("adc_preferred_tce_escape_risk", "tce_escape_risk"):
        extra = _M._surface_tension_extra({"surface_modality_verdict": token, "fit_class": "both_viable"})
        assert extra and extra["severity"] == 3, f"{token} still has no top tension"
        assert extra["source"] == "surface_modality_downgrade"
        assert "escape reservoir" in extra["text"]


# ── the vocabulary is shared and derived, not copied ──────────────────────────────────────────────
def test_arm_labels_are_the_one_shared_vocabulary():
    """run.py imports headline_hero's `_ARM_LABEL` rather than copying it. Identity, not equality: a
    copied dict would compare equal on the day it was written and drift silently afterwards."""
    assert _M._ARM_LABEL is _ARM_LABEL


def test_every_arm_state_renders_as_a_word_without_a_map():
    """The state word is DERIVED (`replace("_", " ")`), so no state can be missing a row. Assert the
    transform is total over the pinned map and leaves no underscore in a rendered phrase."""
    states = {s for arms in _M._VERDICT_ARMS.values() for s in arms.values()}
    assert len(states) >= 10, f"the arm-state vocabulary shrank unexpectedly: {sorted(states)}"
    for state in states:
        word = state.replace("_", " ")
        assert word and "_" not in word
    for token in _DOWNGRADE_TOKENS:
        for fit_class in _POSITIVE_FIT:
            assert "_" not in _M._downgraded_arm_phrase(fit_class, _M._surface_verdict_by_modality(token))


# ── the phrase survives the hero's truncation ─────────────────────────────────────────────────────
@pytest.mark.parametrize("token", _DOWNGRADE_TOKENS)
@pytest.mark.parametrize("fit_class", _POSITIVE_FIT)
def test_downgraded_arm_survives_hero_truncation(token, fit_class):
    """headline_hero truncates the phrase for the badge, so the DOWNGRADED states are ordered FIRST.
    The longest phrase (tce_patient_variable, 58 chars) does get an ellipsis — but the exclusion is
    still the part the reader sees. This is why the ordering is load-bearing, not cosmetic."""
    arms = _M._surface_verdict_by_modality(token)
    shown = _truncate(_M._downgraded_arm_phrase(fit_class, arms), _HERO_TRUNCATE)
    for arm, state in arms.items():
        if state in _M._ARM_DOWNGRADED:
            assert _ARM_LABEL[arm] in shown, f"truncated badge {shown!r} lost the downgraded {arm} arm"


# ── WIRING: it must fire where a real run enters ──────────────────────────────────────────────────
def test_build_headline_block_applies_the_override():
    """A phrase builder nothing calls is decoration. Enter through `_build_headline_block` — the one
    call site the dispatcher uses — and check every surface the phrase fans out to."""
    blk = _M._build_headline_block(_headline("adc_preferred_tce_unsafe", "both_viable"))
    assert blk["verdict"]["phrase"] == "TCE unsafe; ADC & mAb viable"
    assert blk["headline_text"].startswith("TCE unsafe; ADC & mAb viable — ")
    # the spine did NOT move with the display phrase
    assert blk["verdict"]["call"] == "both_viable"
    assert blk["verdict"]["gate"] == "surface_modality"
    assert blk["verdict"]["polarity"] == "positive"
    # the hero chips and the phrase come from ONE arm resolution, so they cannot contradict
    assert blk["hero"]["modality_arms"]["bite_tce"] == "unsafe"
    assert [a["key"] for a in blk["hero"]["axes"]] == ["FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"]


def test_clean_row_headline_block_is_unchanged():
    blk = _M._build_headline_block(_headline("both_viable", "both_viable"))
    assert blk["verdict"]["phrase"] == "ADC & TCE viable"
    assert blk["verdict"]["call"] == "both_viable"


def test_the_phrase_reaches_the_skill_report_and_the_evidence_graph():
    """`skill_report.honest_phrase` and `evidence_graph.verdict.call` both read the headline phrase, so
    one producer fixes six surfaces. `evidence_graph.verdict.id` must stay the fit_class token — the
    #1384 invariant — while its sibling `call` carries the honest phrase."""
    headline = _headline("adc_preferred_tce_unsafe", "both_viable")
    blk = _M._build_headline_block(headline)
    headline["headline_block"] = blk
    report = build_skill_report(role=_M.ROLE_GATING, verdict="both_viable", headline_block=blk)
    assert report["honest_phrase"] == "TCE unsafe; ADC & mAb viable"
    assert report["call"] == "both_viable"

    headline["skill_report"] = report
    graph = build_evidence_graph({"target": "CEACAM5", "indication": "COADREAD", "headline": headline, "cards": []})
    verdict = graph["verdict"]
    assert verdict["id"] == "both_viable", "the spine token moved — #1384's invariant"
    assert verdict["call"] == "TCE unsafe; ADC & mAb viable"
