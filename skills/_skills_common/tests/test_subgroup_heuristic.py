"""Default heuristic reader + subgroup_signals_for — so fleet wiring needs no per-skill reader spec.
The heuristic picks the primary signal field (*_class, else signal-keyword string) + n fields; the
convenience helper loads a skill's question_hierarchy.yaml and derives pooled + stratified in one call."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT
from _skills_common.subgroup_derivation import (  # noqa: E402
    _TIERS,
    _TIERV,
    UNMEASURED,
    _heuristic_reader,
    default_classify,
    derive_subgroups,
    is_measured,
    make_value_classifier,
    subgroup_signals_for,
)


def _contracts_absent():
    root = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
    return not (root / "cards").is_dir()


def test_heuristic_picks_class_field():
    r = _heuristic_reader({"tumor_expression_class": "broadly_high", "n_tumor_samples": 669, "median_log2tpm": 9.6})
    assert r["class"] == "tumor_expression_class" and "n_tumor_samples" in r["n"]


def test_heuristic_picks_keyword_field_when_no_class():
    # concordance card's signal field has no _class suffix — caught by the signal-keyword fallback
    r = _heuristic_reader({"rna_as_biomarker": "adequate_proxy", "n_paired_models": 370})
    assert r["class"] == "rna_as_biomarker" and "n_paired_models" in r["n"]


def test_heuristic_none_when_no_signal_field():
    assert _heuristic_reader({"method_version": "1.0", "target": "X"}) is None


# ── make_value_classifier: per-skill value→tier map (fixes lens-blind default polarity) ──────────────
def test_value_classifier_maps_explicit_tiers():
    clf = make_value_classifier(
        {
            "concordant_dependent": "strong",
            "broad_organoid_dependency": "strong",
            "moderately_concordant_non_dependent": "weak",
        }
    )
    # default_classify flips these positives to 'absent'; the map restores correct polarity
    assert default_classify("concordant_dependent") == "absent"
    assert clf("concordant_dependent") == "strong"
    assert clf("broad_organoid_dependency") == "strong"
    assert clf("moderately_concordant_non_dependent") == "weak"


def test_value_classifier_falls_back_to_default_for_unmapped():
    clf = make_value_classifier({"concordant_dependent": "strong"})
    # an unmapped value degrades to the token heuristic, NOT silently to 'absent'
    assert clf("broadly_high") == default_classify("broadly_high") == "strong"
    assert clf("sparse") == "weak"
    # A MISSING value is an abstention, not a measured absence. This asserted `absent` until the off-axis
    # `unmeasured` tier existed, which made "no value to read" and "read as no signal" the same output.
    assert clf(None) == "unmeasured"


def test_value_classifier_case_insensitive_and_bad_tier_ignored():
    clf = make_value_classifier({"Strongly_Selective": "strong", "x": "bogus_tier"})
    assert clf("strongly_selective") == "strong"  # case-normalized
    assert clf("x") == default_classify("x")  # unknown tier ignored → default


# ── confidence-only skip sentinel: a falsy reader_spec entry drops a caveat card from the signal ─────
def _cards_two_mts():
    # two cards; the heuristic would read both — one is a magnitude source, one a caveat.
    return [
        {"card_id": "dep", "summary": {"dependency_class": "strongly_selective", "n_cell_lines": 900}},
        {"card_id": "buf", "summary": {"buffering_class": "strong", "n": 12}},
    ]


def test_confidence_only_card_skipped_via_falsy_spec(monkeypatch):
    import _skills_common.subgroup_derivation as SD

    monkeypatch.setattr(
        SD, "_card_meta", lambda cid: {"dep": ("dep_mt", None), "buf": ("buf_mt", "target")}.get(cid, (None, None))
    )
    hier = {"sub_groups": [{"id": "DEP", "questions": [{"measurement_types": ["dep_mt", "buf_mt"]}]}]}
    clf = make_value_classifier({"strongly_selective": "strong"})
    # buf_mt marked confidence-only (None) → not a source; dep_mt reads via heuristic
    out = derive_subgroups(hier, _cards_two_mts(), {"buf_mt": None}, clf)
    cards_in = {s["card"] for s in out["DEP"]["sources"]}
    assert cards_in == {"dep"}, f"buffering caveat should be skipped, got {cards_in}"
    assert out["DEP"]["signal"] == "strong"


# ── n-selection mis-bind fixes (bugs 2/3/4): prefer sample-size, deny feature counts, catch ligands ──
def test_n_selection_prefers_sample_size_over_strata_count():
    # bug 4: n_admissible_strata(=14) must NOT outrank n_patients(=1796)
    r = _heuristic_reader(
        {
            "subtype_survival_association_class": "subtype_stratifies_survival",
            "n_admissible_strata": 14,
            "n_events": 319,
            "n_patients": 1796,
        }
    )
    assert r["n"][0] == "n_patients"  # true cohort size chosen first
    assert "n_admissible_strata" not in r["n"]  # feature count denied entirely


def test_n_selection_denies_alphafold_disorder_metric():
    # bug 3: n_domains_low_plddt(=6) is an AlphaFold disorder count, not PDB coverage — never a sample size
    r = _heuristic_reader({"structure_features_class": "high", "n_domains_low_plddt": 6, "n_ligandability_axes": 4})
    assert r["n"] == []  # both denied → honest n=None downstream


def test_n_selection_catches_ligand_count():
    # bug 2: chembl_n_potent_ligands has a mid-token _n_ that the old regex missed
    r = _heuristic_reader(
        {
            "potency_class": "potent_measured_ligand",
            "chembl_n_potent_ligands": 8619,
            "bindingdb_n_potent_ligands": 11644,
        }
    )
    assert set(r["n"]) == {"chembl_n_potent_ligands", "bindingdb_n_potent_ligands"}


def test_dedup_byte_identical_provenance(monkeypatch):
    # bug 7: two cards, same _data_source + same value = ONE measurement, not two agreeing sources
    import _skills_common.subgroup_derivation as SD

    monkeypatch.setattr(SD, "_card_meta", lambda cid: {"a": ("mt_a", None), "b": ("mt_b", None)}.get(cid, (None, None)))
    hier = {"sub_groups": [{"id": "FUS", "questions": [{"measurement_types": ["mt_a", "mt_b"]}]}]}
    cards = [
        {"card_id": "a", "summary": {"x_class": "tumor_shifted", "_data_source": "tcga-spliceseq"}},
        {"card_id": "b", "summary": {"x_class": "tumor_shifted", "_data_source": "tcga-spliceseq"}},
    ]
    out = derive_subgroups(hier, cards, None)
    assert out["FUS"]["n_sources"] == 1  # deduped (byte-identical provenance+value)


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")
def test_signals_for_derives_reader_spec_free():
    """subgroup_signals_for on presence's hierarchy + EPCAM cards, WITHOUT an explicit reader spec
    (pure heuristic) — proves fleet wiring is reader-spec-free."""
    fix = SKILLS / "tumor-presence/tests/fixtures/epcam_coadread.yaml"
    frozen = yaml.safe_load(fix.read_text()) or {}
    cards = [{"card_id": k, "summary": v} for k, v in frozen.items() if isinstance(v, dict)]
    sg = subgroup_signals_for(SKILLS / "tumor-presence", cards)  # no reader_spec => heuristic
    assert set(sg) >= {"abundance", "malignant_intrinsic", "generality"}, f"got {set(sg)}"
    assert sg["abundance"]["signal"] == "strong"
    assert any(s["card"] == "cellline-protein-abundance-procan" for s in sg["abundance"]["sources"])


# ── THE ABSTENTION TIER: a source that did not measure must not vote, rank, or disagree ────────────
# Before `unmeasured` existed the only home for a non-measurement was `absent`, so "we could not look"
# and "we looked and found nothing" produced identical output. These pin each of the four consumption
# sites that had to decide explicitly what an abstention means.
def _hier_two():
    return {"sub_groups": [{"id": "SG", "questions": [{"measurement_types": ["mt_a", "mt_b"]}]}]}


def _patch_meta(monkeypatch, tiers=None):
    import _skills_common.subgroup_derivation as SD

    m = tiers or {"a": ("mt_a", None), "b": ("mt_b", None)}
    monkeypatch.setattr(SD, "_card_meta", lambda cid: m.get(cid, (None, None)))


def test_the_abstention_is_off_the_presence_ordinal_not_a_fifth_rung():
    """A NUMBER for `unmeasured` would be worse than the bug it fixes: the ordinal is consumed as a
    DISTANCE too (evidence_capsule flags a >=2 tier spread as a cross-card conflict), so any value —
    including a below-`absent` -1 — turns every coverage gap into a fabricated contradiction."""
    assert UNMEASURED not in _TIERV, "must not be rankable"
    assert UNMEASURED in _TIERS, "...but must be a valid tier"
    assert not is_measured(UNMEASURED)
    assert all(is_measured(t) for t in _TIERV)


def test_a_non_measurement_token_no_longer_reads_as_a_measured_negative():
    """default_classify checked its presence substrings first and fell through to `absent`, so a coverage
    gap was indistinguishable from a measured zero. The abstention family is checked FIRST now."""
    for tok in ("data_unavailable", "not_measured", "no_data", "not_assessed", "lymphoid_denominator_unreliable"):
        assert default_classify(tok) == UNMEASURED, tok
    assert default_classify(None) == UNMEASURED
    # ...and a MEASURED negative is still a measured negative — the distinction is the whole point.
    assert default_classify("immune_desert") == "absent"
    assert default_classify("no_high_confidence_interactors") == "absent"


def test_indeterminate_is_not_swept_into_the_abstention_family():
    """`indeterminate` / `insufficient` are MEASURED-but-inconclusive: the measurement happened and did
    not resolve. Calling those unmeasured would overstate how much coverage is missing."""
    assert default_classify("indeterminate") != UNMEASURED
    assert default_classify("insufficient") != UNMEASURED


def test_an_abstaining_source_leaves_the_agreement_denominator(monkeypatch):
    """The bug this closes: 1 strong + 1 unread card scored "1 of 2 agree", which reads as one source
    DISAGREEING when it never spoke — a coverage gap silently demoted to weak evidence."""
    _patch_meta(monkeypatch)
    cards = [
        {"card_id": "a", "summary": {"x_class": "broadly_high", "n_samples": 500}},
        {"card_id": "b", "summary": {"x_class": "data_unavailable"}},
    ]
    out = derive_subgroups(_hier_two(), cards, None)["SG"]
    assert out["signal"] == "strong"  # the measured read is the signal
    assert out["n_sources"] == 1 and out["n_agree"] == 1  # the abstention is out of BOTH
    assert out["n_unmeasured"] == 1  # ...but VISIBLE, not silently dropped
    assert len(out["sources"]) == 2  # the source list still shows the card that abstained


def test_an_abstention_never_outranks_a_measured_absence(monkeypatch):
    """`unmeasured` sorted below `absent` would make the non-measurement the sub-group's signal whenever
    it was the only read; sorted above, it would mask a real negative. It does neither — it is not ranked."""
    _patch_meta(monkeypatch)
    cards = [
        {"card_id": "a", "summary": {"x_class": "immune_desert"}},  # a MEASURED absence
        {"card_id": "b", "summary": {"x_class": "data_unavailable"}},
    ]
    assert derive_subgroups(_hier_two(), cards, None)["SG"]["signal"] == "absent"


def test_a_subgroup_whose_every_source_abstained_reports_unmeasured_not_absent(monkeypatch):
    """The headline case: an axis nothing could read now SAYS so, instead of claiming a measured zero."""
    _patch_meta(monkeypatch)
    cards = [
        {"card_id": "a", "summary": {"x_class": "data_unavailable"}},
        {"card_id": "b", "summary": {"x_class": "not_measured"}},
    ]
    out = derive_subgroups(_hier_two(), cards, None)["SG"]
    assert out["signal"] == UNMEASURED
    assert out["n_sources"] == 0 and out["n_unmeasured"] == 2
    assert out["confidence"] == "low"  # nothing measured cannot be high confidence


def test_a_held_out_source_cannot_leave_a_lone_card_reading_high_confidence(monkeypatch):
    """Holding abstentions out of the denominator must not INVERT into over-confidence: 1-of-3 unanimity
    is not `high`. Without this cap, removing the unread cards would make a thin panel look unanimous."""
    _patch_meta(monkeypatch, {"a": ("mt_a", None), "b": ("mt_b", None), "c": ("mt_c", None)})
    hier = {"sub_groups": [{"id": "SG", "questions": [{"measurement_types": ["mt_a", "mt_b", "mt_c"]}]}]}
    cards = [
        {"card_id": "a", "summary": {"x_class": "broadly_high", "n_samples": 5000}},
        {"card_id": "b", "summary": {"x_class": "data_unavailable"}},
        {"card_id": "c", "summary": {"x_class": "data_unavailable"}},
    ]
    out = derive_subgroups(hier, cards, None)["SG"]
    assert out["signal"] == "strong" and out["n_unmeasured"] == 2
    assert out["confidence"] == "moderate", "1-of-3 measured is not high confidence"
