"""flow.py — the workflow schema diagrams, at MULTIPLE altitudes.

The framework is legible at different zoom levels, so the Flow tab renders several diagrams
behind a level picker:

  1. overview     — 10,000 ft: dataset -> method -> card -> rule -> verdict -> skill -> package
  2. card         — anatomy of ONE real card (inputs · method · outputs/vocab · identity)
  3. post_card    — card label -> rule fires -> resolver ladder -> verdict emission
  4. narration    — verdicts + capsules -> enum-locked LLM prompt -> fail-closed clamp
  5. composition  — target-profile fan-out -> synthesis -> evidence package -> downstream

Each level is a small data model (`layout` = pipeline | hub | lanes) the renderer draws as a
self-contained SVG/CSS diagram. Where the graph has the facts (the example card's anatomy, the
target-profile fan-out list) the level is DATA-DRIVEN; the rest is a curated worked example
(KRAS in COADREAD, dependency gate) whose tokens are REAL contract tokens, verified by
`flow_token_errors()` so the diagram cannot drift away from the contracts.
"""

from __future__ import annotations

WORKED = {"target": "KRAS", "indication": "COADREAD", "gate": "dependency"}
EXAMPLE_CARD = "pan-cancer-crispr-dependency-distribution"

# tokens the diagrams surface; validated against the graph glossary (self-check).
WORKED_TOKENS = {
    "measurement_type": "crispr_lof_dependency",
    "card": EXAMPLE_CARD,
    "rule": "strongly-selective-supportive",
    "verdict": "selective_dependent",
    "gate": "dependency",
}


