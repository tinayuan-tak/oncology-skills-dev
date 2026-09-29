"""target_profiling_axes vocabulary tests — THE canonical objective→axis→card ontology (v1.0.0).

This artifact SUPERSEDES the three drifted generations (8-gate scaffold doc, gate_coverage.yaml v2,
per-skill `phase:` letters). These tests pin:
  - the shape is well-formed + versioned 1.0.0 + declares its supersedes provenance,
  - every question keys on a letter-free `short`, sits in a valid band, carries a coverage token,
    a home_skill, and a legacy_letters crosswalk (the retirement record),
  - the EQUIVALENCE GUARANTEE: every gate_coverage.yaml v2 short is present in the ontology with the
    SAME framework_can_evidence — the fresh scheme ported v2 content with no coverage regression,
  - the three conditioner axes (modality / subtype / molecular_form) are first-class, and
    molecular_form refines expression+selectivity and unifies the four scattered pieces,
  - reports_into / conditioned_by / refines edges name real shorts (no dangling refs),
  - the scientific_gaps backlog enumerates exactly the non-`captured` axes.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
AX = yaml.safe_load((REPO / "vocabularies" / "target_profiling_axes.yaml").read_text())
GC = yaml.safe_load((REPO / "vocabularies" / "gate_coverage.yaml").read_text())

COVERAGE_VOCAB = {"captured", "partial", "blind", "license_blocked", "out_of_scope"}
BANDS = {"necessity", "sufficiency"}


def _question_shorts():
    return {q["short"] for q in AX["questions"]}


def _conditioner_ids():
    return {c["id"] for c in AX["conditioner_axes"]}


def _ontology_coverage():
    """short -> framework_can_evidence over questions + biomarker_facets."""
    m = {q["short"]: q["framework_can_evidence"] for q in AX["questions"]}
    m.update({f["short"]: f["framework_can_evidence"] for f in AX["biomarker_facets"]})
    return m


def _gate_coverage_coverage():
    """short -> framework_can_evidence over every gate_coverage v2 list."""
    m = {}
    for key in ("biology_gates", "modality_fit", "unbuilt"):
        for e in GC.get(key, []) or []:
            m[e["short"]] = e["framework_can_evidence"]
    for e in GC.get("biomarker_facets", []) or []:
        m[e["short"]] = e["framework_can_evidence"]
    return m


# --- shape + version ---------------------------------------------------------


def test_wellformed_and_versioned():
    assert AX["enum_id"] == "target_profiling_axes"
    assert str(AX["version"]) == "1.1.0"
    for key in (
        "questions",
        "conditioner_axes",
        "biomarker_facets",
        "coverage_vocab",
        "bands",
        "homing_rule",
        "scientific_gaps",
        "supersedes",
    ):
        assert AX[key], f"{key} must be present + non-empty"
    assert set(AX["bands"]) == BANDS


def test_supersedes_names_the_three_generations():
    arts = {s["artifact"] for s in AX["supersedes"]}
    assert any("gate_coverage.yaml" in a for a in arts)
    assert any("CARD_ARCHITECTURE_DECISION" in a for a in arts)
    assert any("phase" in a for a in arts)


def test_questions_wellformed():
    for q in AX["questions"]:
        assert q["short"], q
        assert q["band"] in BANDS, q["short"]
        assert q["framework_can_evidence"] in COVERAGE_VOCAB, q["short"]
        assert q.get("home_skill"), f"{q['short']}: must declare a home_skill (homing rule)"
        assert q.get("question"), f"{q['short']}: must state the decision question"
        assert q.get("legacy_letters"), f"{q['short']}: must carry the legacy_letters crosswalk"


# --- THE equivalence guarantee ----------------------------------------------

_COVERAGE_ORDER = {"blind": 0, "license_blocked": 1, "partial": 2, "captured": 3}
# Documented supersede-upgrades: the ontology may CORRECT a stale gate_coverage v2 baseline UPWARD
# (never downward). Each entry is (v2_value, ontology_value) and must strictly improve coverage.
# surface_modality — review H1: v2's `blind` is stale; surface-abundance-density is LIVE → partial.
_SUPERSEDE_UPGRADES = {"surface_modality": ("blind", "partial")}


def test_equivalence_no_coverage_regression_vs_gate_coverage_v2():
    """Every gate_coverage v2 short appears in the ontology; coverage is EQUAL, or a documented
    supersede-UPGRADE (blind→partial). A silent or downward change fails here."""
    g = _gate_coverage_coverage()
    a = _ontology_coverage()
    missing = sorted(s for s in g if s not in a)
    assert not missing, f"gate_coverage shorts absent from the ontology: {missing}"
    for s in g:
        if s not in a or g[s] == a[s]:
            continue
        exp = _SUPERSEDE_UPGRADES.get(s)
        assert exp == (g[s], a[s]), f"undocumented coverage change {s}: v2={g[s]} ontology={a[s]}"
        assert _COVERAGE_ORDER[a[s]] > _COVERAGE_ORDER[g[s]], (
            f"{s}: a supersede-correction must UPGRADE, not downgrade ({g[s]}→{a[s]})"
        )


def test_review_fixes_applied():
    """Guards for the review-fix corrections so they can't silently regress."""
    q = {x["short"]: x for x in AX["questions"]}
    # H1: surface_modality rebanded partial (not blind)
    assert q["surface_modality"]["framework_can_evidence"] == "partial"
    # M1: mechanism flagged characterization-only (advisory, not a gate)
    assert q["mechanism"].get("characterization_only") is True
    # M2: necessity band declares the ANY-OF (non-conjunctive) invariant
    assert "ANY-OF" in AX["bands"]["necessity"]


