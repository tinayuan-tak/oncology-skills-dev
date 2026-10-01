"""Shared signals-first helpers for the fleet rollout (mirrors the tumor-presence pilot).

Two verdict-INERT primitives used by the per-lens narrators (synthesis_*.py) and the per-skill
strength_certainty sidecars, so every lens can LEAD with its signal vector and expose a continuous
portfolio-ranking scalar — without each skill re-implementing them:

  render_signal_vector(cv, axis_labels) — render a claim_vector dict as a leading prompt block.
  certainty_composite(strength, level)  — a monotone [0,1] certainty-discounted-strength ranking scalar.

Generic over any lens's claim_vector (top-level axis keys → {signal, corroboration, evidence, conflict})
and over the fleet's strength vocabularies. Never touches any verdict.
"""

from __future__ import annotations

from typing import Optional


def render_signal_vector(cv: Optional[dict], axis_labels: Optional[dict] = None) -> str:
    """One line per claim-vector axis: signal × corroboration + cited evidence, conflict flagged.
    Skips private/metadata keys and any entry that is not a claim (no `signal`). A no-op note when the
    decision predates the claim vector (so the narration degrades to the fields below)."""
    if not isinstance(cv, dict):
        return "  (signal vector not present in this decision — narrate from the fields below.)"
    labels = axis_labels or {}
    rows = []
    for k, cl in cv.items():
        if k.startswith("_") or not isinstance(cl, dict) or "signal" not in cl:
            continue
        name = labels.get(k, "")
        line = (
            f"    {k} {name}: signal={cl.get('signal')} corroboration={cl.get('corroboration')} — {cl.get('evidence')}"
        )
        if cl.get("conflict"):
            line += f"  CONFLICT: {cl['conflict']}"
        rows.append(line)
    return "\n".join(rows) if rows else "  (signal vector empty for this run)"


# Robust across the fleet's strength vocabularies (presence: *_positive; dependency: +broad_nonselective;
# selectivity / surface / genomic / tractability variants). Unknown tier → 0.0 (conservative).
_COMPOSITE_STRENGTH = {
    "strong_positive": 1.0,
    "moderate_positive": 0.66,
    "weak_positive": 0.33,
    "broad_nonselective": 1.0,  # a genuine (broad) dependency — strong signal, selectivity is a separate axis
    "negative": 0.0,
    "none": 0.0,
    "unmeasured": 0.0,
}
_COMPOSITE_CERTAINTY = {"high": 1.0, "medium": 0.75, "low": 0.5}


def certainty_composite(strength: str, certainty_level: str) -> float:
    """Monotone [0,1] ranking scalar = peak signal tier × weakest-link certainty. A NAMED projection
    ('certainty-discounted strength'), NOT a canonical single value — other lens weightings are equally
    valid. Non-substituting: certainty multiplies, never averages against signal. Unknown strength → 0.0;
    unknown level → 0.5."""
    return round(_COMPOSITE_STRENGTH.get(strength, 0.0) * _COMPOSITE_CERTAINTY.get(certainty_level, 0.5), 3)


# ─── (strength, certainty) SIDECAR assembly — the ONE definition of the per-axis certainty object +
#     ordinal map every lens's `_strength_certainty` hook builds (CERTAINTY_MODEL.md). Previously the
#     entire assembly (dict shape, weakest-link `min(..., key=_ORD)`, the composite + composite_basis +
#     provenance + _model_ref envelope) was copy-pasted verbatim across functional-requirement, genomic-
#     alteration-profile, surface-modality-fit, tumor-presence and tumor-selectivity, each redefining the
#     same `{"low":0,"medium":1,"high":2}` ordinal map. Verdict-INERT: a render sidecar, never a verdict.
# The ordinal map for the three-tier certainty bands (low<medium<high). ONE definition.
STRENGTH_CERTAINTY_ORD = {"low": 0, "medium": 1, "high": 2}


def coverage_band(n, *, high_n, med_n) -> str:
    """Bucket a sample count into a low/medium/high coverage band. A missing / non-numeric / bool count
    is `low` — the conservative direction (no measured power basis). The bool-guard (`isinstance(n, bool)`)
    is unified HERE so the per-axis coverage readers can never silently diverge on whether True/False
    counts as a numeric sample size (it does not)."""
    if not isinstance(n, (int, float)) or isinstance(n, bool):
        return "low"
    return "high" if n >= high_n else ("medium" if n >= med_n else "low")


