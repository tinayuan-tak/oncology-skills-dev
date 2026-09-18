"""Governance for the interpretation-encoding reference-frame rulers (Stage 2).

Lives skills-side (not target-contracts) because it cross-checks SALIENCE_SPECS — which are defined in
_skills_common — against the card contracts' `outputs.summary_fields` + `thresholds:`; target-contracts
cannot import skills. Fail-soft when the contracts checkout is absent (isolated CI) so it never red-fails
on environment, only on a real spec/contract drift.

Invariants:
  1. Every verdict-bearing measurement_type is GAUGEABLE — has a `direction` (numeric ruler) OR a
     non-empty `categorical` (the class IS the ruler). No un-gaugeable verdict type.
  2. Every `reference_frame` is well-formed: value_field + scale (no bare number) + direction (to orient).
  3. Every reference_frame field (value/distance/position + anchor fields) is a REAL summary_field of the
     naming card (sync check — a renamed contract field can't silently break the ruler).
  4. Every reference_frame cut single-sources to a REAL numeric key in the driving card's `thresholds:`
     (never re-hardcoded; never dangling).
  5. The frame's REACH is what evidence_salience.py's notes claim: verdict-INERT (no gate reads it) but NOT
     display-only (it is also ATLAS-live and CLAIM-RECORD-live). Two-sided, so neither half can go vacuous.
"""

import ast
import json
import os
import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[1]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.archetype_core import _SHIPPED_ATLAS
from _skills_common.claim_record import magnitude_from_interpretation
from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation, contract_threshold
from _skills_common.feature_vectoriser import numeric_feature_specs, numeric_source_cards
from _skills_common.paths import target_contracts_root


@lru_cache(maxsize=256)
def _card_summary_fields(card_id: str):
    """The declared outputs.summary_fields of a card (or None when the contracts checkout is absent)."""
    p = target_contracts_root() / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    spec = yaml.safe_load(p.read_text()) or {}
    fields = ((spec.get("outputs") or {}).get("summary_fields")) or []
    return {f for f in fields if isinstance(f, str)}


def _frames(mt):
    """A spec's reference_frame normalized to a LIST of frame dicts — one card may carry >1 ruler
    (reference_frame is a dict OR a list of dicts). Empty list when the type has no frame."""
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    if isinstance(rf, list):
        return [f for f in rf if isinstance(f, dict)]
    return [rf] if isinstance(rf, dict) else []


def _cuts(rf):
    """Every cut dict on a frame: the single `cut` (distance_to_cut / floor_cut_ceiling / count_of_total)
    plus the `cuts` ladder (graded_band)."""
    return ([rf["cut"]] if isinstance(rf.get("cut"), dict) else []) + [
        c for c in (rf.get("cuts") or []) if isinstance(c, dict)
    ]


def test_every_verdict_bearing_type_is_gaugeable():
    bad = [mt for mt, s in SALIENCE_SPECS.items() if not (s.get("direction") or s.get("categorical"))]
    assert not bad, f"measurement_types with neither a direction (numeric ruler) nor categorical: {bad}"


# ── invariant 1b: the verdict-bearing SET comes from the CONTRACTS, not from SALIENCE_SPECS ────────────
# test_every_verdict_bearing_type_is_gaugeable above iterates SALIENCE_SPECS.items(), so a verdict-bearing
# measurement_type with NO SPEC AT ALL is INVISIBLE to it — it passes by not being enumerated. That is the
# vacuous half: when this was written, 13 of the 43 verdict-bearing types had no spec and the test was green.
# The authoritative set is derived here from the contracts instead: rules named `gating` in
# coverage/rule_role_partition.yaml → their when.card_id → that card's measurement_type.

# DECLARED DEBT, not a gap. Verdict-bearing types that carry no SALIENCE_SPEC yet, each owned by the review
# of its own subskill (this ratchet is scoped to genomic-alteration-profile, whose three —
# copy_number_alteration, mutation_variant_class_spectrum, mutation_clonality — were filled 2026-09-12).
# A NEW gating card must either ship a spec or be added here DELIBERATELY, with the owning review named.
_UNSPECCED_VERDICT_BEARING_DEBT = {
    "cis_dosage_coupling",  # cis-feature-expression-coherence — cis-feature-coherence review
    "dosage_sensitivity_safety",  # clingen-dosage — on-target-safety review
    "exon_window",  # modality-exon-window — modality-fit review
    "human_genetic_safety",  # gene-burden-safety — on-target-safety review
    "known_drug_tractability",  # known-drug-tractability — tractability review
    "paralog_buffering",  # paralog-buffering — functional-requirement review
    "partner_conditional_dependency",  # partner-conditional-dependency — combination review
    "pmhc_epitope_evidence",  # pmhc-epitope-evidence-iedb — pMHC review
    "pmhc_presentation",  # pmhc-presentation — pMHC review
}


