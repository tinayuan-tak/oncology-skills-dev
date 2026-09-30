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
    out = {
        "findings": [{"finding": "Ocular tox", "kind": "eye", "cited_pmids": ["111", "999"]}],
        "corroborations": [],
        "contradicts_deterministic": True,
        "notes": "",
    }
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={"mindate": "2015"}, n_retrieved=5)
    assert g["findings"][0]["cited_pmids"] == ["111"]
    assert g["confabulated_dropped"] == ["999"]


def test_escalate_only_shape_no_risk_score():
    g = ga.build_grounded_block(
        DET,
        {"findings": [], "corroborations": [], "contradicts_deterministic": False, "notes": ""},
        set(),
        corpus_pin={},
        n_retrieved=0,
    )
    assert g["escalate_only"] is True
    assert "risk_level" not in g and "bin" not in g
    assert g["anchor_verdict"] == DET["verdict"]


def test_unwraps_structured_output_and_quarantines_uncited_finding():
    # A bare-string finding carries NO citations; under the cite-or-abstain grounding contract it is
    # quarantined into dropped_uncited_findings (never kept as a live escalate-only finding on
    # hallucinated/absent support). A finding whose cited PMID is in the retrieved set is kept.
    out = {
        "findings": {
            "value": ["CRS liability", {"finding": "hepatic", "kind": "liver", "cited_pmids": {"value": ["222"]}}],
            "_source": "llm",
        },
        "corroborations": {"value": []},
        "contradicts_deterministic": {"value": True},
    }
    g = ga.build_grounded_block(DET, out, {"222"}, corpus_pin={}, n_retrieved=2)
    findings = [f["finding"] for f in g["findings"]]
    assert findings == ["hepatic"]
    quarantined = [f["finding"] for f in g["dropped_uncited_findings"]]
    assert "CRS liability" in quarantined
    assert g["contradicts_deterministic"] is True


def test_partial_confab_finding_is_flagged_not_silently_scrubbed():
    # (#1614 facet b) a finding backed by one real + one confabulated citation is kept (a surviving
    # cite grounds it) but must carry `confabulated_dropped` so the package does not present a
    # partially-confabulated finding as clean. BEFORE the fix the dropped id vanished from the finding.
    out = {
        "findings": [{"finding": "Ocular tox", "kind": "eye", "cited_pmids": ["111", "999"]}],
        "corroborations": [],
        "contradicts_deterministic": False,
        "notes": "",
    }
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={}, n_retrieved=5)
    assert g["findings"][0]["cited_pmids"] == ["111"]
    assert g["findings"][0]["confabulated_dropped"] == ["999"]  # per-finding partial-confab annotation
    assert "prose_references_dropped_pmid" not in g["findings"][0]  # prose does not name 999


def test_residual_prose_naming_dropped_pmid_is_flagged():
    # (#1614 facet a) the residual-prose hole: containment scrubs the id-list but the finding text still
    # literally names the confabulated PMID's digits — flag it so the reader knows the prose out-runs
    # its surviving support. BEFORE the fix the prose was kept verbatim with no annotation.
    out = {
        "findings": [
            {
                "finding": "A phase III trial (PMID 99999999) showed 40% hepatotox",
                "kind": "liver",
                "cited_pmids": ["111", "99999999"],
            }
        ],
        "corroborations": [],
        "contradicts_deterministic": False,
        "notes": "",
    }
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={}, n_retrieved=5)
    assert g["findings"][0]["prose_references_dropped_pmid"] is True
    assert g["findings"][0]["confabulated_dropped"] == ["99999999"]


def test_discordance_reset_when_every_finding_is_quarantined():
    # (#1614 facet c) contradicts_deterministic may only stand on ≥1 SURVIVING grounded finding. When
    # every finding is quarantined (zero surviving citation), the discordance flag rested on
    # confabulated support and is RESET. BEFORE the fix it was copied straight from the LLM (True).
    out = {
        "findings": [{"finding": "engine is wrong", "kind": "x", "cited_pmids": ["999"]}],  # 999 not retrieved
        "corroborations": [],
        "contradicts_deterministic": True,
        "notes": "",
    }
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={}, n_retrieved=5)
    assert g["findings"] == []  # quarantined
    assert g["dropped_uncited_findings"]  # the finding is carried in the review lane
    assert g["contradicts_deterministic"] is False  # discordance reset — no surviving support


