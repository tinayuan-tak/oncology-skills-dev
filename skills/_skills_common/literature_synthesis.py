"""literature_synthesis — OPTIONAL, verdict-INERT LLM literature-review lane (fleet-generic).

Parallel to `narrator_engine`. Given a (target, indication) + a `LensConfig` (its axes + thesis), this
asks the model what the PUBLISHED literature asserts on each of the lens's axes — each assertion carrying
a direction, a confidence, CITATION(s) ({label, pmid?, doi?, verified}), and an AGREEMENT read vs the
omics signal ALREADY computed on the decision (agree | extends | contradicts | omics_blind |
omics_unavailable). It also collects `blind_spots` — literature-only signals the omics CANNOT measure
(protein localization, invasive-front antigen loss, clinical/functional outcome) — and one overall
consistency read.

Two-slot / VERDICT-INERT: attached as ``decision['literature_synthesis']`` AFTER the deterministic spine
is composed and BEFORE the narrator runs (so the single-lens narrator can CITE it). It never mints or
moves a verdict; provenance-stamped by ``synthesize_structured`` (model_id + prompt_hash). OPTIONAL: only
runs under ``--literature``.

HONESTY DISCIPLINE (this lane brings EXTERNAL knowledge, so it is NOT evidence-only):
  * the model must set ``citation.verified=false`` UNLESS it is certain of the PMID/DOI;
  * it must prefer ``literature_read='not_addressed'`` over speculation;
  * it must ground ``agreement_vs_omics`` in the omics signals shown to it, never restate them as literature.
GROUNDING: each axis is tagged ``[MEASURED]`` / ``[NO-OMICS-DATA]`` in the prompt (from the claim-vector
``signal`` tier via ``SIGNAL_ORD`` — a measured floor ``absent`` / wrong-direction ``negative`` counts as
MEASURED), the system prompt reserves ``omics_unavailable`` / ``omics_blind`` for ``[NO-OMICS-DATA]`` axes,
and a deterministic post-pass (``_reground_agreement``) rewrites any measured axis the model still tagged
unavailable/blind to ``extends`` — so a MEASURED axis can NEVER be reported as unmeasured.
The axis tiers are a VERDICT SUMMARY, so the prompt also carries a ``MEASURED EVIDENCE`` section
(``_measured_evidence_lines``): the per-card decisive datum the skill actually EMITTED — reading, the
reference-frame ruler it was gauged against, and whether the card is verdict-bearing or display-only.
This lets a literature read engage the MEASUREMENT and not only the call: agreeing with an observed value
while disputing the cut applied to it, or agreeing on direction while contradicting the magnitude, are
distinguishable claims that an axis tier alone erases. Rows come from the report layer's OWN builder
(``report_render.ir._evidence_signals_block``) so this never becomes a second reader of
``evidence_graph.cards[]``. It is grounding DETAIL only: the ``[MEASURED]`` tags stay the sole authority
on whether ``omics_blind`` / ``omics_unavailable`` is permissible.
A live retrieval + PMID-verification backend (Europe PMC / NCBI) is a documented FOLLOW-ON, wired via the
optional ``retrieve_fn`` hook: when provided, its abstracts are injected to GROUND the synthesis (and only
then may citations be marked verified); without it, the model uses internal knowledge and every citation
defaults to unverified. This keeps the lane honest and replayable while leaving the retrieval seam clean.
"""

from __future__ import annotations

from typing import Callable, Optional

# SIGNAL_ORD is the fleet's canonical measured-vs-gap contract: a measured tier (strong/moderate/weak/
# absent/negative) maps to an int, while `unmeasured` (a GAP) maps to None. We ground the agreement lane
# on it so a MEASURED axis — including a measured floor (`absent`) or a wrong-direction result
# (`negative`) — can never be mislabeled omics_unavailable.
from _skills_common.claim_vector_core import SIGNAL_ORD

# Reuse the fleet lens contract so the literature lane and the narrator share axes/thesis/scope.
from _skills_common.narrator_engine import LensConfig

_LIT_READ = ("strongly_supports", "supports", "mixed", "contradicts", "not_addressed")
_AGREE = ("agree", "extends", "contradicts", "omics_blind", "omics_unavailable")
_CONF = ("high", "moderate", "low")
_CONSISTENCY = ("concordant", "partially_concordant", "discordant", "insufficient")