@lru_cache(maxsize=1)
def _verdict_bearing_measurement_types():
    """{measurement_type} for every card named by a GATING interpretation rule, read from the contracts.
    None when the contracts checkout is absent."""
    root = target_contracts_root()
    part = root / "coverage" / "rule_role_partition.yaml"
    if not part.exists():
        return None
    gating = set((yaml.safe_load(part.read_text()) or {}).get("gating") or [])
    rule_to_card = {}
    for f in sorted((root / "interpretation-rules").glob("*.rules.yaml")):
        doc = yaml.safe_load(f.read_text())
        rules = doc if isinstance(doc, list) else ((doc or {}).get("rules") or [])
        for r in rules:
            if isinstance(r, dict) and r.get("rule_id"):
                rule_to_card[r["rule_id"]] = (r.get("when") or {}).get("card_id")
    gating_cards = {rule_to_card[r] for r in gating if rule_to_card.get(r)}
    types = set()
    for c in sorted((root / "cards").glob("*.card.yaml")):
        spec = yaml.safe_load(c.read_text()) or {}
        if spec.get("card_id") in gating_cards and spec.get("measurement_type"):
            types.add(spec["measurement_type"])
    return types


def test_every_contract_declared_verdict_bearing_type_has_a_spec():
    types = _verdict_bearing_measurement_types()
    if types is None:
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    assert types, "derived NO verdict-bearing types — the derivation broke, not the contracts"
    unspecced = {t for t in types if t not in SALIENCE_SPECS}
    undeclared = sorted(unspecced - _UNSPECCED_VERDICT_BEARING_DEBT)
    assert not undeclared, (
        "verdict-bearing measurement_types with NO SALIENCE_SPEC and no declared debt entry "
        f"(a gating card whose numbers reach no capsule/ruler): {undeclared}"
    )


def test_the_unspecced_debt_list_has_no_stale_entries():
    """The ratchet's other direction: an entry that has since been given a spec, or that is no longer
    verdict-bearing, must LEAVE the list — otherwise the allowlist grows into a permanent excuse and stops
    measuring anything. This is what forces the list to shrink as each subskill review lands."""
    types = _verdict_bearing_measurement_types()
    if types is None:
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    now_specced = sorted(t for t in _UNSPECCED_VERDICT_BEARING_DEBT if t in SALIENCE_SPECS)
    not_gating = sorted(t for t in _UNSPECCED_VERDICT_BEARING_DEBT if t not in types)
    assert not now_specced, f"declared debt that now HAS a spec — remove from the list: {now_specced}"
    assert not not_gating, f"declared debt that is no longer verdict-bearing — remove from the list: {not_gating}"


def test_the_genomic_verdict_bearing_types_are_all_specced():
    """The scope this PR closed, pinned so a later edit cannot quietly re-open it. These three are named by
    GATING genomic rules; copy_number_alteration and mutation_variant_class_spectrum key resolver rungs."""
    for mt in ("copy_number_alteration", "mutation_variant_class_spectrum", "mutation_clonality"):
        assert mt in SALIENCE_SPECS, f"{mt}: verdict-bearing genomic type lost its spec"
        assert mt not in _UNSPECCED_VERDICT_BEARING_DEBT, f"{mt}: specced, so it must not be in the debt list"


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")))
def test_reference_frame_is_wellformed(mt):
    frames = _frames(mt)
    assert frames, f"{mt}: reference_frame present but no frame dict resolved"
    for rf in frames:
        assert rf.get("value_field"), f"{mt}: reference_frame needs a value_field"
        assert rf.get("scale"), f"{mt}: reference_frame needs a scale (no bare number)"
        assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: reference_frame needs a direction to orient the gauge"
        assert rf.get("kind") in (
            "percentile",
            "floor_cut_ceiling",
            "comparator_delta",
            "distance_to_cut",
            "graded_band",
            "count_of_total",
            "cohort_percentile",
        ), f"{mt}: unknown frame kind {rf.get('kind')!r}"
        if rf.get("kind") == "graded_band":
            assert len(_cuts(rf)) >= 2, f"{mt}: graded_band needs >=2 cut anchors (the ladder)"
        if rf.get("kind") == "count_of_total":
            assert rf.get("total_field"), f"{mt}: count_of_total needs a total_field (the denominator)"
        if rf.get("kind") == "cohort_percentile":
            # the atlas feature key whose corpus column IS the known-target cohort; keyed as
            # {measurement_type}::num::{value_field} so it matches the atlas numeric feature.
            assert rf.get("cohort_key") == f"{mt}::num::{rf['value_field']}", (
                f"{mt}: cohort_percentile needs cohort_key '{mt}::num::{rf['value_field']}', got {rf.get('cohort_key')!r}"
            )


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")))
def test_reference_frame_fields_are_real_summary_fields(mt):
    for rf in _frames(mt):
        card_id = next((c.get("card_id") for c in _cuts(rf) if c.get("card_id")), None)
        if not card_id:
            continue  # no cut card to anchor the summary-field sync check for this frame
        sf = _card_summary_fields(card_id)
        if sf is None:
            pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
        named = [rf.get("value_field"), rf.get("distance_field"), rf.get("position_field"), rf.get("total_field")]
        named += [a.get("field") for a in (rf.get("anchors") or []) if isinstance(a, dict)]
        missing = sorted(f for f in named if f and f not in sf)
        assert not missing, f"{mt}: reference_frame fields not in {card_id} outputs.summary_fields: {missing}"


