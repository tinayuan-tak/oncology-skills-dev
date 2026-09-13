"""The capsule's NUMBERS come from the card contract, not from a substring scan.

WHY THIS EXISTS. `evidence_capsule.emit_capsules` projects each card into a compact capsule — a `class`
plus a few `numeric_anchors` — and that projection is what the dashboard and the evidence graph SHOW. The
class-pick became contracts-first earlier (`capsule.primary_class`); the numbers did not, and kept coming
from `_ANCHOR_HINTS`: take every summary field whose NAME contains one of ~26 substrings, sort
ALPHABETICALLY, keep the first FOUR. That guesses wrong in three independent ways, and all three were live
on the genomic axis:

  1. ALPHABETICAL — the class-setting number is surfaced only by luck of its name.
  2. CAPPED AT 4 — mutation-stratified-dependency has 11 hint-matching fields, so its own headline gauges
     (`hotspot_effect_size`, the `median_chronos_hotspot_{mutant,wildtype}` pair the salience ruler is cut
     against) were crowded out by alphabetically-earlier fields.
  3. UNREACHABLE — a field matching NO hint cannot be surfaced at all. "score" is not a hint, so
     copy-number-distribution's `cn_recurrent_deletion_score` — the value the `copy_number_class` cut is
     literally taken against — could never appear, while four alphabetical `cn_fraction_*` values did.

Every one of those failures is SILENT and verdict-INERT: the capsule still renders, just with the wrong
numbers, which is exactly why nothing caught it. This module pins the reader half of the fix (target-contracts
#751 declares `capsule.numeric_anchors` on the 12 genomic verdict-driving cards; mirror-guard order is card
DECLARES then reader EMITS). Tests monkeypatch the contract reader rather than reading the live contracts
root, so they pin the READER's behaviour and stay green whatever the contracts fleet currently declares.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import evidence_capsule as EC  # noqa: E402
from _skills_common import subgroup_derivation as SD  # noqa: E402

# The REAL copy-number-distribution summary, field-for-field (ABL1/CML shape). Two `*_score` fields match no
# hint; five `*_fraction*`/`*median*` fields do. Taken from a live run so no assertion below can be vacuous
# on a value the producer never emits.
_CN_SUMMARY = {
    "copy_number_class": "recurrently_deleted",
    "cn_recurrent_amplification_score": 0.047,
    "cn_recurrent_deletion_score": 0.2016,
    "cn_fraction_high_amplification": 0.011,
    "cn_fraction_deep_deletion": 0.0402,
    "patient_high_amp_fraction": 0.0,
    "patient_homdel_fraction": 0.0134,
    "cn_median_panel": -0.0281,
    "n_samples": 1084,
}

# The declaration target-contracts #751 puts on the card: READING order — the effect that sets the class
# first, then the arms it separates, then the patient-cohort arm the cap at 4 dropped entirely.
_CN_DECLARED = (
    "cn_recurrent_amplification_score",
    "cn_recurrent_deletion_score",
    "cn_fraction_high_amplification",
    "cn_fraction_deep_deletion",
    "patient_high_amp_fraction",
    "patient_homdel_fraction",
    "cn_median_panel",
)


def _cn_card():
    return [{"card_id": "copy-number-distribution", "summary": dict(_CN_SUMMARY)}]


def _anchors(monkeypatch, declared=(), cfg=None, summary=None):
    """Emit the card's numeric_anchors with `declared` as its contract declaration, in ORDER."""
    monkeypatch.setattr(EC, "_card_capsule_contract", lambda cid: ("copy_number_class", (), tuple(declared)))
    cards = [{"card_id": "copy-number-distribution", "summary": dict(summary or _CN_SUMMARY)}]
    cap = EC.emit_capsules(cards, "CML", config=cfg or {})["capsules"]["copy-number-distribution"]
    return [a["metric"] for a in (cap["numeric_anchors"] or [])]