# A retrieve_fn (optional) supplies grounding abstracts: (target, indication, lens) -> str | None.
RetrieveFn = Callable[[Optional[str], Optional[str], LensConfig], Optional[str]]

_LIT_HONESTY = (
    " Report ONLY established peer-reviewed findings. Cite sources. Set each citation.verified=false"
    " UNLESS you are certain of the PMID/DOI (never fabricate an identifier). Prefer"
    " literature_read='not_addressed' over speculation. Report magnitudes with scale + direction."
)


def _citation_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["label", "verified"],
        "properties": {
            "label": {"type": "string", "description": "first-author, year, journal (e.g. 'Went 2006, Br J Cancer')."},
            "pmid": {"type": "string", "description": "PubMed id if known; omit if unknown."},
            "doi": {"type": "string", "description": "DOI if known; omit if unknown."},
            "verified": {
                "type": "boolean",
                "description": "true ONLY if certain of the identifier (or it came from a supplied abstract); else false.",
            },
        },
    }


def _tool(lens: LensConfig) -> tuple:
    name = f"emit_{lens.name.replace('-', '_')}_literature"
    cite = _citation_schema()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["axes", "blind_spots", "overall_consistency", "key_divergence"],
        "description": (
            f"Verdict-INERT published-literature read for the {lens.name} lens. For EACH omics axis "
            "shown, report what the literature asserts + how it agrees with the omics. SINGLE-LANE — "
            "informs confidence, never mints/flips a verdict."
        ),
        "properties": {
            "axes": {
                "type": "array",
                "description": "one entry per omics axis shown in the prompt.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "axis_key",
                        "literature_read",
                        "assertion",
                        "agreement_vs_omics",
                        "confidence",
                        "citations",
                    ],
                    "properties": {
                        "axis_key": {"type": "string", "description": "the axis LETTER from the prompt (e.g. 'A')."},
                        "literature_read": {"type": "string", "enum": list(_LIT_READ)},
                        "assertion": {
                            "type": "string",
                            "description": "1-2 sentences: what the literature says on this axis; scale + direction.",
                        },
                        "agreement_vs_omics": {"type": "string", "enum": list(_AGREE)},
                        "confidence": {"type": "string", "enum": list(_CONF)},
                        "citations": {"type": "array", "items": cite},
                    },
                },
            },
            "blind_spots": {
                "type": "array",
                "description": "literature-supported signals the OMICS in this package cannot measure.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["signal", "why_omics_blind"],
                    "properties": {
                        "signal": {"type": "string"},
                        "why_omics_blind": {"type": "string"},
                        "citations": {"type": "array", "items": cite},
                    },
                },
            },
            "overall_consistency": {"type": "string", "enum": list(_CONSISTENCY)},
            "key_divergence": {
                "type": "string",
                "description": "the single most important literature↔omics divergence, or 'none'.",
            },
        },
    }
    return name, schema


def _system(lens: LensConfig) -> str:
    s = [
        f"You are a computational-oncology LITERATURE analyst. PURPOSE (verdict-INERT literature lane): "
        f"report what the ESTABLISHED peer-reviewed literature asserts for a (target, indication) on the "
        f"{lens.name} axes below, and judge how each literature read AGREES with the omics signal shown to you: "
        f"{lens.thesis}",
        "You never invent facts and never change the deterministic, rule-computed verdict (FIXED upstream).",
        "Ground every `agreement_vs_omics` in the OMICS signals shown — do not restate the omics as literature.",
        "Each axis is tagged [MEASURED] or [NO-OMICS-DATA]. Reserve `omics_unavailable` / `omics_blind` for a "
        "[NO-OMICS-DATA] axis ONLY. A [MEASURED] axis always has an omics result to compare against — even a "
        "measured floor (signal=absent) or a wrong-direction result (signal=negative) — so classify it "
        "agree / extends / contradicts, NEVER unavailable/blind.",
        "Flag signals the OMICS CANNOT measure (protein localization, invasive-front antigen loss, "
        "clinical / functional outcome) under `blind_spots`.",
        "You are shown the axis-level signal tiers AND, where available, the per-card MEASURED EVIDENCE "
        "they were collapsed from (the decisive reading + the reference frame it was judged against). "
        "Judge against the EVIDENCE, not only the tier: a literature read can agree with an observed value "
        "while disagreeing with the threshold applied to it, or agree on direction while contradicting the "
        "effect MAGNITUDE — report those as `extends` / `contradicts` and say which one you mean. "
        "Contradicting a verdict-bearing card challenges the call; contradicting a display-only card does "
        "not. The readings never redefine measured-ness — the axis tags remain the only authority there.",
    ]
    if lens.polarity_note:
        s.append(f"POLARITY: {lens.polarity_note}")
    if lens.scope_exclusions:
        s.append("SCOPE — do NOT adjudicate (owned by sibling lenses): " + "; ".join(lens.scope_exclusions) + ".")
    s.append("REGISTER: scientific-publication voice; declarative, precise; no promotional language.")
    return " ".join(s) + _LIT_HONESTY


