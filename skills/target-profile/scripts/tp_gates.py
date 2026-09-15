"""target-profile — the cross-gate nomination gate + gate-coverage + positive-tier + gate-scorecard.
Deterministic nomination spine loaders (declarative policy from target-contracts, conservative fallbacks)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import yaml

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from tp_common import _CONTRACTS_REPO

# Skills root on path for the shared per-modality safety transform (VERDICT_REPRESENTATION.md L2b/3).
_SKILLS_ROOT = str(Path(__file__).resolve().parents[2])
if _SKILLS_ROOT not in sys.path:
    sys.path.insert(0, _SKILLS_ROOT)
from _skills_common.modality_safety import safety_verdict_by_modality

# The WT-loss / full-KO safety concerns the resolver now emits RAW (the role-proxy scalar downgrade
# was retired 2026-08-24). exists-safe-modality re-applies the modality-conditional downgrade at the
# gate: a concern is cleared when the per-modality safety verdict shows an admissible safe channel.
_SAFETY_WT_LOSS_CONCERNS = frozenset(
    {
        "highly_constrained_safety_concern",
        "human_genetics_safety_concern",
        "pan_essential_broad_tox_concern",
        "normal_tissue_protein_safety_concern",
    }
)
# An allele-selective escape (small_molecule=conditional) UNCONDITIONALLY clears a fired WT-loss concern
# — matching the retired resolver downgrade's GoF-only scope. 'no_concern'/'supportive' never legitimately
# co-occur with a fired concern; excluding them also stops a minimal/empty fired list from spuriously
# clearing a real hold (fail-closed). 'not_applicable' (biologics) is handled SEPARATELY in the
# exists-safe-modality block (T2c) — it clears a WT-loss hold ONLY when the biologics arm is viable
# (explicit biologics --modality or a favorable surface fit), never unconditionally.
_SAFETY_SAFE_ACTIONS = frozenset({"conditional"})
# Surface-directed biologics channels: WT-loss is not their operative safety axis (they report
# safety action=not_applicable). Kept in sync with modality_safety.py's not_applicable engagement set.
_BIOLOGICS_CHANNELS = frozenset({"adc", "bite_tce", "antibody"})


# --- Deterministic recommendation gate --------------------------------------
#
# The overall_recommendation was historically 100% LLM-chosen (the LLM saw the
# sub-verdicts as prompt text and picked nominate|hold|veto|insufficient_evidence).
# A killer sub-verdict must FORCE the call, not merely suggest it.
#
# This is the cross-gate NOMINATION gate — a DISTINCT layer from the 9 per-axis
# verdict gates. It does NOT reimplement per-gate verdicts: each sub-skill already
# resolves its own gate via the shared resolver, and target-profile INHERITS those
# sub-verdicts (r["verdict"]); this gate only maps the (sub_skill, verdict) tuples to
# a nominate/hold/veto action. That policy is itself declarative — it lives in
# target-contracts/vocabularies/nomination_verdict_gate.yaml (there is no per-gate
# resolver for "nomination"; this vocab is its home), loaded below with a conservative
# hardcoded fallback-of-record.
#
# HISTORY: this gate's killer-short-circuit shape once echoed compose-dashboard's
# _synthesis.py fit_level scorer. That second engine was removed —
# compose-dashboard now routes through the same shared resolver — so the "two composition
# engines" that motivated the copied-not-shared pattern no longer exist; only this
# higher-level nomination layer remains, and it is intentionally its own declarative gate.
#
# CURATED veto set (conservative): only genuine CROSS-TARGET vetoes force veto.
# Modality-scoped killers (surface neither_viable, degrader expression killers)
# are deliberately EXCLUDED — they foreclose one modality, not the target (KRAS
# hits surface/degrader killers yet is a correct `nominate` via small molecule;
# see the KRAS×COADREAD golden).
#
# The AUTHORITATIVE policy lives in target-contracts/vocabularies/
# nomination_verdict_gate.yaml (reviewable by product owners without a code
# change). This hardcoded set is the FALLBACK-OF-RECORD: if the vocab is
# missing/unparseable, _load_gate_verdicts() returns this and warns. The gate
# must NEVER become permissive on a missing policy file — a silently-disabled
# pan-essential veto would be a safety regression — so the fallback is
# conservative-and-complete, and the vocab can only match-or-tighten it.
_FALLBACK_GATE_VERDICTS: dict[tuple[str, str], str] = {
    ("dependency", "pan_essential_killer"): "veto",  # non-selective essentiality — no window
    ("dependency", "non_dependent"): "veto",  # no dependency at all
    ("safety", "highly_constrained_safety_concern"): "hold",  # concern → hold, not veto
    # 2026-08-16: the fallback must be conservative-AND-COMPLETE — it must mirror the ENTIRE
    # gates block, not just the veto arms, so a missing/unparseable vocab still fires every
    # HOLD too (a missing policy silently dropping the human-genetics or subtype hold would be a
    # fail-open). These two were previously vocab-only.
    ("safety", "human_genetics_safety_concern"): "hold",  # P5 human-genetics WT-loss concern
    ("safety", "pan_essential_broad_tox_concern"): "hold",  # data-util expansion 2026-08-21 — broad tox
    ("safety", "normal_tissue_protein_safety_concern"): "hold",  # data-util expansion 2026-08-21 — HPA-IHC
    ("subtype_fit", "subtype_specific_non_dependence"): "hold",  # queried subtype has no dependency
}
# Precedence when multiple gates fire: veto dominates hold. (2026-08-20): READ from the
# owner-editable vocab (nomination_verdict_gate.action_precedence) so the vocab is authoritative, with
# this hardcoded map as the conservative fallback-of-record — NEVER empty (a missing precedence must not
# flatten veto vs hold into a permissive tie). The guard test asserts the loaded value matches vocab.
_FALLBACK_GATE_ACTION_RANK = {"veto": 2, "hold": 1}


def _load_action_precedence(contracts_repo: Path | None = None) -> dict:
    """action_precedence (veto/hold ranks) from the nomination-gate vocab; _FALLBACK on any failure."""
    repo = contracts_repo or _CONTRACTS_REPO
    try:
        data = yaml.safe_load((repo / "vocabularies" / "nomination_verdict_gate.yaml").read_text())
        prec = (data or {}).get("action_precedence")
        if isinstance(prec, dict) and prec:
            return {str(k): int(v) for k, v in prec.items()}
    except Exception:  # noqa: BLE001 — any failure → conservative hardcoded fallback (never empty)
        pass
    return dict(_FALLBACK_GATE_ACTION_RANK)


_GATE_ACTION_RANK = _load_action_precedence()

# --- Fail-closed, gate-complete guard (invariant 6) -----------
#
# The GATING (recommendation-forcing) axes: the sub-skills that can force
# overall_recommendation via a `gates` veto/hold. An UNKNOWN / RENAMED / MALFORMED
# verdict on one of THESE axes previously returned None → a SILENT PERMISSIVE PASS
# (the fail-open). Instead, such a verdict now routes to the axis's LEAST-PERMISSIVE
# action (never None), loudly recorded. Hardcoded (not derived from the loaded vocab)
# so a degraded/missing vocab cannot shrink the gating-axis set and re-open the hole.
_GATING_AXES: frozenset[str] = frozenset({"dependency", "safety", "subtype_fit"})

# OPT-IN-BY-SCOPE gating axes: gating (a fired verdict forces a hold/veto) BUT
# ONE-DIRECTIONAL and only in scope when the run requests it. subtype_fit fires
# `subtype_specific_non_dependence` ONLY on a MEASURED, floor-cleared, not-dependent
# QUERIED stratum (see tp_fanout._subtype_verdict); it enters sub_results ONLY under
# --subtypes. Its SILENCE is therefore the dormant/OK state — NOT a coverage gap that
# could hide a kill. So when such an axis produced no verdict it must NOT be labelled
# `blind` in the hard-gate status block: the cross-evidence integrator's fail-closed
# ceiling treats a blind gated axis as a veto, which would wrongly DECLINE every target
# on the (default) no-subtypes path. Distinguish scope-foreclosed (axis absent → not
# requested) from evaluated-but-dormant (requested, positive/None verdict).
_SCOPE_OPTIN_GATING_AXES: frozenset[str] = frozenset({"subtype_fit"})

# The COMPLETE recognized verdict vocabulary each gating axis can legitimately emit
# (mirrors resolvers/{dependency,safety}.resolver.yaml + the subtype panorama). A verdict
# on a gating axis OUTSIDE this set is treated as unrecognized (a possible renamed kill) and
# fails CLOSED. This is the "hardcoded complete fallback": if a resolver adds a genuinely NEW
# benign verdict without this set being updated, the gate OVER-clamps (least-permissive) —
# the SAFE direction (loud, never silent) — and the regression fixtures catch it immediately.
_RECOGNIZED_GATING_VERDICTS: dict[str, frozenset[str]] = {
    "dependency": frozenset(
        {
            "pan_essential_killer",
            "non_dependent",  # the two vetoes
            "concordant_dependent",
            "lineage_selective",
            "selective_dependent",
            "chemical_genetic_confirmed_dependent",
            "partner_conditional_dependent",
            "discordant",
            "broadly_dependent",  # contradictions
            "non_dependent_paralog_buffered",  # veto-rescue (benign)
            "insufficient",
            "insufficient_underpowered",
            "insufficient_underpowered_pan_essential",  # admissibility guards
        }
    ),
    "safety": frozenset(
        {
            "highly_constrained_safety_concern",
            "human_genetics_safety_concern",  # the four holds
            "pan_essential_broad_tox_concern",
            "normal_tissue_protein_safety_concern",  # data-util expansion 2026-08-21
            # (the wt_*_mechanism_mismatch downgrade tokens were RETIRED with the scalar role-proxy downgrade,
            # safety.resolver v2.0.0 — pruned here 2026-09-07; the resolver no longer emits them.)
            "tolerant_reduced_safety_risk",
            "moderately_constrained_safety",
            "data_unavailable",
            "insufficient",
        }
    ),
    "subtype_fit": frozenset(
        {
            "subtype_specific_non_dependence",  # the hold
            "subtype_restricted_dependency",  # SUPPORTIVE positive + veto-suppressor
            "subtype_restricted_selectivity",  # SUPPORTIVE positive (tumor-tissue selectivity; NOT a
            #                                                               veto-suppressor) — 2026-09-11 STAD subtype-shard
            #                                                               wiring. Non-gating: falls through as a permissive
            #                                                               pass (like subtype_restricted_dependency).
            "insufficient",  # (vocab: positive_signals + veto_suppressors,
            #                                                               NOT gates/kill_capable → recognized, non-gating:
            #                                                               falls through as a permissive pass, never forces
            #                                                               hold. Was missing → fail-closed hold on --subtypes
            #                                                               runs where the subtype tier fired positive.)
        }
    ),
}

# The LEAST-PERMISSIVE forced action per gating axis, applied when that axis emits an
# unrecognized / malformed verdict. dependency's floor is veto (it owns the two vetoes);
# safety + subtype are hold. Never None.
_GATING_AXIS_FAILCLOSED_ACTION: dict[str, str] = {
    "dependency": "veto",
    "safety": "hold",
    "subtype_fit": "hold",
}


# The complete kill_capable_verdicts registry FALLBACK (mirrors target-contracts
# vocabularies/nomination_verdict_gate.yaml). {(sub_skill, verdict): disposition}, disposition
# ∈ {gated, excluded_modality_scoped, contradiction, uncorroborated}. Used to iterate the COMPLETE
# declared kill set for the hard_gates status block; conservative-and-complete on load failure
# (never empty). MUST move in lockstep with the vocab: this mirror is what a pre-v1.20.0 (or
# unreadable) contracts checkout falls back to, so a disposition that moves there and not here makes
# the hard_gates block disagree with the gate depending only on which checkout CI happened to read.
_FALLBACK_KILL_CAPABLE_VERDICTS: dict[tuple[str, str], str] = {
    ("dependency", "pan_essential_killer"): "gated",
    ("dependency", "non_dependent"): "gated",
    # `uncorroborated`, not `contradiction` (vocab v1.20.0): CRISPR and RNAi disagree with EACH OTHER,
    # which is an absence of resolution, not a measurement against the target. Still blocks `strong`.
    ("dependency", "discordant"): "uncorroborated",
    ("dependency", "broadly_dependent"): "contradiction",
    ("safety", "highly_constrained_safety_concern"): "gated",
    ("safety", "human_genetics_safety_concern"): "gated",
    ("safety", "pan_essential_broad_tox_concern"): "gated",  # data-util expansion 2026-08-21
    ("safety", "normal_tissue_protein_safety_concern"): "gated",  # data-util expansion 2026-08-21
    ("subtype_fit", "subtype_specific_non_dependence"): "gated",
    ("selectivity", "not_selective"): "contradiction",
    # `uncorroborated`, not `contradiction` (vocab v1.20.0) — the two comparator arms disagree on the
    # tumour-vs-normal window (rung `tvn-discordant-neutral-flagged`; the resolver's own `upgrade:`
    # block groups it with `not_informative` as rescuable). NOTE tractability_sm/discordant BELOW
    # deliberately stays a `contradiction`: there the discordance IS the finding.
    ("selectivity", "discordant_across_comparators"): "uncorroborated",
    ("selectivity", "selective_but_broadly_normal"): "contradiction",  # post-resolver clamp KILL (gate v1.10.0)
    ("selectivity", "selective_but_stromal_confound"): "contradiction",  # post-resolver clamp KILL (gate v1.10.0)
    ("surface_modality", "neither_viable"): "excluded_modality_scoped",
    ("surface_modality", "adc_preferred_tce_unsafe"): "excluded_modality_scoped",
    ("surface_modality", "tce_unsafe_normal_liability"): "excluded_modality_scoped",
    ("surface_modality", "shed_dominant_opposed"): "excluded_modality_scoped",
    ("tractability_sm", "structurally_intractable"): "excluded_modality_scoped",
    ("tractability_sm", "chemically_unhit"): "contradiction",
    ("tractability_sm", "discordant"): "contradiction",
}


def _load_gate_verdicts(contracts_repo: Path | None = None) -> tuple[dict[tuple[str, str], str], str]:
    """Load the (sub_skill, verdict) → action policy from the target-contracts
    vocabulary. Returns (mapping, source) where source ∈ {"vocab", "fallback"}.

    SAFETY CONTRACT: on ANY failure (file missing, parse error, malformed) this
    returns the conservative hardcoded _FALLBACK_GATE_VERDICTS + "fallback" and
    warns — it must never return an empty/permissive map, which would silently
    disable the veto.
    """
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        gates = data["gates"]
        mapping = {(g["sub_skill"], g["verdict"]): g["action"] for g in gates}
        if not mapping:
            raise ValueError("empty gates list")
        return mapping, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → safe conservative fallback
        print(
            f"[target-profile] WARN: could not load nomination_verdict_gate vocab "
            f"({type(e).__name__}: {e}); using hardcoded conservative fallback.",
            file=sys.stderr,
        )
        return dict(_FALLBACK_GATE_VERDICTS), "fallback"


def _load_kill_capable_verdicts(
    contracts_repo: Path | None = None,
) -> tuple[dict[tuple[str, str], str], str]:
    """Load the COMPLETE kill_capable_verdicts registry from the vocab.
    Returns ({(sub_skill, verdict): disposition}, source), disposition ∈
    {gated, excluded_modality_scoped, contradiction}.

    SAFETY CONTRACT (mirrors _load_gate_verdicts): on ANY failure this returns the
    conservative-and-complete hardcoded fallback + "fallback" and warns — never an empty
    map (a missing registry must not shrink the declared kill set the hard_gates block
    iterates)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        reg = data["kill_capable_verdicts"]
        mapping: dict[tuple[str, str], str] = {}
        for sub_skill, entries in reg.items():
            for e in entries:
                mapping[(sub_skill, e["verdict"])] = e["disposition"]
        if not mapping:
            raise ValueError("empty kill_capable_verdicts")
        return mapping, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → conservative-and-complete fallback
        print(
            f"[target-profile] WARN: could not load kill_capable_verdicts registry "
            f"({type(e).__name__}: {e}); using hardcoded complete fallback.",
            file=sys.stderr,
        )
        return dict(_FALLBACK_KILL_CAPABLE_VERDICTS), "fallback"