@pytest.mark.parametrize(
    "mt",
    sorted(
        mt
        for mt, s in SALIENCE_SPECS.items()
        if any(
            _cuts(f)
            for f in (
                s["reference_frame"] if isinstance(s.get("reference_frame"), list) else [s.get("reference_frame")]
            )
            if isinstance(f, dict)
        )
    ),
)
def test_reference_frame_cut_resolves_to_a_real_threshold(mt):
    for rf in _frames(mt):
        for cut in _cuts(rf):
            if _card_summary_fields(cut.get("card_id")) is None:
                pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
            v = contract_threshold(cut.get("card_id"), cut.get("threshold"))
            assert v is not None, (
                f"{mt}: cut {cut.get('threshold')!r} does not resolve to a numeric key in "
                f"{cut.get('card_id')} thresholds: (single-source it from the contract)"
            )


def test_significance_field_added_for_mutation_stratified_is_real():
    # the Stage-2 coverage-gap fill must name a real summary_field
    sf = _card_summary_fields("mutation-stratified-dependency")
    if sf is None:
        pytest.skip("contracts checkout absent")
    assert "hotspot_mannwhitney_q" in sf


# ── invariant 5: the frame's REACH — verdict-INERT, but NOT display-only ────────────────────────────────
# WHAT THIS PINS, AND WHY IT IS NOT JUST DOCUMENTATION. evidence_salience.py annotates its reference_frame
# blocks "DISPLAY-ONLY / verdict-INERT" at 12 sites, and NONE of them names an authority — no test, no PR,
# no command. Measured against trunk, the label is half right and half BACKWARDS:
#
#   verdict-INERT   TRUE   — 3 production readers, ZERO of them a gate / resolver / veto / dispatcher.
#   display-only    FALSE  — the same key is ATLAS-live (it mints FROZEN numeric columns) and
#                            CLAIM-RECORD-live (the projection is re-read as the record's magnitude).
#
# So the reach is THREE-LIVE / ONE-INERT, and "gates" is the only inert consumer of the four. The file's own
# history is why the distinction matters rather than being pedantry: the note beside _UNRANKABLE_SCALES
# records a defect that "survived because it was verdict-inert, so it still rendered — just wrong."
# Verdict-inertness is not a safety argument, so the claim has to be enforced instead of asserted in prose.
#
# Everything below cites evidence_salience.py by SYMBOL, never by line number — the commit that added this
# invariant also inserted a header block into that file, so every line number in it shifted. A pointer that
# rots in the same commit that creates it is worse than no pointer.
#
# PRIMARY vs SECONDARY is the discrimination no reader can recover from those comments, and it is why a
# blanket relabel of all 12 sites would have introduced a NEW false claim in the opposite direction: only
# rf[0] mints a column (feature_vectoriser reads the primary frame), so across 77 frames on 35 framed axes
# there are just 32 columns. An APPENDED / secondary frame genuinely IS display-only. Relabel per SITE.
#
# AST, NOT GREP — a text scan is wrong in BOTH directions here, which is why _frame_key_readers() parses:
#   false POSITIVE — immune_context_claims.py owns an unrelated `reference_frame` CLAIM SCALAR (its
#     `_reference_frame()` helper, written onto the claim vector). It never LOADS the SALIENCE_SPECS key, so
#     a grep would put a claims module on the readers list. Pinned by the companion test below.
#   false NEGATIVE — frames are injected by helper loops at FOUR write sites (the _BATCH_DISTANCE_TO_CUT_METERS
#     primary injection, the two _SECONDARY_FRAMES append branches, and the fleet-wide cohort roll), so a
#     literal-string scan of the spec blocks cannot see them. That is exactly how an earlier audit recorded
#     31 framed axes against a live 35.
# Store contexts are excluded ON PURPOSE: writing the key AUTHORS a ruler, reading it CONSUMES one, and only
# a consumer can falsify a claim about who consumes it.
#
# KNOWN LIMIT of the census, stated rather than left to be discovered: it matches the key as a LITERAL, so a
# reader that goes through a variable (`spec.get(SOME_KEY)`) is invisible to it. Demonstrated — replacing the
# literal in field_disposition with a behaviour-identical constant reds this file and nothing else. The
# equality therefore catches a new READER FILE reliably, and in-file indirection only if the literal remains.
#
# claim_record.py is absent from the readers list and that is not an omission — it consumes the frame's
# OUTPUT (a gauged_value, via magnitude_from_interpretation), not the spec key, so no census of the key can
# see it. That reach is pinned by test_every_framed_axis_reaches_display_and_the_claim_record instead.
#
# WHY AN EQUALITY AND NOT "no gate reads it". A predicate over a hand-listed set of gate modules goes vacuous
# the moment a gate lands in a file the list never heard of — precisely the hole invariant 1b above
# documents, where a verdict-bearing type with NO SPEC AT ALL passed by not being enumerated. An exact
# equality has no such hole: any new consumer, gate or not, reds until a human classifies it.
#
# ROOTED AT THE REPO, NOT AT skills/. A guard rooted where its author works is blind to a second vocabulary
# elsewhere — `eval/` is not under `skills/` — so the walk starts at SKILLS.parent.
_REFERENCE_FRAME_KEY_READERS = {
    "skills/_skills_common/evidence_salience.py": (
        "DISPLAY — build_interpretation() projects the frame(s) into key_evidence.interpretation[] as a "
        "gauged_value. The helper loops that INJECT frames also read the key, but only to avoid overwriting "
        "an authored one."
    ),
    "skills/_skills_common/feature_vectoriser.py": (
        "ATLAS — numeric_feature_specs() mints {measurement_type}::num::{value_field} off the PRIMARY frame "
        "only, and numeric_source_cards() reads that frame's cut card_id. This is the half that makes "
        "'display-only' false: those columns are FROZEN, and every shipped cohort_percentile moves with them."
    ),
    "skills/_skills_common/field_disposition.py": (
        "ACCOUNTING — the reach census reads the frames to attribute summary_fields to a reader, and names "
        "the frame's cut card_id. Consumes the ruler without gauging anything."
    ),
    "skills/_skills_common/field_descriptor.py": (
        "DISPLAY — _spec_frame_value_fields() reads the key ONLY to enumerate each frame's value_field so "
        "the derived per-field descriptor can FLAG it atlas_live=True (a PRIMARY value_field mints frozen "
        "atlas columns, so the descriptor DESCRIBES it and must never reshape it). Gauges nothing, gates "
        "nothing, resolves nothing — verdict-INERT + additive, and nothing consumes the descriptor yet. So "
        "the 'verdict-INERT' notes in evidence_salience.py stay TRUE; this is a fourth inert reader, not a gate."
    ),
}

