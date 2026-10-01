"""target-profile — --emit evidence-package writer + card-figure emission + governance validation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import resolve_cards
from tp_common import _CONTRACTS_REPO, SKILL_NAME


def _claim_vectors_from_sub_results(sub_results: dict) -> dict:
    """Per-short verdict-INERT claim_vector (+ key_signals) carried into the machine envelope so a
    downstream reasoner (e.g. cross-evidence-hypothesis) consumes the SIGNAL decomposition + citable
    evidence atoms, not just the verdict label. Sourced from each sub-skill's `_synthesis_facet` (the
    fan-out stashes it at sub_results[short]['synthesis_facet']): dependency carries DEP/SEL/COND/CHEM
    with citable atoms, presence carries its A/B/C/D. Empty when no sub-skill exposes one, so the
    envelope stays byte-stable for un-migrated skills."""
    out: dict = {}
    for short, r in sub_results.items():
        facet = r.get("synthesis_facet")
        if isinstance(facet, dict) and isinstance(facet.get("claim_vector"), dict):
            entry = {"claim_vector": facet["claim_vector"], "key_signals": facet.get("key_signals")}
            # The canonical headline block (verdict + confidence + top tension + hero payload), carried
            # alongside the signal decomposition so the store / dashboard / reasoner read ONE object.
            if isinstance(facet.get("headline_block"), dict):
                entry["headline_block"] = facet["headline_block"]
            out[short] = entry
    return out


# Per-card capsule selector overrides. The numeric-anchor / n_basis shapes only carry floats/ints, so a
# card whose DECISION-relevant datum is a stage label, class enum, or agent list was invisible to the
# capsule DATA layer the cross-evidence agent cites. These cards carry the clinical/competitive/maturity
# reality (approved-in-indication vs approved-anywhere, stage, competitor drug names) — declare their
# salient categorical fields so `categorical_anchors` surfaces them. VERDICT-INERT (rider only).
_CAPSULE_CONFIG: dict = {
    "clinical-precedent": {
        "categorical_fields": ["highest_clinical_stage", "approved_agents", "clinical_precedent_class"]
    },
    "competitor-landscape": {
        "categorical_fields": [
            "highest_clinical_stage",
            "competitor_class",
            "n_approved",
            "late_stage_non_approved_agents",
            "indication_scope",
        ]
    },
    "known-drug-tractability": {
        "categorical_fields": ["known_drug_tractability_class", "has_approved_drug", "n_approved_drug_interactions"]
    },
    "target-development-level": {"categorical_fields": ["tdl_class", "target_family"]},
}


def _capsules_from_sub_results(sub_results: dict, indication: str) -> dict:
    """Per-short evidence-capsule package (evidence_capsule.emit_capsules over the sub-skill's own cards):
    the complete-but-limited DATA layer — 6 bounded selector shapes + a card-floor manifest — carried into
    the machine envelope so the retrieve-don't-recall cross-evidence agent can cite the bounded RAW data
    (strata, magnitudes, categoricals, conflicts, provenance) behind each verdict, not just the class label.
    Every card that fed a sub-verdict emits ≥1 citable capsule (card floor). VERDICT-INERT; empty on any fault."""
    out: dict = {}
    try:
        from _skills_common.evidence_capsule import emit_capsules
    except Exception:  # noqa: BLE001
        return out
    for short, r in sub_results.items():
        cards = r.get("cards") or []
        if not cards:
            continue
        try:
            out[short] = emit_capsules(cards, indication, config=_CAPSULE_CONFIG)
        except Exception:  # noqa: BLE001 — never break emit on one sub-skill
            continue
    return out


def _load_figure_registry():
    """Import the shared figure-emission registry (emit_figures_for_card).

    ONE figure registry, many consumers (the one-source-many-consumers lesson): it lives in
    `_skills_common/_figure_emitters/` and the same per-card emitters draw the SVGs + Plotly specs for
    target-profile, the subskill --figures path, and example-gallery. Graceful None on import failure —
    a run without per-card figures still emits every other artifact.
    """
    try:
        import _skills_common._figure_emitters as _fe  # type: ignore

        return _fe
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: figure registry unavailable: {e}", file=sys.stderr)
        return None


def _emit_card_figures(sub_results: dict, figures_dir: Path, target: str, indication: str) -> dict:
    """Produce each card's distribution figures (SVG + interactive .plotly.json) by invoking the
    shared figure registry per card, writing into figures_dir/cards/<card_id>/.

    This is what makes a target-profile RUN produce the per-card charts the dynamic dashboard embeds
    — previously the run was rules/summary-only and only the composite panel was drawn. Returns a
    map {card_id: [figure_descriptor, ...]} (paths relative to figures_dir) for the renderer to
    embed; the `dynamic: True` descriptors are the Plotly specs, the rest are SVGs. Best-effort:
    a card with no registered emitter or a data-blocked summary simply contributes nothing.
    """
    fe = _load_figure_registry()
    if fe is None:
        return {}
    by_card: dict[str, list] = {}
    seen: set[str] = set()
    for r in sub_results.values():
        for c in r.get("cards") or []:
            if not isinstance(c, dict):
                continue
            card_id = c.get("card_id")
            if not card_id or card_id in seen or c.get("_missing"):
                continue
            seen.add(card_id)
            try:
                figs = fe.emit_figures_for_card(card_id, c.get("summary") or {}, figures_dir, target, indication)
            except Exception as e:  # noqa: BLE001 — figure emission never blocks the run
                print(f"[target-profile] WARN: figure emit failed for {card_id}: {e}", file=sys.stderr)
                figs = []
            if figs:
                by_card[card_id] = figs
    n_plotly = sum(1 for figs in by_card.values() for f in figs if f.get("dynamic"))
    print(
        f"[target-profile] per-card figures: {len(by_card)} cards, {n_plotly} interactive Plotly specs", file=sys.stderr
    )
    return by_card


# --- Evidence-package emitter (--emit evidence-package) --------------------------------------
# The MACHINE-facing sibling of nomination.json: a deterministic, LLM-free evidence_package.json
# envelope conforming to the shared contract (target-contracts/schemas/evidence_package.schema.json),
# assembled from the per-sub-skill CompositionResult carriers via the SHARED writer. Purely
# additive — selected by --emit; the nomination path is untouched.


def _deciding_short(deciding_axis: dict) -> Optional[str]:
    """Map the deciding_axis block to the short whose gate is the envelope PRIMARY.

    gate_fired  → the gate that won; positive_signal → the strongest positive dimension;
    abstaining  → None (no primary; every gate block becomes `additional`)."""
    if deciding_axis.get("basis") == "gate_fired":
        return (deciding_axis.get("deciding_axis") or {}).get("short")
    if deciding_axis.get("basis") == "positive_signal":
        rows = deciding_axis.get("deciding_axes") or []
        return rows[0].get("short") if rows else None
    return None


def _framework_version() -> str:
    """The framework semver stamped into the envelope (distinct from SKILL_VERSION). Reads the
    canonical _skills_common.FRAMEWORK_VERSION (rehomed from the retired compose-dashboard)."""
    try:
        from _skills_common import FRAMEWORK_VERSION

        return FRAMEWORK_VERSION
    except Exception:  # noqa: BLE001
        return "2.0.0"


def _validate_evidence_package(ep: dict, contracts_root: Path) -> list[str]:
    """Validate an evidence_package against evidence_package.schema.json — the SAME check
    compose-dashboard applies to its envelope (compose_dashboard.py::_validate_evidence_package).
    target-profile's --emit path historically SKIPPED this, so a schema-invalid governance artifact
    was silently persisted + reported as success — most notably the `hgnc_id=-1` unresolved-identity
    sentinel that assemble_evidence_package emits ON PURPOSE to FAIL validation (envelope.py) but which
    only fails if someone actually validates. Returns a list of human-readable error strings (empty =
    valid). Graceful-skip (returns []) if jsonschema or the schema file is unreachable — never let the
    validator itself break an emit. FUTURE: consolidate this + compose-dashboard's identical copy into
    _skills_common.envelope beside assemble_evidence_package."""
    try:
        from jsonschema import Draft202012Validator
    except Exception:  # noqa: BLE001 — jsonschema absent (isolated env) → skip, don't crash emit
        return []
    schema_path = contracts_root / "schemas" / "evidence_package.schema.json"
    if not schema_path.exists():
        return []
    schema = json.loads(schema_path.read_text())
    errors = []
    for e in Draft202012Validator(schema).iter_errors(ep):
        path_str = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"[{path_str}] {e.message}")
    return errors


def _validation_summary_from_sub_results(sub_results: dict) -> dict:
    """The 5-field validation_summary, computed over the card union DEDUPED by card_id.

    (2026-08-15): a card can compose under >1 sub-skill lens (~5 multi-homed cards), so the raw
    cross-sub-skill card union double-counts them (~85 vs ~77 distinct) — inflating
    n_cards_attempted/passed/failed relative to the emitted evidence-package payload. That payload's
    `cards` array is deduped first-occurrence-per-card_id (skipping card_id-less entries) by
    _write_evidence_package; the governance counts must reflect the SAME deduped union, so the
    evidence-package governance AND nomination.json governance agree with what was actually emitted.
    (passed_with_warnings + excluded_by_applies_when stay 0: target-profile does no method validation
    and no target-level applies_when gating.)"""
    seen: set = set()
    deduped: list[dict] = []
    for r in sub_results.values():
        for c in r.get("cards") or []:
            cid = c.get("card_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            deduped.append(c)
    n_failed = sum(1 for c in deduped if c.get("_missing"))
    validation_summary = {
        "n_cards_attempted": len(deduped),
        "n_cards_passed": len(deduped) - n_failed,
        "n_cards_passed_with_warnings": 0,
        "n_cards_failed": n_failed,
        "n_cards_excluded_by_applies_when": 0,
    }
    return validation_summary


# --- Subtype-resolved evidence block (subtype-first-class-evidence spec, Option A) ------------
# Makes the per-stratum subtype SIGNALS machine-readable in the evidence package so the cross-evidence
# integrator can later reason at subtype resolution — WITHOUT changing the spine's deliberate
# "subtype = context, not a gate" treatment (the block is verdict-inert; agent consumption is a later stage).
# Two subtype-grain cards carry per_subgroup_metrics in target-profile's fan-out; the cross-axis
# convergence blob (_subtype_facet) — previously computed but DROPPED from the package (it rode only
# to nomination.json) — is embedded here too. The block is emitted ONLY under --subtypes; a default
# (no-strata) run gets None (no key added → byte-stable).
# (source-short, card_id, axis) — mirrors tp_facets._SUBTYPE_INPUTS so the per_stratum axes map covers
# the SAME three subtype-grain cards the convergence facet does. The expression (tumor-presence) card
# lives under the 'expression' short; dependency + mutation-frequency resolve under SUBTYPE_SHORT in
# production (per-gate short in the synthetic fixtures) — both are tried, per axis.
_SUBTYPE_STRAT_CARDS = [
    ("expression", "tumor-rna-distribution-by-subtype", "expression"),
    ("expression", "tumor-protein-distribution-by-subtype", "protein"),
    ("dependency", "subgroup-stratified-dependency", "dependency"),
    ("genomic_alteration", "subgroup-stratified-mutation-frequency", "mutation_frequency"),
]
# per_subgroup_metrics bookkeeping keys → everything else on a row is the axis metric (effect-size).
# Includes the tumor-rna-distribution-by-subtype reader's row keys (stratum_id / n_tumor_samples /
# match_rate) so the expression axis's metric block is not polluted by bookkeeping.
_SUBTYPE_BOOKKEEPING = {
    "stratum",
    "stratum_id",
    "subgroup_id",
    "subgroup_label",
    "subgroup",
    "subgroup_n",
    "n_tumor_samples",
    "match_rate",
    "subgroup_n_floor_met",
    "evidence_state",
    "source_cohort",
}
_SUBTYPE_RESOLVED_DISCLAIMER = (
    "SOFT integrator context, NOT a gate (subtype-first-class-evidence, Option A): per-stratum "
    "subtype SIGNALS surfaced machine-readable for the cross-evidence integrator. The deterministic "
    "spine is UNCHANGED — subtype cards stay verdict-inert, the negative-selection "
    "subtype_specific_non_dependence->hold is preserved, and NO positive subtype signal here enters "
    "the hard gate. Subtype never raises certainty beyond what a stratum's n supports; a stratum with "
    "subgroup_n_floor_met=false carries NO weight (absence-discipline at stratum grain)."
)


def _subtype_resolved_block(sub_results: dict, subtypes: list, subtype_facet: Optional[dict]) -> dict:
    """Assemble the first-class `subtype_resolved` evidence block. Per requested stratum: the
    per-axis per_subgroup_metrics projection (evidence_state + subgroup_n + n-floor-met + the
    effect-size metric) from the THREE subtype-grain cards — expression/presence
    (tumor-rna-distribution-by-subtype), dependency, and mutation-frequency — PLUS the cross-axis
    convergence facet (`_subtype_facet`). Deterministic, additive, verdict-inert.

    The expression/presence axis (added 2026-08-21) lets the integrator reason subtype-resolved
    PRESENCE — "present in MSS but absent/underpowered in MSI-H" — which was previously impossible
    (the presence per-stratum signal collapsed to display-only card scalars and never reached this
    block). Mirrors tp_facets._SUBTYPE_INPUTS so the per_stratum axes and the convergence facet cover
    the same cards.

    Absence is HONEST: a stratum/axis with no per_subgroup_metrics row contributes nothing; a row
    below its n-floor is carried with subgroup_n_floor_met=false so a consumer must not credit it.
    Called ONLY when subtypes were requested (byte-stable default otherwise)."""
    # subtype cards resolve under SUBTYPE_SHORT in production (composed inline in tp_fanout); tolerate
    # the per-gate short too (matches synthetic test fixtures) — mirrors _subtype_facet's lookup.
    from tp_facets import _first_card_per_subgroup, _subtype_stratum_key
    from tp_fanout import SUBTYPE_SHORT  # local import: avoid an import cycle at module load

    per_stratum_map: dict = {}
    available: set = set()
    for source_short, card_id, axis in _SUBTYPE_STRAT_CARDS:
        rows: list = []
        for _src in (source_short, SUBTYPE_SHORT):
            r = sub_results.get(_src)
            if r:
                rows = _first_card_per_subgroup(r, card_id)
                if rows:
                    break
        for rec in rows:
            st = _subtype_stratum_key(rec)
            if not st:
                continue
            available.add(st)
            rec_block = per_stratum_map.setdefault(st, {"stratum": st, "axes": {}})
            metric = {k: v for k, v in rec.items() if k not in _SUBTYPE_BOOKKEEPING and v is not None}
            # n normalization: the tumor-rna-distribution-by-subtype reader exposes per-stratum n as
            # `n_tumor_samples`, the subgroup_common panoramas as `subgroup_n`.
            n = rec.get("subgroup_n") if rec.get("subgroup_n") is not None else rec.get("n_tumor_samples")
            rec_block["axes"][axis] = {
                "evidence_state": rec.get("evidence_state"),
                "subgroup_n": n,
                "subgroup_n_floor_met": rec.get("subgroup_n_floor_met"),
                "metric": metric,
            }
    block = {
        "schema_version": 1,
        "requested_strata": list(subtypes),
        "available_strata": sorted(available),
        "per_stratum": [per_stratum_map[s] for s in sorted(per_stratum_map)],
        "_disclaimer": _SUBTYPE_RESOLVED_DISCLAIMER,
    }
    if subtype_facet is not None:
        block["convergence_facet"] = subtype_facet
    return block


def _write_evidence_package(
    *,
    args,
    sub_results: dict,
    gate_action: Optional[str],
    recommendation_gate: dict,
    confidence_tier: dict,
    deciding_axis: dict,
    validation_summary: dict,
    subtypes: Optional[list] = None,
    subtype_facet: Optional[dict] = None,
    certainty_by_axis: Optional[dict] = None,
    cross_gate_shared_evidence: Optional[dict] = None,
    fragility: Optional[dict] = None,
    competitor_crossref: Optional[dict] = None,
    modality_fit_by_channel: Optional[dict] = None,
    magnitude_borderline: Optional[list] = None,
    modality: Optional[str] = None,
) -> Path:
    """Assemble + write evidence_package.json around target-profile's composed verdict.

    Reuses the shared normalizers (`_envelope_card_present`, `_availability_state_for`) and writer
    (`assemble_evidence_package`) so the envelope conforms to the shared
    evidence_package.schema.json contract. The synthesis block is the SUPERSET shape (per product
    decision): target-profile's nomination fields (recommendation_gate / confidence_tier /
    deciding_axis) AND a schema-conformant primary/additional split AND the full per-sub-skill
    sub_verdicts — all sourced from the CompositionResult on each sub-skill (r["composition"]);
    NO re-resolution.
    """
    from _skills_common.dispatcher import _availability_state_for, _envelope_card_present
    from _skills_common.envelope import assemble_evidence_package
    from _skills_common.gitmeta import skills_repo_sha

    # Function-local: tp_facets imports tp_fanout/tp_gates, and run.py imports THIS module before
    # tp_facets — keep the module-import order it already relies on unperturbed.
    from tp_facets import _skill_reports_by_short, build_skill_report_rollup

    # 1. Union the sub-skills' cards by card_id (a card may compose under >1 lens; keep first),
    #    splitting present (normalized) vs reasoned-absence (card_unavailable).
    seen: set = set()
    env_present: list[dict] = []
    env_unavailable: list[dict] = []
    for r in sub_results.values():
        for c in r.get("cards") or []:
            cid = c.get("card_id")
            if not cid or cid in seen:
                continue
            seen.add(cid)
            if c.get("_missing"):
                state, reason = _availability_state_for(c)
                env_unavailable.append(
                    {
                        "card_id": cid,
                        "card_version": c.get("card_version", "n/a"),
                        "availability_state": state,
                        "availability_reason": reason,
                    }
                )
            else:
                env_present.append(_envelope_card_present(c))

    # 2. Resolve target-identity-summary separately so context.target carries a real hgnc_id
    #    (schema requires >= 1). Best-effort — on failure the writer emits the -1 sentinel.
    try:
        for c in resolve_cards(["target-identity-summary"], args.target, args.indication):
            cid = c.get("card_id")
            if not c.get("_missing") and cid and cid not in seen:
                seen.add(cid)
                env_present.append(_envelope_card_present(c))
    except Exception as e:  # noqa: BLE001 — identity read is best-effort; never break emit
        print(
            f"[target-profile] --emit evidence-package: target-identity read failed "
            f"({type(e).__name__}); context.target.hgnc_id will be the unresolved sentinel.",
            file=sys.stderr,
        )

    # 3. Synthesis block — SUPERSET. Per-short verdicts mirror nomination.json (verdict present even
    #    for gateless shorts); the primary/additional split reads the gate blocks the
    #    CompositionResult carries (gateless shorts contribute no block).
    sub_verdicts: dict = {}
    gate_blocks: dict = {}  # short -> primary_dict() (only shorts with a resolver gate)
    for short, r in sub_results.items():
        v = r.get("verdict")
        comp = r.get("composition")
        blk = comp.primary_dict() if comp is not None else None
        sub_verdicts[short] = {
            "gate": blk["gate"] if blk else None,
            "verdict": v[0] if v else None,
            "driving_rule_id": v[1] if v else None,
            "fired_rule_ids": [f["rule_id"] for f in (r.get("fired") or [])],
        }
        # Modality×safety seam: stamp the per-modality safety verdict onto the safety entry so the
        # cross-evidence integrator can refine its hold-grade safety cap per its OWN --modality (the
        # scalar `verdict` conflates all channels). Recomputed from the safety fired rules exactly as
        # tp_gates does for the exists_safe_modality suppression (single source of truth =
        # modality_safety.safety_verdict_by_modality). Best-effort + VERDICT-INERT: on any failure the
        # key is simply absent, so the envelope stays byte-stable for a target without a safety axis.
        if short == "safety":
            try:
                from _skills_common.modality_safety import safety_verdict_by_modality

                sub_verdicts[short]["safety_verdict_by_modality"] = safety_verdict_by_modality(r.get("fired") or [])
            except Exception as e:  # noqa: BLE001 — never break emit on a vocabulary read
                print(
                    f"[target-profile] --emit evidence-package: safety_verdict_by_modality stamp "
                    f"failed ({type(e).__name__}); the per-modality safety block will be absent.",
                    file=sys.stderr,
                )
        if blk is not None:
            gate_blocks[short] = blk

    primary_short = _deciding_short(deciding_axis)
    primary_block = gate_blocks.get(primary_short)
    # additional = every other gate block, in SUB_SKILLS iteration order (deterministic)
    additional_blocks = [b for s, b in gate_blocks.items() if s != primary_short]

    # gate_action is None when NO killer gate (veto/hold) fired. That is NOT "insufficient evidence" —
    # it means "no deterministic kill; the nominate/advance decision belongs to the narrative synthesis
    # (see nomination.json)". Labeling it "insufficient" mislabeled a strong POSITIVE target (a machine
    # consumer reading synthesis.headline saw "insufficient (strong confidence)" — incoherent, and it
    # disagreed with the same run's nomination.json). Use an honest neutral term for the no-kill case.
    # A1 (2026-09-11): `gate_action` carries only the KILL actions (veto/hold). The positive path
    # writes its forced `nominate` to recommendation_gate.forced_recommendation instead (it is
    # deliberately not a gate action — see nomination_verdict_gate.yaml action_precedence), so read
    # it here or --emit would keep publishing "no_deterministic_kill" for a strong-tier nomination.
    recommendation = gate_action or recommendation_gate.get("forced_recommendation") or "no_deterministic_kill"
    # The per-skill skill_report[] spine. It reached ONLY nomination.json (target_report.skill_reports)
    # even though the cross-evidence-hypothesis integrator consumes THIS artifact — so every report slot
    # a sub-skill emits (role / polarity / call / driving_rule_id / question_table / subgroup_signals /
    # evidence_graph / confidence / modality_scope) was absent from the machine package. That silently
    # erased the GATELESS descriptive axes: target-intrinsic's `sub_verdicts` entry is all-null
    # (gate/verdict/driving_rule_id) and its `claim_vectors` entry carries no role, so the integrator
    # could not distinguish "no verdict BECAUSE gateless-by-design (role=descriptive,
    # polarity=not_scored)" from "no verdict because the axis failed / had no data" — the exact
    # distinction routing needs. Carried verbatim (no re-derivation) + its role-grouped projection.
    skill_reports = _skill_reports_by_short(sub_results)
    tier = confidence_tier.get("tier")
    headline = f"{args.target} in {args.indication}: {recommendation}" + (f" ({tier} confidence)" if tier else "")
    synthesis_block = {
        "headline": headline,
        "caveats_summary": (
            "Composed target-profile evidence envelope (--emit evidence-package): a deterministic "
            "nomination gate over per-sub-skill resolver verdicts. LLM narrative intentionally "
            "omitted (see nomination.json for the narrated form); not concurrence-reviewed."
        ),
        # nomination-shaped — target-profile's actual verdict model
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        # compose-dashboard-shaped — comparable to the other engine's envelopes
        "primary_gate_verdict": primary_block,
        "additional_gate_verdicts": additional_blocks,
        # full per-sub-skill grouping
        "sub_verdicts": sub_verdicts,
        # verdict-INERT per-skill skill_report[] SPINE (see the `skill_reports` derivation above) plus its
        # role-grouped projection. The rollup's INV-6 coherence flag is cross-checked against the
        # recommendation THIS package publishes (`recommendation`), not nomination.json's narrated call, so
        # the flag describes the artifact the reader is holding. Both default-empty → a run whose skills
        # emit no reports stays BYTE-STABLE. NEVER moves the spine (sub_verdicts / recommendation_gate).
        "skill_reports": skill_reports,
        "skill_report_rollup": (
            build_skill_report_rollup(skill_reports, {"recommendation": recommendation}, modality_fit_by_channel)
            if skill_reports
            else {}
        ),
        # verdict-INERT claim-vector signal facets — the SIGNAL decomposition + citable
        # evidence atoms per sub-skill, for downstream cross-evidence reasoning (not just the label).
        "claim_vectors": _claim_vectors_from_sub_results(sub_results),
        # verdict-INERT DATA layer — per-sub-skill evidence capsules (bounded raw behind the classes,
        # card-floor complete) so the cross-evidence agent can cite the raw data, not just labels.
        "evidence_capsules": _capsules_from_sub_results(sub_results, args.indication),
        # verdict-INERT DECISION FACETS — the reader-facing facet layer that previously reached only
        # nomination.json (certainty, cross-gate correlation, flip-fragility + acquisition backlog,
        # competitor cross-ref). Carried here so the cross-evidence-hypothesis integrator (which consumes
        # THIS artifact, not nomination.json) can reason over per-axis certainty, prefer the spine's own
        # correlated-evidence grouping over its re-derivation, and surface contested/backlog/competitor
        # signals. NEVER moves the recommendation spine (sub_verdicts / recommendation_gate). All members
        # default-empty so a run that computed none stays BYTE-STABLE.
        "decision_facets": {
            "certainty_by_axis": certainty_by_axis or {},
            "cross_gate_shared_evidence": cross_gate_shared_evidence or {},
            "fragility": fragility or {},
            "competitor_crossref": competitor_crossref or {},
            # FACTORED-RECORD consumers (M4): per-modality favorability rolled up from each axis's
            # record modality_scope (worst-case conjunction), and the over-precision/knife-edge audit
            # from magnitude value+distance_to_cut. Carried so the cross-evidence integrator reasons over
            # per-MODALITY calls + magnitude fragility, not just the scalar verdict. Verdict-INERT;
            # default-empty → byte-stable for packages that computed none.
            "modality_fit_by_channel": modality_fit_by_channel or {},
            "magnitude_borderline": magnitude_borderline or [],
            # The modality this package was COMPOSED under (None for a modality-agnostic run). The
            # recommendation_gate.hard_gates (esp. the exists_safe_modality safety suppression) are
            # frozen under THIS modality, so the cross-evidence integrator must compare it to its own
            # --modality and surface a mismatch rather than trusting a ceiling built for another channel.
            # (Homed here, not context, so the shared assemble_evidence_package envelope stays untouched.)
            "composed_modality": modality,
        },
    }

    # subgroup_spec: STOP hardcoding null (subtype-first-class-evidence, Option A). Record the
    # requested strata when the run was subtype-scoped (--subtypes); a default (no-strata) run keeps
    # None, so the envelope stays BYTE-STABLE. The schema's context.subgroup_spec accepts null | 'all'
    # | list-of-strings.
    input_context = {
        "target_symbol": args.target,
        "indication": args.indication,
        "subgroup_spec": (list(subtypes) if subtypes else None),
        # The evidence_package schema's governance.data_mode enum is {latest_approved, pinned,
        # exploratory} — target-profile's internal "live_latest" is not a member. A live, unpinned,
        # non-concurrence-reviewed composed run IS exploratory (mirrors the dispatcher subskill
        # emitter's _GOVERNANCE_DATA_MODE default). nomination.json keeps its own "live_latest"
        # governance (that artifact is not bound to this schema).
        "data_mode": "exploratory",
        "release_pin": args.release_pin or "unpinned",
    }
    ep = assemble_evidence_package(
        input_context=input_context,
        dashboard_spec_ref="skill:target-profile",
        card_outputs=env_present,
        unavailable_cards=env_unavailable,
        validation_summary=validation_summary,
        synthesis_block=synthesis_block,
        deterministic_timestamps=False,
        framework_version=_framework_version(),
        generated_by=f"skills/{SKILL_NAME}@{skills_repo_sha()}",
        # (2026-08-15): target-profile cards declare their inputs as products.yaml product_ids
        # (resolve_cards stamps card_input_manifest_ids), so a product-id family's is_stale was
        # trivially True (head — a concrete manifest id — is never == a product_id). Opt into the
        # honest-staleness refinement so those families report indeterminate, not false-stale. Kept
        # OFF for compose-dashboard (its envelope byte-golden is unchanged).
        refine_product_id_staleness=True,
        # Stamp per-card (measurement_type, evidence_substrate, required_product_ids) so
        # cross-evidence-hypothesis's correlated-evidence discount (substrate_independence) actually
        # fires — without a stamp every card counts as its own independent substrate and the discount
        # is inert. Best-effort / fail-open in envelope; the fields are schema-declared-optional.
        stamp_evidence_substrate=True,
    )
    # First-class subtype_resolved block (subtype-first-class-evidence, Option A). Attached ONLY under
    # --subtypes; a default run adds no key, so the envelope is byte-identical. Added AFTER assembly
    # (not via the shared writer) to keep this change entirely within skills/target-profile/ — the
    # shared envelope.py is owned by a sibling PR. Verdict-inert; the spine is untouched.
    if subtypes:
        ep["subtype_resolved"] = _subtype_resolved_block(sub_results, subtypes, subtype_facet)
    # target-profile reads live + has no target-level applies_when gating; keep its governance
    # `_note` annotation off the envelope (it is a nomination.json/provenance detail).
    out_path = args.out / "evidence_package.json"
    out_path.write_text(json.dumps(ep, indent=2, default=str))
    # Validate the emitted envelope against evidence_package.schema.json — the sibling engine
    # (compose-dashboard) does this; target-profile must too, else a schema-invalid governance
    # artifact (e.g. hgnc_id=-1 when target-identity failed to resolve) is silently persisted and
    # reported as success. Fail LOUD: the file is written for inspection, but a non-zero exit + the
    # error list stop it being mistaken for a valid governance-grade package.
    # FAIL-LOUD is scoped to the MACHINE-EMIT mode (--emit evidence-package) only. The
    # grounded-substrate chain is DEFAULT-ON (SKILL_VERSION 1.2.0), so _write_evidence_package now
    # runs on EVERY normal nomination (run.py gates the call on `... or substrate_chain_on`). A
    # target whose target-identity fails to resolve (the hgnc_id=-1 sentinel) yields a schema-invalid
    # INTENDED-substrate envelope — but that must NOT abort the flagship run before the human-facing
    # artifacts (target_profile.md / .html / nomination.json) are written. So: raise ONLY in the
    # machine mode where a governance-grade envelope is the sole deliverable; on a default/substrate
    # run, WARN and continue (return the path) so the schema-invalid substrate degrades gracefully
    # and the nomination path still emits.
    schema_errors = _validate_evidence_package(ep, _CONTRACTS_REPO)
    if schema_errors:
        _machine_emit = getattr(args, "emit", None) == "evidence-package"
        _lead = "--emit evidence-package: envelope FAILED" if _machine_emit else "grounded-substrate envelope FAILED"
        print(
            f"[target-profile] {_lead} evidence_package.schema "
            f"validation ({len(schema_errors)} error(s)) — NOT a governance-grade artifact "
            f"(written to {out_path} for inspection):",
            file=sys.stderr,
        )
        for e in schema_errors[:20]:
            print(f"    - {e}", file=sys.stderr)
        if _machine_emit:
            raise SystemExit(1)
        print(
            "[target-profile] WARN: schema-invalid substrate envelope on a default/nomination run "
            "— continuing so target_profile.md / .html / nomination.json still emit (the invalid "
            "envelope is retained for inspection; it feeds the verdict-inert substrate chain only).",
            file=sys.stderr,
        )
    return out_path


__all__ = [
    "_deciding_short",
    "_emit_card_figures",
    "_framework_version",
    "_load_figure_registry",
    "_validate_evidence_package",
    "_subtype_resolved_block",
    "_validation_summary_from_sub_results",
    "_write_evidence_package",
]