# ── the baseline the fix is measured against ──────────────────────────────────────────────────────────
def test_the_hint_scan_baseline_is_alphabetical_capped_and_unreachable(monkeypatch):
    """Pins the DEFECT, so the improvement below is a measured delta rather than an assertion of intent.
    Without a declaration all three failure modes are visible in one call."""
    got = _anchors(monkeypatch, declared=())
    assert got == [
        "cn_fraction_deep_deletion",
        "cn_fraction_high_amplification",
        "cn_median_panel",
        "patient_high_amp_fraction",
    ], got
    assert len(got) == 4  # (2) the cap
    assert got == sorted(got)  # (1) alphabetical, not salience
    # (3) the two numbers the class is cut against are STRUCTURALLY unreachable — "score" is not a hint
    assert not any("score" in m for m in got)
    assert "patient_homdel_fraction" not in got  # a hint-matching field the cap still dropped


# ── the fix ───────────────────────────────────────────────────────────────────────────────────────────
def test_a_declared_list_replaces_the_scan_verbatim(monkeypatch):
    """Declared order is READING order and must survive: not re-sorted (the scan's alphabetical order is
    defect 1) and not capped at 4 (defect 2). The card schema caps the declaration itself at 8."""
    got = _anchors(monkeypatch, declared=_CN_DECLARED)
    assert got == list(_CN_DECLARED), got
    assert got != sorted(got), "declared order was re-sorted — the alphabetical defect is back"
    assert len(got) == 7 > 4


def test_a_declaration_reaches_a_field_no_hint_can_match(monkeypatch):
    """The `copy_number_class` cut is taken against `cn_recurrent_deletion_score` 0.2016 vs 0.2. The scan
    can never surface it; the declaration must, WITH its value, or the capsule shows a class whose
    deciding number is absent."""
    monkeypatch.setattr(EC, "_card_capsule_contract", lambda cid: ("copy_number_class", (), _CN_DECLARED))
    caps = EC.emit_capsules(_cn_card(), "CML")["capsules"]["copy-number-distribution"]
    by_metric = {a["metric"]: a["value"] for a in caps["numeric_anchors"]}
    assert by_metric["cn_recurrent_deletion_score"] == 0.2016
    assert by_metric["cn_recurrent_amplification_score"] == 0.047
    assert caps["class"] == "recurrently_deleted"  # the class and the number that set it, together


def test_config_override_still_beats_the_contract(monkeypatch):
    """Precedence is cfg > contract > hints. The runtime override has no live users today, but it is the
    documented escape hatch, so it must not be silently demoted by the contract path."""
    got = _anchors(
        monkeypatch,
        declared=_CN_DECLARED,
        cfg={"copy-number-distribution": {"anchor_fields": ["cn_median_panel", "cn_recurrent_deletion_score"]}},
    )
    assert got == ["cn_median_panel", "cn_recurrent_deletion_score"], got


# ── what a declaration must NOT do ────────────────────────────────────────────────────────────────────
def test_a_declared_field_absent_from_this_run_is_dropped_not_backfilled(monkeypatch):
    """The tempting fallback is the wrong one. If a declared field is missing from THIS run's summary,
    re-entering the hint scan would show hint-picked numbers on exactly the runs where the card's own were
    unavailable — restoring the guess the declaration exists to replace, and only on the runs nobody looks
    at. Drop the missing field; never back-fill."""
    got = _anchors(monkeypatch, declared=("cn_recurrent_deletion_score", "field_that_this_run_did_not_emit"))
    assert got == ["cn_recurrent_deletion_score"], got
    # and when NONE of the declared fields landed, the anchors are honestly empty — not the scan's picks
    none_landed = _anchors(monkeypatch, declared=("field_a_absent", "field_b_absent"))
    assert none_landed == [], none_landed