# Biologics modalities for which the dependency veto is INFORMATIVE-only (a
# surface-directed biologic kills via antigen engagement, not genetic dependency).
_BIOLOGICS_MODALITIES = {"adc", "bite_tce", "antibody"}


# Surface_modality fit_class verdicts that mean a surface therapeutic arm is VIABLE — the
# co-condition that lets the biology-axis downgrade (branch C) fire (a surface antigen with NO viable
# arm, neither_viable / shed_dominant_opposed, still vetoes). Keep in sync with the vocab block.
_SURFACE_FAVORABLE_VERDICTS = frozenset(
    {
        "both_viable",
        "adc_preferred",
        "tce_preferred",
        "adc_preferred_tce_unsafe",
        "surface_viable_density_caveated",
    }
)

# Among the FAVORABLE surface verdicts, the tokens that nonetheless EXPLICITLY foreclose a specific
# biologics channel — so a WT-loss escape must NOT cite that (foreclosed) channel as a safe modality.
# Only `adc_preferred_tce_unsafe` names an explicit foreclosure within the favorable set (TCE unsafe;
# it is the surface_modality `excluded_modality_scoped` verdict); the others foreclose nothing. This keeps
# `exists_safe_modality.safe_channels` = channels that are BOTH WT-loss-safe AND not surface-foreclosed
# (the "genuinely viable" arm the escape actually rests on), rather than a per-veto scope list that a
# reader could over-read as global modality viability (e.g. listing bite_tce for an ADC-only ERBB2).
_SURFACE_VERDICT_FORECLOSED_CHANNELS = {
    "adc_preferred_tce_unsafe": frozenset({"bite_tce"}),
}


def _load_veto_suppressors(
    contracts_repo: Path | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict], str]:
    """Load the veto-suppression + downgrade policies from the vocab. Returns
    (context_escape_suppressors, modality_scoped_suppression, biology_axis_downgrade,
    gof_driver_downgrade, source).

    CONSERVATIVE FALLBACK (mirrors the never-permissive contract, inverted for a
    suppressor): on ANY failure this returns EMPTY lists — a missing/malformed
    suppressor block means NO suppression fires and the full veto stands. A
    suppressor can therefore only ever make the gate MORE conservative when its
    own policy is present; its absence can never disable a veto.
    """
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        ctx = data.get("veto_suppressors", []) or []
        msvs = data.get("modality_scoped_veto_suppression", []) or []
        bavd = data.get("biology_axis_scoped_veto_downgrade", []) or []
        gdvd = data.get("gof_driver_scoped_veto_downgrade", []) or []
        return ctx, msvs, bavd, gdvd, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no suppression, veto stands)
        print(
            f"[target-profile] WARN: could not load veto suppressors "
            f"({type(e).__name__}: {e}); suppression DISABLED (full veto stands).",
            file=sys.stderr,
        )
        return [], [], [], [], "fallback"


def _load_thesis_axis_relevance(contracts_repo: Path | None = None) -> dict[str, set[tuple[str, str]]]:
    """Load the Step-2b `thesis_axis_relevance` block → {thesis: {(sub_skill, verdict), ...}}: the
    (axis, verdict) gate hits a given thesis makes IRRELEVANT (dropped before the veto is forced).
    CONSERVATIVE FALLBACK: any failure / absent block → EMPTY → NO thesis routing (today's gate). A
    missing block can never disable a veto; only a present, PR-reviewed entry can."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        out: dict[str, set[tuple[str, str]]] = {}
        for blk in data.get("thesis_axis_relevance", []) or []:
            th = blk.get("thesis")
            if not th:
                continue
            out[th] = {(ir["sub_skill"], ir["verdict"]) for ir in (blk.get("irrelevant") or []) if ir.get("sub_skill")}
        return out
    except Exception:  # noqa: BLE001 — absent/malformed → no thesis routing (veto stands)
        return {}


def _card_field_value(sub_results: dict, card_id: str, field: str):
    """The live value of `sub_results[*].cards[*].summary[field]` for the card `card_id`, or None if
    the card did not compose this run or carries no such key. A local scan (NOT
    tp_facets._find_card_summary) avoids a tp_gates→tp_facets import cycle (tp_facets already imports
    tp_gates). ABSENCE and an explicit null are indistinguishable here ON PURPOSE — both mean "not
    measured", and every caller must treat that as UNSATISFIED (the honest-negative discipline)."""
    for r in sub_results.values():
        if not isinstance(r, dict):
            continue
        for c in r.get("cards") or []:
            if isinstance(c, dict) and c.get("card_id") == card_id:
                got = (c.get("summary") or {}).get(field)
                if got is not None:
                    return got
    return None


def _trigger_label(w: dict, present: set, sub_results: dict) -> Optional[str]:
    """Return a provenance label if the veto-suppressor `when_present` trigger `w` is satisfied,
    else None. Trigger forms:
      - VERDICT-tuple  {sub_skill, verdict}      → matched against the live sub-verdict `present` set.
      - CARD-FIELD     {card_id, field, value}   → matched against a composed card's summary field
        (2026-08-21). Lets a suppressor key on a signal carried by a card under a GATELESS sub-skill
        (verdict=None) — e.g. synthetic-lethal-partners.sl_partner_class after the SL short was
        consolidated into combination_vulnerability.
      - CARD-FIELD SET {card_id, field, value_in: [...]}  → the same, satisfied by ANY value in the
        list (Step 3, 2026-09-11). The single-`value` form forced one policy entry per admissible
        token, which for a graded enum (density_floor_verdict has 3 measured values vs 1 abstention
        token) meant the policy said "these 3 specific values" three times instead of once. `value`
        and `value_in` are mutually exclusive; if both appear, BOTH must match (fail-closed).
    Defensive: an unrecognized/garbled trigger shape returns None (never matches, never raises)."""
    if not isinstance(w, dict):
        return None
    if "card_id" in w:
        cid, field = w.get("card_id"), w.get("field")
        got = _card_field_value(sub_results, cid, field)
        if got is None:
            return None
        if "value" in w and got != w.get("value"):
            return None
        if "value_in" in w:
            allowed = w.get("value_in")
            if not isinstance(allowed, (list, tuple, set)) or got not in allowed:
                return None
        if "value" not in w and "value_in" not in w:
            return None  # a card-field trigger with no expected value is vacuous → never matches
        return f"{cid}.{field}={got}"
    if "sub_skill" in w and "verdict" in w:
        return f"{w['sub_skill']}:{w['verdict']}" if (w["sub_skill"], w["verdict"]) in present else None
    return None


def _verdict_token(v) -> Optional[str]:
    """The bare verdict string from a sub-result's `verdict` ((verdict, driving_rule) tuple / list)."""
    return v[0] if isinstance(v, (list, tuple)) and len(v) >= 1 and isinstance(v[0], str) else None