def axis_measured_state(decision: dict, lens: LensConfig) -> dict:
    """Per-axis grounding truth: {axis_key: {"measured": bool, "class": <str|None>}}.

    PRIMARY source is the claim-vector `signal` tier via SIGNAL_ORD — a measured tier (incl. the measured
    floor `absent` and wrong-direction `negative`) → measured; `unmeasured` / a missing atom → a gap.
    This is authoritative: the fleet's `gap ≠ absent` discipline means a deliberate `unmeasured` is a real
    coverage gap, so we never override it. As an OPPORTUNISTIC cross-check we resolve the axis's citable
    atom (`evidence_atom.cite.card_id`) to its evidence capsule; a capsule with `evidence_state=='measured'`
    can only UPGRADE an axis the claim vector left ambiguous (signal missing because the axis carries no
    atom), never downgrade a measured signal. `class` (the capsule's primary class) is surfaced when the
    capsule is present, purely to enrich the prompt. Capsules are frequently absent in real run-dirs, so the
    signal tier — never the capsule — is the load-bearing measured flag."""
    h = decision.get("headline") or {}
    cv = h.get("claim_vector") or {}
    caps = ((h.get("evidence_capsules") or {}).get("capsules")) or {}
    out: dict = {}
    for k in lens.axis_labels or {}:
        cl = cv.get(k) if isinstance(cv.get(k), dict) else {}
        measured = SIGNAL_ORD.get(cl.get("signal")) is not None
        cap = {}
        cid = ((cl.get("evidence_atom") or {}).get("cite") or {}).get("card_id")
        if cid and isinstance(caps.get(cid), dict):
            cap = caps[cid]
            if not measured and cap.get("evidence_state") == "measured":
                measured = True  # atom-less axis the vector left ambiguous, but its source card WAS measured
        out[k] = {"measured": measured, "class": cap.get("class")}
    return out


# ── GENERIC conditional/stratified-signal surfacing ─────────────────────────────────────────────────
# A subskill's per-axis claim_vector is POOLED. A signal that is CONDITIONAL on a genotype/subtype
# stratum (partner-conditional dependency, mutation-stratified dependency, …) therefore lives in a
# SEPARATE headline field, invisible to the pooled axes — so the literature lane, reading only the
# pooled axes, mislabels a real measured conditional signal as an omics_blind spot (the WRN×MSI-H case:
# verdict correctly partner_conditional_dependent, but the lane read the pooled SEL axis as
# "no lineage enrichment" and flagged contradicts). This generalizes the subtype-enrichment block
# above: a small declarative registry of conditional-signal fields, each rendered [MEASURED] when
# present+positive on the headline so the model classifies it agree/extends, not omics_blind.
# LENS-AGNOSTIC + guarded → byte-stable for a headline that carries none. Extend by adding a spec.
_CONDITIONAL_SIGNAL_SPECS: tuple = (
    {
        "class_field": "partner_conditional_class",  # functional-requirement (depmap_partner_conditional_dependency)
        "label": "partner/genotype-conditional dependency",
        "is_positive": lambda v: isinstance(v, str) and "conditional" in v and "dependent" in v,
        "detail_fields": (
            ("n_partner_deficient", "n_partner_deficient"),
            ("partner_stratification_q", "stratification_q"),
        ),
    },
)