# --------------------------------------------------------------------------- #
# Monospace "wire" schematics — one per level that has a natural topology (fan-in,
# lanes, clamp, fork) the box layout can't show. «tokens» are injected from the graph
# (real card/rule/verdict/measurement_type ids) so the schematics are drift-checked too.
# --------------------------------------------------------------------------- #
SCHEMATICS = {
    "overview": r"""
  ┌── CARD: «card» ──────────────────────────────────────────┐
  │ emits ONE closed-vocab label:  dependency_class = strongly_selective │
  └───────────────────────────┬──────────────────────────────┘
                   same evidence forks 3 ways
      ┌────────────────────────┼────────────────────────┐
      ▼                        ▼                         ▼
 ╔═══════════╗          ╔═════════════╗           ╔═════════════╗
 ║ A DECIDES ║          ║ B DESCRIBES ║           ║ C NARRATES  ║
 ║  (spine)  ║          ║  (signals)  ║           ║  (LLM pkg)  ║
 ╠═══════════╣          ╠═════════════╣           ╠═════════════╣
 ║ rule      ║          ║ claim vector║           ║ capsule     ║
 ║   ↓       ║          ║   ↓         ║           ║  + A + B    ║
 ║ resolver  ║          ║ subgroup    ║           ║  (as text)  ║
 ║   ↓       ║          ║   ↓         ║           ║   ↓ propose ║
 ║ VERDICT   ║          ║ certainty   ║           ║   ↓ CLAMP   ║
 ╚═══════════╝          ╚═════════════╝           ╚═════════════╝
 authoritative           ranks only                narrates only
      ▲                                                  │
      └──────────────── clamp reads A's verdict ◀────────┘
  Only A moves the verdict. B ranks it, C explains it; neither feeds back.
""",
    "card": r"""
  STEP 0 · THE CARD EMITS
    CARD  «card»
      dependency_class = strongly_selective        ← the decision datum
      median_chronos = -0.30 · frac_strong = 0.18  ← numerics (context)
      capsule.primary_class = dependency_class
          ├────────▶ LANE A · DECIDES              (authoritative)
          ├────────▶ LANE B · DESCRIBES / RANKS    (verdict-inert)
          └────────▶ LANE C · NARRATES             (verdict-inert)

  LANE A · DECIDES ────────────────────────────────────────────────
    A1  rule: when dependency_class ∈ {strongly_selective}
            ▸ fires «rule»  {small_molecule: supportive}
    A2  + rules from sibling cards  ▸  FIRED-RULE SET { … }
    A3  resolver ladder («gate»): first / priority match
            ▸ verdict = «verdict» · driving_rule = «rule»
    A4  ▸ decision.json / sub_verdict  (byte-stable) ────────────┐ outputs
                                                                 │ read
  LANE B · DESCRIBES / RANKS ─────────────────────────────────  │ only,
    B1  claim_vector[DEP]: signal = strong · corroboration = low │ by C
            (RNAi conflict caps corroboration · gap → None, not 0)│
    B2  subgroup rollup: card→question→sub_group by «mtype»      │
            confidence = agreement × power (capped by conflict)  │
    B3  certainty_by_axis  (DISJOINT — corroboration card fires  │
            no resolver rung → confidence never double-counts)   │
    B4  ▸ question table + narrator signals (display / prompt) ──┤
                                                                 │
  LANE C · NARRATES ──────────────────────────────────────────  │
    C1  evidence_capsule(card): primary_class + top_k strata +   │
            numeric/categorical anchors + conflicts (hash-stable)│
    C2  prompt = capsule ⊕ sub_verdicts(◀A4) ⊕ signals(◀B1/B4) ⊕ fired rules
    C3  enum-locked tool_use ▸ LLM PROPOSES  rec = "hold"  (_source: llm_synthesized)
    C4  CLAMP: nomination gate reads A's verdict ▸ killer ⇒ overwrite ⇒ VETO
            (_gated; original llm value retained)
    C5  ▸ PACKAGE.synthesis slot (prose, gated)  ⟂  sub_verdicts slot (= A4)

  INVARIANTS
   • A is the only decider; B and C have no back-edge into A (verdict byte-stable without them).
   • B: signal ⟂ corroboration; unmeasured → None (never averaged as 0); certainty disjoint.
   • C: LLM reads A+B as read-only text, proposes in enum-locked slots, gate clamps; two slots.
""",
    "post_card": r"""
   cards (emit labels)                    rules fire  (rule_id : signal)
 ┌──────────────────────────┐
 │ «card»                   │─ dependency_class=strongly_selective ─▶ «rule»            ┐
 │ partner-conditional-dep. │─ partner_class=moderately_dep        ─▶ partner-cond-supp │ fired
 │ crispr-rnai-concordance  │─ concordance_class=discordant        ─▶ concordance-warn  │  set
 └──────────────────────────┘                                                          ┘
                                       │
                                       ▼   «gate».resolver.yaml  (ordered; first/priority wins)
        ┌───────────────────────────────────────────────────────────────┐
        │  0  pan_essential_killer          when_fired …          ✗       │
        │  4  «verdict»                     when_fired: «rule»     ✔ MATCH │
        │ 14  non_dependent (VETO)          when_fired: non-dep…  (lower)  │
        │ …   default: insufficient                                       │
        └───────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
             verdict = «verdict» · driving_rule_id = «rule»  ▸ decision.json
""",
    "narration": r"""
 DETERMINISTIC SPINE (authoritative)
 ───────────────────────────────────────────────────────────────
   fired rules ─▶ resolver ─▶ sub_verdicts ───────────────┐
                                  (safety: killer)         │ read-only
                                        ┌─────────────────┐│
                                        │ NOMINATION GATE │◀┘
                                        │  fail-closed    │
                                        └───────┬─────────┘
                                    forced=veto │  ▲ overwrite (keeps llm_recommendation)
                                                ▼  │
                        overall_recommendation = VETO  (_gated=true)
 ───────────────────────────────────────────────────────────────
 LLM LANE (advisory)                              │ proposes "hold"
   capsule ⊕ sub_verdicts ⊕ signals (as TEXT) ─▶ LLM ─┘  (_source: llm_synthesized)
   → enum-locked: recommendation ∈ {nominate,hold,veto,insufficient}
""",
    "composition": r"""
        ┌──────────────── target-profile (composed root) ────────────────┐
        │        fan out in parallel · reassemble in fixed order          │
        └───────────────┬─────────┬─────────┬─────────┬──────────────────┘
                 ▼       ▼         ▼         ▼         ▼   … 13 skills
             presence  funct-req  genomic  surface   safety  ── each resolves
                 └───────┴─────────┴────┬────┴─────────┘          its OWN sub-verdict
                           inherit sub_verdicts (never re-resolve)
                                        ▼
                 ┌─────────────────────────┐      ┌──────────────────────────┐
                 │ nomination GATE (clamp) │◀────▶│ Tier-3 LLM synthesis      │
                 │ 8 gated · 5 gateless    │      │ (prose, clamped)          │
                 └────────────┬────────────┘      └──────────────────────────┘
                              ▼
                 evidence package → data-products → registry · dashboards · query
""",
}


