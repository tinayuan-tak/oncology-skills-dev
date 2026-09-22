"""headline_core — the SHARED canonical HEADLINE block for the subskill fleet.

WHAT THIS IS: the skill-agnostic machinery that distils a subskill's already-computed decision into ONE
concise, canonical headline message — a *verdict + confidence + top-tension* triple — carried as both a
deterministic one-sentence text and a renderer-agnostic `hero` plot_data payload. It is the
`claim_vector_core` analogue for the headline: the SHAPE is uniform across skills; the per-skill
specifics (verdict phrasing, which claim axes to surface, extra tension sources) are declared in a
`HeadlineSpec`.

WHY: today verdict, confidence, and the top tension live in three unrelated places and the verdict is
spelled differently by every downstream consumer (plots, cross-reasoning agents, the persistent store,
dashboards). This module gives all four a SINGLE object to read: `decision.headline.headline_block`.

THE DISCIPLINE (inherited from claim_vector_core — this is a one-way VIEW, never a verdict input):
  * verdict-INERT. Built from the ALREADY-computed headline + claim_vector + key_signals; it never feeds
    a rule, resolver, or gate. The consuming skill's verdict spine stays byte-identical (frozen by its
    golden/replay test).
  * confidence is SEPARATE from signal. It is the weakest-link over the claim vector's own
    `corroboration` tiers (measured axes only), capped by any active `conflict` and floored by coverage
    (how many axes are measured at all). A skill that emits the authoritative CERTAINTY_MODEL sidecar
    (`strength_certainty`/`certainty_by_axis`) passes it in and it WINS over the derived value.
  * gap ≠ absent. An `unmeasured` axis never counts as a measured floor — it lowers COVERAGE, not signal.
  * offline-renderable. The `hero` payload is pure data; the reference renderer (headline_hero.py) plots
    it with no live read — matching the framework's offline-figure discipline
    (docs/FIGURE_EMITTER_ARCHITECTURE_2026-08-19.md §3.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

from _skills_common.claim_vector_core import CORROBORATION_ORD, SIGNAL_ORD, weakest

# Confidence tiers, ordinal (strong > moderate > weak > insufficient). `insufficient` is the coverage
# floor — the honest "we can't say" when nothing decision-critical is measured (distinct from a weak
# but MEASURED read).
CONFIDENCE_ORD = {"strong": 3, "moderate": 2, "weak": 1, "insufficient": 0}
_CONF_BY_INDEX = {3: "strong", 2: "moderate", 1: "weak", 0: "insufficient"}
# A CERTAINTY_MODEL sidecar may grade its level in the low/medium/high vocabulary (functional-requirement's
# strength_certainty) rather than the headline's strong/moderate/weak. Normalize so a skill can pass its
# sidecar verbatim instead of hand-writing an adapter.
_CERTAINTY_LEVEL_ALIAS = {"high": "strong", "medium": "moderate", "low": "weak"}
# corroboration tier → confidence tier (a claim's support quality maps onto how much we trust the call).
# `single_arm` → `weak` is the CAP the measured-arm frame exists to deliver: a claim resting on one
# measured arm cannot read as more than weakly confident, however strong that arm is. It shares the
# `weak` slot with `low` (a conflict) because both are thin support — but the two stay DISTINCT on the
# corroboration ladder, because only `low` means the arms were compared and disagreed, and the eval
# discordance ledger keys its sharpness predicate on exactly that difference.
_CORR_TO_CONF = {
    "high": "strong",
    "moderate": "moderate",
    "single_arm": "weak",
    "low": "weak",
    "unmeasured": "insufficient",
    # `underpowered` (a gap WITH intent — the arm ran but was under-powered) reads as the SAME
    # `insufficient` confidence as the `unmeasured` gap. Explicit rather than via the `.get(..., "insufficient")`
    # default so a rung can never silently fall through (see test_every_corroboration_rung_has_a_confidence
    # _projection). Verdict-inert: no live corroboration projection emits `underpowered` (the _cn/_fus arm
    # guards collapse an underpowered signal to `unmeasured` corroboration) — this is the gap-consistent
    # reading for the day a producer does.
    "underpowered": "insufficient",
}


@dataclass(frozen=True)
class HeadlineSpec:
    """Per-skill declaration for the shared headline builder.

    gate          : the verdict gate name (e.g. "presence") — the canonical `verdict.gate`.
    verdict_label : verdict token -> human phrase (e.g. "present" -> "Present"). Defaults to a
                    de-underscoring prettifier; a skill may pass a dict-backed labeler for its vocab.
    axis_keys     : the claim_vector axes to surface in the hero, in display order (e.g. ("A","B","C","D")).
    axis_labels   : {axis_key: short label} for the hero rows.
    critical_axes : the decision-critical axes whose coverage floors confidence (defaults to axis_keys).
    tension_extra : OPTIONAL (headline_dict) -> {text, source, severity} | None — a skill-specific tension
                    source beyond the claim_vector conflicts + key_signals.caveat (e.g. presence's
                    `presence_headline_conflict` cross-modal flag). Higher severity wins the single slot.
    """

    gate: str
    axis_labels: dict
    axis_keys: Sequence[str]
    verdict_label: Callable[[str], str] = field(default=lambda v: str(v).replace("_", " ").strip().capitalize())
    critical_axes: Optional[Sequence[str]] = None
    tension_extra: Optional[Callable[[dict], Optional[dict]]] = None


# ── confidence ────────────────────────────────────────────────────────────────────────────────────
def derive_confidence(
    claim_vector: dict, axis_keys: Sequence[str], critical_axes: Sequence[str], certainty: Optional[dict] = None
) -> dict:
    """Weakest-link confidence over the claim vector's measured axes, capped by conflict and floored by
    coverage. If a CERTAINTY_MODEL sidecar is supplied it WINS (its `level` is authoritative).

    Returns {level, basis, coverage:{n_measured, n_axes, n_critical_measured}}."""
    axes = [(k, (claim_vector or {}).get(k) or {}) for k in axis_keys]
    measured = [(k, cl) for k, cl in axes if SIGNAL_ORD.get(cl.get("signal")) is not None]
    n_axes, n_measured = len(axes), len(measured)
    crit = list(critical_axes or axis_keys)
    n_crit_measured = sum(1 for k, cl in axes if k in crit and SIGNAL_ORD.get(cl.get("signal")) is not None)
    coverage = {"n_measured": n_measured, "n_axes": n_axes, "n_critical_measured": n_crit_measured}

    if certainty and isinstance(certainty, dict):
        lvl = (
            (certainty.get("certainty") or {}).get("level")
            if isinstance(certainty.get("certainty"), dict)
            else certainty.get("level")
        )
        lvl = _CERTAINTY_LEVEL_ALIAS.get(lvl, lvl)  # accept low/medium/high sidecars verbatim
        if lvl in CONFIDENCE_ORD:
            return {"level": lvl, "basis": "certainty_model_sidecar", "coverage": coverage}

    # No decision-critical axis measured at all → we honestly cannot say.
    if n_crit_measured == 0:
        return {"level": "insufficient", "basis": "no decision-critical axis measured", "coverage": coverage}

    # Base = weakest-link over MEASURED corroboration tiers (a gap does not count as weak corroboration).
    corrs = [cl.get("corroboration") for _, cl in measured]
    weakest_corr = weakest(corrs, CORROBORATION_ORD)
    base = _CORR_TO_CONF.get(weakest_corr, "insufficient")
    idx = CONFIDENCE_ORD[base]
    basis = f"weakest-link corroboration = {weakest_corr}"

    # Conflict cap: an active conflict on ANY measured axis caps confidence one step down.
    if any((cl.get("conflict") for _, cl in measured)):
        idx = min(idx, CONFIDENCE_ORD["moderate"])
        basis += "; capped by an unresolved conflict"

    # Coverage floor: if fewer than half the critical axes are measured, cap at weak.
    if n_crit_measured * 2 < len(crit):
        idx = min(idx, CONFIDENCE_ORD["weak"])
        basis += f"; capped by thin coverage ({n_crit_measured}/{len(crit)} critical axes measured)"

    return {"level": _CONF_BY_INDEX[idx], "basis": basis, "coverage": coverage}


# ── top tension ─────────────────────────────────────────────────────────────────────────────────
def rank_tension(claim_vector: dict, key_signals: dict, spec: HeadlineSpec, headline: dict) -> Optional[dict]:
    """The single highest-severity tension, chosen from (a) claim_vector conflicts, (b) the key_signals
    caveat, (c) an optional skill-specific source. Severity is ordinal; ties break toward the
    higher-signal claim (a conflict undermining a STRONG claim matters more). Returns {text, source,
    severity} or None."""
    cands = []
    for k in spec.axis_keys:
        cl = (claim_vector or {}).get(k) or {}
        conf = cl.get("conflict")
        if conf:
            # A conflict on a strong claim is the sharpest tension; scale severity by the claim's signal.
            sev = SIGNAL_ORD.get(cl.get("signal")) or 1
            cands.append({"text": conf, "source": f"claim:{k}", "severity": sev})
    cav = (key_signals or {}).get("caveat")
    if cav:
        cands.append({"text": cav, "source": "key_signals.caveat", "severity": 1})
    if spec.tension_extra is not None:
        extra = spec.tension_extra(headline or {})
        if extra and extra.get("text"):
            cands.append(
                {"text": extra["text"], "source": extra.get("source", "skill"), "severity": extra.get("severity", 3)}
            )
    if not cands:
        return None
    return max(cands, key=lambda t: t["severity"])


# ── the hero payload (renderer-agnostic) ──────────────────────────────────────────────────────────
def headline_hero_plot_data(
    *,
    verdict: dict,
    confidence: dict,
    tension: Optional[dict],
    claim_vector: dict,
    spec: HeadlineSpec,
    modality_arms: Optional[dict] = None,
) -> dict:
    """The renderer-agnostic hero payload: the data the reference renderer (or any consumer) needs to
    draw the headline — verdict badge, confidence meter, per-axis signal×corroboration, tension marker.
    Pure data; no target/indication (the renderer injects those from the decision).

    modality_arms: OPTIONAL {arm: call} — a skill whose one-word verdict packs a PER-MODALITY-ARM call
    (surface-modality-fit: adc/bite_tce/antibody) surfaces the decomposition here so the arms are legible
    in the hero, not string-parsed from the token. The evidence `axes` above stay the evidence axes; this
    is the orthogonal modality-arm channel. Omitted from the payload entirely when None (other skills'
    hero stays byte-identical)."""
    axes = []
    for k in spec.axis_keys:
        cl = (claim_vector or {}).get(k) or {}
        axes.append(
            {
                "key": k,
                "label": spec.axis_labels.get(k, k),
                "signal": cl.get("signal"),
                "corroboration": cl.get("corroboration"),
                "conflict": bool(cl.get("conflict")),
            }
        )
    payload = {
        "kind": "headline_hero",
        "verdict": {
            "call": verdict.get("call"),
            "phrase": verdict.get("phrase"),
            "gate": verdict.get("gate"),
            "polarity": verdict.get("polarity"),
        },
        "confidence": {"level": confidence.get("level"), "coverage": confidence.get("coverage")},
        "tension": ({"text": tension["text"]} if tension else None),
        "axes": axes,
    }
    if modality_arms is not None:
        payload["modality_arms"] = modality_arms
    return payload


# ── deterministic headline text ─────────────────────────────────────────────────────────────────
def compose_headline_text(verdict: dict, confidence: dict, tension: Optional[dict]) -> str:
    """One deterministic sentence: <call> — <confidence> confidence[; tension: <tension>]. This is NOT
    the LLM narration (that stays a separate, optional llm_synthesis) — it is the always-available,
    reproducible headline."""
    phrase = verdict.get("phrase") or verdict.get("call") or "No call"
    phrase = str(phrase).rstrip(". ")  # descriptive phrases may end in "." → avoid a double period
    lvl = confidence.get("level", "insufficient")
    conf_clause = "coverage insufficient for a confidence call" if lvl == "insufficient" else f"{lvl} confidence"
    text = f"{phrase} — {conf_clause}"
    if tension and tension.get("text"):
        text += f"; tension: {tension['text']}"
    return text + "."


# ── citations ─────────────────────────────────────────────────────────────────────────────────────
def collect_citations(claim_vector: dict, axis_keys: Sequence[str]) -> list:
    """Lift the {card_id, fields} citations from each axis's evidence_atom (when present), so the
    headline block carries its own provenance for the store / cross-reasoning consumers."""
    cites = []
    for k in axis_keys:
        atom = ((claim_vector or {}).get(k) or {}).get("evidence_atom")
        cite = (atom or {}).get("cite") if isinstance(atom, dict) else None
        if cite and cite.get("card_id"):
            cites.append({"axis": k, "card_id": cite["card_id"], "fields": cite.get("fields", [])})
    return cites


# ── the builder ─────────────────────────────────────────────────────────────────────────────────
def build_headline(
    headline: dict,
    claim_vector: dict,
    key_signals: dict,
    *,
    spec: HeadlineSpec,
    verdict_token: Optional[str],
    driving_rule_id: Optional[str] = None,
    verdict_polarity: Optional[str] = None,
    certainty: Optional[dict] = None,
    descriptive_phrase: Optional[str] = None,
    phrase_override: Optional[str] = None,
    modality_arms: Optional[dict] = None,
) -> dict:
    """Assemble the canonical Headline block from a skill's ALREADY-computed decision objects.

    verdict_polarity: OPTIONAL "positive" | "negative" | "neutral" — the skill's OWN reading of the call
    (it knows its polarity; the renderer colours the badge by it, falling back to a lexical heuristic).

    descriptive_phrase: OPTIONAL — for GATELESS / descriptive skills (verdict_token is None), the phrase
    to headline with (e.g. the deterministic key_signals.headline dominant-signal summary). The block
    stays well-formed (call=None, polarity defaults "neutral") so descriptive lenses get the same
    verdict+confidence+tension shape without a gate verdict.

    phrase_override: OPTIONAL — display PHRASE to show instead of spec.verdict_label(verdict_token), while
    KEEPING verdict.call = verdict_token for traceability. Lets a skill headline with an honest projection
    of its signal package (e.g. tumor-presence's presence_state phrase) rather than the raw collapsed
    verdict word, without moving the spine token.

    Pure projection — reads the headline + claim_vector + key_signals and writes nothing back. Returns
    {verdict, confidence, top_tension, headline_text, hero, provenance, _disclaimer}."""
    crit = spec.critical_axes or spec.axis_keys
    confidence = derive_confidence(claim_vector, spec.axis_keys, crit, certainty=certainty)
    tension = rank_tension(claim_vector, key_signals, spec, headline)
    if verdict_token is not None:
        phrase = phrase_override or spec.verdict_label(verdict_token)
    else:
        phrase = descriptive_phrase or "No call"
        if verdict_polarity is None:
            verdict_polarity = "neutral"  # a descriptive lens has no positive/negative call to colour
    verdict = {
        "call": verdict_token,
        "phrase": phrase,
        "gate": spec.gate,
        "driving_rule_id": driving_rule_id,
        "polarity": verdict_polarity,
    }
    hero = headline_hero_plot_data(
        verdict=verdict,
        confidence=confidence,
        tension=tension,
        claim_vector=claim_vector,
        spec=spec,
        modality_arms=modality_arms,
    )
    return {
        "verdict": verdict,
        "confidence": confidence,
        "top_tension": tension,
        "headline_text": compose_headline_text(verdict, confidence, tension),
        "hero": hero,
        "provenance": collect_citations(claim_vector, spec.axis_keys),
        "_disclaimer": (
            "Canonical headline (verdict + confidence + top-tension) — a verdict-INERT "
            "projection over the computed decision. Confidence is weakest-link over the "
            "claim vector's corroboration (measured axes), capped by conflict and coverage; "
            "it never moves the verdict."
        ),
    }


__all__ = [
    "CONFIDENCE_ORD",
    "HeadlineSpec",
    "derive_confidence",
    "rank_tension",
    "headline_hero_plot_data",
    "compose_headline_text",
    "collect_citations",
    "build_headline",
]
