"""ground_axis: escalate-only grounded-substrate block — pure-core tests (no network / no Bedrock).

Invariants of the substrate layer:
  - CONTAINMENT: a cited PMID not in the retrieved set is dropped (confabulation guard).
  - ESCALATE-ONLY SHAPE: emits escalate-only FINDINGS + escalate_only=True, and NO risk score
    (LOW/MED/HIGH) — the absence of a re-scored bin is what prevents anchor-propagation.
  - WRAPPER-TOLERANCE: unwraps the structured-output {"value":...} field wrapper; tolerates a
    finding emitted as a bare string.
  - AXIS-PARAMETERIZED: the contract is one structure across axes; safety + dependency are configured
    with different finding nouns/kinds but the same block shape.
"""
from __future__ import annotations
from pathlib import Path

from _test_support import load_module

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "ground_axis.py"

ga = load_module(_MOD, "ground_axis")
DET = {"verdict": "wt_human_genetics_mechanism_mismatch", "driving_rule_id": "r", "cards": {}}


def test_containment_drops_pmids_not_in_corpus():
    out = {"findings": [{"finding": "Ocular tox", "kind": "eye", "cited_pmids": ["111", "999"]}],
           "corroborations": [], "contradicts_deterministic": True, "notes": ""}
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={"mindate": "2015"}, n_retrieved=5)
    assert g["findings"][0]["cited_pmids"] == ["111"]
    assert g["confabulated_dropped"] == ["999"]


def test_escalate_only_shape_no_risk_score():
    g = ga.build_grounded_block(DET, {"findings": [], "corroborations": [],
                                       "contradicts_deterministic": False, "notes": ""},
                                set(), corpus_pin={}, n_retrieved=0)
    assert g["escalate_only"] is True
    assert "risk_level" not in g and "bin" not in g
    assert g["anchor_verdict"] == DET["verdict"]


def test_unwraps_structured_output_and_quarantines_uncited_finding():
    # A bare-string finding carries NO citations; under the cite-or-abstain grounding contract it is
    # quarantined into dropped_uncited_findings (never kept as a live escalate-only finding on
    # hallucinated/absent support). A finding whose cited PMID is in the retrieved set is kept.
    out = {"findings": {"value": ["CRS liability",
                {"finding": "hepatic", "kind": "liver", "cited_pmids": {"value": ["222"]}}], "_source": "llm"},
           "corroborations": {"value": []}, "contradicts_deterministic": {"value": True}}
    g = ga.build_grounded_block(DET, out, {"222"}, corpus_pin={}, n_retrieved=2)
    findings = [f["finding"] for f in g["findings"]]
    assert findings == ["hepatic"]
    quarantined = [f["finding"] for f in g["dropped_uncited_findings"]]
    assert "CRS liability" in quarantined
    assert g["contradicts_deterministic"] is True


def test_severity_passthrough_and_safe_default():
    # a valid severity is carried through verbatim; a missing/off-enum severity defaults to 'moderate'
    # so the pseudo-card bin never crashes or silently escalates. A bare-string (uncited) finding is
    # quarantined out of the live findings list (grounding-integrity: no bin on uncited support).
    out = {"findings": [
        {"finding": "Ph3 discontinued", "kind": "x", "severity": "high", "cited_pmids": ["1"]},
        {"finding": "some context", "kind": "x", "severity": "bogus", "cited_pmids": ["1"]},
        {"finding": "no severity field", "kind": "x", "cited_pmids": ["1"]},
        "bare string finding"],
        "corroborations": [], "contradicts_deterministic": False, "notes": ""}
    g = ga.build_grounded_block(DET, out, {"1"}, corpus_pin={}, n_retrieved=1)
    sev = [f["severity"] for f in g["findings"]]
    assert sev == ["high", "moderate", "moderate"]
    assert [f["finding"] for f in g["dropped_uncited_findings"]] == ["bare string finding"]
    # single source of truth: the enum + escalator token are exported for the consumer (risk_rollup)
    assert ga.SEVERITY_HIGH in ga.SEVERITY_LEVELS
    assert not hasattr(ga, "PSEUDO_ESCALATOR_KINDS")  # dead duplicate removed