def _load_contradiction_reconcilers(contracts_repo: Path | None = None) -> list:
    """Load the cross-axis `contradiction_reconcilers` block from the gate vocab. A reconciler DROPS a
    CONTRADICTION verdict (distinct from veto_suppressors, which suppress a dependency VETO/HOLD action)
    when a co-present verdict on another axis proves it is measured on the wrong basis. CONSERVATIVE
    FALLBACK: [] on any failure — nothing reconciled, the contradiction stands (gate stays conservative)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        return yaml.safe_load(path.read_text()).get("contradiction_reconcilers", []) or []
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (nothing reconciled; contradiction stands)
        print(
            f"[target-profile] WARN: could not load contradiction_reconcilers "
            f"({type(e).__name__}: {e}); reconciliation DISABLED (contradictions stand).",
            file=sys.stderr,
        )
        return []


def _reconciled_contradiction_keys(sub_results: dict, contracts_repo: Path | None = None) -> set:
    """Return the {(short, verdict)} contradiction keys to RECONCILE (drop) given the live cross-axis
    sub-verdicts. A key reconciles only when (a) its `reconciles` verdict is actually PRESENT and (b) a
    `when_present` trigger fires. Fail-closed: empty set on any failure. Callers subtract this from the
    contradiction set so the deterministic strong-block, the gate scorecard, and the synthesis role all
    move together (a reconciled contradiction no longer blocks `strong` nor reads as opposing)."""
    recs = _load_contradiction_reconcilers(contracts_repo)
    if not recs:
        return set()
    present = {(short, _verdict_token(r.get("verdict"))) for short, r in sub_results.items() if isinstance(r, dict)}
    out: set = set()
    for rc in recs:
        rec = rc.get("reconciles") or {}
        key = (rec.get("sub_skill"), rec.get("verdict"))
        if key not in present:  # only reconcile a contradiction that actually fired
            continue
        if any(_trigger_label(w, present, sub_results) for w in (rc.get("when_present") or [])):
            out.add(key)
    return out


def _suppressed_gate_hits(
    hits: list[dict],
    sub_results: dict,
    modality: Optional[str],
    contracts_repo: Path | None = None,
    biology_axis: Optional[str] = None,
    thesis: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """Apply v1.2.0 veto suppression to the fired gate hits. Returns
    (surviving_hits, suppression_records). A hit is suppressed when EITHER:

    (A) context-escape — a `veto_suppressors` rule names it as `suppresses` AND one
        of its `when_present` rescue verdicts fired (a MEASURED biomarker-stratified
        dependency proves the target is required in its stratum → the pooled
        non_dependent read is a dilution artifact). Rescues EGFR/IDH1/FLT3.
    (B) modality-scoped — a `modality_scoped_veto_suppression` rule names it AND the
        declared modality is in the rule's `when_modality_in` (a surface biologic
        kills via antigen engagement, not dependency). Rescues CD19/TROP2/DLL3.
        Fires ONLY when a modality is explicitly declared.

    CONSERVATIVE: empty suppressor policy → nothing suppressed (full veto stands).
    Only `dependency` veto arms are ever suppressible (the vocab enforces this too).
    """
    ctx_supps, msvs, bavd, gdvd, src = _load_veto_suppressors(contracts_repo)
    # Step 2b: the target's thesis may make an axis IRRELEVANT (drop the veto before it forces). Loaded
    # here so a thesis can suppress even when the epicycle suppressors are empty (they are retired in 2c).
    thesis_irrelevant = _load_thesis_axis_relevance(contracts_repo)
    thesis_drop = thesis_irrelevant.get(thesis, set()) if thesis else set()
    if not ctx_supps and not msvs and not bavd and not gdvd and not thesis_drop:
        return hits, []
    # The live surface_modality verdict, for the biology-axis downgrade (C) co-condition.
    _surf = sub_results.get("surface_modality", {}).get("verdict")
    surface_verdict = _surf[0] if isinstance(_surf, (list, tuple)) and _surf else None
    # The live genomic_alteration verdict, for the GoF-driver downgrade (D) co-condition.
    _gen = sub_results.get("genomic_alteration", {}).get("verdict")
    genomic_verdict = _gen[0] if isinstance(_gen, (list, tuple)) and _gen else None

    # Build the present-verdict set for suppressor matching. Defensive against a MALFORMED
    # verdict (a bare string, a dict): only a WELL-FORMED (verdict, ...) tuple can be a
    # suppressor trigger, and a garbled verdict must not crash the gate (fail-closed discipline —
    # the malformed sub-verdict already routed to least-permissive upstream).
    def _first(v):
        return v[0] if isinstance(v, (list, tuple)) and len(v) >= 1 and isinstance(v[0], str) else None

    present = {(short, _first(r.get("verdict"))) for short, r in sub_results.items()}
    survivors: list[dict] = []
    suppressions: list[dict] = []
    for h in hits:
        key = (h["short"], h["verdict"])
        suppressed_by = None
        # (0) THESIS ROUTING (Step 2b) — runs FIRST so it takes precedence + records the thesis
        # attribution. The target's thesis makes this (axis, verdict) IRRELEVANT: an antigen_driven /
        # tme_io / neomorphic_gof / partner_conditional_sl target's pooled `non_dependent` is not a
        # trusted disqualifier. The vocab NEVER lists pan_essential_killer or a safety verdict, so this
        # can only ever drop the pooled-dependency dilution arm. `unresolved`/oncogene_addiction have no
        # entry → thesis_drop is empty → today's gate.
        if key in thesis_drop:
            suppressed_by = {"kind": "thesis_irrelevant_axis", "thesis": thesis}
        # (A) context-escape. A `when_present` trigger is EITHER a verdict-tuple form
        # ({sub_skill, verdict} — matched against the live sub-verdict set) OR a CARD-FIELD form
        # ({card_id, field, value} — matched against a composed card's summary field). The latter
        # (2026-08-21) lets a suppressor key on a signal that lives on a card under a GATELESS
        # sub-skill (verdict=None), e.g. the SL rescue after synthetic_lethal_partners consolidated
        # into combination_vulnerability. _trigger_label returns the match label or None.
        for s in ctx_supps if suppressed_by is None else ():
            sup = s.get("suppresses", {})
            if (sup.get("sub_skill"), sup.get("verdict")) != key:
                continue
            label = next(
                (lbl for w in s.get("when_present", []) if (lbl := _trigger_label(w, present, sub_results))), None
            )
            if label:
                suppressed_by = {"kind": "context_escape", "trigger": label}
                break
        # (B) modality-scoped
        if suppressed_by is None and modality:
            for m in msvs:
                sup = m.get("suppresses", {})
                if (sup.get("sub_skill"), sup.get("verdict")) != key:
                    continue
                if modality in set(m.get("when_modality_in", [])):
                    suppressed_by = {"kind": "modality_scoped", "modality": modality}
                    break
        # (B2) EXISTS-SAFE-MODALITY (safety WT-loss concern). The resolver emits the raw WT-loss concern;
        # the modality-conditional downgrade lives here. Compute the per-modality safety verdict from the
        # safety sub-skill's fired rules. Suppress the hold when a safe channel is admissible:
        #   --modality specified → THAT channel's action must be safe (a degrader run keeps the hold);
        #   enumerate-all        → ANY applicable channel safe (an allele-selective SM exists) clears it.
        # Non-GoF constrained targets (all channels hold) are NOT cleared → the hold correctly stands.
        #
        # T2c (2026-08-25): a BIOLOGICS channel (adc/bite_tce/antibody) reports action=not_applicable —
        # WT-loss is not that modality's operative safety axis (an ADC/TCE does not deplete WT protein),
        # so a WT-loss hold is irrelevant to it. But not_applicable alone must NOT clear: EVERY target
        # (incl. a purely intracellular one with no surface arm) reports not_applicable on those
        # unreachable channels, so treating it as safe unconditionally would GLOBALLY defeat the WT-loss
        # hold. Gate it on the biologics arm being VIABLE — an explicitly-declared biologics --modality,
        # or (enumerate-all) a FAVORABLE surface_modality fit. This is the amp-selective-ADC case
        # (ERBB2): no allele-selective SM escape, but a viable ADC arm to which WT-loss does not apply.
        if suppressed_by is None and h["short"] == "safety" and h["verdict"] in _SAFETY_WT_LOSS_CONCERNS:
            _sfired = (sub_results.get("safety") or {}).get("fired") or []
            _vbm = safety_verdict_by_modality(_sfired, str(contracts_repo) if contracts_repo else None)
            _surface_ok = surface_verdict in _SURFACE_FAVORABLE_VERDICTS

            _surface_foreclosed = _SURFACE_VERDICT_FORECLOSED_CHANNELS.get(surface_verdict, frozenset())

            def _channel_is_safe(ch: str, action: Optional[str]) -> bool:
                if action in _SAFETY_SAFE_ACTIONS:  # allele-selective SM escape (GoF)
                    return True
                if action == "not_applicable" and ch in _BIOLOGICS_CHANNELS:
                    # WT-loss n/a to a biologic — clears only if that arm is genuinely viable, i.e. the
                    # surface verdict does not EXPLICITLY foreclose THIS channel (e.g. bite_tce under
                    # adc_preferred_tce_unsafe) — else safe_channels over-reads as global viability.
                    if ch in _surface_foreclosed:
                        return False
                    return (modality == ch) or (modality is None and _surface_ok)
                return False

            if modality:
                _chans = [modality] if _channel_is_safe(modality, _vbm.get(modality, {}).get("action")) else []
            else:
                _chans = sorted(ch for ch, c in _vbm.items() if _channel_is_safe(ch, c.get("action")))
            if _chans:
                suppressed_by = {"kind": "exists_safe_modality", "safe_channels": _chans}
        if suppressed_by:
            suppressions.append({**h, "suppressed_by": suppressed_by, "policy_source": src})
            continue
        # (C) biology-axis-scoped DOWNGRADE (not suppress): a surface-antigen target with a FAVORABLE
        # surface fit has its dependency `non_dependent` VETO downgraded to `hold` — the veto contradicts
        # the captured surface biology, but we stop short of fully clearing it absent an explicit
        # --modality (branch B does that). The downgraded hit SURVIVES with action=hold.
        downgrade = None
        for d in bavd:
            dn = d.get("downgrades", {})
            if (dn.get("sub_skill"), dn.get("verdict")) != key:
                continue
            if biology_axis in set(d.get("when_biology_axis_in", [])) and surface_verdict in set(
                d.get("when_surface_verdict_in", [])
            ):
                downgrade = {
                    "kind": "biology_axis_downgrade",
                    "to_action": d.get("to_action", "hold"),
                    "biology_axis": biology_axis,
                    "surface_verdict": surface_verdict,
                }
                break
        # (D) GoF-driver-scoped DOWNGRADE: a confirmed GoF/activating oncogenic driver (neomorphic-
        # enzyme archetype IDH1 R132) with a pooled `non_dependent` read — whole-gene KO != mutant-
        # selective inhibition, so the non-dependence is an irrelevant criterion. Downgrade the VETO to
        # `hold` (the neomorphic/intracellular slice the surface downgrade in (C) cannot reach). Keyed on
        # the GENOMIC sub-verdict; LoF drivers + non-driver reads are excluded by the vocab list, so a
        # non-driver non_dependent (GLS) still vetoes. Only if (C) did not already downgrade this hit.
        if downgrade is None:
            for d in gdvd:
                dn = d.get("downgrades", {})
                if (dn.get("sub_skill"), dn.get("verdict")) != key:
                    continue
                if genomic_verdict in set(d.get("when_genomic_verdict_in", [])):
                    downgrade = {
                        "kind": "gof_driver_downgrade",
                        "to_action": d.get("to_action", "hold"),
                        "genomic_verdict": genomic_verdict,
                    }
                    break
        if downgrade:
            survivors.append({**h, "action": downgrade["to_action"], "_downgraded_from": h["action"]})
            suppressions.append({**h, "suppressed_by": downgrade, "policy_source": src})
        else:
            survivors.append(h)
    return survivors, suppressions


def _gate_recommendation(
    sub_results: dict,
    contracts_repo: Path | None = None,
    modality: Optional[str] = None,
    biology_axis: Optional[str] = None,
    thesis: Optional[str] = None,
) -> tuple[Optional[str], list[dict], list[dict]]:
    """Deterministically derive a forced overall_recommendation from sub-verdicts.

    Returns (forced_action | None, hits, suppressions). `hits` is the list of
    surviving {short, verdict, action, driving_rule_id} that force the action —
    for provenance. `suppressions` records any veto hit that fired but was
    suppressed (v1.2.0 context-escape / modality-scoped) — also for provenance, so
    a suppressed veto is never silent. None action means no (surviving) gate fired.
    When multiple survive, the highest-rank action wins (veto > hold). Policy comes
    from the target-contracts vocab (conservative hardcoded fallback on load failure).
    """
    gate_verdicts, policy_source = _load_gate_verdicts(contracts_repo)
    hits: list[dict] = []
    for short, r in sub_results.items():
        v = r.get("verdict")
        # An ABSENT/empty verdict is a coverage gap (the axis did not measure), NOT a kill —
        # never fail-closed on it (that would veto every target an axis was blind on). Skip.
        if not v:
            continue
        # FAIL-CLOSED: a MALFORMED verdict tuple on a veto-capable (gating) axis is NOT a
        # silent continue — a garbled sub-verdict on dependency/safety/subtype could be masking a
        # kill. Route to the axis's least-permissive action; never None.
        well_formed = isinstance(v, (list, tuple)) and len(v) >= 1 and isinstance(v[0], str)
        if not well_formed:
            if short in _GATING_AXES:
                fc = _GATING_AXIS_FAILCLOSED_ACTION[short]
                hits.append(
                    {
                        "short": short,
                        "verdict": "<malformed>",
                        "action": fc,
                        "driving_rule_id": None,
                        "policy_source": policy_source,
                        "_fail_closed": True,
                        "fail_closed_reason": "malformed_verdict",
                    }
                )
                print(
                    f"[target-profile] recommendation GATE fail-closed: malformed verdict "
                    f"{v!r} on gating axis '{short}' → forced least-permissive '{fc}'.",
                    file=sys.stderr,
                )
            continue
        verdict_str, driving_rule_id = v[0], (v[1] if len(v) > 1 else None)
        action = gate_verdicts.get((short, verdict_str))
        if action:
            hits.append(
                {
                    "short": short,
                    "verdict": verdict_str,
                    "action": action,
                    "driving_rule_id": driving_rule_id,
                    "policy_source": policy_source,
                }
            )
            continue
        # No gate action matched. FAIL-CLOSED: on a gating axis, an UNRECOGNIZED verdict
        # token (renamed kill, unknown enum) is NOT a silent permissive pass — if the token is not
        # in the axis's complete recognized vocabulary it may be a renamed veto, so route to the
        # axis's least-permissive action. Recognized-but-non-gating verdicts (positives, neutrals,
        # insufficient) fall through exactly as before (no forced action).
        if short in _GATING_AXES and verdict_str not in _RECOGNIZED_GATING_VERDICTS.get(short, frozenset()):
            fc = _GATING_AXIS_FAILCLOSED_ACTION[short]
            hits.append(
                {
                    "short": short,
                    "verdict": verdict_str,
                    "action": fc,
                    "driving_rule_id": driving_rule_id,
                    "policy_source": policy_source,
                    "_fail_closed": True,
                    "fail_closed_reason": "unrecognized_verdict",
                }
            )
            print(
                f"[target-profile] recommendation GATE fail-closed: unrecognized verdict "
                f"'{verdict_str}' on veto-capable axis '{short}' (not in recognized set) → "
                f"forced least-permissive '{fc}' (never a silent pass).",
                file=sys.stderr,
            )
    # v1.2.0: apply veto suppression (context-escape + modality-scoped) before
    # resolving the forced action. A suppressed veto does not force — but is recorded.
    hits, suppressions = _suppressed_gate_hits(
        hits, sub_results, modality, contracts_repo, biology_axis=biology_axis, thesis=thesis
    )
    if not hits:
        return None, [], suppressions
    # .get(a, 0): an action outside {veto, hold} (a vocab typo or a new action a product owner adds —
    # the module comment explicitly invites editing this vocab "without a code change") must NOT crash
    # the run with a KeyError, which would defeat the "gate never crashes the run" contract. Unknown
    # actions rank LOWEST (0) so a real veto/hold always wins; the target-contracts CI test
    # (test_every_gate_well_formed) is the primary guard — this is defense-in-depth.
    forced = max((h["action"] for h in hits), key=lambda a: _GATE_ACTION_RANK.get(a, 0))
    return forced, hits, suppressions


# The LLM recommendations that are NEGATIVE calls — the ones a fired rule must back.
_ABSTENTION_NEGATIVE_RECS = frozenset({"veto", "hold"})


def abstention_lower_bound_clamp(llm_recommendation: Optional[str]) -> tuple[Optional[str], Optional[dict]]:
    """The missing LOWER half of the recommendation clamp (2026-09-11). It is called ONLY on gate
    ABSTENTION — the else-branch of `_gate_recommendation` firing — i.e. when NO veto/hold rule fired.

    The gate clamp is one-DIRECTIONAL (never forces `nominate`) but was one-SIDED: on abstention it
    left `overall_recommendation` = the LLM's value unbounded below, so the LLM could author a
    `veto`/`hold` with no rule behind it and nothing in the audit spine to attribute it to (measured:
    41 of 120 run artifacts published a recommendation the gate did not produce; 5 LLM-authored vetoes
    on approved drugs). This restores the symmetry: just as a `nominate` requires a positive tier, a
    NEGATIVE requires a fired veto/hold rule — absent one, the honest deterministic floor is
    `insufficient_evidence` (the framework's own grammar for "we could not decide"). The LLM narrative
    is untouched and still explains the concern; only the composed recommendation VALUE is clamped.

    Returns (clamped_value_or_None, record_or_None). A None value means NO clamp — the caller leaves
    the LLM value (a `nominate` or `insufficient_evidence` on abstention is not a negative and stands;
    `nominate` remains bounded above by the existing kill gate). Pure + deterministic — unit-tested."""
    if llm_recommendation in _ABSTENTION_NEGATIVE_RECS:
        return "insufficient_evidence", {
            "applied": True,
            "llm_recommendation": llm_recommendation,
            "clamped_to": "insufficient_evidence",
            "reason": "gate abstained (no veto/hold rule fired); an LLM-authored negative is unbacked by the audit spine",
        }
    return None, None


# --- Thesis DECIDING axis → the first deterministic `nominate` (Step 3, 2026-09-11) ----------------
#
# WHY THIS EXISTS. `_gate_recommendation` is one-directional-UP: `action_precedence` is
# {veto: 2, hold: 1} and the forced action is a max() over those, so the deterministic gate could only
# ever VETO or HOLD. `nominate` was an LLM enum value only — every published nomination was
# LLM-authored, and the eval panel's `must_not_nominate` arm was VACUOUS (green by construction,
# because no deterministic path to `nominate` existed to be wrong). Meanwhile Step 2b removed the
# false pooled-`non_dependent` veto on surface antigens but did not make surface a POSITIVE decider,
# so FOLR1/DLL3/MSLN landed at `insufficient_evidence` and the abstention lower-bound clamp floored
# them there: 0 of 14 surface antigens had ever been adjudicated on surface biology.
#
# WHY IT IS A SEPARATE STAGE AND NOT A NEW `action_precedence` RANK. `nominate` is minted HERE, in a
# stage the caller reaches only in the else-branch of the kill gate — structurally unreachable while
# ANY veto/hold hit survives. That is the identical reachability argument the existing positive tier
# already rests on, and it means F1 safety is a property of the CONTROL FLOW rather than of a
# precedence number. Adding `nominate` to `action_precedence` would instead demote "kills resolve
# first" to a policy ordering in an editable vocab, and would perturb every fail-closed path
# (`max()` over an action set that now contains a positive).
#
# FOUR FAIL-CLOSED PATHS. Routing must never invent a GO:
#   1. abstention-only  — `hits` non-empty (incl. any `_fail_closed` clamp) → refuse outright.
#   2. measured-only    — every conjunct needs a MEASURED value present in `sub_results`; an absent
#                         card, a null field, or an abstention token is UNSATISFIED, never neutral.
#   3. registered-only  — no `thesis_deciding_axes` entry for this thesis → today's gate verbatim
#                         (so `unresolved` and the oncogene_addiction/KRAS golden are untouched).
#   4. inverted loader  — a missing or malformed vocab yields an EMPTY decider set, never a
#                         permissive one (mirrors _load_positive_signals / _load_veto_suppressors).


def _load_thesis_deciding_axes(contracts_repo: Path | None = None) -> tuple[list[dict], str]:
    """Load the Step-3 `thesis_deciding_axes` blocks → (blocks, source).

    INVERTED FALLBACK (the suppressor/positive convention, and the one that matters most here):
    ANY failure — unreadable file, malformed YAML, absent block — returns an EMPTY list, i.e. NO
    deterministic nomination is possible. For a kill loader "fail closed" means conservative-and-
    complete; for a loader that can mint a GO it means EMPTY. A broken policy file must never
    nominate anything."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        blocks = yaml.safe_load(path.read_text()).get("thesis_deciding_axes", []) or []
        return [b for b in blocks if isinstance(b, dict) and b.get("thesis")], "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no deterministic nomination)
        print(
            f"[target-profile] WARN: could not load thesis_deciding_axes "
            f"({type(e).__name__}: {e}); deterministic nomination DISABLED.",
            file=sys.stderr,
        )
        return [], "fallback"


def thesis_nomination(
    sub_results: dict,
    thesis: Optional[str],
    hits: Optional[list[dict]] = None,
    contracts_repo: Path | None = None,
) -> tuple[Optional[str], Optional[dict]]:
    """The deterministic POSITIVE decider. Returns (action | None, record | None).

    Called ONLY on gate abstention (the caller's else-branch), AFTER
    `abstention_lower_bound_clamp` — so the order of authority is: kill gate > lower-bound clamp >
    this stage. `action` is `"nominate"` or None; a None action with a non-None record means the
    thesis WAS registered and the stage RAN but the conjunction was not satisfied — that negative is
    recorded too, so "the framework declined to nominate, and here is the conjunct that failed" is in
    the audit spine rather than being an invisible default.

    A block fires only when ALL of the following hold, every one of them on a MEASURED value:
      * the thesis's DECIDING axis carries one of its `favorable_verdicts`;
      * every `requires` conjunct (an INDEPENDENT axis) carries a verdict in its `verdict_in`;
      * every `requires_measured_card_field` conjunct reads a value in its `value_in` — this is the
        ANTI-BLIND bound: the thesis's own ground-truth deciding sub-question must have been
        measured, not estimated (all 7 surface reference targets are `blind` on E2 antigen density,
        so without it the stage would nominate on an unmeasured decider);
      * no live sub-verdict is an un-reconciled `positive_contradictions` entry (a MEASURED opposing
        read anywhere blocks the nomination, using the same reconcilers `_positive_tier` uses -- but
        contradictions ALONE, a strict SUBSET of the union that blocks `strong` there; see GUARD 4).
    """
    if hits:  # GUARD 1 — abstention-only. Any surviving veto/hold (or fail-closed clamp) → refuse.
        return None, None
    if not thesis:
        return None, None
    blocks, src = _load_thesis_deciding_axes(contracts_repo)
    blk = next((b for b in blocks if b.get("thesis") == thesis), None)
    if blk is None:  # GUARD 3 — unregistered thesis → today's gate, byte-for-byte.
        return None, None

    live = {short: _verdict_token(r.get("verdict")) for short, r in sub_results.items() if isinstance(r, dict)}
    unsatisfied: list[str] = []

    # GUARD 4 — a MEASURED opposing verdict anywhere blocks a nomination outright. Same
    # `positive_contradictions` load and the same reconcilers `_positive_tier` uses -- but deliberately
    # NOT the same set the tier blocks `strong` on. `_split_contradictions` subtracts only on the
    # contradiction side and returns the uncorroborated set WHOLE, so the tier's strong-block is the
    # UNION (9 keys on vocab-1.21.0) while this conjunct reads contradictions ALONE (7). The 2-key gap
    # is exactly (dependency, discordant) and (selectivity, discordant_across_comparators), the rows
    # 1.20.0 relabelled. ON THOSE TWO KEYS THE SURFACES AGREE: `_gate_scorecard._status` tests
    # `uncorroborated` FIRST and returns `coverage_gap`, so an axis whose verdict says it resolved
    # NOTHING blocks `strong` without ever being labelled opposing evidence. The 1.20.0 relabel
    # therefore introduced no decider/scorecard divergence.
    #
    # ⚠️ THE GENERAL INVARIANT WAS FALSE WHEN STEP 3 LANDED, AND IS NOW TRUE BY CONSTRUCTION. The
    # claim "the decider can never nominate what the gate scorecard reads as `opposing`" was REFUTED
    # by `dependency: non_dependent` under `antigen_driven` — the decider NOMINATED while the
    # scorecard said `opposing`. The cause was not 1.20.0; it is v1.17.0/Step-2b
    # `thesis_axis_relevance`, which drops the `non_dependent` veto for that thesis by design (the
    # 0/14-surface fix above). The gate applied that thesis scoping and `_gate_scorecard` did not —
    # it took `modality` but no `thesis`, so it classified `non_dependent` via `kill_map` and read
    # `opposing`. Per the 0/14 rationale a surface antigen measuring `non_dependent` is the TYPICAL
    # case, not an edge.
    #   CLOSED 2026-09-15 by threading `thesis` into `_gate_scorecard` (see its docstring): the
    #   scorecard now performs the SAME `_load_thesis_axis_relevance(...).get(thesis, set())` lookup
    #   this function's `_suppressed_gate_hits` performs, and labels a thesis-dropped row `neutral`
    #   instead of `opposing`. The invariant now holds for a caller that passes `thesis`, and
    #   `run.py` does. It STILL does not hold for `thesis=None`, and that is deliberate: the default
    #   drops nothing, so every caller that never had a thesis keeps its exact previous output.
    #   MEASURED REACH — and it is TWO different numbers, because the mislabel contradicts TWO
    #   different surfaces and each has its own denominator. Canonical thesis vocabulary = 5
    #   (`target_thesis.yaml`: antigen_driven, tme_io, neomorphic_gof, partner_conditional_sl,
    #   oncogene_addiction).
    #     · `thesis_axis_relevance` carries 4 of those 5 and ALL FOUR drop
    #       (`dependency`, `non_dependent`) — `oncogene_addiction` is simply ABSENT from the map, so
    #       it keeps the veto and `forced` stays `veto`. Under all four, `hard_gates[].status` reads
    #       `suppressed` while the unthreaded scorecard read `opposing`: an artifact contradicting
    #       ITSELF, reach 4/5.
    #     · `thesis_deciding_axes` carries 1 of the 5 (`antigen_driven` only), so a thesis that is
    #       not registered there hits GUARD 3 above and the decider returns `None` — it cannot
    #       nominate, and there is nothing for a scorecard label to contradict. THE DECIDER-side
    #       divergence this comment is about therefore had reach 1/5, not 4/5.
    #   Stated separately because collapsing them is a real error and I made it: the first draft of
    #   this paragraph claimed the original note "under-stated the divergence 4×", which silently
    #   promoted the artifact-self-contradiction count into the decider claim. Both numbers are
    #   defects worth closing; they are not the same defect. WHEN A COUNT LOOKS LIKE IT GREW, CHECK
    #   WHETHER THE DENOMINATOR MOVED WITH IT — a defect quantified on the example that surfaced it
    #   looks like an edge case and gets deferred, but a count borrowed from a neighbouring surface
    #   over-states it in the other direction, and both mis-price the fix.
    #   WHICH SURFACE CARRIES IT, measured rather than assumed -- and an earlier draft of this comment
    #   said "rendered reports", which names the one consumer that provably does NOT read it:
    #   `report_render/DATA_CONTRACT.md` records `.target_call.gate_scorecard` as "carried, not
    #   destructured", so the text backend never prints a per-row status. The surfaces that DO read
    #   `gate_scorecard[].status` are `nomination.json` (emitted at run.py's `_gate_scorecard` call) and
    #   the projection `build_polarity_surface_projection.py` labels "dashboard polarity". Being EMITTED
    #   into an artifact and being RENDERED to a human are different reach claims; ask what the
    #   consumer reads.
    #   ALREADY PRESENT IN A REAL CORPUS, not merely reachable: the frozen 629-row projection
    #   (`tests/fixtures/polarity_surface_projection.json`, 37 pairs run 2026-09-08/09) carries
    #   (`non_dependent`, `opposing`) on 24 of its 37 dependency rows -- the DOMINANT state, not a
    #   constructed one. Those runs predate step 3, so the decider vetoed them at freeze time; step 3
    #   is what stops the veto and leaves the scorecard's `opposing` standing beside a nomination.
    #   THE SAME FIXTURE CROSS-VALIDATES THE PARAGRAPH ABOVE: it shows (`discordant`, `opposing`) 6x
    #   where this file now measures `coverage_gap`, because it is a PRE-1.20.0 vintage. A fixture
    #   disagreeing with a live read is usually stale rather than wrong, but only its VINTAGE can say
    #   which, and here the delta is exactly the relabel this comment describes.
    #   AND THAT FIXTURE IS NOW STALE FOR A SECOND, INDEPENDENT REASON — worth stating because the
    #   two look identical from inside the file. It is pre-1.20.0 (the relabel, paragraph above) AND
    #   pre-2026-09-15 (this fix). Its 24 (`non_dependent`, `opposing`) rows are what a run WITHOUT a
    #   threaded thesis produced; a fresh run of the same pairs would read `neutral` wherever the
    #   target's thesis is one of the four. It is deliberately NOT regenerated here: the fixture's job
    #   is to record what the surfaces DID emit, and re-freezing it would erase the only durable
    #   evidence that the divergence was real and populous rather than constructed.
    # Pinned by `test_decider_and_scorecard_agree_where_the_thesis_is_threaded`, which replaced
    # `..._except_where_thesis_scoping_is_invisible_to_the_scorecard`. That earlier pin asserted
    # `"thesis" not in signature(_gate_scorecard).parameters` — i.e. it pinned the DEFECT open, on
    # purpose, so that closing it could not be done silently. This diff falsifies it by design, which
    # is the pin working rather than the pin failing: a guard that reds when the thing it describes
    # gets fixed is the only kind that cannot be quietly out-lived.
    #
    # MINUS the thesis's declared `irrelevant_contradiction_axes`. This is not a loophole: it can only
    # stop a CONTRADICTION on a named axis from blocking, never make a kill suppressible (kills resolve
    # in `_gate_recommendation`, before this stage is reachable). It exists because the unrestricted
    # form reproduced the very defect this remediation removes — a grounded FOLR1/OV run declined the
    # nomination of an APPROVED ADC target on `tractability_sm: discordant`, i.e. a SMALL-MOLECULE
    # chemistry disagreement read as an AND-conjunct of an antibody thesis.
    _pos_map, contra_set, _cfg, _s = _load_positive_signals(contracts_repo)
    contra_set = contra_set - _reconciled_contradiction_keys(sub_results, contracts_repo)
    _irrelevant_axes = {
        e["sub_skill"]
        for e in (blk.get("irrelevant_contradiction_axes") or [])
        if isinstance(e, dict) and e.get("sub_skill")
    }
    contra_set = {(s, v) for (s, v) in contra_set if s not in _irrelevant_axes}
    opposing = sorted(f"{k}:{v}" for k, v in live.items() if v and (k, v) in contra_set)
    if opposing:
        unsatisfied.append(f"opposing_measured_verdict({','.join(opposing)})")

    # The deciding axis itself.
    dec = blk.get("deciding") or {}
    dec_short, favorable = dec.get("sub_skill"), set(dec.get("favorable_verdicts") or [])
    dec_verdict = live.get(dec_short)
    if not favorable or dec_verdict not in favorable:
        unsatisfied.append(f"deciding({dec_short}={dec_verdict})")

    # Corroboration on independent axes.
    corroborating: list[dict] = []
    for req in blk.get("requires") or []:
        short, allowed = req.get("sub_skill"), set(req.get("verdict_in") or [])
        got = live.get(short)
        if not allowed or got not in allowed:
            unsatisfied.append(f"requires({short}={got})")
        else:
            corroborating.append({"short": short, "verdict": got})

    # The anti-blind MEASURED-card-field conjuncts.
    measured: list[dict] = []
    for m in blk.get("requires_measured_card_field") or []:
        cid, field = m.get("card_id"), m.get("field")
        got = _card_field_value(sub_results, cid, field)
        allowed = m.get("value_in") or []
        if got is None or got not in allowed:
            unsatisfied.append(f"unmeasured({cid}.{field}={got})")
        else:
            measured.append({"card_id": cid, "field": field, "value": got})
    if not (blk.get("requires") and blk.get("requires_measured_card_field")):
        # A block with no corroboration or no measured conjunct would make the decider SUFFICIENT on
        # its own. The contracts tests forbid authoring one; refuse here too rather than trust them.
        unsatisfied.append("malformed_block(missing requires / requires_measured_card_field)")

    record = {
        "stage": "thesis_decider",
        "thesis": thesis,
        "policy_source": src,
        "deciding": {"short": dec_short, "verdict": dec_verdict},
        "corroborating": corroborating,
        "measured_conjuncts": measured,
    }
    if unsatisfied:
        return None, {**record, "applied": False, "unsatisfied": unsatisfied}
    return "nominate", {
        **record,
        "applied": True,
        "action": "nominate",
        "reason": (
            f"thesis '{thesis}' deciding axis {dec_short}={dec_verdict} is favorable and MEASURED, "
            f"corroborated on {len(corroborating)} independent axis/axes with "
            f"{len(measured)} measured card conjunct(s), on gate abstention (no veto/hold fired)"
        ),
        "rationale": (blk.get("rationale") or "").strip() or None,
    }


def _hard_gates_status(
    sub_results: dict,
    hits: list[dict],
    suppressions: list[dict],
    contracts_repo: Path | None = None,
) -> list[dict]:
    """Build the COMPLETE-declared-set hard-gate status block (gate-complete
    ceiling). Iterates EVERY kill-capable verdict declared in the target-contracts
    kill_capable_verdicts registry (hardcoded complete fallback on load failure) and reports,
    per (sub_skill, verdict), its status THIS run — so the full hard-gate set is legible and a
    kill is never silently absent from the audit. Purely additive: reads the already-resolved
    gate state, forces nothing.

    Per-entry status:
      fired      — a `gated` verdict matched the live sub-verdict and forced the recommendation
                   (includes fail-closed clamps).
      suppressed — a `gated` verdict matched but a veto suppressor lifted it (recorded).
      excluded   — an `excluded_modality_scoped` verdict matched live (a modality-local
                   foreclosure that deliberately did NOT blanket-veto).
      opposing   — a `contradiction` OR `uncorroborated` verdict matched live (a non-veto
                   kill-capable verdict; blocks `strong`, not a veto). This token is a LIFECYCLE
                   event, not a polarity claim, and it deliberately does NOT fork with the
                   disposition — see the `uncorroborated` note in the branch chain below.
      reconciled — a `contradiction` verdict matched live but a cross-axis reconciler dropped it
                   (a co-present verdict proved it is measured on the wrong basis). NON-opposing —
                   keeps this view consistent with the scorecard + positive-tier, which also
                   subtract the reconciled set, so the deterministic call and the LLM's hard-gate
                   view move together (was: still showed `opposing` here → an inconsistency).
      blind      — the axis produced NO verdict this run (coverage gap — could not evaluate).
      latent     — the axis WAS evaluated but did not emit this kill verdict (declared, dormant).
    """
    registry, source = _load_kill_capable_verdicts(contracts_repo)
    fired_pairs = {(h["short"], h["verdict"]) for h in hits}
    suppressed_pairs = {(s["short"], s["verdict"]) for s in suppressions}
    reconciled_pairs = _reconciled_contradiction_keys(sub_results, contracts_repo)

    def _live_verdict(short: str):
        r = sub_results.get(short)
        if not r:
            return None, True  # axis absent → blind
        v = r.get("verdict")
        if not (isinstance(v, (list, tuple)) and len(v) >= 1 and isinstance(v[0], str)):
            return None, True  # absent/malformed → blind (the fail-closed hit carries the force)
        return v[0], False

    rows: list[dict] = []
    for (short, verdict), disposition in sorted(registry.items()):
        live, blind = _live_verdict(short)
        matched = live == verdict
        if (short, verdict) in fired_pairs:
            status = "fired"
        elif (short, verdict) in suppressed_pairs:
            status = "suppressed"
        elif blind and short in _SCOPE_OPTIN_GATING_AXES:
            # One-directional, opt-in-by-scope gate produced no verdict. NOT a coverage gap
            # (its silence is the OK state) — so never `blind` (which the integrator ceiling
            # fail-closes on). `excluded` = scope-foreclosed (axis absent → --subtypes not
            # requested this run); `latent` = requested but no negative stratum fired. Both are
            # no-veto in the ceiling, mirroring surface_modality's excluded_modality_scoped.
            status = "excluded" if short not in sub_results else "latent"
        elif blind:
            status = "blind"
        elif matched and disposition == "excluded_modality_scoped":
            status = "excluded"
        elif matched and disposition in ("contradiction", "uncorroborated"):
            # `uncorroborated` (vocab v1.20.0) shares this branch ON PURPOSE. The DISPOSITION moves —
            # it is vocab-owned and mirrored here (`policy_source: vocab`) — but the LIFECYCLE token
            # holds at `opposing`, and the two must not be conflated:
            #
            #   * `status` is the ONLY field of this block the downstream fail-closed ceiling switches
            #     on (cross-evidence-hypothesis `hypothesis_core._gate_ceiling`), and that switch
            #     handles exactly {fired, blind, opposing, excluded}. Every other token — `latent`
            #     today, a hypothetical `uncorroborated` tomorrow — falls through it with NO signal.
            #     So dropping out of this branch, or minting a new token here, would silently remove
            #     the `advanceable_with_caveat` clamp from every uncorroborated target. The
            #     relabelling would fail OPEN one surface further out than the one it fixes.
            #   * `opposing` here is a lifecycle event ("a non-veto kill-capable verdict matched
            #     live"), NOT the polarity claim the scorecard makes. The scorecard is the surface
            #     that carries polarity, and there this verdict correctly reads `coverage_gap`.
            #
            # Splitting the lifecycle token therefore lands WITH the integrator change, not before
            # it — see docs/UNIFIED_OUTPUT_CONTRACT.md § "Typed surface authority", ordered
            # follow-up. Same LABEL-NOT-DROP discipline as the tier: change the label only on the
            # surface whose readers you can see.
            status = "reconciled" if (short, verdict) in reconciled_pairs else "opposing"
        elif matched and disposition == "gated":
            status = "fired"  # gated + matched but not in hits (defensive; normally in hits)
        else:
            status = "latent"
        rows.append(
            {
                "short": short,
                "verdict": verdict,
                "disposition": disposition,
                "status": status,
                "live_verdict": live,
                "policy_source": source,
            }
        )
    return rows


# --- Deciding-axis router -----
#
# Turns a bare `insufficient_evidence` into a ROUTING statement: which gate is load-bearing
# for THIS run, and whether the framework can evidence it. HONESTY GUARDRAIL: this does NOT
# predict which gate WILL decide a target prospectively ("a mis-route
# fails more confidently than a portrait"). It only REPORTS, from the run's actual sub-verdicts:
#   - gate FIRED (veto/hold)  → the firing gate IS the deciding axis (known, not predicted);
#                               framework_can_evidence = captured (we evidenced it → it fired).
#   - abstaining (no gate)    → list the NECESSITY gates we could not evidence + their standing
#                               ("we can't decide because gates X,Y are the ones we're blind on").
#   - positive (no gate)      → the strongest positive dimension is the load-bearing axis.
# The gate_coverage.yaml baseline is the STATIC standing; the router DOWNGRADES it per-run to
# `blind`/`data_blocked` when a gate's own cards came back missing, and never upgrades past it.
_COVERAGE_RANK = {"captured": 3, "partial": 2, "license_blocked": 1, "blind": 0, "out_of_scope": 0}


# The v2 (2.0.0) gate_coverage splits the v1 flat `gates:` list into three lists by grain/axis:
#   biology_gates  — the necessity gates (A..E incl. "Altered"); scorecard rows.
#   modality_fit   — per-lens sufficiency assessments (named, letterless); scorecard rows.
#   biomarker_facets — relational feature×outcome sub-skills. Two GRAINS live here:
#       grain: sub_skill  → a real sub-verdict slot the composer emits (synthetic_lethal_partners,
#                           subtype_fit) → IS a scorecard row (as in v1).
#       grain: card       → a card-level facet (mutation_stratified, crispr_rnai_concordance, …)
#                           that surfaces INSIDE its outcome gate's section, NEVER its own row.
# The loader below reads EITHER shape and returns the same {short: entry} map the router+scorecard
# consumed under v1 — containing exactly the sub-skill-grain entries (biology + modality_fit + the
# sub_skill-grain facets), so no phantom card-grain rows appear. Missing `grain:` defaults to
# sub_skill (fail-open: a mis-tagged facet becomes a visible row rather than silently vanishing).
_V2_GATE_LISTS = ("biology_gates", "modality_fit", "biomarker_facets")


def _flatten_gate_coverage(data: dict) -> dict:
    """Return {short: entry} for the scorecard/router, accepting v1 (`gates:`) or v2 (three-list).
    v2 card-grain biomarker_facets are EXCLUDED (they are in-section facets, not scorecard rows)."""
    if "gates" in data:  # v1 / v1.1.0 flat shape — every entry is a row.
        return {g["short"]: g for g in data["gates"]}
    by_short: dict = {}  # v2 three-list shape.
    for key in _V2_GATE_LISTS:
        for g in data.get(key, []):
            if key == "biomarker_facets" and g.get("grain", "sub_skill") == "card":
                continue  # card-grain facet → rendered in-section, not a row
            by_short[g["short"]] = g
    return by_short


def _load_gate_coverage(contracts_repo: Path | None = None) -> tuple[dict, str]:
    """Load the per-short gate_coverage map from the target-contracts vocab. Returns
    ({short: {gate, gate_name, band, axis, framework_can_evidence, ...}}, source). Accepts BOTH the
    v1 flat `gates:` list and the v2 three-list (biology_gates/modality_fit/biomarker_facets) shape
    — see _flatten_gate_coverage. EMPTY-on-failure (source='none'): the router then degrades to a
    bare abstention note rather than fabricating a coverage claim — a missing map must never invent
    a `captured`."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "gate_coverage.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        by_short = _flatten_gate_coverage(data)
        if not by_short:
            raise ValueError("no gate entries (neither v1 `gates:` nor v2 three-list)")
        return by_short, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → empty (never a fabricated coverage)
        print(
            f"[target-profile] WARN: could not load gate_coverage vocab "
            f"({type(e).__name__}: {e}); deciding-axis router degrades to a bare note.",
            file=sys.stderr,
        )
        return {}, "none"


def _load_target_thesis(contracts_repo: Path | None = None) -> Optional[dict]:
    """Load the governed thesis-routing vocab (target_thesis.yaml). Returns the spec dict, or None if
    absent/malformed → derive_thesis then yields `unresolved` (today's gate). Fail-soft: a missing vocab
    must never fabricate a thesis."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "target_thesis.yaml"
    try:
        spec = yaml.safe_load(path.read_text())
        if not spec or "theses" not in spec or "derivation" not in spec:
            raise ValueError("missing theses/derivation")
        return spec
    except Exception:  # noqa: BLE001 — absent/malformed → None (derive_thesis falls to unresolved)
        return None


def _refinement_matches(when_verdicts: dict, sub_results: dict) -> bool:
    """True iff EVERY (sub_skill → allowed-verdict-list) in `when_verdicts` holds against the run's
    sub-verdicts (AND). A missing/None sub-verdict never matches — a refinement needs a MEASURED signal."""
    for short, allowed in (when_verdicts or {}).items():
        v = (sub_results.get(short) or {}).get("verdict")
        vs = v[0] if isinstance(v, (list, tuple)) and v and isinstance(v[0], str) else None
        if vs not in set(allowed):
            return False
    return True


def derive_thesis(
    archetype_companion: Optional[dict],
    biology_axis: Optional[str],
    sub_results: Optional[dict] = None,
    contracts_repo: Path | None = None,
) -> dict:
    """Derive the target's THESIS from archetype_core's verdict-inert soft_membership under the governed
    hard-margin rule (Step 2a COARSE typing), then apply the Step-2b axis-signal REFINEMENT to promote a
    coarse thesis to a finer one (e.g. oncogene_addiction → neomorphic_gof on a confirmed GoF driver whose
    pooled KO is non_dependent). Falls back to the curated biology_axis lookup when the mixture is
    ambiguous. `unresolved` reproduces today's gate by construction.

    Returns {thesis, basis, ...evidence}. basis ∈ {archetype_mixture, biology_axis_fallback, unresolved,
    no_vocab, step_2b_refinement}. Governance: archetype_core mints nothing; THIS deterministic function
    + the PR-reviewable target_thesis.yaml do the typing. `sub_results` is required only for the finer
    refinement; without it the coarse thesis stands (backward-compatible)."""
    spec = _load_target_thesis(contracts_repo)
    if spec is None:
        return {"thesis": "unresolved", "basis": "no_vocab"}
    deriv = spec["derivation"]
    cross = deriv.get("archetype_label_to_thesis") or {}
    hm = deriv.get("hard_margin") or {}
    dom_min = hm.get("dominant_weight_min", 0.5)
    sep_min = hm.get("separation_min", 0.2)

    # ── COARSE typing (Step 2a) ──
    coarse: dict = {"thesis": "unresolved", "basis": "unresolved", "biology_axis": biology_axis}
    sm = (archetype_companion or {}).get("soft_membership") or {}
    if sm:
        ranked = sorted(sm.items(), key=lambda kv: (-kv[1], kv[0]))  # weight desc, label asc (deterministic)
        dom_label, dom_w = ranked[0]
        second_w = ranked[1][1] if len(ranked) > 1 else 0.0
        if dom_w >= dom_min and (dom_w - second_w) >= sep_min and cross.get(dom_label, "unresolved") != "unresolved":
            coarse = {
                "thesis": cross[dom_label],
                "basis": "archetype_mixture",
                "dominant_label": dom_label,
                "dominant_weight": round(dom_w, 3),
                "margin": round(dom_w - second_w, 3),
            }
    if coarse["basis"] in ("unresolved",):  # mixture ambiguous / no membership → curated biology_axis fallback
        fb = spec.get("biology_axis_fallback") or {}
        th = fb.get(biology_axis, "unresolved") if biology_axis else "unresolved"
        coarse = {
            "thesis": th,
            "basis": "biology_axis_fallback" if th != "unresolved" else "unresolved",
            "biology_axis": biology_axis,
        }

    # ── Step 2b REFINEMENT: promote to a finer thesis from AXIS SIGNALS (needs sub_results) ──
    if sub_results:
        for rule in spec.get("step_2b_refinement", []) or []:
            if coarse["thesis"] not in set(rule.get("from") or []):
                continue
            if _refinement_matches(rule.get("when_verdicts") or {}, sub_results):
                return {
                    "thesis": rule["to"],
                    "basis": "step_2b_refinement",
                    "refined_from": coarse["thesis"],
                    "when_verdicts": rule.get("when_verdicts"),
                }
    return coarse


def _sub_result_has_signal(r: dict) -> bool:
    """A sub-result 'evidenced its gate' iff it produced a non-sentinel verdict OR fired any
    rule on a card that returned real (non-missing) data. Absence of both = we could not look."""
    v = r.get("verdict")
    verdict_str = v[0] if v else None
    if verdict_str and verdict_str not in ("insufficient", "data_unavailable", None):
        return True
    return bool(r.get("fired"))


def _run_coverage_for_short(short: str, r: dict, baseline: dict) -> str:
    """Per-run framework_can_evidence for a sub-result: start from the static baseline and
    DOWNGRADE (never upgrade) when this gate's cards actually came back missing this run.
    All cards missing → the framework could not look here → `blind` for this run."""
    base = baseline.get(short, {}).get("framework_can_evidence", "blind")
    cards = r.get("cards") or []
    if cards and all(c.get("_missing") for c in cards):
        return "blind"  # every card for this gate was unavailable this run
    return base


# --- Positive tier (deterministic confidence FLOOR; F1-safe) ----------------
#
# Graded positives (dependency/selectivity/small-molecule tractability) raise an
# AUDITABLE confidence tier (strong/moderate) instead of being LLM-advisory only.
# STRICTLY F1-SAFE: this is computed ONLY when NO kill fired (the else-branch of
# the gate clamp in main), so a positive can never mask a kill; and it writes ONLY
# to `confidence` as a FLOOR, never to `overall_recommendation` — it cannot force
# `nominate`. Policy in target-contracts/vocabularies/nomination_verdict_gate.yaml.
#
# INVERTED FALLBACK vs the kill gate: the kill loader falls back conservative-and-
# complete (missing vocab still fires vetoes). The positive loader falls back to
# EMPTY (missing/malformed vocab → no positive tier, LLM confidence stands) — it must
# NEVER mint a spurious `strong`.
_CONFIDENCE_RANK = {"insufficient": 0, "low": 1, "medium": 2, "high": 3}
_TIER_TO_CONFIDENCE = {"strong": "high", "moderate": "medium"}


def _load_positive_signals(
    contracts_repo: Path | None = None, modality: str | None = None
) -> tuple[dict, set, dict, str]:
    """Load the positive-tier policy. Returns
    (positive_map: {(short,verdict): weight}, contradiction_set: {(short,verdict)},
     config: dict, source). EMPTY-on-failure (never permissive).

    MODALITY-SCOPED POSITIVES: when `modality` is an explicit biologics modality,
    favorable surface_modality verdicts listed under `positive_signals_modality_scoped`
    (whose `when_modality_in` contains `modality`) are ADDED to the positive map —
    symmetric to `modality_scoped_veto_suppression`. In default mode (modality=None)
    these do NOT apply (surface stays excluded), so pos_map is identical to before."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        pos = {(p["sub_skill"], p["verdict"]): p["weight"] for p in data["positive_signals"]}
        contra = {(c["sub_skill"], c["verdict"]) for c in data["positive_contradictions"]}
        cfg = data["positive_tier_config"]
        if not pos:
            raise ValueError("empty positive_signals")
        # Modality-scoped positives (backward-compatible: missing key → no-op).
        if modality is not None:
            for entry in data.get("positive_signals_modality_scoped", []):
                if modality in entry.get("when_modality_in", []):
                    pos[(entry["sub_skill"], entry["verdict"])] = entry["weight"]
        return pos, contra, cfg, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no positive tier)
        print(
            f"[target-profile] WARN: could not load positive_signals vocab "
            f"({type(e).__name__}: {e}); positive tier DISABLED (LLM confidence stands).",
            file=sys.stderr,
        )
        return {}, set(), {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True}, "fallback"


# The `positive_uncorroborated` block's FALLBACK mirror (vocab v1.20.0). Verdicts whose content is
# that the axis's own arms disagree WITH EACH OTHER, so the axis resolved nothing.
#
# FAIL-CLOSED, and note which direction that is here. These pairs must stay inside the `strong`-block
# on EVERY contracts checkout: dropping them RELAXES the gate, which is fail-OPEN (measured over 56
# target×indication pairs: 0 carrying pairs are at `strong` today, but 2 — KRAS/COADREAD selectivity
# and CEACAM5/NSCLC — REACH `strong` if the block is lost). So an absent/unreadable
# `positive_uncorroborated` key falls back to this mirror rather than to the empty set.
#
# The consequence worth stating plainly: `contradictions ∪ uncorroborated` is IDENTICAL on a
# pre-v1.20.0 checkout (where these rows are still filed under `positive_contradictions`) and on a
# v1.20.0+ one (where they are filed here). The tier is therefore byte-stable across the relabelling
# BY CONSTRUCTION, on either checkout. Only the LABEL moves — see `_gate_scorecard`.
_FALLBACK_POSITIVE_UNCORROBORATED: set[tuple[str, str]] = {
    ("selectivity", "discordant_across_comparators"),
    ("dependency", "discordant"),
}


def _load_positive_uncorroborated(contracts_repo: Path | None = None) -> tuple[set[tuple[str, str]], str]:
    """Load the `positive_uncorroborated` classification block. Returns (pairs, source).

    A SEPARATE loader rather than a 5th element on `_load_positive_signals`, deliberately: that
    function's 4-tuple is consumed by `tp_facets.py` (the report-render-dashboard-arc's file) at two
    call sites, and widening the tuple would force an edit there for no behavioural reason. Keeping
    the signature means the per-axis-role label change propagates to those readers for free.

    Fail-CLOSED to `_FALLBACK_POSITIVE_UNCORROBORATED` — see that constant for why the empty set is
    the WRONG default here (it would relax the `strong` gate).
    """
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        block = data.get("positive_uncorroborated")
        if not block:
            # Pre-v1.20.0 contracts: the rows are still filed under `positive_contradictions`. Use the
            # mirror so the strong-block is the same set either way.
            return set(_FALLBACK_POSITIVE_UNCORROBORATED), "fallback_pre_1_20"
        return {(u["sub_skill"], u["verdict"]) for u in block}, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → the MIRROR (never the empty set)
        print(
            f"[target-profile] WARN: could not load positive_uncorroborated "
            f"({type(e).__name__}: {e}); using the hardcoded mirror (strong-block preserved).",
            file=sys.stderr,
        )
        return set(_FALLBACK_POSITIVE_UNCORROBORATED), "fallback"


def _split_contradictions(
    contra: set, contracts_repo: Path | None = None
) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Split a loaded contradiction set into (opposing_contradictions, uncorroborated).

    Subtracting `uncorroborated` from the contradiction set is what makes the LABEL follow the
    v1.20.0 policy on a pre-v1.20.0 checkout too (where the same pairs are still listed as
    contradictions). The UNION is unchanged, so the tier does not move; only what we CALL these rows
    does. Callers that need the strong-block must use the union, never `contra` alone.
    """
    uncorr, _src = _load_positive_uncorroborated(contracts_repo)
    return contra - uncorr, uncorr


def _positive_tier(
    sub_results: dict, contracts_repo: Path | None = None, modality: str | None = None
) -> tuple[Optional[str], list[dict]]:
    """Deterministic confidence tier from graded positive sub-verdicts.

    Returns (tier | None, hits). tier ∈ {strong, moderate}. None = no positive
    signal (LLM confidence stands). MUST be called only when no kill fired (caller
    guards this) — but it is also self-safe: it reads only positive_signals and
    never emits an action. A contradiction (opposing MEASURED verdict on a
    positive-eligible axis) blocks `strong`. insufficient/data_unavailable are NOT
    contradictions (measured-vs-null).

    A `positive_uncorroborated` verdict (vocab v1.20.0) ALSO blocks `strong`, on its own flag: a
    `strong` claim requires corroboration and an axis whose own arms disagree has corroborated
    nothing. Two flags rather than one because the two must be labelled differently downstream
    (`opposing` vs `coverage_gap`) while having identical effect on the tier.
    """
    pos_map, contra_set, cfg, _src = _load_positive_signals(contracts_repo, modality=modality)
    if not pos_map:
        return None, []
    # CROSS-AXIS RECONCILE: drop contradictions a co-present verdict proves are measured on the wrong
    # basis (e.g. selectivity selective_but_broadly_normal when genomic biomarker_stratified_dependency —
    # the bulk-RNA no-window read dilutes an amp-selected window). Fail-closed (empty → nothing dropped).
    contra_set = contra_set - _reconciled_contradiction_keys(sub_results, contracts_repo)
    # SPLIT the loaded set: `uncorroborated` rows block `strong` exactly as a contradiction does, but
    # are NOT opposing evidence. Deliberately AFTER the reconcile subtraction and NOT reconciled
    # themselves — a reconciler's premise is that a contradiction was measured on the wrong basis, and
    # an axis whose own arms disagree measured nothing to be on the wrong basis about. Reconciling one
    # would drop it from the strong-block, which is fail-open.
    contra_set, uncorr_set = _split_contradictions(contra_set, contracts_repo)
    hits: list[dict] = []
    contradicted = False
    uncorroborated = False
    for short, r in sub_results.items():
        v = r.get("verdict")
        if not v:
            continue
        verdict_str = v[0]
        if (short, verdict_str) in contra_set:
            contradicted = True
            continue
        if (short, verdict_str) in uncorr_set:
            # Same two effects as a contradiction — blocks `strong`, and cannot itself count as a
            # positive dimension (two channels that disagree have corroborated nothing) — under a
            # DIFFERENT name, so the scorecard can label it `coverage_gap` instead of `opposing`.
            uncorroborated = True
            continue
        weight = pos_map.get((short, verdict_str))
        if weight:
            hits.append(
                {
                    "short": short,
                    "verdict": verdict_str,
                    "weight": weight,
                    "driving_rule_id": v[1] if len(v) > 1 else None,
                }
            )
    if not hits:
        return None, []
    # n_dims counts INDEPENDENT lines of evidence. correlated_dimension_groups (vocab) collapse
    # axes that are two reads of the same measurement to ONE dimension for the min_dimensions test —
    # e.g. expression+selectivity are both the tumor-vs-normal RNA contrast, so counting both
    # double-counted one line (the HTR1D would-be-strong FP). A short not in any group is its own
    # dimension; missing key → no grouping (backward-compatible). Weights/has_dominant are unaffected.
    _short_to_group = {}
    for _i, _grp in enumerate(cfg.get("correlated_dimension_groups", []) or []):
        for _s in _grp:
            _short_to_group[_s] = f"__corr_group_{_i}"
    n_dims = len({_short_to_group.get(h["short"], h["short"]) for h in hits})
    has_dominant = any(h["weight"] == "dominant" for h in hits)
    min_dims = cfg.get("min_dimensions_for_strong", 2)
    require_dom = cfg.get("require_dominant_for_strong", True)
    # `not uncorroborated` is the LABEL-NOT-DROP clause: it keeps the strong-block byte-identical to
    # what `not contradicted` alone enforced before the two rows were relabelled.
    strong_ok = n_dims >= min_dims and (has_dominant or not require_dom) and not contradicted and not uncorroborated
    tier = "strong" if strong_ok else "moderate"
    return tier, hits


def _positive_tier_nominates(
    tier: Optional[str], contracts_repo: Path | None = None, modality: str | None = None
) -> bool:
    """True when `tier` is the tier the VOCAB says forces `nominate`.

    The policy lives in nomination_verdict_gate.yaml
    (`positive_tier_config.forces_nominate_at_tier`, v1.18.0), not here — product owners set the
    nomination bar without a code change, same as the veto/hold policy.

    FAIL-CLOSED: a missing/null/unreadable key returns False (no nomination), which reproduces
    pre-1.18.0 behaviour byte-for-byte. This is the INVERTED fallback the positive loader already
    uses — a broken vocab must never MINT a GO, whereas a broken kill vocab must still FIRE vetoes.
    `tier=None` (no positive signal at all) is likewise never a nomination.

    Note this is deliberately NOT routed through `_GATE_ACTION_RANK`/`action_precedence`: that map
    keys a `max()` over FIRED KILL hits, so putting a positive token in it would let a nomination be
    ranked against — and tie-broken with — a restraint. `nominate` is a separate branch, reachable
    only on abstention; see the caller in run.py.
    """
    if not tier:
        return False
    _, _, cfg, _ = _load_positive_signals(contracts_repo, modality=modality)
    return bool(cfg.get("forces_nominate_at_tier")) and cfg["forces_nominate_at_tier"] == tier


# --- Reconciling the TWO deterministic nominate paths -----------------------
#
# A1 was fixed twice, independently, by two different mechanisms that both live in run.py's
# abstention else-branch:
#
#   * the POSITIVE TIER (vocab 1.18.0, `positive_tier_config.forces_nominate_at_tier: strong`) —
#     thesis-AGNOSTIC evidence QUANTITY: >= min_dimensions independent dims, one of them `dominant`,
#     no unreconciled measured contradiction.
#   * the THESIS DECIDER (vocab 1.21.0, `thesis_deciding_axes`) — thesis-SPECIFIC necessity
#     CONJUNCTION on one named deciding axis, plus an anti-blind measuredness conjunct.
#     (Authored against vocab 1.19.0; RENUMBERED to 1.21.0 on reland, because 1.19.0 and
#     1.20.0 both landed on contracts main while this branch sat unmerged — 1.19.0 now names
#     the +3 tractability middle-ladder positives, an unrelated feature. Cite 1.21.0.)
#
# They are COMPLEMENTARY, not redundant: their firing sets are disjoint and neither can reach the
# other's targets (the favorable surface verdicts sit in `positive_signals_modality_scoped`, so the
# tier can never nominate an antigen in default biology-first mode; and `oncogene_addiction` has no
# `thesis_deciding_axes` entry, so the decider can never nominate EGFR/ERBB2).
#
# Landing them as two independent writers produced three real defects, which is why the decision is
# hoisted into ONE pure function here instead of living inline at two call sites:
#
#   1. WRITE COLLISION — both wrote `recommendation_gate["forced_recommendation"]`; whichever ran
#      last silently relabelled the attribution.
#   2. `fired` — one path set `recommendation_gate["fired"] = True`. That is WRONG and this function
#      never does it: consumers read `fired` as "a RESTRAINT gate fired". tp_facets silences the
#      DISSENT record when an evidence-band block co-occurs with `fired` (suppressing the
#      disagreement most worth surfacing), and cross-evidence-hypothesis maps fired+no-suppression
#      to `declined`, INVERTING a nomination into a kill.
#   3. INTERLOCK DIVERGENCE — they answered "may we nominate over an LLM-authored negative?"
#      differently, which would make the framework's most consequential output depend on which path
#      happened to fire.
_NOMINATE_PATH_PRECEDENCE = ("thesis_decider", "positive_tier")


def reconcile_positive_nomination(
    *,
    thesis_action: Optional[str],
    thesis_record: Optional[dict],
    tier: Optional[str],
    tier_nominates: bool,
    pos_hits: list,
    clamped: bool,
    llm_value: Optional[str],
    allow_over_llm_authored_negative: bool = True,
) -> tuple[Optional[str], dict]:
    """The SINGLE decision point + SINGLE writer for both deterministic `nominate` paths.

    Returns `(value, patch)`: `value` is the recommendation to force (None = force nothing), and
    `patch` holds the `recommendation_gate` keys to merge. Pure — it mutates nothing, so the policy
    is testable without running a profile.

    PRECEDENCE (`_NOMINATE_PATH_PRECEDENCE`): the thesis decider wins the attribution. Both mint the
    identical VALUE, so precedence is purely about what the audit spine says decided it — and the
    decider is the strictly more specific claim (a named axis + a necessity conjunction + a
    measuredness conjunct, versus a thesis-agnostic count of dimensions). Agreement between the two
    is recorded as `also_reached_by` corroboration rather than overwriting.

    THE INTERLOCK, asked ONCE for both paths (`allow_over_llm_authored_negative`), so they can never
    diverge again: may a fired deterministic conjunction nominate over an LLM-authored negative?

    ANSWER = YES (default True). The #1291 abstention lower-bound clamp exists precisely to floor an
    LLM negative that has NO RULE behind it; a fired conjunction is exactly the auditable rule it was
    waiting for, so deferring to the LLM here would invert the whole point of the clamp. MEASURED, not
    assumed: on the grounded full-LLM FOLR1/OV run (APPROVED — mirvetuximab) the LLM authored `hold`,
    the clamp demoted it to insufficient_evidence, and the thesis conjunction was fully satisfied. The
    withhold reading would therefore have suppressed the nomination of an approved drug on the strength
    of a rule-less LLM opinion — the exact failure mode #1291 was built to stop.

    THE COST, recorded not hidden: the published report then carries a positive VALUE beside prose
    arguing the negative. That disagreement is the most decision-relevant thing on the page, so it is
    emitted explicitly as `nominated_over_llm_negative` rather than left for a reader to notice. Note
    `fired` is never set (see defect 2), which is also what keeps tp_facets' DISSENT record alive on
    exactly these runs.

    Setting the flag False restores the withhold reading for BOTH paths in one place.

    FAIL-CLOSED shape: nothing here can mint a GO on its own. It only forwards a decision a caller
    already made (`thesis_action` from the vocab-driven conjunction, `tier_nominates` from the
    vocab-driven threshold), and every unrecognized combination returns `(None, {})`.
    """
    fired: dict[str, dict] = {}
    if thesis_action and thesis_record is not None:
        fired["thesis_decider"] = {
            "value": thesis_action,
            "detail": (
                f"thesis '{thesis_record.get('thesis')}' decided on "
                f"{(thesis_record.get('deciding') or {}).get('short')}="
                f"{(thesis_record.get('deciding') or {}).get('verdict')}"
            ),
            "hits": list(thesis_record.get("corroborating") or []),
        }
    if tier_nominates and tier:
        fired["positive_tier"] = {
            "value": "nominate",
            "detail": f"positive tier reached `{tier}` on {sorted({h['short'] for h in pos_hits})}",
            "hits": [{**h, "action": "nominate", "policy_source": "positive_tier"} for h in pos_hits],
        }
    if not fired:
        return None, {}

    order = [p for p in _NOMINATE_PATH_PRECEDENCE if p in fired]
    winner = order[0]

    if clamped and not allow_over_llm_authored_negative:
        return None, {
            "nominate_withheld": {
                "tier": tier,
                "path": winner,
                "also_reached_by": order[1:],
                "reason": "llm_authored_negative",
                "llm_recommendation": llm_value,
                "detail": (
                    "a deterministic positive path reached its nominating bar, but the LLM authored a "
                    "rule-less negative (clamped by the abstention lower bound) — refusing to publish "
                    "a positive call beside a narrative arguing against it. " + fired[winner]["detail"]
                ),
            }
        }

    value = fired[winner]["value"]
    # `fired` is deliberately ABSENT from this patch — see defect 2 in the block comment above.
    patch = {
        "forced_recommendation": value,
        "forced_by": winner,
        "positive_gate_fired": True,
        "llm_recommendation": llm_value,
        "overridden": llm_value != value,
        "triggered_by": fired[winner]["hits"],
    }
    if clamped:
        # The interlock allowed this, but the published call now DISAGREES with the narrative beside
        # it. Emit the disagreement as a first-class record: a reader must not have to infer it by
        # noticing that the prose argues the opposite of the recommendation.
        patch["nominated_over_llm_negative"] = {
            "path": winner,
            "llm_recommendation": llm_value,
            "forced": value,
            "detail": (
                f"the LLM authored `{llm_value}`, which the abstention lower-bound clamp demoted to "
                f"insufficient_evidence for having no rule behind it; {fired[winner]['detail']}, which "
                f"IS a rule, so the deterministic path forced `{value}`. The narrative still argues the "
                f"negative — read it as the standing dissent against this call, not as agreement."
            ),
        }
    if order[1:]:
        patch["also_reached_by"] = {
            "paths": order[1:],
            "tier": tier,
            "detail": (
                f"{winner} forced this `{value}`; "
                + "; ".join(fired[p]["detail"] for p in order[1:])
                + ". Recorded as corroboration — the more specific path keeps the attribution."
            ),
        }
    return value, patch


# --- Gate scorecard (deterministic; category × status × finding) ------------
#
# The top-of-report glanceable grid: one row per QUESTION-GATE (A Present … H Translational),
# rows driven by the gate_coverage registry so a gate with NO sub-verdict this run (e.g. H, which
# has no sub-skill) STILL appears — greyed — rather than being silently dropped (the "no cell for
# we-didn't-look" failure a 3-color RAG light has; scorecard-level version of L's discipline).
#
# The 4-state status is a PURE PROJECTION of the SAME policy the deterministic gate uses — reusing
# _load_gate_verdicts (kill tuples), _load_positive_signals (positive + contradiction sets) — so
# the scorecard can NEVER disagree with the recommendation gate. No new classification logic:
#   opposing     = verdict in the kill tuples OR a positive_contradiction (a MEASURED negative)
#   supportive   = verdict in positive_signals (a MEASURED positive)
#   coverage_gap = insufficient / data_unavailable / None / gate absent this run (we didn't look),
#                  OR a positive_uncorroborated verdict (v1.20.0 — we DID look, but the axis's own
#                  arms disagreed with each other, so nothing was corroborated). The second case
#                  still BLOCKS `strong` in the gate; it just isn't opposing evidence. "The arms
#                  disagree" != "the measurement opposes".
_SCORECARD_STATUS_ORDER = {"opposing": 0, "supportive": 1, "coverage_gap": 2}
_COVERAGE_GAP_VERDICTS = {None, "insufficient", "data_unavailable", "not_implemented", "phase_not_yet_wired"}


def _gate_scorecard(
    sub_results: dict,
    deciding_axis: Optional[dict] = None,
    contracts_repo: Path | None = None,
    modality: str | None = None,
    thesis: str | None = None,
) -> list[dict]:
    """Build the 8-gate scorecard rows. Rows come from the gate_coverage REGISTRY (not from
    iterating sub_results), so gates we're blind on this run still render as greyed rows. Status
    reuses the nomination-gate policy so it cannot diverge from the deterministic verdict.
    `modality` is threaded so a modality-scoped surface positive classifies as `supportive`
    (not `coverage_gap`) under an explicit biologics modality — consistent with the gate.

    `thesis` is threaded for the SAME reason and closes a divergence that was measured, not
    supposed: without it this function classifies an axis the target's thesis has declared
    IRRELEVANT (`thesis_axis_relevance`) as `opposing`, while `_hard_gates_status` — reading the
    same run's suppression records — reports that veto as `suppressed` with the provenance
    `{kind: thesis_irrelevant_axis, thesis: <t>}`. Both blocks are emitted into ONE
    `nomination.json`, so the artifact asserted "this veto was lifted because the thesis makes the
    axis irrelevant" and "this axis is opposing evidence" simultaneously, of the same axis and the
    same live verdict. NOT verdict-moving (see `_SCORECARD_STATUS_ORDER`: nothing switches on
    scorecard status to force a call); it is the LABEL the two views disagreed on.

    Defaults to None, which reproduces the pre-2026-09-15 output BY CONSTRUCTION: an absent thesis
    drops nothing, so every caller that does not pass one is byte-identical."""
    baseline, _ = _load_gate_coverage(contracts_repo)
    kill_map, _ = _load_gate_verdicts(contracts_repo)  # {(short,verdict): action}
    positive_map, contradictions, _, _ = _load_positive_signals(contracts_repo, modality=modality)
    # Step-2b thesis scoping, the SAME load and the same `.get(thesis, set())` shape
    # `_suppressed_gate_hits` uses, so the two views cannot drift apart on which keys are dropped.
    # CONSERVATIVE by inheritance: `_load_thesis_axis_relevance` returns {} on any failure, and an
    # absent/garbled block can only leave a row labelled `opposing` — never mint a favourable label.
    thesis_drop = _load_thesis_axis_relevance(contracts_repo).get(thesis, set()) if thesis else set()
    # cross-axis reconcile (same as the recommendation gate) so the scorecard's opposing status can't
    # disagree with the deterministic call — a reconciled contradiction is no longer 'opposing'.
    contradictions = contradictions - _reconciled_contradiction_keys(sub_results, contracts_repo)
    # Split off the `uncorroborated` rows so they are not LABELLED opposing. They remain in the
    # recommendation gate's strong-block (see `_positive_tier`), so this changes the WORD on the
    # scorecard, not the decision.
    contradictions, uncorroborated = _split_contradictions(contradictions, contracts_repo)
    deciding_short = None
    if deciding_axis and deciding_axis.get("basis") == "gate_fired":
        deciding_short = (deciding_axis.get("deciding_axis") or {}).get("short")

    def _status(short: str, verdict: Optional[str]) -> str:
        if verdict in _COVERAGE_GAP_VERDICTS:
            return "coverage_gap"
        if (short, verdict) in uncorroborated:
            # The axis's own arms disagree, so it resolved nothing — a COVERAGE gap in the corroborated
            # sense, not opposing evidence. Checked BEFORE the kill/contradiction test so the label can
            # never depend on which contracts version happened to be readable.
            return "coverage_gap"
        if (short, verdict) in thesis_drop:
            # The thesis declares this axis IRRELEVANT, so `_suppressed_gate_hits` already lifted the
            # veto and `hard_gates[].status` reads `suppressed`. Calling the same row `opposing` here
            # would make ONE artifact contradict itself. `neutral`, not `coverage_gap`: we DID measure
            # the axis and got a verdict — it is the THESIS that makes the verdict non-dispositive, not
            # a gap in evidence, and the row still carries its true `verdict` for anyone who disagrees
            # with the scoping. Placement is measured, not stylistic: `('dependency','non_dependent')`
            # is in `kill_map` (True) and NOT in `contradictions` (False), so the ONLY test that would
            # otherwise claim it is the combined one directly below — while the two `coverage_gap`
            # tests above must keep precedence, since an unmeasured or self-disagreeing axis is a gap
            # whatever the thesis says. Reuses EXISTING vocabulary, so no consumer needs to learn a
            # word (see the `additionalProperties: false` hazard: a new FIELD would red 9/14 skills
            # until contracts declared it; a new VALUE in an existing field reds nothing).
            return "neutral"
        if (short, verdict) in kill_map or (short, verdict) in contradictions:
            return "opposing"
        if (short, verdict) in positive_map:
            return "supportive"
        # A measured verdict that is neither a gate kill nor a curated positive/contradiction —
        # report it as measured-but-neutral, still on-scale, NOT a coverage gap (we DID look).
        # Treated as supportive-family for chip purposes only if it's a positive; otherwise 'neutral'.
        # MEASURED POPULATION (vocab 1.21.0, no modality): exactly the 7 `excluded_modality_scoped`
        # rows — 6 `surface_modality` verdicts (`neither_viable`, `adc_preferred_tce_unsafe`,
        # `tce_unsafe_normal_liability`, `adc_preferred_tce_escape_risk`, `tce_escape_risk`,
        # `shed_dominant_opposed`) plus `tractability_sm: structurally_intractable`. This replaces an
        # example that was simply wrong: `broadly_dependent` is a `positive_contradictions` entry and
        # measures `opposing`, never `neutral`. A named population beats an example, because an
        # example cannot be re-checked against the vocabulary and a population can.
        return "neutral"

    rows = []
    # Rows carry gate/gate_name/band + axis (biology|modality_fit). axis derives from the contract
    # (v2) or is inferred from the band (v1 has no axis field): necessity→biology, sufficiency→
    # modality_fit — the 1:1 alignment the additive v1.1.0 file also asserts.
    for short, meta in baseline.items():
        r = sub_results.get(short) or {}
        v = r.get("verdict")
        verdict_str = v[0] if v else None
        driving = v[1] if (v and len(v) > 1) else None
        axis = meta.get("axis") or ("biology" if meta.get("band") == "necessity" else "modality_fit")
        # risk_category (5R dashboard spine) from the contract; fall back to axis if a pre-field
        # contract is live (biology→biological; else the row is uncategorized, grouped under 'other').
        risk_category = meta.get("risk_category") or ("biological" if axis == "biology" else None)
        rows.append(
            {
                "short": short,
                "gate": meta.get("gate"),
                "gate_name": meta.get("gate_name"),
                "band": meta.get("band"),
                "axis": axis,
                "risk_category": risk_category,
                "verdict": verdict_str,
                "driving_rule_id": driving,
                "status": _status(short, verdict_str),
                "framework_can_evidence": _run_coverage_for_short(short, r, baseline),
                "is_deciding": short == deciding_short,
            }
        )
    # Sort AXIS-primary (biology before modality_fit) so grouping is stable even when v2 modality-fit
    # rows are letterless; then by gate letter (A..H; letterless → 'Z' last within its axis), then
    # band (necessity first) as a stable tiebreak.
    _AXIS_ORDER = {"biology": 0, "modality_fit": 1}
    rows.sort(
        key=lambda x: (_AXIS_ORDER.get(x.get("axis"), 2), str(x.get("gate") or "Z"), x.get("band") != "necessity")
    )
    return rows


__all__ = [
    "_BIOLOGICS_MODALITIES",
    "_CONFIDENCE_RANK",
    "_COVERAGE_GAP_VERDICTS",
    "_COVERAGE_RANK",
    "_FALLBACK_GATE_VERDICTS",
    "_FALLBACK_KILL_CAPABLE_VERDICTS",
    "_FALLBACK_POSITIVE_UNCORROBORATED",
    "_GATE_ACTION_RANK",
    "_GATING_AXES",
    "_GATING_AXIS_FAILCLOSED_ACTION",
    "_RECOGNIZED_GATING_VERDICTS",
    "_SCORECARD_STATUS_ORDER",
    "_TIER_TO_CONFIDENCE",
    "_V2_GATE_LISTS",
    "abstention_lower_bound_clamp",
    "derive_thesis",
    "_load_target_thesis",
    "_load_thesis_axis_relevance",
    "_load_thesis_deciding_axes",
    "thesis_nomination",
    "reconcile_positive_nomination",
    "_card_field_value",
    "_flatten_gate_coverage",
    "_gate_recommendation",
    "_gate_scorecard",
    "_hard_gates_status",
    "_load_gate_coverage",
    "_load_gate_verdicts",
    "_load_kill_capable_verdicts",
    "_load_positive_signals",
    "_load_positive_uncorroborated",
    "_load_veto_suppressors",
    "_split_contradictions",
    "_positive_tier",
    "_positive_tier_nominates",
    # Exported so a test can ASSERT that no reconciler ever drops an `uncorroborated` verdict, rather
    # than relying on today's two reconcilers both happening to target a different one.
    "_reconciled_contradiction_keys",
    "_run_coverage_for_short",
    "_sub_result_has_signal",
    "_suppressed_gate_hits",
    "_trigger_label",
]