def _fill_schematic(art: str, graph: dict) -> str:
    """Inject real contract tokens into a schematic template (drift-checked separately)."""
    reps = {
        "«card»": WORKED_TOKENS["card"],
        "«rule»": WORKED_TOKENS["rule"],
        "«verdict»": WORKED_TOKENS["verdict"],
        "«gate»": WORKED_TOKENS["gate"],
        "«mtype»": WORKED_TOKENS["measurement_type"],
    }
    for k, v in reps.items():
        art = art.replace(k, v)
    return art.strip("\n")


def flow_token_errors(graph: dict) -> list:
    errs = []
    gl = graph.get("glossary") or {}
    for kind, tok in WORKED_TOKENS.items():
        if tok not in (gl.get(kind) or {}):
            errs.append(f"flow worked-example {kind} '{tok}' no longer exists (diagram stale — update flow.py)")
    return errs


def _node(label, kind, plain, example=None, artifact=None, token=None, token_kind=None, concept=None, tag=None):
    return {
        "label": label,
        "kind": kind,
        "plain": plain,
        "example": example,
        "artifact": artifact,
        "token": token,
        "token_kind": token_kind,
        "concept": concept,
        "tag": tag,
    }


# --------------------------------------------------------------------------- #
# Level 1 — 30,000 ft: the 5-repo topology (where everything lives).
# --------------------------------------------------------------------------- #
def _level_repos():
    stages = [
        _node(
            "data-catalog",
            "source_manifest",
            "Source-of-record for WHAT data exists + WHERE. Manifest YAMLs (pointers + provenance); bytes live on S3.",
            "manifests/{sources,derived}/*.yaml",
            "resolver-releases · subgroup-catalogs",
        ),
        _node(
            "analysis-methods",
            "method",
            "Deterministic COMPUTE. fn(target,indication) → numbers/labels. Never a verdict.",
            "onc_methods/<name>/{read,cli}.py",
            "reads catalog products → derived parquet",
        ),
        _node(
            "target-contracts",
            "card",
            "The GOVERNANCE spine: cards, interpretation-rules, resolvers, vocabularies, schemas, validators.",
            "cards/ · interpretation-rules/ · resolvers/",
            "contracts-first",
        ),
        _node(
            "claude-oncology-skills",
            "skill",
            "ORCHESTRATION: one skill per question + the composed target-profile fan-out.",
            "skills/<name>/{SKILL.md,run.py}",
            "shared resolver kernel",
        ),
        _node(
            "data-products",
            "evidence_package",
            "Terminal OUTPUT surface: evidence packages per target×indication, provenance-pinned.",
            "<TARGET>/<INDICATION>/ep-*/",
            "+ output registry / dashboards",
        ),
    ]
    return {
        "id": "repos",
        "title": "1 · 30,000 ft — the five repos",
        "subtitle": "Where everything lives. The dependency arrow runs left→right: catalog "
        "(data) → methods (compute) → contracts (govern) → skills (orchestrate) → "
        "products (output). Bytes never live in git — only pointers + contracts.",
        "layout": "pipeline",
        "stages": stages,
        "lane": None,
    }