def _conditional_signal_lines(h: dict) -> list:
    """Render one `· CONDITIONAL SIGNAL [MEASURED] …` line per positive conditional-signal spec present
    on the headline. [] when none (byte-stable)."""
    out = []
    for spec in _CONDITIONAL_SIGNAL_SPECS:
        cls = h.get(spec["class_field"])
        if not spec["is_positive"](cls):
            continue
        details = ", ".join(f"{short}={h.get(key)}" for key, short in spec["detail_fields"] if h.get(key) is not None)
        out.append(
            f"  · CONDITIONAL SIGNAL [MEASURED]: {spec['label']} = {cls}"
            + (f" ({details})" if details else "")
            + ". This IS a measured genotype/subtype-CONDITIONAL signal (it lives outside the pooled axes "
            "above) — classify a conditional/biomarker-stratified literature read as agree/extends, NOT "
            "omics_blind."
        )
    return out


# ── MEASURED EVIDENCE grounding ─────────────────────────────────────────────────────────────────────
# The axis block is a VERDICT SUMMARY: `signal`/`corroboration` are tiers the resolver already COLLAPSED
# out of the underlying measurements. A literature read judged only against that can agree or contradict
# a CALL without ever engaging the number that produced it, and it cannot see two things the tier erases:
# that a card was measured but DISPLAY-ONLY (fired no rule), and the reference frame the value was judged
# against (so "literature disagrees with the measurement" and "literature disagrees with the threshold"
# collapse into one undifferentiated `contradicts`). So we also show the per-card decisive datum the skill
# actually EMITTED — the same rows the report's "Measured evidence" view renders.
#
# SINGLE READER, deliberately: rows come from `report_render.ir._evidence_signals_block`. Re-deriving them
# from `evidence_graph.cards[]` here would make this a SECOND independent reader of that shape, and each
# such pair in this codebase has drifted. The import is LAZY (as the dispatcher's own evidence_graph import
# is) so no module-load edge is added from every literature-bearing skill into the render layer.
#
# ORDERING — measured, not assumed: `headline.evidence_graph` does NOT exist yet when this runs. The
# dispatcher attaches this lane at step 8a (dispatcher.py:1066) and the graph at step 8d (:1106), and 8d
# PROJECTS `literature_synthesis` INTO the graph, so the dependency is inverted BY DESIGN and the graph
# cannot simply be built earlier. tp_fanout is the same shape (lane :1485, graph :1578). We therefore build
# the projection ON DEMAND; reading a pre-existing graph is the rarer path (a re-run over a saved
# decision.json). Safe because the cycle is only at WHOLE-GRAPH granularity — `cards[]` reads only
# capsules/cards/fired_rules/subgroup_signals, and only `_build_literature` reads this lane. A
# questions-less build suffices: the five card fields the block reads are identical with and without the
# registry (pinned by test), so no skill_dir is needed here.
_ROLE_GLOSS = {
    "verdict_bearing": "verdict-bearing",
    "display_only": "display-only, measured but fired no rule",
}


def _evidence_rows(decision: dict, lens: LensConfig) -> tuple:
    """(rows, n_unmeasured) from the report layer's own builder. ([], 0) on ANY fault: this is a
    prompt-enrichment section, and degrading it must not degrade the whole lane (the dispatcher would
    turn a raise here into a `_literature_error` stub for the entire synthesis). Silence is therefore
    invisible by construction, so a POSITIVE-CONTROL test asserts the section IS emitted for a realistic
    decision — never infer from a passing suite that these rows are reaching the model."""
    try:
        from _skills_common.evidence_graph import build_evidence_graph
        from _skills_common.report_render.ir import _evidence_signals_block

        eg = (decision.get("headline") or {}).get("evidence_graph")
        if not (isinstance(eg, dict) and eg.get("cards")):
            eg = build_evidence_graph(decision)
        # `lens.name` is the skill kebab id; the block also derives a display title from it, which we do
        # not render (this prompt is single-lens, so the skill label carries no information here).
        blk = _evidence_signals_block([(lens.name, {"evidence_graph": eg}, "gating")])
        if blk is None:
            return [], 0
        rollup = blk.payload.get("rollup") or {}
        return list(blk.payload.get("rows") or []), int(rollup.get("n_unmeasured") or 0)
    except Exception:  # noqa: BLE001 — prompt enrichment; a fault must cost this section only
        return [], 0