# The REAL display-only boundary, with the reason each axis opts out — all three transcribed from the
# rationale written beside the flag in evidence_salience.py, not inferred here.
_ATLAS_NUMERIC_OPTOUT = {
    "alteration_role": (
        "DEGENERATE value — every gene with a driver call has intogen_min_qvalue at or below 0.05 and most "
        "sit orders of magnitude below, while genes without one have no value at all, so the ::mask already "
        "carries the whole signal. Its scale is in _UNRANKABLE_SCALES for the same reason."
    ),
    "immune_context": (
        "TARGET-INDEPENDENT — median_cd8_fraction is the INDICATION's immune landscape, identical for every "
        "target in a cohort, so an atlas numeric would cluster known targets by indication and phrase an "
        "indication property as a target property."
    ),
    "mutation_variant_class_spectrum": (
        "NON-MONOTONE polarity — a high mut_fraction_missense reads DRIVER for an oncogene and PASSENGER for "
        "a tumour suppressor, so a fixed _DIR_SIGN would be wrong for whichever half of the corpus it is not "
        "describing."
    ),
    "sc_normal_celltype_expression": (
        "ATLAS DEFERRED — the graded_band ruler is display-only (atlas_numeric: False) because the "
        "target-archetype atlas is deferred out of go-live; minting a new frozen column now is a one-way "
        "door. The descriptor + display cut-line (the Gap-A goal) need no atlas feature. Flip when the atlas "
        "returns."
    ),
    "shet_lof_selection": (
        "ATLAS DEFERRED — same reason as sc_normal_celltype_expression: the s_het graded_band is a "
        "display-only ruler (atlas_numeric: False) because the target-archetype atlas is deferred out of "
        "go-live, and minting a new frozen column now is a one-way door. The descriptor-coverage goal (label "
        "+ units + a cut-line for the previously-unclassified shet_score) needs no atlas feature. Flip when "
        "the atlas returns."
    ),
    "spatial_til_fraction": (
        "TARGET-INDEPENDENT — median_til_percentage is the INDICATION's H&E TIL landscape (Saltz DL maps), "
        "identical for every target in a cohort, so a target atlas numeric would cluster known targets by "
        "indication and phrase an indication property as a target property (same reasoning as immune_context). "
        "The graded_band stays a display ruler (atlas_numeric: False)."
    ),
}