# --------------------------------------------------------------------------- #
# Level 2 — 10,000 ft overview (the whole spine + narration lane).
# --------------------------------------------------------------------------- #
def _level_overview():
    stages = [
        _node(
            "Dataset",
            "source_manifest",
            "External data recorded in the catalog; gene-sorted parquet on S3.",
            "DepMap 26Q1 · CRISPRGeneEffect.csv",
            "manifest: depmap-consortium-26q1",
            concept="source_manifest",
        ),
        _node(
            "Method",
            "method",
            "Deterministic compute → numbers + labels. No verdict.",
            "depmap_chronos_distribution(KRAS)",
            "median_chronos = -0.30",
            concept="method",
        ),
        _node(
            "Card",
            "card",
            "Evidence contract (the hinge). Emits a closed-vocab label.",
            EXAMPLE_CARD,
            "dependency_class = strongly_selective",
            token="crispr_lof_dependency",
            token_kind="measurement_type",
            concept="card",
        ),
        _node(
            "Rule",
            "interpretation_rule",
            "Maps a label → a per-modality signal, firing a rule_id.",
            "strongly-selective-supportive",
            "→ small_molecule: supportive",
            token="strongly-selective-supportive",
            token_kind="rule",
            concept="interpretation_rule",
        ),
        _node(
            "Resolver → verdict",
            "resolver",
            "Reduces fired rule_ids → ONE verdict + driving_rule_id.",
            "dependency.resolver.yaml",
            "verdict = selective_dependent",
            token="selective_dependent",
            token_kind="verdict",
            concept="resolver",
        ),
        _node(
            "Skill",
            "skill",
            "Answers one biological question by composing its cards.",
            "functional-requirement",
            "dependency_verdict = selective_dependent",
            concept="skill",
        ),
        _node(
            "Evidence package",
            "evidence_package",
            "Terminal composed output; provenance-pinned.",
            "nomination.json",
            "sub_verdict recorded",
            concept="evidence_package",
        ),
    ]
    lane = {
        "from": "Resolver → verdict",
        "label": "LLM narration (read-only, clamped)",
        "steps": [
            "reads verdicts + rules as TEXT",
            "proposes a recommendation (enum-locked, _source-tagged)",
            "fail-closed gate CLAMPS it — killer → veto",
        ],
        "invariant": "Narrative describes the verdict; it can never move it.",
    }
    return {
        "id": "overview",
        "title": "2 · 10,000 ft — dataset → decision",
        "subtitle": "The whole spine, one real slice (KRAS in COADREAD). The left→right chain is "
        "the ONLY thing that decides; narration rides alongside, clamped.",
        "layout": "pipeline",
        "stages": stages,
        "lane": lane,
    }


# --------------------------------------------------------------------------- #
# Level 2 — card anatomy (DATA-DRIVEN from the example card in the graph).
# --------------------------------------------------------------------------- #
def _level_card(graph):
    c = (graph.get("cards") or {}).get(EXAMPLE_CARD, {})
    inputs = [ri.get("product_id") for ri in (c.get("required_inputs") or []) if ri.get("product_id")]
    methods = [m.get("call") for m in (c.get("methods") or []) if m.get("call")]
    fields = (c.get("summary_fields") or [])[:6]
    vocab_field = next(iter(c.get("vocabulary") or {}), None)
    vocab_vals = (c.get("vocabulary") or {}).get(vocab_field, [])[:5] if vocab_field else []
    center = _node(
        EXAMPLE_CARD,
        "card",
        c.get("question") or "the evidence contract",
        None,
        None,
        token="crispr_lof_dependency",
        token_kind="measurement_type",
        concept="card",
    )
    satellites = [
        {"role": "READS (required_inputs)", "items": inputs or ["—"], "kind": "source_manifest"},
        {"role": "VIA method", "items": methods or ["—"], "kind": "method"},
        {"role": "EMITS (summary_fields)", "items": fields or ["—"], "kind": "card"},
        {"role": f"VOCAB · {vocab_field}" if vocab_field else "VOCAB", "items": vocab_vals or ["—"], "kind": "card"},
        {
            "role": "IDENTITY = measurement_type × entity_grain",
            "items": [c.get("measurement_type") or "—"] + list(c.get("entity_grains") or []),
            "kind": "card",
        },
        {"role": "CONSUMED BY (skills)", "items": (c.get("consumers") or ["—"])[:6], "kind": "skill"},
    ]
    return {
        "id": "card",
        "title": "3 · Card level — anatomy of one contract",
        "subtitle": f"A real card ({EXAMPLE_CARD}). Identity is (measurement_type × entity_grain): "
        "gates PULL a type, data PUSHES a provider, so a new dataset slots in "
        "without touching any rule. Cards emit closed-vocab labels only.",
        "layout": "hub",
        "center": center,
        "satellites": satellites,
        "verdict_bearing": bool(c.get("is_verdict_bearing")),
    }


