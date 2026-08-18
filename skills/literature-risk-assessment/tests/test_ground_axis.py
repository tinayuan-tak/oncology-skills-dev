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
import importlib.util
from pathlib import Path

_MOD = Path(__file__).resolve().parent.parent / "scripts" / "ground_axis.py"


def _load():
    spec = importlib.util.spec_from_file_location("ground_axis", _MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ga = _load()
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


def test_unwraps_structured_output_and_tolerates_string_finding():
    out = {"findings": {"value": ["CRS liability",
                {"finding": "hepatic", "kind": "liver", "cited_pmids": {"value": ["222"]}}], "_source": "llm"},
           "corroborations": {"value": []}, "contradicts_deterministic": {"value": True}}
    g = ga.build_grounded_block(DET, out, {"222"}, corpus_pin={}, n_retrieved=2)
    findings = [f["finding"] for f in g["findings"]]
    assert "CRS liability" in findings and "hepatic" in findings
    assert g["contradicts_deterministic"] is True


def test_severity_passthrough_and_safe_default():
    # a valid severity is carried through verbatim; a missing/off-enum severity (and a bare-string
    # finding) defaults to 'moderate' so the pseudo-card bin never crashes or silently escalates.
    out = {"findings": [
        {"finding": "Ph3 discontinued", "kind": "x", "severity": "high", "cited_pmids": ["1"]},
        {"finding": "some context", "kind": "x", "severity": "bogus", "cited_pmids": ["1"]},
        {"finding": "no severity field", "kind": "x", "cited_pmids": ["1"]},
        "bare string finding"],
        "corroborations": [], "contradicts_deterministic": False, "notes": ""}
    g = ga.build_grounded_block(DET, out, {"1"}, corpus_pin={}, n_retrieved=1)
    sev = [f["severity"] for f in g["findings"]]
    assert sev == ["high", "moderate", "moderate", "moderate"]
    # single source of truth: the enum + escalator token are exported for the consumer (risk_rollup)
    assert ga.SEVERITY_HIGH in ga.SEVERITY_LEVELS
    assert not hasattr(ga, "PSEUDO_ESCALATOR_KINDS")  # dead duplicate removed


def test_severity_in_tool_schema_enum():
    props = ga.TOOL_SCHEMA["properties"]["findings"]["items"]
    assert props["properties"]["severity"]["enum"] == list(ga.SEVERITY_LEVELS)
    assert "severity" in props["required"]


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
    # ROLLOUT 2026-08-18: every indication-conditioned target-profile SUB_SKILLS short now has a
    # grounded axis (target_intrinsic intentionally excluded — gateless + indication-independent).
    expected = {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm",
                "mechanism", "genomic_alteration", "differentiation", "synthetic_lethal_partners",
                "combinatorial_dependency", "expression"}
    assert expected <= set(ga.AXIS_CONFIG)
    assert "target_intrinsic" not in ga.AXIS_CONFIG        # deliberately deferred
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
    # the six former 'biological'-collision axes now produce DISTINCT queries
    qs = {ax: ga._axis_query("FOO", "lung cancer", ax) for ax in
          ("dependency", "mechanism", "genomic_alteration", "synthetic_lethal_partners",
           "combinatorial_dependency", "expression")}
    assert len(set(qs.values())) == 6        # all distinct, not one shared 'biological' query


def test_axis_query_unknown_axis_is_target_only():
    q = ga._axis_query("FOO", "lung cancer", "not_an_axis")
    assert q == "(FOO) AND ()" or "FOO" in q      # defensive: no crash, gene present