def _measured_evidence_lines(decision: dict, lens: LensConfig) -> list:
    """Render the `MEASURED EVIDENCE` prompt section. [] when the skill emitted no decisive datum
    (byte-stable, same discipline as `_conditional_signal_lines`)."""
    rows, n_unmeasured = _evidence_rows(decision, lens)
    if not rows:
        return []
    out = [
        "",
        "MEASURED EVIDENCE — the per-card decisive datum BEHIND those axis signals. The axis block above",
        "shows the tier the resolver collapsed to; these are the readings it was collapsed FROM, each with",
        "its reference-frame ruler (the gauged value vs the cut / cohort it was judged against). Ground your",
        "assertions in THESE, and name the card_id when a literature read speaks to one. Three distinctions",
        "the axis tiers cannot express:",
        "  (1) MEASUREMENT vs THRESHOLD — literature can agree with the observed value and still disagree",
        "      with the cut applied to it, or the reverse. Say which you disagree with; different claims.",
        "  (2) verdict-bearing vs display-only — contradicting a verdict-bearing card challenges the call;",
        "      contradicting a display-only card does not, because it fired no rule.",
        "  (3) EFFECT SIZE and n — a literature read agreeing on direction can still contradict the",
        "      MAGNITUDE. That is `extends` or `contradicts`, not `agree`.",
        "These readings do NOT redefine which axes are measured: the [MEASURED] / [NO-OMICS-DATA] tags above",
        "remain the ONLY authority on whether omics_blind / omics_unavailable is permissible.",
    ]
    for r in rows:
        role = _ROLE_GLOSS.get(r.get("role")) or (r.get("role") or "role unstated")
        seg = f"  · card {r.get('card_id')} [{role}]"
        if r.get("measurement_type"):
            seg += f" ({r['measurement_type']})"
        # a row is present when it has a reading OR a gauge, so join whichever it carries
        bits = [b for b in (r.get("reading"), f"vs reference: {r['gauge']}" if r.get("gauge") else None) if b]
        seg += ": " + " | ".join(bits)
        if r.get("n") is not None:
            seg += f" | n={r['n']}"
        out.append(seg)
    if n_unmeasured:
        out.append(
            f"  ({n_unmeasured} further card(s) were consulted and surfaced NO decisive measured datum. Do "
            "not count them as measured, and do not read a coverage gap into them either — the axis tags "
            "above are authoritative.)"
        )
    return out