# --------------------------------------------------------------------------- #
# Level 3 — card → verdict emission (the deterministic spine, in detail).
# --------------------------------------------------------------------------- #
def _level_post_card():
    stages = [
        _node(
            "Card label",
            "card",
            "The closed-vocab datum the card emits.",
            "dependency_class = strongly_selective",
            None,
            concept="card",
        ),
        _node(
            "Rule fires",
            "interpretation_rule",
            "A rule whose `when` matches the label fires its rule_id with a per-modality signal.",
            "strongly-selective-supportive",
            "small_molecule: supportive",
            token="strongly-selective-supportive",
            token_kind="rule",
            concept="interpretation_rule",
        ),
        _node(
            "Fired-rule set",
            "interpretation_rule",
            "ALL matching rules across the gate's cards collect into a set (no arithmetic).",
            "{ strongly-selective-supportive, … }",
            None,
        ),
        _node(
            "Resolver ladder",
            "resolver",
            "Ordered precedence over the fired set; first/priority match wins; provable default.",
            "dependency.resolver.yaml",
            "rung: selective_dependent",
            token="selective_dependent",
            token_kind="verdict",
            concept="resolver",
        ),
        _node(
            "Verdict + provenance",
            "resolver",
            "One verdict token + the driving_rule_id that produced it.",
            "verdict = selective_dependent",
            "driving_rule = strongly-selective-supportive",
        ),
        _node(
            "decision.json → package",
            "evidence_package",
            "Written to the skill's decision + the composed evidence package, byte-stable.",
            "decision.json",
            "sub_verdict recorded",
            concept="evidence_package",
        ),
    ]
    return {
        "id": "post_card",
        "title": "4 · Card → verdict — the deterministic spine",
        "subtitle": "How a label becomes an auditable verdict. Rules turn labels into signals; "
        "the resolver reduces the fired SET to one verdict — pattern-match only, "
        "no arithmetic — and records which rule drove it.",
        "layout": "pipeline",
        "stages": stages,
        "lane": None,
    }


# --------------------------------------------------------------------------- #
# Level 5 — the signals layer (verdict-INERT re-projection beside the spine).
# --------------------------------------------------------------------------- #
def _level_signals():
    stages = [
        _node(
            "Card evidence",
            "card",
            "The same card labels the verdict spine reads — re-projected, never re-decided.",
            "dependency_class = strongly_selective",
            None,
            concept="card",
        ),
        _node(
            "Claim vector",
            "interpretation_rule",
            "Orthogonal axes, each with an INDEPENDENT (signal × corroboration). "
            "unmeasured → None, so a gap is never averaged as a zero.",
            "DEP: strong · CHEM: unmeasured",
            "signal ⟂ corroboration",
        ),
        _node(
            "Corroboration / conflict",
            "interpretation_rule",
            "A second AGREEING assay raises corroboration (never the signal); a disagreeing "
            "one caps it and surfaces a conflict.",
            "RNAi agrees → corroboration↑",
            "sub-additive",
        ),
        _node(
            "Subgroup rollup",
            "skill",
            "Signals roll up card → question → sub-group by measurement_type; confidence = "
            "agreement × power, capped by conflict (not weakest-link).",
            "overlay_claim_signals",
            "authoritative sub-group signal",
        ),
        _node(
            "Certainty (disjoint)",
            "resolver",
            "A separate per-axis certainty sidecar — corroboration cards must fire NO verdict "
            "rung (enforced), so confidence never double-counts the verdict.",
            "certainty_by_axis",
            "verdict-inert",
        ),
    ]
    lane = {
        "from": "Certainty (disjoint)",
        "label": "Why it sits BESIDE the spine",
        "steps": [
            "re-projects the same evidence for ranking + prompting",
            "reachability proves which cards can move a verdict vs enrich it",
        ],
        "invariant": "The signals layer never feeds the resolver — verdict byte-stable with or without it.",
    }
    return {
        "id": "signals",
        "title": "5 · Signals layer — beside the spine (verdict-inert)",
        "subtitle": "The richer re-projection humans + the LLM read: signal separated from "
        "corroboration, gaps kept distinct from negatives, confidence held "
        "disjoint from signal. It ranks and explains; it never decides.",
        "layout": "pipeline",
        "stages": stages,
        "lane": lane,
    }