def weakest_link_level(coverage: str, corroboration: str, *, force_low: bool = False) -> str:
    """Weakest-link certainty `level` over the MEASURED certainty components: coverage always counts,
    corroboration counts only when it is not `unmeasured` (an absent comparator raises ignorance — carried
    in unknown_mass — rather than dropping the level to its floor). `force_low` pins the level to `low`
    (a none / insufficient verdict). The min is taken over STRENGTH_CERTAINTY_ORD."""
    if force_low:
        return "low"
    components = [coverage] + ([corroboration] if corroboration != "unmeasured" else [])
    return min(components, key=lambda c: STRENGTH_CERTAINTY_ORD[c]) if components else "low"


def assemble_strength_certainty(
    strength: str,
    coverage: str,
    corroboration: str,
    unknown_mass,
    *,
    level: str,
    composite_basis: str,
    provenance: dict,
    model_ref: str,
    composite=None,
    certainty_extra: Optional[dict] = None,
    extra_fields: Optional[dict] = None,
) -> dict:
    """Assemble the per-axis (strength, certainty) SIDECAR dict in its ONE canonical key order:
    strength, certainty{level, coverage, corroboration, unknown_mass[, …extras]}, [extra sibling fields],
    composite, composite_basis, provenance, _model_ref.

      composite        — defaults to certainty_composite(strength, level); pass a value to override
                         (tumor-presence supplies its own identical _presence_composite projection).
      certainty_extra  — extra keys appended INSIDE the certainty object (tumor-presence's
                         corroboration_boundary_fragile / corroboration_note audit annotation).
      extra_fields     — extra top-level keys inserted BETWEEN certainty and composite
                         (tumor-selectivity's structured veto_coverage sibling).

    Verdict-INERT: this is a render sidecar emitted beside the verdict, never a verdict input."""
    certainty = {
        "level": level,
        "coverage": coverage,
        "corroboration": corroboration,
        "unknown_mass": unknown_mass,
    }
    if certainty_extra:
        certainty.update(certainty_extra)
    out = {"strength": strength, "certainty": certainty}
    if extra_fields:
        out.update(extra_fields)
    out["composite"] = certainty_composite(strength, level) if composite is None else composite
    out["composite_basis"] = composite_basis
    out["provenance"] = provenance
    out["_model_ref"] = model_ref
    return out


# ─── Narrator-input CONTRACT (v1) ─────────────────────────────────────────────────────────────────
# The single leading SIGNAL block every lens narrator (synthesis*.py) leads with, composed from a
# DECLARED slice of the deterministic headline. The point of the contract: a narrator's signal lead is
# derived SOLELY from these three headline keys, so ANY skill that populates them is narrated with NO
# per-builder edit — signals flow STRUCTURALLY, not by hand-wiring each prompt. Verdict-INERT: reads the
# headline, never writes it. Precedence (strangler): the hierarchy-derived sub-group signals are PRIMARY;
# the legacy per-axis claim_vector is the supporting evidence detail (and the FALLBACK lead for lenses
# not yet migrated to sub-group signals).


def _render_subgroup_signals(sg, lead: bool = True) -> list:
    """Lines for headline['subgroup_signals'] — the hierarchy-derived, measurement_type-bound per-sub-
    group signals (PRIMARY): each sub-group's peak signal × agreement-and-power confidence, its binding
    sources, and (first-class subtype) any per-stratum `by_stratum` conditioning. [] when absent/empty.
    `lead=False` drops the single-lens 'LEAD your narration' framing for a SECTION context (e.g. the
    composed target-profile presence facet, where presence is one facet among many, not the lead)."""
    if not isinstance(sg, dict) or not sg:
        return []
    hdr = (
        "SUB-GROUP SIGNALS (hierarchy-derived; sources bound by measurement_type — LEAD your "
        "narration with THIS: the strongest, best-corroborated sub-group signals carry the story):"
        if lead
        else "SUB-GROUP SIGNALS (hierarchy-derived; sources bound by measurement_type — the within-lens "
        "signal decomposition behind this facet):"
    )
    out = [hdr]
    for name, s in sg.items():
        if not isinstance(s, dict):
            continue
        flag = "  CONFLICT (level vs breadth disagree)" if s.get("conflict") else ""
        out.append(
            f"    {name}: signal={s.get('signal')} confidence={s.get('confidence')} "
            f"({s.get('n_agree')}/{s.get('n_sources')} sources agree, power={s.get('power')}){flag}"
        )
        for src in s.get("sources") or []:
            if isinstance(src, dict):
                sc = "  CONFLICT" if src.get("conflict") else ""
                out.append(
                    f"        - {src.get('label')}: {src.get('tier')} (value={src.get('value')}, n={src.get('n')}){sc}"
                )
        by_stratum = s.get("by_stratum")
        if isinstance(by_stratum, dict) and by_stratum:
            axis = s.get("subtype_axis") or {}
            out.append(
                f"        by stratum (subtype is an ORTHOGONAL conditioner, not a new sub-group; "
                f"stratification={axis.get('stratification_class')}, ε²={axis.get('epsilon_squared')}):"
            )
            for sid, st in by_stratum.items():
                if isinstance(st, dict):
                    out.append(
                        f"            {sid}: signal={st.get('signal')} "
                        f"certainty={st.get('certainty')} (n={st.get('n')})"
                    )
    return out