# --- conditioner axes --------------------------------------------------------


def test_conditioner_axes_present():
    # The three original orthogonal refinements + the two blind conditioners the card-audit
    # (2026-08-21) surfaced (genetic_ancestry, disease_setting). Pinned as an exact set so any
    # further conditioner axis is a conscious, reviewed addition — not silent drift.
    assert _conditioner_ids() == {
        "modality",
        "subtype",
        "molecular_form",
        "genetic_ancestry",
        "disease_setting",
    }


def test_conditioners_refine_real_questions():
    qs = _question_shorts()
    for c in AX["conditioner_axes"]:
        assert c.get("refines"), f"{c['id']}: must declare what it refines"
        bad = set(c["refines"]) - qs
        assert not bad, f"{c['id']}: refines unknown questions {bad}"


def test_molecular_form_is_a_conditioner_not_a_gate():
    mf = next(c for c in AX["conditioner_axes"] if c["id"] == "molecular_form")
    # refines Expressed + Selective (the scientifically load-bearing placement)
    assert {"expression", "selectivity"} <= set(mf["refines"])
    assert mf["short"] not in _question_shorts() if "short" in mf else True
    # unifies the four scattered pieces named in plan Part 6.3
    pieces = {u.get("piece") for u in mf["unifies"]}
    assert {"cellline_isoform", "tumor_splice", "exon_window", "isoform_guardrail"} <= pieces
    # the new tumor-specific-splice -> selectivity foreign edge is recorded
    splice = next(u for u in mf["unifies"] if u.get("piece") == "tumor_splice")
    assert "tumor-selectivity" in splice.get("foreign_consumers", [])


def test_conditioned_by_names_real_conditioners():
    cids = _conditioner_ids()
    for q in AX["questions"]:
        for c in q.get("conditioned_by", []):
            assert c in cids, f"{q['short']}: conditioned_by unknown conditioner {c!r}"


# --- edges + facets ----------------------------------------------------------


def test_reports_into_and_facets_name_real_questions():
    qs = _question_shorts()
    for q in AX["questions"]:
        for tgt in q.get("reports_into", []):
            assert tgt in qs, f"{q['short']}: reports_into unknown question {tgt!r}"
    for f in AX["biomarker_facets"]:
        assert f.get("grain") in {"sub_skill", "card"}, f["short"]
        for tgt in f.get("reports_into", []):
            assert tgt in qs, f"{f['short']}: facet reports_into unknown question {tgt!r}"


def test_biomarker_facets_ported_from_gate_coverage():
    onto = {f["short"] for f in AX["biomarker_facets"]}
    gc = {f["short"] for f in GC.get("biomarker_facets", [])}
    assert gc <= onto, f"biomarker_facets dropped in the port: {gc - onto}"


# --- scientific gaps backlog -------------------------------------------------


def test_skill_objectives_wellformed():
    """Every skill declares an objective + a primary_axis that is a real question short (or null for
    descriptive/extrinsic skills). The user's per-skill scientific-objective requirement."""
    qs = _question_shorts()
    seen = set()
    for s in AX["skill_objectives"]:
        assert s.get("skill"), s
        seen.add(s["skill"])
        assert s.get("objective"), f"{s['skill']}: must state a scientific objective"
        pa = s.get("primary_axis", "__missing__")
        assert pa is None or pa in qs, f"{s['skill']}: primary_axis {pa!r} not a real question"
    # the nomination-spine skills must all declare an objective
    for core in (
        "tumor-presence",
        "tumor-selectivity",
        "functional-requirement",
        "genomic-alteration-profile",
        "surface-modality-fit",
        "on-target-safety-liability",
    ):
        assert core in seen, f"{core}: missing a skill objective"


def test_candidate_edges_report_into_real_questions():
    qs = _question_shorts()
    for e in AX["candidate_edges"]:
        assert e.get("proposed_card") and e.get("question"), e
        for tgt in e.get("reports_into", []):
            assert tgt in qs, f"{e['proposed_card']}: reports_into unknown question {tgt!r}"


def _real_card_ids():
    cards_dir = REPO / "cards"
    ids = set()
    for p in cards_dir.glob("*.card.yaml"):
        try:
            doc = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        if doc.get("card_id"):
            ids.add(doc["card_id"])
    # resolve historical renames via the alias map
    alias_path = REPO / "vocabularies" / "card_id_aliases.yaml"
    if alias_path.exists():
        adoc = yaml.safe_load(alias_path.read_text()) or {}
        for entry in adoc.get("aliases") or []:
            if isinstance(entry, dict) and entry.get("from"):
                ids.add(entry["from"])
    return ids