# --------------------------------------------------------------------------- #
# Level 6 — card/verdict → narration LLM (the parallel, clamped lane).
# --------------------------------------------------------------------------- #
def _level_narration():
    stages = [
        _node(
            "Verdicts + fired rules",
            "resolver",
            "The deterministic sub-verdicts, driving rules, and rule rationales — as TEXT.",
            "selective_dependent (+ rationale)",
            None,
        ),
        _node(
            "Evidence capsules",
            "card",
            "Hash-stable, bounded per-card data packages (primary_class + anchors). Read-only.",
            "capsule(pan-cancer-crispr-…)",
            "primary_class = dependency_class",
            concept="card",
        ),
        _node(
            "Enum-locked prompt",
            "evidence_package",
            "Forced structured tool_use. Recommendation + confidence are ENUM-locked so the LLM cannot free-form them.",
            "target_profile_synthesis(tool)",
            "recommendation ∈ {nominate,hold,veto,insufficient}",
        ),
        _node(
            "LLM proposes",
            "evidence_package",
            "Prose + a PROPOSED recommendation, every field tagged _source: llm_synthesized.",
            "proposes: hold",
            "_model_id · _prompt_hash",
        ),
        _node(
            "Fail-closed gate",
            "resolver",
            "A killer sub-verdict OVERWRITES the proposal (blind axis ≠ kill; positives only "
            "raise confidence). The original is kept on record.",
            "gate: safety killer fires",
            "forced = veto (_gated=true)",
        ),
    ]
    lane = {
        "from": "Fail-closed gate",
        "label": "Two-slot invariant",
        "steps": [
            "deterministic spine + LLM prose live in DISTINCT schema slots",
            "the clamp is one-directional (can only be more conservative)",
        ],
        "invariant": "The LLM sees read-only text and proposes; the rules decide.",
    }
    return {
        "id": "narration",
        "title": "6 · Card → narration LLM — read-only, clamped",
        "subtitle": "How prose rides on top WITHOUT touching the verdict. The LLM consumes "
        "capsules + verdicts as text, proposes in enum-locked slots, and a "
        "fail-closed gate clamps the proposal.",
        "layout": "pipeline",
        "stages": stages,
        "lane": lane,
    }


# --------------------------------------------------------------------------- #
# Level 5 — composed skills → downstream (DATA-DRIVEN fan-out list).
# --------------------------------------------------------------------------- #
def _level_composition(graph):
    fanout = graph.get("fanout") or []
    n = len(fanout)
    stages = [
        _node(
            "target-profile",
            "skill",
            f"The composed root. Fans out (in parallel, in-process) to {n} focused skills.",
            "run.py --target KRAS --indication COADREAD",
            f"{n} sub-skills",
            concept="skill",
        ),
        _node(
            f"{n} focused skills",
            "skill",
            "Each answers one question and resolves its own verdict via the shared resolver.",
            ", ".join(fanout[:6]) + (" …" if n > 6 else ""),
            "per-gate sub-verdicts",
        ),
        _node(
            "Inherit sub-verdicts",
            "resolver",
            "The composer INHERITS each sub-verdict from the shared spine — never re-resolves.",
            "sub_verdicts[]",
            "byte-stable",
        ),
        _node(
            "Synthesis + substrate",
            "evidence_package",
            "Tier-3 LLM synthesis (clamped) + ground→risk→hypothesis substrate chain (verdict-inert).",
            "executive_summary · risk_rollup · hypothesis",
            None,
        ),
        _node(
            "Evidence package",
            "evidence_package",
            "target_profile.md + nomination.json + provenance, pinned to manifest versions.",
            "ep-kras-coadread-…",
            "governance.resolved_releases",
            concept="evidence_package",
        ),
        _node(
            "data-products",
            "evidence_package",
            "The terminal output surface — one dir per target×indication.",
            "KRAS/COADREAD/ep-…",
            None,
        ),
        _node(
            "Downstream ingestions",
            "source_manifest",
            "Output registry (catalog.json/coverage), dashboards, and retrieval skills "
            "(query-target-evidence) consume the packages.",
            "output_registry · dashboards · query-target-evidence",
            None,
            tag="downstream",
        ),
    ]
    return {
        "id": "composition",
        "title": "7 · Composed skills → downstream",
        "subtitle": f"Zoomed OUT: target-profile fans out to {n} skills, inherits their "
        "sub-verdicts (never re-resolves), adds clamped synthesis, and writes an "
        "evidence package that downstream registries + dashboards ingest.",
        "layout": "pipeline",
        "stages": stages,
        "lane": None,
    }