def test_a_declared_categorical_is_never_rendered_as_a_number(monkeypatch):
    """`numeric_anchors` is consumed as numbers (rulers gauge them against cuts). A declaration naming a
    class token or a boolean flag must be dropped, not emitted with a string/bool `value` — the
    CAPSULE_CATEGORICAL_AS_NUMERIC failure the contracts validator errors on, defended a second time here
    because a card predating that validator, or a hand-written config, can still reach this code."""
    summary = dict(_CN_SUMMARY, cn_homozygous_deletion_recurrent=True)
    got = _anchors(
        monkeypatch,
        declared=("copy_number_class", "cn_homozygous_deletion_recurrent", "cn_recurrent_deletion_score"),
        summary=summary,
    )
    assert got == ["cn_recurrent_deletion_score"], got


def test_denied_and_private_keys_cannot_be_smuggled_in_by_a_declaration(monkeypatch):
    """A declaration is trusted for SELECTION, not for the echo denylist: `_`-prefixed internals stay
    internal. (They are non-numeric in practice, but a numeric one must still not leak.)"""
    summary = dict(_CN_SUMMARY, _internal_scratch_value=1.23)
    got = _anchors(monkeypatch, declared=("_internal_scratch_value", "cn_recurrent_deletion_score"), summary=summary)
    assert "_internal_scratch_value" not in got, got


# ── the contract READER itself ─────────────────────────────────────────────────────────────────────────
def _write_card(tmp_path: Path, body: str) -> None:
    (tmp_path / "cards").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cards" / "synthetic-anchor-card.card.yaml").write_text(body)


def _read(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(SD, "_CT", tmp_path)
    SD._card_capsule_contract.cache_clear()
    try:
        return SD._card_capsule_contract("synthetic-anchor-card")
    finally:
        SD._card_capsule_contract.cache_clear()  # the cache is module-global; never leak a tmp read


def test_reader_returns_declared_anchors_in_order(monkeypatch, tmp_path):
    _write_card(
        tmp_path,
        "card_id: synthetic-anchor-card\n"
        "capsule:\n"
        "  primary_class: copy_number_class\n"
        "  categorical_fields: [copy_number_class]\n"
        "  numeric_anchors: [z_effect, a_arm, m_significance]\n",
    )
    pc, cat, anchors = _read(monkeypatch, tmp_path)
    assert pc == "copy_number_class"
    assert cat == ("copy_number_class",)
    assert anchors == ("z_effect", "a_arm", "m_significance")  # declared order, NOT sorted


def test_reader_is_backward_compatible_and_never_raises(monkeypatch, tmp_path):
    """Three degradations must all yield the same inert (None, (), ()) so an un-migrated, half-migrated or
    corrupt card falls back to the heuristic instead of breaking the spine."""
    _write_card(tmp_path, "card_id: synthetic-anchor-card\n")  # no capsule: block at all
    assert _read(monkeypatch, tmp_path) == (None, (), ())
    # capsule with no numeric_anchors → third element empty, first two still honored (the pre-#751 shape)
    _write_card(tmp_path, "card_id: synthetic-anchor-card\ncapsule:\n  primary_class: cn_class\n")
    assert _read(monkeypatch, tmp_path) == ("cn_class", (), ())
    # non-string entries are dropped rather than crashing the projection
    _write_card(tmp_path, "card_id: synthetic-anchor-card\ncapsule:\n  numeric_anchors: [ok_field, 7, null]\n")
    assert _read(monkeypatch, tmp_path) == (None, (), ("ok_field",))
    # unparseable YAML
    _write_card(tmp_path, "card_id: [unclosed\n")
    assert _read(monkeypatch, tmp_path) == (None, (), ())
    # absent card file
    monkeypatch.setattr(SD, "_CT", tmp_path / "nowhere")
    SD._card_capsule_contract.cache_clear()
    assert SD._card_capsule_contract("synthetic-anchor-card") == (None, (), ())
    SD._card_capsule_contract.cache_clear()