def test_skill_question_sets_wellformed_and_reference_real_cards():
    """Every skill_objectives.questions entry has a q + a non-empty answered_by, and every
    answered_by card_id resolves to a real card (or historical alias). This is the declarative
    per-skill question set the user asked to build out (like tumor-presence / tumor-selectivity)."""
    real = _real_card_ids()
    assert real, "expected to load some real card_ids"
    n_with_questions = 0
    for s in AX["skill_objectives"]:
        qs = s.get("questions")
        if not qs:
            continue
        n_with_questions += 1
        for entry in qs:
            assert entry.get("q"), f"{s['skill']}: a question needs a `q`"
            ab = entry.get("answered_by")
            assert ab, f"{s['skill']}: question {entry.get('q')!r} needs a non-empty answered_by"
            unknown = [c for c in ab if c not in real]
            assert not unknown, f"{s['skill']}: answered_by names unknown cards {unknown}"
    # the whole nomination fan-out (+ the descriptive/relational skills) should be built out now.
    # Floor dropped 15→14 by #479: the relational trio (synthetic-lethal-partners /
    # combinatorial-dependency / combo-and-resistance) was consolidated into a single
    # combination-and-vulnerability skill (net -2) and cis-feature-coherence gained a question set (+1).
    assert n_with_questions >= 14, f"expected >=14 skills with question sets, got {n_with_questions}"


def test_every_skill_objective_has_at_least_an_objective():
    for s in AX["skill_objectives"]:
        assert s.get("objective"), f"{s['skill']}: needs an objective"


def test_relational_axis_is_first_class_and_pair_grained():
    q = {x["short"]: x for x in AX["questions"]}
    assert "combination_vulnerability" in q, "the relational axis must be a first-class question"
    cv = q["combination_vulnerability"]
    assert cv["unit_of_analysis"] == "pair", "relational axis is pair-grained, not single-target scalar"
    assert cv["output_contract"] == "ranked_partner_table"
    assert "dependency" in cv.get("reports_into", []), "SL context reports_into dependency (veto-suppressor)"


def test_relational_trio_consolidated_into_the_relational_axis():
    """Post-#479 (2026-08-20): the relational trio (synthetic-lethal-partners /
    combinatorial-dependency / combo-and-resistance) was RETIRED from the fan-out and consolidated
    into a single combination-and-vulnerability skill that owns the relational axis. The trio must no
    longer appear as standalone skill_objectives, the consolidated owner must carry the relational
    axis, and the retirement must be recorded in the relational_consolidation annex."""
    by_skill = {s["skill"]: s for s in AX["skill_objectives"]}
    assert by_skill["combination-and-vulnerability"]["primary_axis"] == "combination_vulnerability", (
        "the consolidated skill must own the relational axis"
    )
    trio = {"synthetic-lethal-partners", "combinatorial-dependency", "combo-and-resistance"}
    lingering = trio & set(by_skill)
    assert not lingering, f"retired relational trio should not be standalone skill_objectives: {lingering}"
    # the retirement is the consolidation annex's record
    absorbed = {e["skill"] for e in AX["relational_consolidation"]["absorbed_skills"]}
    assert absorbed == trio, f"relational_consolidation.absorbed_skills should record the retired trio, got {absorbed}"


def test_output_contracts_and_consolidation_wellformed():
    oc = AX["output_contracts"]
    assert "scalar_verdict" in oc and "ranked_partner_table" in oc
    assert "combination_vulnerability" in oc["ranked_partner_table"]["used_by_axis"]
    rc = AX["relational_consolidation"]
    assert rc["axis"] == "combination_vulnerability"
    # #479 renamed absorbs_skills → absorbed_skills and marked the consolidation completed.
    absorbed = {e["skill"] for e in rc["absorbed_skills"]}
    assert absorbed == {"synthetic-lethal-partners", "combinatorial-dependency", "combo-and-resistance"}
    # the absorbed trio is RETIRED from skill_objectives; the consolidation TARGET now carries the axis.
    by_skill = {s["skill"]: s for s in AX["skill_objectives"]}
    assert rc["target_skill"] == "combination-and-vulnerability"
    assert by_skill[rc["target_skill"]]["primary_axis"] == "combination_vulnerability"


def test_scientific_gaps_cover_every_hard_gap_axis():
    """The gaps backlog must name every question whose standing is a HARD gap
    (`blind` or `license_blocked`) — the axes the framework genuinely cannot evidence.
    `partial` axes (wired but thin) may be enumerated but are not required."""
    gap_axes = {g["axis"] for g in AX["scientific_gaps"]}
    hard = {q["short"] for q in AX["questions"] if q["framework_can_evidence"] in {"blind", "license_blocked"}}
    missing = hard - gap_axes
    assert not missing, f"hard-gap questions missing from scientific_gaps: {missing}"
    # every gap entry names a real axis (question short OR a conditioner id)
    valid = _question_shorts() | _conditioner_ids()
    bad = gap_axes - valid
    assert not bad, f"scientific_gaps names unknown axes: {bad}"
