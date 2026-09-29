"""L1 units are FIRST-CLASS on every emitted measurement value (Arm A gap 1, #1860).

Before this, a capsule `numeric_anchors` entry was `{metric, value}` — a BARE scalar whose unit lived only
in the metric NAME (`_log2tpm`, `_percentile`, `_qvalue`), so a consumer had to know the naming convention
to interpret the number. First-class units existed but un-wired, in the `evidence_salience` reference-frame
rulers (`{value, scale, …}` where `scale` is the unit). This wires that ruler scale onto each emitted anchor
and enforces the claim_record schema's no-bare-numbers invariant at the capsule grain.

The fix is a PATTERN fix in `_skills_common` (every axis's capsules), not tumor-presence only — the tests
below exercise a genomic axis (copy_number) alongside the tumor-presence axes to prove it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import display_gloss as DG  # noqa: E402
from _skills_common import evidence_capsule as EC  # noqa: E402
from _skills_common.evidence_salience import (  # noqa: E402
    _SCALE_ALIASES,
    SCALE_UNITS,
    canonical_scale,
    scale_for_field,
)


# ── the ruler is the first-class unit source ────────────────────────────────────────────────────────
def test_scale_for_field_reads_the_ruler_scale():
    """The un-wired first-class unit: a reference-frame `value_field` → its `scale` token, canonicalised."""
    # #2017: the ruler spelling is `log2FC`; the emitted machine unit is the single governed
    # `log2_fold_change` (one SPELLING collapse onto SCALE_UNITS — verdict-inert).
    assert scale_for_field("tumor_vs_adjacent_expression", "log2_fc") == "log2_fold_change"
    assert scale_for_field("cell_line_protein_abundance", "median_log2_abundance_panel") == "log2_abundance"
    assert scale_for_field("tumor_protein_abundance", "protein_effect_cohens_d") == "cohens_d"
    assert scale_for_field("sc_tumor_celltype_expression", "malignant_detection_fraction") == "detection_fraction"


def test_scale_for_field_reaches_secondary_and_anchor_fields():
    """A frame's ANCHOR fields (floor/ceiling/comparator) share the value's unit, and a SECONDARY frame's
    value_field (the allgene percentile companion) is scaled too — not just the primary."""
    assert scale_for_field("cell_line_protein_abundance", "p5_log2_abundance_panel") == "log2_abundance"
    assert scale_for_field("cell_line_protein_abundance", "allgene_percentile") == "percentile"
    # a comparator anchor on the single-cell delta frame
    assert scale_for_field("sc_tumor_celltype_expression", "top_microenvironment_detection_fraction") == (
        "detection_fraction"
    )


def test_scale_for_field_is_none_off_ruler_and_on_bad_input():
    assert scale_for_field("tumor_vs_adjacent_expression", "gtex_q_value") is None  # not a frame field
    assert scale_for_field("no_such_measurement_type", "log2_fc") is None
    assert scale_for_field(None, "log2_fc") is None
    assert scale_for_field("tumor_vs_adjacent_expression", None) is None


# ── the backstop layering: ruler → display-gloss units → explicit null ────────────────────────────────
def test_scale_resolution_prefers_ruler_then_gloss_then_explicit_null():
    """_scale_for is the 3-layer resolver the emitter uses."""
    # 1. ruler wins even where gloss also has an (affix) opinion
    assert EC._scale_for("cell_line_protein_abundance", "median_log2_abundance_panel") == "log2_abundance"
    # 2. gloss backstop for the L3 tail the rulers do not reach (a fraction / q-value)
    assert EC._scale_for("tumor_vs_adjacent_expression", "gtex_q_value") == "q"
    assert EC._scale_for("rna_protein_concordance", "rna_expressed_fraction") == "fraction"
    # 3. explicit null for the genuinely-unitless residual (gloss leaves a median_* effect unitless) —
    #    NOT an error: the unit slot is still emitted, honestly declared not-yet-first-class.
    assert EC._scale_for("tumor_elevation_breadth", "median_effect_across_elevated") is None


# ── every emitted anchor carries a scale SLOT (the pattern fix, all axes) ──────────────────────────────
def _cn_card():
    # a GENOMIC axis card (copy_number), to prove this is a _skills_common pattern fix, not tumor-presence.
    return [
        {
            "card_id": "copy-number-distribution",
            "summary": {
                "copy_number_class": "recurrently_deleted",
                "cn_recurrent_deletion_score": 0.2016,
                "cn_fraction_deep_deletion": 0.0402,
                "n_samples": 1084,
            },
        }
    ]


def test_emitted_numeric_anchors_all_carry_a_scale_key():
    caps = EC.emit_capsules(_cn_card(), "CML")["capsules"]["copy-number-distribution"]
    anchors = caps["numeric_anchors"] or []
    assert anchors, "anti-vacuity: the genomic card must emit numeric_anchors"
    for a in anchors:
        assert "scale" in a, f"{a['metric']} emitted as a BARE number — no scale slot"
        # + "provenance" since #1862 (value-grain provenance tuple); scale + value are the units concern here.
        assert set(a) == {"metric", "value", "scale", "provenance"}


def test_scale_addition_is_verdict_inert_metric_and_value_unchanged():
    """Additive: the metric/value pair a consumer already reads is byte-for-byte what it was; only the new
    scale slot is added."""
    anchors = EC._numeric_anchors(
        _cn_card()[0]["summary"], cfg={}, contract_anchors=("cn_recurrent_deletion_score",), measurement_type=None
    )
    assert len(anchors) == 1
    a = anchors[0]
    # the metric/value pair a consumer already reads is byte-for-byte unchanged; only a scale slot is added.
    assert a["metric"] == "cn_recurrent_deletion_score" and a["value"] == 0.2016
    assert set(a) == {"metric", "value", "scale", "provenance"}  # + provenance since #1862 (additive)


# ── the no-bare-numbers invariant, at capsule grain ───────────────────────────────────────────────────
def test_assert_no_bare_numbers_refuses_a_value_without_a_scale_slot():
    """The MUTATION: a number emitted with NO scale key is a bare number and must be refused — the capsule
    form of the claim_record schema invariant (value non-null ⇒ a declared unit)."""
    with pytest.raises(ValueError, match="no bare numbers"):
        EC.assert_no_bare_numbers([{"metric": "median_log2tpm", "value": 9.62}])


def test_assert_no_bare_numbers_admits_a_declared_unit_and_an_explicit_null():
    """A resolved scale passes; so does an EXPLICIT null (the unit slot is declared, just not-yet-first-class
    for that field) — that is the honest state, distinct from a silently bare number. A null VALUE needs no
    scale."""
    ok = [
        {"metric": "log2_fc", "value": -0.362, "scale": "log2FC"},
        {"metric": "median_effect_across_elevated", "value": 1.0234, "scale": None},
        {"metric": "absent_field", "value": None},
    ]
    assert EC.assert_no_bare_numbers(ok) is ok  # returns unchanged so it can wrap an emission


def test_emit_capsules_output_passes_the_bare_number_guard():
    """End-to-end: the real emitter never produces a bare number for any axis."""
    caps = EC.emit_capsules(_cn_card(), "CML")["capsules"]
    for c in caps.values():
        EC.assert_no_bare_numbers(c.get("numeric_anchors") or [])


# ── #2017: the scale/unit token is GOVERNED by a controlled vocabulary ────────────────────────────────
# #1860 gave the emitted anchor a `scale` SLOT but left the token free-form: the same unit reached it under
# several spellings (`percentile`/`%ile`, `log2FC`/`log2tpm`/`log2 TPM`) and spaced display pseudo-units
# (`effect size`, `correlation r`). SCALE_UNITS is now the single source-of-truth vocabulary; every emitted
# numeric-anchor / retained-attr scale must be one of its (space-free) members. These are the MUTATION
# TEETH: RED before the fix (an emitted `effect size` / `%ile` has a space and is ∉ SCALE_UNITS).


def test_scale_units_vocabulary_is_self_consistent():
    """The enum is space-free and every alias resolves INTO it; canonicalisation is idempotent."""
    assert all(" " not in u for u in SCALE_UNITS), "a SCALE_UNITS member carries a space"
    for raw, canon in _SCALE_ALIASES.items():
        assert canon in SCALE_UNITS, f"alias {raw!r} → {canon!r} which is not a SCALE_UNITS member"
        assert " " not in canon
        assert canonical_scale(canon) == canon, f"canonical_scale is not idempotent on {canon!r}"
    assert canonical_scale(None) is None and canonical_scale("") is None


def test_every_gloss_units_hint_canonicalises_into_the_enum():
    """MUTATION TEETH on the display-gloss fallback source: `_scale_for(None, field)` bypasses the ruler
    and returns the (canonicalised) gloss units hint. Pre-#2017 this passed the raw display string through,
    so `protein_effect_size` → 'effect size' (a SPACE, ∉ enum) reached the machine `scale`. Every unit the
    METRIC_GLOSS registry can hand the emitter must now be a space-free SCALE_UNITS member."""
    checked = 0
    for field in DG.METRIC_GLOSS:
        s = EC._scale_for(None, field)  # measurement_type=None ⇒ pure gloss-fallback path
        if s is None:
            continue
        checked += 1
        assert " " not in s, f"{field}: emitted scale {s!r} carries a space"
        assert s in SCALE_UNITS, f"{field}: emitted scale {s!r} is not in the SCALE_UNITS vocabulary"
    assert checked > 20, "anti-vacuity: the gloss registry must exercise many units"


def _iter_emitted_scales(obj):
    """Every `scale` on the `_scale_for` emission surface — numeric_anchors + retained_attrs lists — walked
    recursively. Deliberately NOT every `scale` key: the L2 interpretation `gauged_value.scale` is a
    separate surface (raw ruler token, out of #2017 scope) and must not be swept in here."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("numeric_anchors", "retained_attrs") and isinstance(v, list):
                for a in v:
                    if isinstance(a, dict) and "scale" in a:
                        yield a["scale"]
            yield from _iter_emitted_scales(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_emitted_scales(v)


@pytest.mark.parametrize(
    "golden_rel",
    [
        "tumor-presence/tests/fixtures/epcam_coadread_decision.json",
        "target-intrinsic/tests/fixtures/target_intrinsic_egfr_full_decision.json",
    ],
)
def test_committed_goldens_emit_only_governed_scale_tokens(golden_rel):
    """Whole-corpus teeth: every scale on the emission surface of a committed decision golden is a
    space-free SCALE_UNITS member. RED pre-#2017 on the `%ile` / `effect size` / `correlation r` /
    `log2 TPM` / `pChEMBL` tokens these goldens carried."""
    import json

    golden = json.loads((SKILLS / golden_rel).read_text())
    scales = [s for s in _iter_emitted_scales(golden) if s is not None]
    assert scales, f"anti-vacuity: {golden_rel} carries no emitted scale tokens"
    offending = sorted({s for s in scales if " " in str(s) or s not in SCALE_UNITS})
    assert not offending, f"{golden_rel} emits ungoverned scale tokens: {offending}"