def test_discordance_survives_with_a_surviving_finding():
    # complement: with ≥1 surviving grounded finding the discordance flag stands
    out = {
        "findings": [{"finding": "engine is wrong", "kind": "x", "cited_pmids": ["111"]}],
        "corroborations": [],
        "contradicts_deterministic": True,
        "notes": "",
    }
    g = ga.build_grounded_block(DET, out, {"111"}, corpus_pin={}, n_retrieved=5)
    assert g["findings"] and g["contradicts_deterministic"] is True


def test_severity_passthrough_and_safe_default():
    # a valid severity is carried through verbatim; a missing/off-enum severity defaults to 'moderate'
    # so the pseudo-card bin never crashes or silently escalates. A bare-string (uncited) finding is
    # quarantined out of the live findings list (grounding-integrity: no bin on uncited support).
    out = {
        "findings": [
            {"finding": "Ph3 discontinued", "kind": "x", "severity": "high", "cited_pmids": ["1"]},
            {"finding": "some context", "kind": "x", "severity": "bogus", "cited_pmids": ["1"]},
            {"finding": "no severity field", "kind": "x", "cited_pmids": ["1"]},
            "bare string finding",
        ],
        "corroborations": [],
        "contradicts_deterministic": False,
        "notes": "",
    }
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
    # #1635: over-budget abstracts are head+tail fitted (not blind head-sliced), so the shown text
    # stays within budget and the tail (RESULTS/CONCLUSIONS) survives. The interpolated abstract body
    # carries the truncation marker and never exceeds the budget.
    fitted = ga._fit_abstract(long, ga.ABSTRACT_CHARS)
    assert ga._ABSTRACT_TRUNC_MARKER in fitted
    assert len(fitted) <= ga.ABSTRACT_CHARS
    p_default = ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_, sentinel="tok")
    assert fitted in p_default
    # explicit override is honored (smaller budget → smaller fitted body)
    small = ga._fit_abstract(long, 100)
    assert len(small) <= 100
    assert small in ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_, abstract_chars=100, sentinel="tok")


def test_fit_abstract_preserves_conclusion_tail():
    # A structured oncology abstract whose escalating CONCLUSIONS sentence lives PAST char 1500 must
    # remain in-window — a blind head-slice would drop it while its PMID still passes containment.
    body = (
        "BACKGROUND: "
        + ("filler background text. " * 90)
        + "RESULTS: "
        + ("filler results text. " * 40)
        + "CONCLUSIONS: unexpected on-target cardiotoxicity was observed in the trial cohort."
    )
    assert len(body) > ga.ABSTRACT_CHARS
    fitted = ga._fit_abstract(body, ga.ABSTRACT_CHARS)
    assert len(fitted) <= ga.ABSTRACT_CHARS
    assert "unexpected on-target cardiotoxicity" in fitted  # the tail conclusion survived
    assert fitted.startswith("BACKGROUND:")  # head framing survives too
    # short abstracts pass through verbatim
    assert ga._fit_abstract("short", ga.ABSTRACT_CHARS) == "short"


def test_prompt_fences_each_abstract_with_sentinel():
    # #1635b: every interpolated abstract is wrapped in the per-run random delimiter the SYSTEM prompt
    # names as the untrusted-data boundary.
    from types import SimpleNamespace

    abs_ = [SimpleNamespace(pmid="1", title="T", abstract="body")]
    p = ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_, sentinel="deadbeef")
    assert "BEGIN-UNTRUSTED-deadbeef" in p and "END-UNTRUSTED-deadbeef" in p
    # the fence is randomized per run when not supplied
    p1 = ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_)
    p2 = ga._prompt("KRAS", "COADREAD", "safety", "concern", abs_)
    assert "BEGIN-UNTRUSTED-deadbeef" not in p1  # a fresh random token, not the test literal
    assert p1 != p2  # per-run randomization


