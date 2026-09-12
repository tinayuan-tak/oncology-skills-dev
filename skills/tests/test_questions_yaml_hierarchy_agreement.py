"""Fleet guard: every skill's hand-maintained questions.yaml agrees with its generated question_hierarchy.

Two files decide which axis a measurement_type belongs to, and BOTH are read by the same layer:

  * `<skill>/question_hierarchy.yaml` — a GENERATED mirror of the governed contracts source
    (`vocabularies/target_profiling_axes.yaml` `question_hierarchies`). Read by `derive_subgroups`, so it
    decides what `subgroup_signals` SCORES per axis.
  * `<skill>/questions.yaml` — hand-maintained. Read by `evidence_graph.build_evidence_graph`, so it
    decides what the dashboard DISPLAYS per question, and it is what the literature axis crosswalk
    resolves against.

When they disagree, a card is scored under one axis and displayed under another **in the same published
artifact**, and nothing fails. That is not hypothetical: on the KRAS-COADREAD run,
`genomic-alteration-profile` listed `mutation_stratified_dependency` + `mutation_drug_response` under
`snv_indel_class`, so `evidence_graph.questions` showed the SNV row drawing on 13 cards while
`subgroup_signals` scored SNV from 8 and put those two under DEP. The display and the claim contradicted
each other, silently, because this seam had no test.

`test_question_hierarchy_drift.py` guards the mirror against the governed SOURCE. It says nothing about
questions.yaml. `cis-feature-coherence/tests/test_questions_hierarchy_agreement.py` closed the gap for ONE
skill, found the same way (an `amp_expr_stratified_dependency` mis-routing). This test generalises that
precedent to the whole fleet, which is what makes it able to fail for a skill nobody is currently reviewing.

The comparison is BY AXIS and order-insensitive, and unions the hierarchy's `context_types` into its axis:
`context_types` are contextual evidence that belongs to the axis but deliberately does not feed its signal
(a documented asymmetry — `derive_subgroups` does not read them), so they are on-axis for routing purposes
even though they are off-signal for scoring.

The remaining fleet drift is exempted per (skill, axis, side, measurement_type) rather than per skill, so a
NEW mis-routing inside an already-drifting skill still fails. See `_KNOWN_DRIFT`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

SKILLS = Path(__file__).resolve().parents[1]

# Skills with a questions.yaml and NO hierarchy at all: they are absent from the governed
# `question_hierarchies` source, so there is nothing to agree with. Pinned as a set so a hierarchy cannot
# appear for one of them without this guard starting to apply.
_NO_HIERARCHY = {"literature-context", "translational-readiness"}

# Exempted drift, as exact (axis, side, measurement_type) triples. `side` says which file has the type on
# that axis: `questions_only` = questions.yaml routes it there and the hierarchy does not, `hierarchy_only`
# = the reverse. A move between axes therefore shows up as TWO triples, which is what makes each one
# individually retirable.
#
# All of these need a fix to the GOVERNED SOURCE (target-contracts
# `vocabularies/target_profiling_axes.yaml`) plus a `sync_question_hierarchies.py --write` re-run — not
# fixable from this repo, which is why they are exemptions and not edits.
#
# NOT ALL DRIFT CAN CAUSE THE DEFECT THIS GUARD EXISTS FOR, and the difference is measurable. A
# display/claim contradiction needs the type to be SCORED on at least one side — i.e. listed in a
# hierarchy `questions[].measurement_types` (which `derive_subgroups` reads) or on a questions.yaml
# question whose role is not `display_only`. A type that is a hierarchy `context_type` AND lives on a
# `display_only` (or absent) questions.yaml question is off-signal on BOTH sides: it is a bookkeeping
# mismatch, reported only because this guard unions `context_types` into the axis — which it must, or it
# would stop catching the real ones. Measured over this ledger: **40 of 59 triples are scored on at least
# one side; 19 are off-signal on both.** The off-signal-both-sides 19 are all of
# on-target-safety-liability (8), all of target-intrinsic (8), differentiation-landscape (2) and
# tractability-small-molecule (1).
#
# Four causes:
#
#   (1) questions.yaml is deliberately FINER — it has an axis the hierarchy has not learned, so the
#       hierarchy leaves those types on the parent axis.
#         on-target-safety-liability  PHARMACOVIGILANCE split out of CONSTRAINT. Off-signal on BOTH sides
#                                     (hierarchy `context_type` ↔ `role: display_only`), so nothing is
#                                     mis-scored. Deliberately NOT fixed in contracts: a sub_group needs at
#                                     least one scored question (`validate_question_hierarchies.py`), so
#                                     giving pharmacovigilance its own sub-group would start publishing a
#                                     graded signal tier for black-box-warning evidence the skill marks
#                                     display_only — a semantics change, not bookkeeping. See
#                                     target-contracts #757.
#       genomic-alteration-profile's SPL-out-of-FUS split WAS this, and is now fixed (contracts #757):
#       `splice_exon_skip` was a FUS measurement_type, so `derive_subgroups` scored a METex14 exon-skip read
#       into the FUSION signal while the skill published an independent SPL driver claim from the same read.
#       The one triple left for it is cause (4).
#   (2) axis VOCABULARY does not correspond at all — tumor-presence questions.yaml uses positional axis
#       letters A/B/C/D while the hierarchy uses semantic ids (abundance / generality /
#       malignant_intrinsic). No axis is shared, so every type reads as drift. This is NOT merely a naming
#       reconciliation: every one of its 26 triples is scored on both sides, so the A-vs-abundance signal is
#       computed from genuinely different card sets while display and claim use different axis names.
#       Listed exhaustively so a real routing change inside it cannot hide.
#   (3) genuine per-axis disagreement about where a type belongs — one side is wrong and it takes a
#       contracts decision to say which: combination-and-vulnerability, differentiation-landscape,
#       functional-requirement, target-intrinsic (the hierarchy's MODALITY_ROUTING carries the whole safety
#       block), tractability-small-molecule, tumor-selectivity (DIST/INT/SAFE/WIN reshuffle).
#       ★ Two of these are the SAME SHAPE as the splice bug and are the best next candidates:
#       tumor-selectivity INT scores `surface_density`, `spatial_colocalization` and `spatial_surface_protein`
#       from the hierarchy while questions.yaml marks all three `display_only`; and
#       combination-and-vulnerability scores `cross_consortium_paralog_gi` into CODEP while questions.yaml
#       does not carry it at all — scored but never displayed.
#   (4) questions.yaml CANNOT express "on this axis, but off the literature crosswalk". Its single
#       `axis_id` field serves both routing and the crosswalk, so a type that belongs to an axis but must
#       stay out of its crosswalk has to sit on an axis-LESS question, which `_axis_map` skips.
#         genomic-alteration-profile  `tumor_splice_dysregulation` is an SPL `context_type` in the
#                                     hierarchy (on-axis, never scored — correct) and sits on the axis-less
#                                     `display_only` `splice_dysregulation` question here. It must stay
#                                     axis-less: giving it `axis_id: SPL` would pull it into the SPL
#                                     crosswalk, which must stay SPL -> [splice_driver] so that "no
#                                     exon-skip driver" stops reading as contradicted by present splice
#                                     dysregulation. Retiring this triple means teaching `_axis_map` to
#                                     model context_type ↔ axis-less-display_only, not moving either file.
_KNOWN_DRIFT: dict[str, set[tuple[str, str, str]]] = {
    "combination-and-vulnerability": {
        ("CODEP", "hierarchy_only", "cross_consortium_paralog_gi"),
    },
    "differentiation-landscape": {
        ("COMUT", "hierarchy_only", "clinical_precedent"),
        ("COMUT", "hierarchy_only", "competitor_landscape"),
    },
    "functional-requirement": {
        ("COND", "questions_only", "paralog_buffering"),
        ("DEP", "hierarchy_only", "paralog_buffering"),
        ("SEL", "questions_only", "crispr_lof_dependency"),
    },
    "genomic-alteration-profile": {
        # cause (4) only. The SPL-out-of-FUS split landed in contracts #757, retiring
        # ("FUS", "hierarchy_only", "splice_exon_skip"), ("FUS", "hierarchy_only",
        # "tumor_splice_dysregulation") and ("SPL", "questions_only", "splice_exon_skip").
        ("SPL", "hierarchy_only", "tumor_splice_dysregulation"),
    },
    "on-target-safety-liability": {
        ("CONSTRAINT", "hierarchy_only", "alteration_role"),
        ("CONSTRAINT", "hierarchy_only", "copy_number_alteration"),
        ("CONSTRAINT", "hierarchy_only", "drug_warning_safety"),
        ("CONSTRAINT", "hierarchy_only", "functional_gene_state"),
        ("CONSTRAINT", "hierarchy_only", "onsides_adverse_event_safety"),
        ("CONSTRAINT", "hierarchy_only", "target_safety_prioritisation"),
        ("PHARMACOVIGILANCE", "questions_only", "drug_warning_safety"),
        ("PHARMACOVIGILANCE", "questions_only", "onsides_adverse_event_safety"),
    },
    "target-intrinsic": {
        ("MODALITY_ROUTING", "hierarchy_only", "clinvar_germline_pathogenicity_safety"),
        ("MODALITY_ROUTING", "hierarchy_only", "dosage_sensitivity_safety"),
        ("MODALITY_ROUTING", "hierarchy_only", "gnomad_lof_constraint"),
        ("MODALITY_ROUTING", "hierarchy_only", "human_genetic_safety"),
        ("MODALITY_ROUTING", "hierarchy_only", "mouse_ko_phenotype_safety"),
        ("MODALITY_ROUTING", "hierarchy_only", "normal_tissue_protein_breadth"),
        ("MODALITY_ROUTING", "hierarchy_only", "paralog_buffering"),
        ("MODALITY_ROUTING", "hierarchy_only", "target_safety_prioritisation"),
    },
    "tractability-small-molecule": {
        ("DRUG", "hierarchy_only", "mutation_hotspot_frequency"),
    },
    "tumor-presence": {
        ("A", "questions_only", "cell_line_protein_abundance"),
        ("A", "questions_only", "cell_line_rna_expression"),
        ("A", "questions_only", "rna_protein_concordance"),
        ("A", "questions_only", "tumor_expression_distribution"),
        ("A", "questions_only", "tumor_protein_abundance"),
        ("A", "questions_only", "tumor_protein_ihc_presence"),
        ("A", "questions_only", "tumor_vs_adjacent_expression"),
        ("B", "questions_only", "normal_tissue_protein_breadth"),
        ("B", "questions_only", "sc_normal_celltype_expression"),
        ("B", "questions_only", "tumor_protein_abundance"),
        ("B", "questions_only", "tumor_vs_adjacent_expression"),
        ("C", "questions_only", "expression_purity_confound"),
        ("C", "questions_only", "sc_normal_celltype_expression"),
        ("C", "questions_only", "sc_tumor_celltype_expression"),
        ("D", "questions_only", "tumor_elevation_breadth"),
        ("abundance", "hierarchy_only", "cell_line_protein_abundance"),
        ("abundance", "hierarchy_only", "cell_line_rna_expression"),
        ("abundance", "hierarchy_only", "expression_purity_confound"),
        ("abundance", "hierarchy_only", "rna_protein_concordance"),
        ("abundance", "hierarchy_only", "tumor_expression_distribution"),
        ("abundance", "hierarchy_only", "tumor_protein_abundance"),
        ("abundance", "hierarchy_only", "tumor_protein_ihc_presence"),
        ("generality", "hierarchy_only", "tumor_elevation_breadth"),
        ("malignant_intrinsic", "hierarchy_only", "expression_purity_confound"),
        ("malignant_intrinsic", "hierarchy_only", "sc_tumor_celltype_expression"),
    },
    "tumor-selectivity": {
        ("DIST", "hierarchy_only", "normal_tissue_protein_abundance"),
        ("DIST", "questions_only", "tumor_vs_normal_percentile_crossing"),
        ("INT", "hierarchy_only", "spatial_colocalization"),
        ("INT", "hierarchy_only", "spatial_surface_protein"),
        ("INT", "hierarchy_only", "surface_density"),
        ("INT", "questions_only", "expression_purity_confound"),
        ("SAFE", "questions_only", "modality_window"),
        ("SAFE", "questions_only", "normal_tissue_protein_abundance"),
        ("WIN", "hierarchy_only", "expression_purity_confound"),
        ("WIN", "hierarchy_only", "modality_window"),
        ("WIN", "hierarchy_only", "tumor_vs_normal_percentile_crossing"),
    },
}


def _skill_dirs() -> list[Path]:
    return sorted(p.parent for p in SKILLS.glob("*/questions.yaml"))


def _axis_map(doc: dict, *, hierarchy: bool) -> dict[str, set[str]]:
    """axis_id -> the measurement_types routed to it, from either file."""
    out: dict[str, set[str]] = {}
    if hierarchy:
        for sg in doc.get("sub_groups") or []:
            # context_types are on-axis for ROUTING even though derive_subgroups does not score them.
            mts = set(sg.get("context_types") or [])
            for q in sg.get("questions") or []:
                mts.update(q.get("measurement_types") or [])
            out[sg["id"]] = mts
        return out
    for q in doc.get("questions") or []:
        axis = q.get("axis_id")
        if axis is None:
            continue  # display_only rows with no axis are deliberately outside the crosswalk
        out.setdefault(axis, set()).update(q.get("measurement_types") or [])
    return out


def _drift(skill_dir: Path) -> set[tuple[str, str, str]]:
    """Every (axis, side, measurement_type) on which the two files disagree. Empty == agreement."""
    q = _axis_map(yaml.safe_load((skill_dir / "questions.yaml").read_text()) or {}, hierarchy=False)
    h = _axis_map(yaml.safe_load((skill_dir / "question_hierarchy.yaml").read_text()) or {}, hierarchy=True)
    triples = set()
    for axis in set(q) | set(h):
        for mt in q.get(axis, set()) - h.get(axis, set()):
            triples.add((axis, "questions_only", mt))
        for mt in h.get(axis, set()) - q.get(axis, set()):
            triples.add((axis, "hierarchy_only", mt))
    return triples


def _guarded() -> list[Path]:
    return [d for d in _skill_dirs() if (d / "question_hierarchy.yaml").exists()]


def test_the_corpus_under_test_is_not_empty():
    """Falsification floor. A bad glob would make every assertion below pass over zero skills."""
    assert len(_skill_dirs()) >= 13, f"only {len(_skill_dirs())} questions.yaml found — glob is wrong"
    assert len(_guarded()) >= 11, f"only {len(_guarded())} skills have a hierarchy to compare against"


def test_no_new_axis_routing_drift():
    """THE guard. Per-triple, so a new mis-routing inside an already-drifting skill still fails."""
    new = {d.name: sorted(_drift(d) - _KNOWN_DRIFT.get(d.name, set())) for d in _guarded()}
    new = {k: v for k, v in new.items() if v}
    assert not new, (
        "questions.yaml routes measurement_type(s) to a different axis than the generated "
        f"question_hierarchy.yaml: {new!r}\n"
        "`side` names the file that has it on that axis. This is not cosmetic: the hierarchy decides what "
        "subgroup_signals SCORES per axis and questions.yaml decides what evidence_graph DISPLAYS, so a "
        "disagreement publishes a display and a claim that contradict each other. Fix the side that is "
        "wrong — if it is the hierarchy, edit target-contracts vocabularies/target_profiling_axes.yaml "
        "(question_hierarchies) and re-run skills/tools/sync_question_hierarchies.py --write; the mirror is "
        "generated and hand-edits are reverted by test_question_hierarchy_drift.py."
    )


def test_the_known_drift_ledger_is_still_needed():
    """Self-retiring: an exemption that no longer describes real drift must be DELETED, not left to rot
    into a permanent licence for the axis it names."""
    stale = {}
    for skill, expected in _KNOWN_DRIFT.items():
        d = SKILLS / skill
        if not (d / "question_hierarchy.yaml").exists():
            stale[skill] = "skill or hierarchy is gone"
            continue
        gone = sorted(expected - _drift(d))
        if gone:
            stale[skill] = gone
    assert not stale, (
        f"_KNOWN_DRIFT entries no longer describe real drift: {stale!r}. They have been fixed — remove them "
        "(and drop the skill's entry entirely once its set is empty)."
    )


def test_the_four_agreeing_skills_stay_agreeing():
    """The skills with ZERO drift are the regression surface that matters most: they are the only ones where
    this guard is currently load-bearing rather than exempting. Named explicitly so that "fixing" a failure
    by adding a ledger entry cannot quietly apply to them."""
    for skill in ("cis-feature-coherence", "immune-context", "mechanism-and-pharmacology", "surface-modality-fit"):
        assert skill not in _KNOWN_DRIFT, f"{skill} must never acquire a _KNOWN_DRIFT exemption"
        assert _drift(SKILLS / skill) == set(), f"{skill} has regressed: {sorted(_drift(SKILLS / skill))}"


def test_genomic_dependency_types_are_on_the_dependency_axis():
    """The measured defect, pinned at the level it was wrong: `mutation_stratified_dependency` and
    `mutation_drug_response` are DEP evidence. They were on the SNV question, which made the SNV row draw
    on 13 cards in evidence_graph while subgroup_signals scored SNV from 8 — a display/claim contradiction
    inside one published nomination.json. The generic guard above would also catch this; this test names it
    so the intent survives a future reshuffle of the ledger."""
    doc = yaml.safe_load((SKILLS / "genomic-alteration-profile" / "questions.yaml").read_text())
    q = _axis_map(doc, hierarchy=False)
    for mt in ("mutation_stratified_dependency", "mutation_drug_response"):
        assert mt in q["DEP"], f"{mt} must be routed to the DEP axis"
        assert mt not in q["SNV"], f"{mt} is dependency evidence and must not also sit on the SNV axis"
    # The three contextual types DO belong to SNV: the hierarchy carries them as SNV `context_types`.
    for mt in ("genomic_instability_state", "ddr_deficiency_context", "mutational_signature_context"):
        assert mt in q["SNV"], f"{mt} is an SNV context_type and must stay on the SNV axis"


def test_genomic_exon_skip_is_scored_on_its_own_axis_not_fusion():
    """The mirror half of target-contracts #757, pinned here because this is where it is CONSUMED.

    `derive_subgroups` builds its type -> sub_group map from `questions[].measurement_types` only, so while
    `splice_exon_skip` sat under FUS a METex14 exon-skip read was SCORED into the fusion signal — even though
    the skill computes an independent exon-skip driver claim from it (`genomic_claims._spl_signal`, rung
    `splice-exon-skip-driver-supportive`, question `splice_driver` on axis SPL). `tumor_splice_dysregulation`
    stays a `context_type`: on-axis, deliberately never scored, because it is a splice-FORM read and not
    evidence for a driver call. The hierarchy is GENERATED, so a regression here means contracts regressed.
    """
    h = yaml.safe_load((SKILLS / "genomic-alteration-profile" / "question_hierarchy.yaml").read_text())
    sgs = {sg["id"]: sg for sg in h["sub_groups"]}
    assert "SPL" in sgs, "SPL sub-group is gone — re-run tools/sync_question_hierarchies.py --write"
    scored = {i: {mt for q in sg["questions"] for mt in q["measurement_types"]} for i, sg in sgs.items()}
    assert scored["SPL"] == {"splice_exon_skip"}
    assert scored["FUS"] == {"fusion_rearrangement", "fusion_stratified_dependency"}
    assert sgs["SPL"].get("context_types") == ["tumor_splice_dysregulation"]
    for sg_id, mts in scored.items():
        assert "tumor_splice_dysregulation" not in mts, f"scored under {sg_id}; it must stay a context_type"


def test_skills_without_a_hierarchy_are_the_expected_ones():
    """A skill absent from the governed source is unguarded by construction. Pinning the set means a new
    hierarchy cannot appear without this guard starting to apply to it, and a hierarchy cannot be DELETED
    to make a failure here go away."""
    missing = {d.name for d in _skill_dirs() if not (d / "question_hierarchy.yaml").exists()}
    assert missing == _NO_HIERARCHY, (
        f"skills without a question_hierarchy.yaml changed: {sorted(missing)} != {sorted(_NO_HIERARCHY)}. "
        "If a hierarchy was added, delete the skill from _NO_HIERARCHY so it is compared; if one was "
        "removed, say why here."
    )