def build_literature_prompt(decision: dict, lens: LensConfig) -> str:
    h = decision.get("headline", {}) or {}
    target, indication = decision.get("target"), decision.get("indication")
    cv = h.get("claim_vector") or {}
    states = axis_measured_state(decision, lens)
    lines = [
        f"TARGET: {target}    INDICATION: {indication}    LENS: {lens.name}",
        f"THESIS: {lens.thesis}",
        "",
        "OMICS SIGNALS ALREADY COMPUTED (ground your agreement_vs_omics in these). Each axis is tagged",
        "[MEASURED] (there IS an omics result to judge against — INCLUDING a measured floor signal=absent",
        "or a wrong-direction signal=negative) or [NO-OMICS-DATA] (a genuine coverage gap). Use",
        "agreement_vs_omics=omics_unavailable / omics_blind ONLY for a [NO-OMICS-DATA] axis; for a",
        "[MEASURED] axis classify agree / extends / contradicts against the shown result:",
    ]
    for k, label in (lens.axis_labels or {}).items():
        cl = cv.get(k) or {}
        if not isinstance(cl, dict):
            continue
        st = states.get(k) or {}
        tag = "MEASURED" if st.get("measured") else "NO-OMICS-DATA"
        cls = f", class={st['class']}" if st.get("class") else ""
        conflict = f"; CONFLICT: {cl.get('conflict')}" if cl.get("conflict") else ""
        lines.append(
            f"  · axis {k} ({label}) [{tag}{cls}]: signal={cl.get('signal')} "
            f"corrob={cl.get('corroboration')} — {cl.get('evidence', '')}{conflict}"
        )
    ks = h.get("key_signals") or {}
    if ks.get("caveat"):
        lines.append(f"  omics caveat: {ks['caveat']}")
    # SUBTYPE-GRAIN presence signal (lens-agnostic; only present for by-subtype-capable lenses e.g.
    # tumor-presence). The per-axis claim_vector above is POOLED, so without this a MEASURED subtype
    # enrichment (e.g. CD274/PD-L1 concentrated in MSI_H) is invisible to the lane and gets mislabeled a
    # blind_spot. Surfacing the enriched-stratum identities as [MEASURED] lets the model classify a
    # subtype/biomarker-specific presence pattern as agree/extends, not omics_blind. Byte-stable for lenses
    # that carry no claim_vector_by_subtype (block omitted).
    cvs = h.get("claim_vector_by_subtype") or {}
    enriched = cvs.get("enriched_subtypes") if isinstance(cvs, dict) else None
    if enriched:
        names = ", ".join(f"{e.get('stratum')}({e.get('subtype_signal')})" for e in enriched[:5] if isinstance(e, dict))
        lines.append(
            f"  · SUBTYPE ENRICHMENT [MEASURED, class={cvs.get('stratification_class')}, "
            f"ε²={cvs.get('subtype_variance_explained')} {cvs.get('subtype_effect_size_class')}]: "
            f"present-enriched in {names} (top={cvs.get('top_enriched_subtype')}). This IS a measured "
            "per-subtype presence signal — a subtype/biomarker-specific presence pattern is agree/extends, "
            "NOT omics_blind; reserve omics_blind for a subtype signal NOT in this list."
        )
    # GENERIC conditional/stratified signals (partner-conditional, mutation-stratified, …) that live
    # outside the pooled axes — the WRN×MSI-H class (see _conditional_signal_lines).
    lines += _conditional_signal_lines(h)
    # Bound once: the TASK below may only POINT AT the MEASURED EVIDENCE section when it actually rendered.
    # An unconditional reference would tell the model to consult a section that is not in its context —
    # a dangling pointer, and an invitation to supply the missing readings from imagination.
    measured_evidence = _measured_evidence_lines(decision, lens)
    lines += measured_evidence
    lines += [
        "",
        "TASK: using the tool, for EACH axis above report the published-literature read + an assertion "
        "with citation(s) (verified=false unless certain) + agreement_vs_omics (agree/extends/contradicts/"
        "omics_blind/omics_unavailable). Set axis_key = the LETTER above."
        + (
            " Where MEASURED EVIDENCE shows a reading for a card bearing on your axis, your assertion must "
            "engage that reading — the value and the reference frame it was judged against — not the axis "
            "tier alone."
            if measured_evidence
            else ""
        )
        + " Add blind_spots for literature signals the omics cannot measure, then an overall_consistency "
        "+ key_divergence.",
    ]
    return "\n".join(lines)


def _unwrap_stamped(v):
    """`_stamp_llm_provenance` wraps EVERY top-level str/list field as {"value": <orig>, "_source":
    "llm_synthesized", "_model_id":.., "_prompt_hash":..}. Unwrap that back to <orig> for the literature
    fields the consumers read; a non-stamped value passes through."""
    if isinstance(v, dict) and "value" in v and v.get("_source") == "llm_synthesized":
        return v["value"]
    return v


def _coerce_shapes(result: dict) -> dict:
    """Normalize model + provenance-stamping shape variance so every consumer (verify_citations, the
    narrator renderer) sees the contract shape, in place.

      1. UNWRAP provenance stamping: synthesize_structured stamps each top-level field, so `axes`/
         `blind_spots` arrive as {"value": [...], "_source": "llm_synthesized", ...} (a 4-key wrapper) and
         the scalars as {"value": "...", ...}. Provenance is preserved by re-attaching _source/_model_id/
         _prompt_hash at the RESULT top level (audit trail intact) before the per-field values are unwrapped.
      2. COERCE `axes`/`blind_spots` to a LIST: the schema declares arrays, but a model may emit an OBJECT
         keyed by axis letter ({"A": {...}}) — coerce dict → list of its dict values (injecting axis_key).
         A missing/odd shape degrades to []."""
    if not isinstance(result, dict):
        return result
    # (1) lift provenance to the result top level (once), then unwrap each field.
    if "_source" not in result:
        for v in result.values():
            if isinstance(v, dict) and v.get("_source") == "llm_synthesized":
                for pk in ("_source", "_model_id", "_prompt_hash"):
                    if pk in v:
                        result[pk] = v[pk]
                break
    for key, id_field in (("axes", "axis_key"), ("blind_spots", None)):
        v = _unwrap_stamped(result.get(key))
        if isinstance(v, dict):  # keyed-by-axis object → list of its dict values
            norm = []
            for k, item in v.items():
                if isinstance(item, dict):
                    if id_field and not item.get(id_field):
                        item[id_field] = k
                    norm.append(item)
            v = norm
        result[key] = v if isinstance(v, list) else []
    for scalar in ("overall_consistency", "key_divergence"):
        result[scalar] = _unwrap_stamped(result.get(scalar))
    return result