def test_axis_config_has_all_rolled_out_axes_with_complete_framing():
    assert {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm"} <= set(ga.AXIS_CONFIG)
    nouns = {cfg["finding_noun"] for cfg in ga.AXIS_CONFIG.values()}
    assert len(nouns) == len(ga.AXIS_CONFIG)  # each axis has a DISTINCT finding noun
    for ax, cfg in ga.AXIS_CONFIG.items():
        assert cfg["pubmed_category"] and cfg["kinds"] and cfg["finding_noun"]
        if cfg.get("pseudo_card"):  # engine-blind pseudo-card
            assert cfg["verdict_key"] is None and cfg["cards"] == []
        else:  # engine-anchored axis
            assert cfg["verdict_key"] and cfg["cards"]


def test_skills_path_resolves_for_live_imports():
    # regression guard: `_skills_common` resolves for ground_axis's call-time live imports. This used
    # to require a module-level `_SKILLS` sys.path insert pointing at skills/ (a merged bug once
    # computed parents[2] = repo root and broke the live path). Since skills#2238 the `skills-common`
    # distribution is editable-installed into the workspace env, so ground_axis imports
    # `_skills_common.llm` with no sys.path hack — the guard now asserts the import itself resolves
    # to the real skills/_skills_common package, which is the invariant the old `_SKILLS` check stood in for.
    import importlib
    from pathlib import Path

    mod = importlib.import_module("_skills_common")
    assert Path(mod.__file__).resolve().parent.name == "_skills_common"
    # and the symbols ground_axis pulls at import time are actually bound (the live import worked)
    assert ga.synthesize_structured is not None and ga.EVIDENCE_ONLY_DIRECTIVE is not None


def test_deterministic_block_selects_axis_cards():
    pkg = {
        "synthesis": {"sub_verdicts": {"dependency": {"verdict": "lineage_selective", "driving_rule_id": "d"}}},
        "cards": [
            {"card_id": "dependency-lineage-selectivity", "interpretation_call": "lineage_selective"},
            {"card_id": "gnomad-lof-constraint", "interpretation_call": "tolerant"},
        ],
    }
    d = ga.deterministic_block(pkg, "dependency")
    assert d["verdict"] == "lineage_selective"
    assert "dependency-lineage-selectivity" in d["cards"]  # dependency card included
    assert "gnomad-lof-constraint" not in d["cards"]  # safety card excluded from dependency axis


def test_all_indication_conditioned_subskill_axes_configured():
    # The 9 grounded engine axes (verdict-anchored). CONSOLIDATION CLEANUP 2026-08-21: the former
    # synthetic_lethal_partners / combinatorial_dependency axes were REMOVED — those shorts consolidated
    # 2026-08-20 into the gateless combination_vulnerability sub-skill (verdict=None), so their verdict_key
    # no longer resolves. This test now DOUBLES AS THE ANTI-DRIFT GUARD: it pins the real covered set AND
    # asserts the orphaned keys stay gone (re-adding one fails here).
    expected = {
        "safety",
        "dependency",
        "selectivity",
        "surface_modality",
        "tractability_sm",
        "mechanism",
        "genomic_alteration",
        "differentiation",
        "expression",
    }
    assert expected <= set(ga.AXIS_CONFIG)
    # NOT grounded — deliberately (see module docstring): gateless / not-yet-wired / consolidated-away.
    for absent in (
        "target_intrinsic",
        "combination_vulnerability",
        "immune_context",
        "cis_coherence",
        "synthetic_lethal_partners",
        "combinatorial_dependency",
    ):
        assert absent not in ga.AXIS_CONFIG, (
            f"{absent!r} must not be a grounded axis (consolidation orphan or deliberately un-grounded)"
        )
    # each newly-rolled-out axis anchors to a real sub-verdict (not a pseudo-card) with complete framing
    for ax in expected - {"safety", "dependency", "selectivity", "surface_modality", "tractability_sm"}:
        cfg = ga.AXIS_CONFIG[ax]
        assert cfg["verdict_key"] == ax and cfg["cards"]  # engine-anchored
        assert not cfg.get("pseudo_card")
        assert cfg["pubmed_category"] in {
            "biological",
            "druggability",
            "translational",
            "clinical",
            "safety",
            "commercial",
        }
        assert "WEAKENING" in cfg["finding_noun"] or "DISCORDANCE" in cfg["finding_noun"]  # escalate-only


def test_new_axis_deterministic_block_reads_its_verdict():
    # a mechanism axis reads the mechanism sub-verdict + its cards, ignoring other axes' cards
    pkg = {
        "synthesis": {"sub_verdicts": {"mechanism": {"verdict": "well_characterized", "driving_rule_id": "m1"}}},
        "cards": [
            {"card_id": "signaling-network-mechanism", "interpretation_call": "clear_moa"},
            {"card_id": "gnomad-lof-constraint", "interpretation_call": "tolerant"},
        ],
    }
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
    qs = {
        ax: ga._axis_query("FOO", "lung cancer", ax)
        for ax in ("dependency", "mechanism", "genomic_alteration", "expression")
    }
    assert len(set(qs.values())) == 4  # all distinct, not one shared 'biological' query


def test_axis_query_unknown_axis_is_target_only():
    q = ga._axis_query("FOO", "lung cancer", "not_an_axis")
    assert q == "(FOO) AND ()" or "FOO" in q  # defensive: no crash, gene present


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
    angles = ga._keyword_angles(
        "KRAS", "colorectal cancer", "dependency", '"colorectal neoplasms"[MeSH Terms]', disease_scoped=True
    )
    assert len(angles) == 2
    assert "colorectal cancer" in angles[0] and "dependency" in angles[0].lower()  # tight
    assert "[MeSH Terms]" in angles[1] and "dependency" in angles[1].lower()  # MeSH precision angle
    assert angles[0] != angles[1]  # complementary, not identical


def test_keyword_angles_broad_fallback_when_no_mesh():
    # no MeSH clause -> 2nd angle is the broad (axis-terms-dropped) recall angle
    angles = ga._keyword_angles("STAG1", "bladder cancer", "dependency", None, disease_scoped=True)
    assert angles[1] == "(STAG1) AND (bladder cancer)"  # broad
    assert "dependency" in angles[0].lower() and "dependency" not in angles[1].lower()


def test_keyword_angles_target_scoped_axis_uses_broad_second():
    # target-scoped axis (safety, disease_scoped=False): MeSH N/A -> tight + broad(gene-only)
    angles = ga._keyword_angles("STAG1", "bladder cancer", "safety", None, disease_scoped=False)
    assert angles[1] == "(STAG1)"
    assert "toxicity" in angles[0]


def test_interleave_round_robin_and_dedup():
    # round-robin across the three lanes (entity, OT-floor, keyword), first occurrence wins on dedup
    entity = ["e1", "e2", "e3"]
    ot = ["o1", "e2"]  # e2 overlaps entity -> deduped, keeps entity position
    kw = ["k1"]
    assert ga._interleave(entity, ot, kw) == ["e1", "o1", "k1", "e2", "e3"]
    # a missing/empty lane (e.g. PubTator down or no OT floor) is simply skipped
    assert ga._interleave([], ["o1", "o2"], []) == ["o1", "o2"]
    assert ga._interleave([], [], []) == []
    # round-robin guarantees every non-empty lane is represented early (not crowded out by a long lane)
    long_entity = [f"e{i}" for i in range(10)]
    merged = ga._interleave(long_entity, ["o1"], ["k1"])
    assert merged.index("o1") <= 2 and merged.index("k1") <= 2


# =============================== #1696: escalate-only path shares the #1613 floor-backfill leak ===============================
# ground_axis() calls the SAME rl.retrieve_axis as run.py's grading path and inherits the same
# RELEVANCE_FLOOR=3 starvation backfill: a dim with zero on-signal (target ∧ (axis ∨ indication))
# abstracts can still be handed <=floor backfilled off-signal abstracts. Those PMIDs are legitimately in
# `retrieved`, so a model-invented escalate-only finding citing one of them would SURVIVE
# build_grounded_block's containment check. The fix mirrors #1613: gate the model call on n_on_signal,
# not on len(kept).


def _write_pkg(tmp_path, verdict_key="safety", verdict="tolerant_null"):
    import json

    pkg = {
        "synthesis": {"sub_verdicts": {verdict_key: {"verdict": verdict, "driving_rule_id": "r1"}}},
        "cards": [],
    }
    p = tmp_path / "pkg.json"
    p.write_text(json.dumps(pkg))
    return str(p)


class _GAb:
    def __init__(self, pmid):
        self.pmid, self.year, self.title, self.abstract = pmid, 2020, "t", "body"


def test_ground_axis_abstains_when_retrieval_is_all_off_signal_backfill(tmp_path, monkeypatch):
    # kept is non-empty (floor backfill) but n_on_signal == 0 -> the model must NOT be consulted, and the
    # grounded block must carry zero findings + the insufficient_relevant_evidence flag, exactly like
    # run.py's not_assessed abstain for the grading path.
    def _backfilled(target, indication, axis, **k):
        return {"kept": [_GAb("111")], "dropped": [], "n_on_signal": 0}

    called = {"n": 0}

    def _spy_synth(*a, **k):
        called["n"] += 1
        raise AssertionError("model must not be consulted when there is zero relevant (on-signal) evidence")

    monkeypatch.setattr(ga.rl, "retrieve_axis", _backfilled)
    monkeypatch.setattr(ga, "synthesize_structured", _spy_synth)
    rec = ga.ground_axis("GENE", "some-indication", _write_pkg(tmp_path), axis="safety")
    assert called["n"] == 0  # deterministic abstain — no model judgment on off-signal-only retrieval
    grounded = rec["grounded"]
    assert grounded["findings"] == []
    assert grounded["n_on_signal"] == 0
    assert grounded["insufficient_relevant_evidence"] is True
    assert grounded["n_retrieved"] == 1  # audit trail: abstracts WERE retrieved, just none relevant
    assert grounded["contradicts_deterministic"] is False


def test_ground_axis_still_grounds_thin_but_real_axis_with_floor_backfill(tmp_path, monkeypatch):
    # #1696 counterpart: the floor's legitimate starvation-prevention is preserved — with >=1 on-signal
    # abstract (n_on_signal == 1) the model IS still consulted even though the floor backfilled an
    # off-signal abstract alongside it.
    def _thin(target, indication, axis, **k):
        return {"kept": [_GAb("111"), _GAb("222")], "dropped": [], "n_on_signal": 1}

    monkeypatch.setattr(ga.rl, "retrieve_axis", _thin)
    monkeypatch.setattr(
        ga,
        "synthesize_structured",
        lambda *a, **k: {
            "findings": [{"finding": "hepatic tox", "kind": "liver", "cited_pmids": ["111"]}],
            "corroborations": [],
            "contradicts_deterministic": False,
            "notes": "",
        },
    )
    rec = ga.ground_axis("GENE", "some-indication", _write_pkg(tmp_path), axis="safety")
    grounded = rec["grounded"]
    assert grounded["n_on_signal"] == 1
    assert "insufficient_relevant_evidence" not in grounded
    assert [f["finding"] for f in grounded["findings"]] == ["hepatic tox"]


def test_ground_axis_true_dry_query_has_no_insufficient_relevant_flag(tmp_path, monkeypatch):
    # a genuinely empty retrieval (kept == [], n_on_signal == 0) is a dry query, not an active
    # off-signal-only relevance decision — the abstain still fires (no model call) but the
    # insufficient_relevant_evidence flag (reserved for "retrieved but all off-signal") stays absent.
    def _dry(target, indication, axis, **k):
        return {"kept": [], "dropped": [], "n_on_signal": 0}

    monkeypatch.setattr(ga.rl, "retrieve_axis", _dry)
    monkeypatch.setattr(
        ga, "synthesize_structured", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no model call"))
    )
    rec = ga.ground_axis("GENE", "some-indication", _write_pkg(tmp_path), axis="safety")
    grounded = rec["grounded"]
    assert grounded["n_on_signal"] == 0
    assert grounded["n_retrieved"] == 0
    assert "insufficient_relevant_evidence" not in grounded