# --------------------------------------------------------------------------- #
# Level 8 — substrate chain (evidence package → ground → risk → hypothesis).
# --------------------------------------------------------------------------- #
def _level_substrate():
    stages = [
        _node(
            "Evidence package",
            "evidence_package",
            "The finished, verdict-bearing package — the substrate chain reads it, never writes back to it.",
            "nomination.json (sub_verdicts)",
            None,
            concept="evidence_package",
        ),
        _node(
            "Ground",
            "skill",
            "literature-risk-assessment grounds each axis against live PubMed (escalate-only, PMID-cited).",
            "grounded_<axis>.json",
            "the shared substrate",
        ),
        _node(
            "Risk roll-up",
            "resolver",
            "Deterministic modality-conditioned 6-dim bins — a PURE function of sub_verdicts. "
            "Literature findings can only RAISE a flag, never change a bin.",
            "risk_rollup.json",
            "bins = f(sub_verdicts)",
        ),
        _node(
            "Risk assessment",
            "evidence_package",
            "LLM retrieval-grounded 6-dim literature read (Biological/Druggability/…). Verdict-inert display context.",
            "risk_assessment.json",
            None,
        ),
        _node(
            "Hypothesis",
            "evidence_package",
            "cross-evidence-hypothesis: cited six-part reasoning, CLAMPED to a fail-closed "
            "ceiling built from the spine's hard_gates.",
            "hypothesis.json",
            "proposed_verdict clamped to ceiling",
        ),
    ]
    lane = {
        "from": "Hypothesis",
        "label": "Best-effort + verdict-inert",
        "steps": [
            "default-ON in a full run; auto-skipped offline/fast",
            "the hypothesis body replaces the exec-summary on the dashboard — "
            "but the header verdict stays the deterministic scalar",
        ],
        "invariant": "The substrate enriches; the spine's hard_gates still bound it.",
    }
    return {
        "id": "substrate",
        "title": "8 · Substrate chain — ground → risk → hypothesis",
        "subtitle": "The richest downstream reading, layered on the FINISHED package. Ground "
        "cites literature; the risk roll-up's bins are a pure function of the "
        "sub-verdicts; the hypothesis is clamped to the spine's kill set.",
        "layout": "pipeline",
        "stages": stages,
        "lane": lane,
    }


# --------------------------------------------------------------------------- #
# Level 9 — governance loop (how the framework stays honest = contracts-first).
# --------------------------------------------------------------------------- #
def _level_governance():
    stages = [
        _node(
            "Schemas + vocab",
            "card",
            "Contracts-first: schemas, measurement-type + verdict-token vocabularies are "
            "authored + validated BEFORE methods/skills conform.",
            "schemas/*.json · vocabularies/*.yaml",
            "the source of truth",
        ),
        _node(
            "Validators (CI)",
            "resolver",
            "14 gap-detection validators enforce referential integrity — orphan rules, dangling "
            "rungs, verdict-token case-match, measurement-type rot.",
            "validators/validate_*.py",
            "contracts-validate.yml",
        ),
        _node(
            "Golden tests",
            "evidence_package",
            "Known-target backtests against checked-in decision SNAPSHOTS "
            "(must_not_veto / abstention_expected / known_gap_expected_fail).",
            "tests/calibration/snapshots/*.json",
            "deterministic, CI-safe",
        ),
        _node(
            "Drift guards",
            "skill",
            "Generated artifacts (this living doc, framework_health, question-hierarchies) carry "
            "--self-check / --check so a stale commit fails CI.",
            "build_*.py --self-check",
            "generated, never hand-drifts",
        ),
        _node(
            "This living doc",
            "evidence_package",
            "Surfaces every gap the validators + health rollup find in ONE ranked place — the loop, made legible.",
            "Gaps tab (189 items)",
            None,
            tag="downstream",
        ),
    ]
    lane = {
        "from": "This living doc",
        "label": "The invariant that makes it auditable",
        "steps": [
            "cards emit labels · rules fire signals · resolvers decide — one shared kernel",
            "everything else (signals, narration, substrate) is verdict-inert by construction",
        ],
        "invariant": "Rules decide; everything else describes. Every override is on the record.",
    }
    return {
        "id": "governance",
        "title": "9 · Governance loop — how it stays honest",
        "subtitle": "Contracts-first, top to bottom: schemas/vocab lead, validators + golden "
        "tests + drift guards enforce, and this document exposes what slips. The "
        "reason the deterministic verdict can be trusted.",
        "layout": "pipeline",
        "stages": stages,
        "lane": lane,
    }