_SCAN_PRUNE = {".git", ".pixi", ".venv", "__pycache__", "node_modules", ".ruff_cache", ".pytest_cache"}

_FRAMED = sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame"))


@lru_cache(maxsize=1)
def _frame_key_readers():
    """{repo-relative path: n_loads} for every PRODUCTION module that READS the `reference_frame` key.

    Rooted at SKILLS.parent (the REPO) so a second vocabulary outside skills/ cannot hide from it. Tests are
    excluded — a test reading the key is not a consumer of the ruler. Store contexts are excluded on purpose
    (see the note above): authoring a frame cannot falsify a claim about who consumes one."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(SKILLS.parent):
        dirnames[:] = [d for d in dirnames if d not in _SCAN_PRUNE]
        for filename in filenames:
            if not filename.endswith(".py") or filename.startswith("test_"):
                continue
            path = Path(dirpath) / filename
            rel = path.relative_to(SKILLS.parent).as_posix()
            if "/tests/" in f"/{rel}":
                continue
            try:
                tree = ast.parse(path.read_text())
            except (SyntaxError, UnicodeDecodeError):  # a vendored/py2 file is not a reader
                continue
            n = 0
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Subscript)
                    and isinstance(node.ctx, ast.Load)
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == "reference_frame"
                ):
                    n += 1
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "reference_frame"
                ):
                    n += 1
            if n:
                found[rel] = n
    return found


def test_the_reference_frame_key_has_exactly_the_declared_readers():
    found = _frame_key_readers()
    assert found, "the census found NO reader of `reference_frame` at all — the census broke, not the code"
    unexpected = sorted(set(found) - set(_REFERENCE_FRAME_KEY_READERS))
    vanished = sorted(set(_REFERENCE_FRAME_KEY_READERS) - set(found))
    assert not unexpected, (
        f"NEW consumer(s) of the `reference_frame` key: {unexpected}. Classify the role before listing it "
        "here. If it is a GATE / resolver / veto, the 'verdict-INERT' notes in evidence_salience.py are now "
        "FALSE and THOSE are what must change — adding the module here would launder a broken claim into a "
        "passing test."
    )
    assert not vanished, (
        f"declared reader(s) that no longer read the key: {vanished}. If the reach genuinely shrank, delete "
        "the entry AND retire the matching claim in evidence_salience.py; a stale entry makes this test a lie."
    )


def test_the_immune_context_reference_frame_is_a_different_token():
    """ONE TOKEN, TWO MEANINGS — pinned so the census above cannot be 'fixed' by listing a claims module.

    immune_context_claims.py owns a `_reference_frame()` helper and WRITES a `reference_frame` key onto its
    claim vector. That is a claim scalar (prose naming the comparison), NOT the SALIENCE_SPECS ruler — it
    never reads the spec key. A text-matching census lists it as a reader, and then 'no gate reads the frame'
    looks refuted by a module that has nothing to do with the frame."""
    path = SKILLS / "_skills_common" / "immune_context_claims.py"
    if not path.exists():
        pytest.skip("immune_context_claims.py absent")
    rel = path.relative_to(SKILLS.parent).as_posix()
    assert rel not in _frame_key_readers(), f"{rel} now READS the SALIENCE_SPECS reference_frame key"
    # anti-vacuity: if the token has left that file, this test proves nothing and should be DELETED, not kept
    assert "reference_frame" in path.read_text(), "the two-meanings hazard is gone — drop this test instead"


@pytest.mark.parametrize("mt", _FRAMED)
def test_every_framed_axis_reaches_display_and_the_claim_record(mt):
    """The other half of invariant 5, and the half the reader census structurally cannot see.

    The census is a claim about CODE: it stays green if every reference_frame is DELETED, because zero frames
    still means zero unexpected readers. This is a claim about the FRAMES — each must actually project,
    twice: into key_evidence.interpretation[] (the DISPLAY ruler) and back out through
    magnitude_from_interpretation (the CLAIM RECORD's magnitude). A frame that silently fails to project is
    the self-dropping SPEC'd-frame failure that has already shipped forever-green once.

    The synthetic summary feeds 0.5 to every field a frame NAMES. That is a stand-in for presence, not a
    claim about type or side: the assertion is that the frame projects at all, so a value is supplied for
    every named field (position fields included) and no assertion is made about the rendered label.

    THE PRIMARY-IDENTITY ASSERTION, WITH ITS COVERAGE MEASURED RATHER THAN ASSERTED — AND THE FIRST
    MEASUREMENT OF IT WAS WRONG, so the METHOD is recorded here and not only the number. This invariant
    exists to stop unsourced reach claims, so an unsourced claim about its OWN strength would be the same
    defect one level up. Why the assertion is right in principle: interp[0] is what
    magnitude_from_interpretation reads, and rf[0]'s value_field is what mints the atlas column, so an
    axis's headline gauge, its frozen coordinate and its claim record must name ONE metric.
    The population it can EVER discriminate on is derivable from the specs rather than from any single
    mutation: the 7 axes whose frames do not all gauge the same value_field — cell_line_protein_abundance,
    cell_line_rna_expression, copy_number_alteration, mutation_variant_class_spectrum,
    tumor_expression_distribution, tumor_protein_abundance, tumor_vs_adjacent_expression. On the other 28
    every frame gauges ONE value (a distance_to_cut plus a percentile companion on that same value), so no
    permutation whatsoever can change interp[0].metric and the assertion has nothing to discriminate.
    Measured: rotating build_interpretation's projection by one — specs untouched, so only ONE side of the
    comparison moves — reds 7 of 35, exactly that set.
    ★ The trap, recorded because the number it produced was already written down once: REVERSING the
    projection reds only 1 (mutation_variant_class_spectrum), and that 1 was first recorded here as the
    assertion's coverage. Reversal maps position 0 to position -1, and on 6 of those 7 axes the FIRST and
    LAST frames carry the SAME value_field, because the companion loop appends a percentile frame gauging
    the primary's own value. A palindromic list is invariant under reversal. So the 1 measured the PROBE's
    power, not the ASSERTION's. One permutation is not a panel, and a mutation that comes back GREEN can
    mean the probe is too weak to move the thing it aims at.
    The weaker sibling is bounded the same way: dropping rf[0] fleet-wide reds only the 2 single-frame axes
    (alteration_role, immune_context), because this test re-reads the mutated spec, so both sides of the
    comparison move together. "interp is non-empty" really is too weak on its own."""
    summary = {}
    frames = _frames(mt)
    for rf in frames:
        for key in ("value_field", "distance_field", "position_field", "total_field"):
            if rf.get(key):
                summary[rf[key]] = 0.5
        for anchor in rf.get("anchors") or []:
            if isinstance(anchor, dict) and anchor.get("field"):
                summary[anchor["field"]] = 0.5
    interp = build_interpretation({}, summary, SALIENCE_SPECS[mt], numeric_source_cards().get(mt), None)
    if not interp and not (target_contracts_root() / "cards").is_dir():
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    assert interp, f"{mt}: a framed axis projected NOTHING into the display ruler"
    assert interp[0].get("metric") == frames[0].get("value_field"), (
        f"{mt}: the FIRST projected gauge is {interp[0].get('metric')!r}, not the primary frame's "
        f"{frames[0].get('value_field')!r} — the claim record's magnitude and the atlas column would name "
        "different metrics for this axis"
    )
    magnitude = magnitude_from_interpretation(interp[0])
    assert magnitude and magnitude.get("value") is not None and magnitude.get("scale"), (
        f"{mt}: the display gauge does not round-trip into the claim record's magnitude: {magnitude!r}"
    )


def test_the_atlas_numeric_optout_is_exactly_the_declared_set():
    """`atlas_numeric: False` is the REAL display-only boundary, and it is a one-way door with no red.

    A frame carrying the flag mints no atlas numeric, so ADDING it to a shipped axis DELETES a frozen column
    at the next re-freeze — and atlas_health compares the artifact against itself, so it reads a
    self-consistent narrowing as green. This ratchet is the only thing that notices. It is two-sided AND
    exhaustive (framed == minted | optout, zero residual), so a third state — framed, unminted, undeclared —
    cannot appear without a red."""
    framed = set(_FRAMED)
    minted = set(numeric_feature_specs())
    assert minted, "numeric_feature_specs() minted NOTHING — the instrument broke, not the specs"
    assert minted <= framed, f"atlas columns minted from axes with no reference_frame: {sorted(minted - framed)}"
    optout = set(_ATLAS_NUMERIC_OPTOUT)
    undeclared = sorted(framed - minted - optout)
    stale = sorted(optout & minted)
    unframed_optout = sorted(optout - framed)
    assert not undeclared, (
        f"framed axes that mint no atlas column and declare no reason: {undeclared}. Either the frame is "
        "genuinely display-only (list it above WITH the reason) or a shipped column just went missing."
    )
    assert not stale, f"declared opt-outs that DO mint an atlas column — remove them above: {stale}"
    assert not unframed_optout, f"declared opt-outs for axes with no frame at all: {unframed_optout}"
    assert framed == minted | optout, f"unclassified residual: {sorted(framed ^ (minted | optout))}"


# ── invariant 5d: the SHIPPED atlas is the second authority, because deleting a frame deletes a TEST ─────
# A MEASURED HOLE in the four checks above, closed here rather than argued away. Removing one axis's
# `reference_frame` — which silently deletes a FROZEN atlas column — took this file from 148 collected to
# 144 and reported SUCCESS. Two independent reasons, both structural:
#   * the reach test is PARAMETRIZED over the framed set, so deleting a frame does not fail a test, it
#     deletes four. A vanishing test is invisible in a pass count; only `collected N` moves.
#   * `framed == minted | optout` still balances, because deleting a frame shrinks BOTH sides at once.
# Every check above derives its population from SALIENCE_SPECS, so all of them are blind in that one
# direction by construction. The only fix is a population the specs cannot move.
#
# That population is skills/target-archetype/atlas/atlas.json — the SHIPPED artifact. Each `::num::` column
# in it was minted by a primary frame that existed when the atlas was frozen, so it is a durable record of
# PAST reach that today's source still has to account for. This is the same instrument the aperture ratchet
# uses: an external number the code under test cannot rewrite to agree with itself.
#
# EQUALITY, not containment, because the two directions are different failures and both are re-freeze terms:
#   frozen column with no producing frame -> a silent DELETION at the next re-freeze. atlas_health compares
#     the artifact against itself, so it reads a self-consistent narrowing as green; nothing else notices.
#   column in the specs with no frozen twin -> the set does NOT carry its own cause, and TWO reach it:
#     (a) a primary frame was ADDED since the freeze -> a silent ADDITION that changes the feature space,
#         moving every shipped cohort_percentile the moment someone rebuilds; or
#     (b) the specs never moved and the ARTIFACT narrowed -> `build_atlas.py:649` keeps a column only when
#         >= 2 targets measured it, so a column whose support fell below 2 was DROPPED at build time, its
#         `::mask` companion with it (:656). PRECEDENT, not hypothesis: that mechanism shipped an orphan
#         mask in the 2026-09-12 freeze. Neither case leaves a trace in `feature_order`, which is why the
#         `added` message reads `meta.n_features_dropped_sparse` rather than asserting one of the two.
# A RENAMED value_field is caught by the same map: the column key is `{mt}::num::{value_field}`, so renaming
# the field renames a frozen column, which is a delete plus an add wearing one commit.
#
# The path single-sources from archetype_core._SHIPPED_ATLAS. Invariant 4 above refuses a re-hardcoded
# threshold for exactly this reason, and a second copy of this path would be the same defect.
# DELIBERATELY NOT A SKIP when the artifact is missing: it is tracked in git, so absent means broken
# checkout, and skipping would restore the green-for-the-wrong-reason this whole invariant exists to remove.
@lru_cache(maxsize=1)
def _frozen_atlas_numeric_columns() -> dict:
    """{measurement_type: value_field} for every ::num:: column in the SHIPPED atlas.

    Columns are `{mt}::num::{value_field}` with a `::mask` companion alongside each one. The mask is dropped:
    it is minted from the same frame and carries no independent frame identity, so counting it would double
    every axis and tell us nothing the value column does not."""
    atlas = json.loads(_SHIPPED_ATLAS.read_text())
    frozen = {}
    for column in atlas["feature_order"]:
        parts = column.split("::")
        if len(parts) < 3 or parts[1] != "num" or parts[-1] == "mask":
            continue
        frozen[parts[0]] = parts[2]
    return frozen


@lru_cache(maxsize=1)
def _frozen_atlas_build_drop_count():
    """`meta.n_features_dropped_sparse` — how many CANDIDATE columns the builder removed when it froze this
    artifact (`build_atlas.py:657` = `len(cand) - len(feature_order)`), or None on an artifact predating it.

    Read ONLY from inside a failure message, which is why it is a second parse and not folded into the map
    above: `assert cond, msg` evaluates `msg` lazily, so the green path never pays for this and a missing
    field can never turn a pass into an error. Nothing else in the repo asserts this value — the per-`meta`
    key sha in atlas_freeze.json is re-written by `atlas_stability.py --write` at an intended re-freeze, so
    it moves WITH a change instead of catching it."""
    return json.loads(_SHIPPED_ATLAS.read_text()).get("meta", {}).get("n_features_dropped_sparse")


def test_every_frozen_atlas_numeric_column_still_has_its_producing_frame():
    # target-archetype/atlas DEFERRED as WIP 2026-09-16: when the skill's SKILL.md is renamed away, the
    # frozen atlas is intentionally STALE (not being re-frozen), so the frozen-column <-> live-frame
    # equality below would force an atlas re-freeze on ANY numeric-ruler change — the exact treadmill
    # the deferral removes. Skip while deferred; re-enable automatically when SKILL.md is restored (the
    # skill is un-deferred and re-frozen). The atlas artifact itself stays in git, so the OTHER
    # invariants in this file (specs-internal) keep running and go-live output is unchanged.
    if not (SKILLS / "target-archetype" / "SKILL.md").exists():
        pytest.skip(
            "target-archetype/atlas deferred (SKILL.md renamed) — frozen-vs-live column equality would "
            "force a re-freeze on any ruler change; re-enable when the skill is un-deferred and re-frozen"
        )
    assert _SHIPPED_ATLAS.is_file(), (
        f"the shipped atlas is missing at {_SHIPPED_ATLAS} — it is tracked in git, so this is a broken "
        "checkout. Fix the checkout; do NOT turn this into a skip."
    )
    frozen = _frozen_atlas_numeric_columns()
    assert frozen, "parsed ZERO ::num:: columns out of the shipped atlas — the parser broke, not the atlas"
    live = {mt: spec[0] for mt, spec in numeric_feature_specs().items()}
    assert live, "numeric_feature_specs() minted NOTHING — the instrument broke, not the specs"
    orphaned = sorted(mt for mt in frozen if mt not in live)
    added = sorted(mt for mt in live if mt not in frozen)
    renamed = {mt: (frozen[mt], live[mt]) for mt in sorted(set(frozen) & set(live)) if frozen[mt] != live[mt]}
    assert not orphaned, (
        f"FROZEN atlas ::num:: column(s) whose producing frame is gone from SALIENCE_SPECS: {orphaned}. The "
        "next re-freeze DROPS those columns and every cohort_percentile computed from them, with no other "
        "red anywhere. If the removal is intended it is a re-freeze term: bundle it, do not slip it in."
    )
    assert not added, (
        f"axes minting an atlas ::num:: column that the shipped atlas does not carry: {added}. TWO causes "
        "reach this set and it cannot tell them apart. (a) A primary frame was ADDED since the freeze, so "
        "the next re-freeze ADDS a column and moves the whole feature space. (b) The specs never moved and "
        "the ARTIFACT narrowed: build_atlas.py:649 keeps a column only when >= 2 targets measured it, so a "
        "column whose support fell below 2 was DROPPED at build time, its ::mask companion with it (:656). "
        f"One-way test from the artifact: n_features_dropped_sparse={_frozen_atlas_build_drop_count()!r}, "
        "and 0 means every name above is case (a). Nonzero only NARROWS — that count spans the ::claim:: "
        "namespace too and folds in the mask-dedup, so it cannot attribute a drop to one measurement_type; "
        "for that, count non-null values per key over the packages the way build_atlas.py:649 does. Both "
        "cases are re-freeze terms: route (a) to the bundle, and for (b) DECLARE the loss (drop the frame, "
        "or atlas_numeric: False) rather than letting the column go silently."
    )
    assert not renamed, (
        f"primary value_field RENAMED under a frozen column ({{mt: (frozen, live)}}): {renamed}. The column "
        "key is {mt}::num::{value_field}, so this is a delete AND an add in one commit."
    )


def test_shet_lof_selection_direction_sign():
    """Sign guard for the descriptor-coverage mint (DIRECTION is the highest-consequence token — an
    inverted sign would read a dominant-LoF-CONSTRAINED gene as SAFE for a full-KO modality). Higher
    s_het = more intolerant = WORSE, and the graded_band cuts must ascend moderate(0.01) -> high(0.1)."""
    spec = SALIENCE_SPECS["shet_lof_selection"]
    assert spec["direction"] == "higher_is_worse"
    frame = spec["reference_frame"]
    assert frame["kind"] == "graded_band" and frame.get("atlas_numeric") is False
    assert [c["label"] for c in frame["cuts"]] == ["moderate_intolerance", "high_intolerance"]


def test_spatial_til_fraction_direction_sign():
    """Sign guard: higher TIL fraction = MORE immune infiltration = a STRONGER immune/TCE-effector
    signal (the card calls til_high 'strongly infiltrated'). This is a display value, not a liability,
    so higher_is_stronger (NOT higher_is_worse). Cuts ascend intermediate(2.0) -> high(5.0)."""
    spec = SALIENCE_SPECS["spatial_til_fraction"]
    assert spec["direction"] == "higher_is_stronger"
    frame = spec["reference_frame"]
    assert frame["kind"] == "graded_band" and frame.get("atlas_numeric") is False
    assert [c["label"] for c in frame["cuts"]] == ["til_intermediate", "til_high"]


def test_surface_confirmation_is_categorical_only():
    """surface_confirmation has no single-sourced numeric cut, so the CLASS is the ruler: a categorical +
    n_field spec with NO reference_frame (mirrors normal_tissue_protein_breadth) — invariant 1 is satisfied
    by the non-empty categorical, and it mints no atlas column."""
    spec = SALIENCE_SPECS["surface_confirmation"]
    assert "reference_frame" not in spec
    assert spec["categorical"] and "surface_confirmation_class" in spec["categorical"]