def _render_question_table(qt) -> list:
    """Lines for headline['question_table'] — the per-governed-question decomposition (data · signal ·
    confidence). Tolerant of both the {tier,...} cell shape and a bare tier string. [] when absent."""
    if not isinstance(qt, list) or not qt:
        return []
    out = [
        "PER-QUESTION DECOMPOSITION (each governed question's signal × confidence — the question-grain "
        "view of the SAME evidence; do not double-count it against the sub-group signals above):"
    ]
    for r in qt:
        if not isinstance(r, dict):
            continue
        sig, cf = r.get("signal"), r.get("confidence")
        stier = sig.get("tier") if isinstance(sig, dict) else sig
        ctier = cf.get("tier") if isinstance(cf, dict) else cf
        out.append(
            f"    {r.get('id')} {r.get('question')}: signal={stier} confidence={ctier}"
            + (f" — {r.get('primary')}" if r.get("primary") else "")
        )
    return out


def render_narrator_signals(headline, axis_labels: Optional[dict] = None, extra_directive: Optional[str] = None) -> str:
    """NARRATOR-INPUT CONTRACT (v1). Compose the leading SIGNAL block from the DECLARED headline slice:
    headline['subgroup_signals'] (PRIMARY; hierarchy-derived, measurement_type-bound),
    headline['question_table'] (per-question decomposition), and headline['claim_vector'] (LEGACY
    per-axis evidence, and the FALLBACK lead for lenses not yet migrated). Any skill that populates these
    keys is narrated with no per-builder edit. `axis_labels` names the claim-vector axes; `extra_directive`
    appends a lens-specific instruction (e.g. presence's abundance∧elevation rule). Verdict-INERT."""
    h = headline if isinstance(headline, dict) else {}
    sg_lines = _render_subgroup_signals(h.get("subgroup_signals"))
    qt_lines = _render_question_table(h.get("question_table"))
    cv_block = render_signal_vector(h.get("claim_vector"), axis_labels)
    have_structural = bool(sg_lines)

    blocks = []
    if sg_lines:
        blocks.append("\n".join(sg_lines))
    if qt_lines:
        blocks.append("\n".join(qt_lines))
    # claim vector: supporting axis detail when structural signals exist; the PRIMARY lead when they don't.
    # NOTE the literal 'SIGNAL VECTOR' header is retained on the fallback lead so the invert-primacy
    # ordering contract (signals lead, verdict trails) holds for un-migrated lenses.
    cv_header = (
        "PER-AXIS EVIDENCE (claim vector — the within-lens axis detail backing the signals above):"
        if have_structural
        else "SIGNAL VECTOR (per-axis claim vector — no hierarchy-derived sub-group signals in this "
        "decision, so LEAD your narration with THIS):"
    )
    blocks.append(cv_header + "\n" + cv_block)

    directive = (
        "  DIRECTIVE: LEAD with the sub-group signals; your confidence read MUST track each "
        "sub-group's `confidence` and DOWNGRADE where `conflict` is set — never over-read a "
        "low/underpowered sub-group. The per-axis claim vector is supporting evidence, not a "
        "second vote. Signals are ORTHOGONAL — never average across sub-groups or axes."
        if have_structural
        else "  DIRECTIVE: your confidence read MUST track the claim corroboration tiers — a "
        "decision-critical claim of corroboration=low/insufficient cannot yield a well-supported "
        "read. Claims are ORTHOGONAL — never average across axes."
    )
    if extra_directive:
        directive += "\n  " + extra_directive.strip()
    blocks.append(directive)
    return "\n\n".join(blocks)


def render_signal_summary(headline) -> str:
    """Register-neutral signal CONTENT (NO lead / directive framing) for a SECTION context — e.g. the
    composed target-profile presence facet, where a lens's signals are one facet among many rather than
    the whole narration's lead. Reads the SAME declared headline slice as render_narrator_signals
    (subgroup_signals + question_table), so the narrator-input contract still holds: signals flow
    STRUCTURALLY off the headline, no per-facet field-picking. '' when neither signal is present."""
    h = headline if isinstance(headline, dict) else {}
    blocks = []
    sg = _render_subgroup_signals(h.get("subgroup_signals"), lead=False)
    if sg:
        blocks.append("\n".join(sg))
    qt = _render_question_table(h.get("question_table"))
    if qt:
        blocks.append("\n".join(qt))
    return "\n\n".join(blocks)