# Navigation graph — how the altitudes COMPOSE. PARENT = the level to zoom back OUT to.
# DRILL = per-level, which stage (by label) zooms IN to which level (connecting the views).
PARENT = {
    "repos": None,
    "overview": "repos",
    "card": "overview",
    "post_card": "overview",
    "signals": "overview",
    "narration": "overview",
    "composition": "overview",
    "substrate": "composition",
    "governance": None,
}
DRILL = {
    "repos": {
        "data-catalog": "overview",
        "analysis-methods": "overview",
        "target-contracts": "card",
        "claude-oncology-skills": "composition",
        "data-products": "composition",
    },
    "overview": {
        "Card": "card",
        "Rule": "post_card",
        "Resolver → verdict": "post_card",
        "Skill": "composition",
        "Evidence package": "composition",
    },
    "card": {},
    "post_card": {"Rule fires": "narration"},
    "signals": {},
    "narration": {},
    "composition": {"Evidence package": "substrate"},
    "substrate": {},
    "governance": {},
}
# lane -> drill target (the narration lane on overview zooms into the narration level)
LANE_DRILL = {"overview": "narration", "signals": "signals", "narration": "narration"}


def build_flow(graph: dict) -> dict:
    """Assemble all levels, attaching Concepts links + glossed labels + the zoom navigation
    (drift-free). Levels COMPOSE: a stage in a zoomed-out level deep-links into the level that
    expands that abstraction, and each level carries a breadcrumb back to its parent."""
    gl = graph.get("glossary") or {}
    concept_ids = {c["id"] for c in graph.get("concepts") or []}

    def _decorate_stage(st):
        comp = (gl.get("component_type") or {}).get(st.get("kind"), {})
        st["component_label"] = comp.get("label") or st.get("label")
        st["concept_present"] = st.get("concept") in concept_ids if st.get("concept") else False
        if st.get("token"):
            st["token_gloss"] = (gl.get(st["token_kind"]) or {}).get(st["token"])
        return st

    levels = [
        _level_repos(),
        _level_overview(),
        _level_card(graph),
        _level_post_card(),
        _level_signals(),
        _level_narration(),
        _level_composition(graph),
        _level_substrate(),
        _level_governance(),
    ]
    idx = {lv["id"]: i for i, lv in enumerate(levels)}
    for lv in levels:
        drill_map = DRILL.get(lv["id"], {})
        for st in lv.get("stages", []):
            _decorate_stage(st)
            tgt = drill_map.get(st["label"])
            st["drill_id"] = tgt
            st["drill_idx"] = idx.get(tgt) if tgt else None
        if lv.get("center"):
            _decorate_stage(lv["center"])
        # lane drill (zoom into the parallel-lane's own level)
        if lv.get("lane"):
            lt = LANE_DRILL.get(lv["id"])
            lv["lane"]["drill_id"] = lt
            lv["lane"]["drill_idx"] = idx.get(lt) if lt and lt != lv["id"] else None
        # attach the monospace wire schematic (if this level has one) + which view leads
        if lv["id"] in SCHEMATICS:
            lv["schematic"] = _fill_schematic(SCHEMATICS[lv["id"]], graph)
            lv["default_schem"] = lv["id"] == "card"  # card level LEADS with the schematic
        # breadcrumb: parent + the children this level drills into
        p = PARENT.get(lv["id"])
        lv["parent_id"] = p
        lv["parent_idx"] = idx.get(p) if p else None
        child_ids = sorted({t for t in drill_map.values() if t and t != lv["id"]})
        lv["child_idx"] = [{"id": c, "idx": idx[c], "title": levels[idx[c]]["title"]} for c in child_ids if c in idx]
    return {"worked": WORKED, "worked_tokens": WORKED_TOKENS, "levels": levels, "index": idx}