def test_severity_in_tool_schema_enum():
    props = ga.TOOL_SCHEMA["properties"]["findings"]["items"]
    assert props["properties"]["severity"]["enum"] == list(ga.SEVERITY_LEVELS)
    assert "severity" in props["required"]


def test_prompt_abstract_truncation_uses_budget():
    from types import SimpleNamespace
    long = "X" * 4000
    abs_ = [SimpleNamespace(pmid="1", title="T", abstract=long)]
    # default budget raised from the original 900
    assert ga.ABSTRACT_CHARS == 1500
    p_default = ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_)
    assert ("X" * ga.ABSTRACT_CHARS) in p_default and ("X" * (ga.ABSTRACT_CHARS + 1)) not in p_default
    # explicit override is honored
    p_small = ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_, abstract_chars=100)
    assert ("X" * 100) in p_small and ("X" * 101) not in p_small


def test_axis_config_has_all_rolled_out_axes_with_complete_framing():
    assert {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm"} <= set(ga.AXIS_CONFIG)
    nouns = {cfg["finding_noun"] for cfg in ga.AXIS_CONFIG.values()}
    assert len(nouns) == len(ga.AXIS_CONFIG)      # each axis has a DISTINCT finding noun
    for ax, cfg in ga.AXIS_CONFIG.items():
        assert cfg["pubmed_category"] and cfg["kinds"] and cfg["finding_noun"]
        if cfg.get("pseudo_card"):                    # engine-blind pseudo-card
            assert cfg["verdict_key"] is None and cfg["cards"] == []
        else:                                         # engine-anchored axis
            assert cfg["verdict_key"] and cfg["cards"]


def test_skills_path_resolves_for_live_imports():
    # regression guard: _SKILLS must point at skills/ so `_skills_common` imports at call time
    # (the merged code used parents[2] = repo root, which broke the live path).
    from pathlib import Path
    assert (Path(ga._SKILLS) / "_skills_common").is_dir()


def test_deterministic_block_selects_axis_cards():
    pkg = {"synthesis": {"sub_verdicts": {"dependency": {"verdict": "lineage_selective",
            "driving_rule_id": "d"}}},
           "cards": [{"card_id": "dependency-lineage-selectivity", "interpretation_call": "lineage_selective"},
                     {"card_id": "gnomad-lof-constraint", "interpretation_call": "tolerant"}]}
    d = ga.deterministic_block(pkg, "dependency")
    assert d["verdict"] == "lineage_selective"
    assert "dependency-lineage-selectivity" in d["cards"]      # dependency card included
    assert "gnomad-lof-constraint" not in d["cards"]           # safety card excluded from dependency axis


def test_all_indication_conditioned_subskill_axes_configured():
    # The 9 grounded engine axes (verdict-anchored). CONSOLIDATION CLEANUP 2026-08-21: the former
    # synthetic_lethal_partners / combinatorial_dependency axes were REMOVED — those shorts consolidated
    # 2026-08-20 into the gateless combination_vulnerability sub-skill (verdict=None), so their verdict_key
    # no longer resolves. This test now DOUBLES AS THE ANTI-DRIFT GUARD: it pins the real covered set AND
    # asserts the orphaned keys stay gone (re-adding one fails here).
    expected = {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm",
                "mechanism", "genomic_alteration", "differentiation", "expression"}
    assert expected <= set(ga.AXIS_CONFIG)
    # NOT grounded — deliberately (see module docstring): gateless / not-yet-wired / consolidated-away.
    for absent in ("target_intrinsic", "combination_vulnerability", "immune_context", "cis_coherence",
                   "synthetic_lethal_partners", "combinatorial_dependency"):
        assert absent not in ga.AXIS_CONFIG, (
            f"{absent!r} must not be a grounded axis (consolidation orphan or deliberately un-grounded)")
    # each newly-rolled-out axis anchors to a real sub-verdict (not a pseudo-card) with complete framing
    for ax in (expected - {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm"}):
        cfg = ga.AXIS_CONFIG[ax]
        assert cfg["verdict_key"] == ax and cfg["cards"]           # engine-anchored
        assert not cfg.get("pseudo_card")
        assert cfg["pubmed_category"] in {"biological", "druggability", "translational",
                                          "clinical", "safety", "commercial"}
        assert "WEAKENING" in cfg["finding_noun"] or "DISCORDANCE" in cfg["finding_noun"]  # escalate-only


def test_new_axis_deterministic_block_reads_its_verdict():
    # a mechanism axis reads the mechanism sub-verdict + its cards, ignoring other axes' cards
    pkg = {"synthesis": {"sub_verdicts": {"mechanism": {"verdict": "well_characterized",
            "driving_rule_id": "m1"}}},
           "cards": [{"card_id": "signaling-network-mechanism", "interpretation_call": "clear_moa"},
                     {"card_id": "gnomad-lof-constraint", "interpretation_call": "tolerant"}]}
    d = ga.deterministic_block(pkg, "mechanism")
    assert d["verdict"] == "well_characterized"
    assert "signaling-network-mechanism" in d["cards"]
    assert "gnomad-lof-constraint" not in d["cards"]


def test_pseudo_cards_are_engine_blind():
    # clinical/commercial are pseudo-cards: no verdict_key, no engine cards
    for ax in ("clinical", "commercial"):
        assert ax in ga.AXIS_CONFIG
        cfg = ga.AXIS_CONFIG[ax]
        assert cfg["verdict_key"] is None and cfg["cards"] == [] and cfg.get("pseudo_card") is True
    d = ga.deterministic_block({"synthesis": {"sub_verdicts": {}}, "cards": []}, "clinical")
    assert d["verdict"] is None and d["cards"] == {} and d["engine_blind"] is True


# =============================== TARGETED per-axis queries (follow-up #3) ===============================
def test_axis_pubmed_terms_cover_every_axis():
    # every configured axis must have a targeted query clause (no axis falls back to empty terms)
    assert set(ga.AXIS_PUBMED_TERMS) >= set(ga.AXIS_CONFIG)
    for ax, (terms, disease_scoped) in ga.AXIS_PUBMED_TERMS.items():
        assert terms and isinstance(disease_scoped, bool)


def test_axis_query_disease_scoping():
    # indication-conditioned axis → disease AND-ed in; the query is axis-distinct (not the shared one)
    q_dep = ga._axis_query("KRAS", "colorectal cancer", "dependency")
    assert "KRAS" in q_dep and "colorectal cancer" in q_dep and "dependency" in q_dep.lower()
    # target-LEVEL axis (safety) → NO disease clause (gnomAD/tox is indication-independent)
    q_saf = ga._axis_query("KRAS", "colorectal cancer", "safety")
    assert "colorectal cancer" not in q_saf and "toxicity" in q_saf
    # the former 'biological'-collision axes now produce DISTINCT queries (synthetic_lethal_partners /
    # combinatorial_dependency removed 2026-08-21 with the consolidation cleanup)
    qs = {ax: ga._axis_query("FOO", "lung cancer", ax) for ax in
          ("dependency", "mechanism", "genomic_alteration", "expression")}
    assert len(set(qs.values())) == 4        # all distinct, not one shared 'biological' query


def test_axis_query_unknown_axis_is_target_only():
    q = ga._axis_query("FOO", "lung cancer", "not_an_axis")
    assert q == "(FOO) AND ()" or "FOO" in q      # defensive: no crash, gene present


# ===================== entity + soft-broaden retrieval widening (2026-08-24) =====================
def test_axis_query_broad_drops_axis_terms():
    # disease-scoped axis: broad keeps (gene) AND (disease) but DROPS the axis-term conjunction
    tight = ga._axis_query("STAG1", "bladder cancer", "dependency")
    broad = ga._axis_query("STAG1", "bladder cancer", "dependency", broad=True)
    assert "dependency" in tight.lower() and "dependency" not in broad.lower()
    assert broad == "(STAG1) AND (bladder cancer)"
    # target-level axis (safety, not disease-scoped): broad collapses to just the gene
    assert ga._axis_query("STAG1", "bladder cancer", "safety", broad=True) == "(STAG1)"
    # the tight safety query is exactly what starved in practice (measured: 0 PMIDs for STAG1)
    assert "toxicity" in ga._axis_query("STAG1", "bladder cancer", "safety")


def test_dedup_is_order_preserving():
    # entity-lane hits must stay ahead of keyword-lane hits, first occurrence wins
    assert ga._dedup(["3", "1", "3", "2", "1"]) == ["3", "1", "2"]
    assert ga._dedup([]) == []


def test_retrieval_widening_constants():
    assert ga.RETRIEVAL_FLOOR >= 1 and ga.MAX_RETRIEVED >= ga.RETRIEVAL_FLOOR


# ===================== engine-aware multi-query angles (2026-08-25) =====================
def test_keyword_angles_mesh_when_disease_scoped_and_available():
    # disease-scoped axis WITH a MeSH clause -> [tight, MeSH-anchored]; the 2nd angle is the MeSH one
    angles = ga._keyword_angles("KRAS", "colorectal cancer", "dependency",
                                '"colorectal neoplasms"[MeSH Terms]', disease_scoped=True)
    assert len(angles) == 2
    assert "colorectal cancer" in angles[0] and "dependency" in angles[0].lower()   # tight
    assert "[MeSH Terms]" in angles[1] and "dependency" in angles[1].lower()          # MeSH precision angle
    assert angles[0] != angles[1]                                                     # complementary, not identical


def test_keyword_angles_broad_fallback_when_no_mesh():
    # no MeSH clause -> 2nd angle is the broad (axis-terms-dropped) recall angle
    angles = ga._keyword_angles("STAG1", "bladder cancer", "dependency", None, disease_scoped=True)
    assert angles[1] == "(STAG1) AND (bladder cancer)"          # broad
    assert "dependency" in angles[0].lower() and "dependency" not in angles[1].lower()


def test_keyword_angles_target_scoped_axis_uses_broad_second():
    # target-scoped axis (safety, disease_scoped=False): MeSH N/A -> tight + broad(gene-only)
    angles = ga._keyword_angles("STAG1", "bladder cancer", "safety", None, disease_scoped=False)
    assert angles[1] == "(STAG1)"
    assert "toxicity" in angles[0]


def test_interleave_round_robin_and_dedup():
    # round-robin across the three lanes (entity, OT-floor, keyword), first occurrence wins on dedup
    entity = ["e1", "e2", "e3"]
    ot = ["o1", "e2"]          # e2 overlaps entity -> deduped, keeps entity position
    kw = ["k1"]
    assert ga._interleave(entity, ot, kw) == ["e1", "o1", "k1", "e2", "e3"]
    # a missing/empty lane (e.g. PubTator down or no OT floor) is simply skipped
    assert ga._interleave([], ["o1", "o2"], []) == ["o1", "o2"]
    assert ga._interleave([], [], []) == []
    # round-robin guarantees every non-empty lane is represented early (not crowded out by a long lane)
    long_entity = [f"e{i}" for i in range(10)]
    merged = ga._interleave(long_entity, ["o1"], ["k1"])
    assert merged.index("o1") <= 2 and merged.index("k1") <= 2