def _reground_agreement(result: dict, states: dict) -> dict:
    """Deterministic honesty guard (in place): a MEASURED axis can NEVER carry agreement_vs_omics =
    `omics_unavailable` / `omics_blind`. `states` = axis_measured_state(decision, lens). For any axis the
    model wrongly tagged unavailable/blind while its omics was measured, rewrite to `extends` — the
    least-committal of {agree, extends, contradicts}: it asserts the literature adds a read ALONGSIDE the
    (present) omics without fabricating a concordance/discordance direction we cannot derive here. This is
    the value the model itself already picks for a measured-but-absent axis (observed: PHARMACOVIGILANCE
    signal=absent → extends). We DO NOT touch a [NO-OMICS-DATA] axis (unavailable/blind is correct there),
    and we never change a value that was already agree/extends/contradicts. Each rewrite drops an audit
    breadcrumb (`agreement_regrounded=True`) on the axis. Best-effort: a malformed result is returned as-is."""
    if not isinstance(result, dict):
        return result
    axes = result.get("axes")
    if not isinstance(axes, list):
        return result
    for ax in axes:
        if not isinstance(ax, dict):
            continue
        if ax.get("agreement_vs_omics") in ("omics_unavailable", "omics_blind") and (
            states.get(ax.get("axis_key")) or {}
        ).get("measured"):
            ax["agreement_vs_omics"] = "extends"
            ax["agreement_regrounded"] = True
    return result


def synthesize_literature(
    decision: dict,
    lens: LensConfig,
    model_id: Optional[str] = None,
    retrieve_fn: Optional[RetrieveFn] = None,
    verify_fn: Optional[Callable[[dict], dict]] = None,
) -> dict:
    """Run the generic literature lane. Returns the provenance-stamped literature_synthesis block. The
    CALLER attaches it as decision['literature_synthesis'] and swallows failures (never break the spine).

    retrieve_fn (optional): GROUND the synthesis in retrieved abstracts (e.g. Europe PMC) — only then may
    the model mark citations verified. verify_fn (optional): a POST-synthesis pass that reconciles each
    citation.verified against ground truth (e.g. PMID existence), so `verified` is trustworthy regardless
    of the model's self-report. Both are best-effort and never raise into the caller."""
    from _skills_common.llm import synthesize_structured

    tool_name, tool_schema = _tool(lens)
    user = build_literature_prompt(decision, lens)
    if retrieve_fn is not None:
        try:
            corpus = retrieve_fn(decision.get("target"), decision.get("indication"), lens)
        except Exception:  # noqa: BLE001 — retrieval is best-effort; degrade to internal-knowledge mode
            corpus = None
        if corpus:
            user += (
                "\n\nRETRIEVED ABSTRACTS (ground every citation in these; you MAY set verified=true "
                "ONLY for identifiers present here):\n" + corpus
            )
    result = synthesize_structured(
        system_prompt=_system(lens), user_prompt=user, tool_name=tool_name, tool_schema=tool_schema, model_id=model_id
    )
    _coerce_shapes(result)
    _reground_agreement(result, axis_measured_state(decision, lens))
    if verify_fn is not None and isinstance(result, dict):
        try:
            result = verify_fn(result)
        except Exception:  # noqa: BLE001 — verification is best-effort; keep the unverified result
            pass
    return result


def make_literature_fn(
    lens: LensConfig, retrieve_fn: Optional[RetrieveFn] = None, verify_fn: Optional[Callable[[dict], dict]] = None
):
    """Adapt a LensConfig to the dispatcher's literature_fn signature (decision, model_id). Each skill's
    run.py passes `literature_fn=make_literature_fn(<LENS>, retrieve_fn=..., verify_fn=...)` to opt into the
    --literature lane (grounded + PMID-verified when the retrieve/verify hooks are supplied)."""

    def _literature(decision, model_id=None):
        return synthesize_literature(decision, lens, model_id, retrieve_fn, verify_fn)

    return _literature
