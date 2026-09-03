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
A live retrieval + PMID-verification backend (Europe PMC / NCBI) is a documented FOLLOW-ON, wired via the
optional ``retrieve_fn`` hook: when provided, its abstracts are injected to GROUND the synthesis (and only
then may citations be marked verified); without it, the model uses internal knowledge and every citation
defaults to unverified. This keeps the lane honest and replayable while leaving the retrieval seam clean.
"""
from __future__ import annotations
from typing import Callable, Optional

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
    return {"type": "object", "additionalProperties": False,
            "required": ["label", "verified"],
            "properties": {
                "label": {"type": "string", "description": "first-author, year, journal (e.g. 'Went 2006, Br J Cancer')."},
                "pmid": {"type": "string", "description": "PubMed id if known; omit if unknown."},
                "doi": {"type": "string", "description": "DOI if known; omit if unknown."},
                "verified": {"type": "boolean",
                             "description": "true ONLY if certain of the identifier (or it came from a supplied abstract); else false."}}}


def _tool(lens: LensConfig) -> tuple:
    name = f"emit_{lens.name.replace('-', '_')}_literature"
    cite = _citation_schema()
    schema = {
        "type": "object", "additionalProperties": False,
        "required": ["axes", "blind_spots", "overall_consistency", "key_divergence"],
        "description": (f"Verdict-INERT published-literature read for the {lens.name} lens. For EACH omics axis "
                        "shown, report what the literature asserts + how it agrees with the omics. SINGLE-LANE — "
                        "informs confidence, never mints/flips a verdict."),
        "properties": {
            "axes": {"type": "array", "description": "one entry per omics axis shown in the prompt.",
                     "items": {"type": "object", "additionalProperties": False,
                               "required": ["axis_key", "literature_read", "assertion", "agreement_vs_omics", "confidence", "citations"],
                               "properties": {
                                   "axis_key": {"type": "string", "description": "the axis LETTER from the prompt (e.g. 'A')."},
                                   "literature_read": {"type": "string", "enum": list(_LIT_READ)},
                                   "assertion": {"type": "string", "description": "1-2 sentences: what the literature says on this axis; scale + direction."},
                                   "agreement_vs_omics": {"type": "string", "enum": list(_AGREE)},
                                   "confidence": {"type": "string", "enum": list(_CONF)},
                                   "citations": {"type": "array", "items": cite}}}},
            "blind_spots": {"type": "array",
                            "description": "literature-supported signals the OMICS in this package cannot measure.",
                            "items": {"type": "object", "additionalProperties": False,
                                      "required": ["signal", "why_omics_blind"],
                                      "properties": {
                                          "signal": {"type": "string"},
                                          "why_omics_blind": {"type": "string"},
                                          "citations": {"type": "array", "items": cite}}}},
            "overall_consistency": {"type": "string", "enum": list(_CONSISTENCY)},
            "key_divergence": {"type": "string", "description": "the single most important literature↔omics divergence, or 'none'."}}}
    return name, schema


def _system(lens: LensConfig) -> str:
    s = [f"You are a computational-oncology LITERATURE analyst. PURPOSE (verdict-INERT literature lane): "
         f"report what the ESTABLISHED peer-reviewed literature asserts for a (target, indication) on the "
         f"{lens.name} axes below, and judge how each literature read AGREES with the omics signal shown to you: "
         f"{lens.thesis}",
         "You never invent facts and never change the deterministic, rule-computed verdict (FIXED upstream).",
         "Ground every `agreement_vs_omics` in the OMICS signals shown — do not restate the omics as literature.",
         "Flag signals the OMICS CANNOT measure (protein localization, invasive-front antigen loss, "
         "clinical / functional outcome) under `blind_spots`."]
    if lens.polarity_note:
        s.append(f"POLARITY: {lens.polarity_note}")
    if lens.scope_exclusions:
        s.append("SCOPE — do NOT adjudicate (owned by sibling lenses): " + "; ".join(lens.scope_exclusions) + ".")
    s.append("REGISTER: scientific-publication voice; declarative, precise; no promotional language.")
    return " ".join(s) + _LIT_HONESTY


def build_literature_prompt(decision: dict, lens: LensConfig) -> str:
    h = decision.get("headline", {}) or {}
    target, indication = decision.get("target"), decision.get("indication")
    cv = h.get("claim_vector") or {}
    lines = [f"TARGET: {target}    INDICATION: {indication}    LENS: {lens.name}",
             f"THESIS: {lens.thesis}",
             "",
             "OMICS SIGNALS ALREADY COMPUTED (ground your agreement_vs_omics in these):"]
    for k, label in (lens.axis_labels or {}).items():
        cl = cv.get(k) or {}
        if not isinstance(cl, dict):
            continue
        conflict = f"; CONFLICT: {cl.get('conflict')}" if cl.get("conflict") else ""
        lines.append(f"  · axis {k} ({label}): signal={cl.get('signal')} corrob={cl.get('corroboration')} "
                     f"— {cl.get('evidence', '')}{conflict}")
    ks = h.get("key_signals") or {}
    if ks.get("caveat"):
        lines.append(f"  omics caveat: {ks['caveat']}")
    lines += ["",
              "TASK: using the tool, for EACH axis above report the published-literature read + an assertion "
              "with citation(s) (verified=false unless certain) + agreement_vs_omics (agree/extends/contradicts/"
              "omics_blind/omics_unavailable). Set axis_key = the LETTER above. Add blind_spots for literature "
              "signals the omics cannot measure, then an overall_consistency + key_divergence."]
    return "\n".join(lines)


def synthesize_literature(decision: dict, lens: LensConfig, model_id: Optional[str] = None,
                          retrieve_fn: Optional[RetrieveFn] = None,
                          verify_fn: Optional[Callable[[dict], dict]] = None) -> dict:
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
            user += ("\n\nRETRIEVED ABSTRACTS (ground every citation in these; you MAY set verified=true "
                     "ONLY for identifiers present here):\n" + corpus)
    result = synthesize_structured(system_prompt=_system(lens), user_prompt=user,
                                   tool_name=tool_name, tool_schema=tool_schema, model_id=model_id)
    if verify_fn is not None and isinstance(result, dict):
        try:
            result = verify_fn(result)
        except Exception:  # noqa: BLE001 — verification is best-effort; keep the unverified result
            pass
    return result


def make_literature_fn(lens: LensConfig, retrieve_fn: Optional[RetrieveFn] = None,
                       verify_fn: Optional[Callable[[dict], dict]] = None):
    """Adapt a LensConfig to the dispatcher's literature_fn signature (decision, model_id). Each skill's
    run.py passes `literature_fn=make_literature_fn(<LENS>, retrieve_fn=..., verify_fn=...)` to opt into the
    --literature lane (grounded + PMID-verified when the retrieve/verify hooks are supplied)."""
    def _literature(decision, model_id=None):
        return synthesize_literature(decision, lens, model_id, retrieve_fn, verify_fn)
    return _literature
