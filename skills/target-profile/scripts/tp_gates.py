"""target-profile — the cross-gate nomination gate + gate-coverage + positive-tier + gate-scorecard.
Deterministic nomination spine loaders (declarative policy from target-contracts, conservative fallbacks)."""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from tp_common import _CONTRACTS_REPO




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
    ("dependency", "pan_essential_killer"): "veto",   # non-selective essentiality — no window
    ("dependency", "non_dependent"): "veto",          # no dependency at all
    ("safety", "highly_constrained_safety_concern"): "hold",  # concern → hold, not veto
    # 2026-08-16: the fallback must be conservative-AND-COMPLETE — it must mirror the ENTIRE
    # gates block, not just the veto arms, so a missing/unparseable vocab still fires every
    # HOLD too (a missing policy silently dropping the human-genetics or subtype hold would be a
    # fail-open). These two were previously vocab-only.
    ("safety", "human_genetics_safety_concern"): "hold",       # P5 human-genetics WT-loss concern
    ("safety", "pan_essential_broad_tox_concern"): "hold",     # data-util expansion 2026-08-21 — broad tox
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
    "dependency": frozenset({
        "pan_essential_killer", "non_dependent",                      # the two vetoes
        "concordant_dependent", "lineage_selective", "selective_dependent",
        "chemical_genetic_confirmed_dependent", "partner_conditional_dependent",
        "discordant", "broadly_dependent",                            # contradictions
        "non_dependent_paralog_buffered",                             # veto-rescue (benign)
        "insufficient", "insufficient_underpowered",
        "insufficient_underpowered_pan_essential",                    # admissibility guards
    }),
    "safety": frozenset({
        "highly_constrained_safety_concern", "human_genetics_safety_concern",  # the (now four) holds
        "pan_essential_broad_tox_concern", "normal_tissue_protein_safety_concern",  # data-util expansion 2026-08-21
        "wt_constraint_mechanism_mismatch", "wt_human_genetics_mechanism_mismatch",
        "tolerant_reduced_safety_risk", "moderately_constrained_safety",
        "data_unavailable", "insufficient",
    }),
    "subtype_fit": frozenset({
        "subtype_specific_non_dependence",                            # the hold
        "insufficient",
    }),
}

# The LEAST-PERMISSIVE forced action per gating axis, applied when that axis emits an
# unrecognized / malformed verdict. dependency's floor is veto (it owns the two vetoes);
# safety + subtype are hold. Never None.
_GATING_AXIS_FAILCLOSED_ACTION: dict[str, str] = {
    "dependency": "veto", "safety": "hold", "subtype_fit": "hold",
}


# The complete kill_capable_verdicts registry FALLBACK (mirrors target-contracts
# vocabularies/nomination_verdict_gate.yaml). {(sub_skill, verdict): disposition}, disposition
# ∈ {gated, excluded_modality_scoped, contradiction}. Used to iterate the COMPLETE declared kill
# set for the hard_gates status block; conservative-and-complete on load failure (never empty).
_FALLBACK_KILL_CAPABLE_VERDICTS: dict[tuple[str, str], str] = {
    ("dependency", "pan_essential_killer"): "gated",
    ("dependency", "non_dependent"): "gated",
    ("dependency", "discordant"): "contradiction",
    ("dependency", "broadly_dependent"): "contradiction",
    ("safety", "highly_constrained_safety_concern"): "gated",
    ("safety", "human_genetics_safety_concern"): "gated",
    ("safety", "pan_essential_broad_tox_concern"): "gated",          # data-util expansion 2026-08-21
    ("safety", "normal_tissue_protein_safety_concern"): "gated",     # data-util expansion 2026-08-21
    ("subtype_fit", "subtype_specific_non_dependence"): "gated",
    ("selectivity", "not_selective"): "contradiction",
    ("selectivity", "discordant_across_comparators"): "contradiction",
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
        print(f"[target-profile] WARN: could not load nomination_verdict_gate vocab "
              f"({type(e).__name__}: {e}); using hardcoded conservative fallback.",
              file=sys.stderr)
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
        print(f"[target-profile] WARN: could not load kill_capable_verdicts registry "
              f"({type(e).__name__}: {e}); using hardcoded complete fallback.",
              file=sys.stderr)
        return dict(_FALLBACK_KILL_CAPABLE_VERDICTS), "fallback"


# Biologics modalities for which the dependency veto is INFORMATIVE-only (a
# surface-directed biologic kills via antigen engagement, not genetic dependency).
_BIOLOGICS_MODALITIES = {"adc", "bite_tce", "antibody"}


def _load_veto_suppressors(
    contracts_repo: Path | None = None,
) -> tuple[list[dict], list[dict], str]:
    """Load the two veto-suppression policies (v1.2.0) from the vocab. Returns
    (context_escape_suppressors, modality_scoped_suppression, source).

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
        return ctx, msvs, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no suppression, veto stands)
        print(f"[target-profile] WARN: could not load veto suppressors "
              f"({type(e).__name__}: {e}); suppression DISABLED (full veto stands).",
              file=sys.stderr)
        return [], [], "fallback"


def _trigger_label(w: dict, present: set, sub_results: dict) -> Optional[str]:
    """Return a provenance label if the veto-suppressor `when_present` trigger `w` is satisfied,
    else None. Two trigger forms:
      - VERDICT-tuple  {sub_skill, verdict}      → matched against the live sub-verdict `present` set.
      - CARD-FIELD     {card_id, field, value}   → matched against a composed card's summary field
        (2026-08-21). Lets a suppressor key on a signal carried by a card under a GATELESS sub-skill
        (verdict=None) — e.g. synthetic-lethal-partners.sl_partner_class after the SL short was
        consolidated into combination_vulnerability. A local card scan (NOT tp_facets._find_card_summary)
        avoids a tp_gates→tp_facets import cycle (tp_facets already imports tp_gates).
    Defensive: an unrecognized/garbled trigger shape returns None (never matches, never raises)."""
    if not isinstance(w, dict):
        return None
    if "card_id" in w:
        cid, field, value = w.get("card_id"), w.get("field"), w.get("value")
        for r in sub_results.values():
            for c in (r.get("cards") or []):
                if isinstance(c, dict) and c.get("card_id") == cid:
                    if (c.get("summary") or {}).get(field) == value:
                        return f"{cid}.{field}={value}"
        return None
    if "sub_skill" in w and "verdict" in w:
        return f"{w['sub_skill']}:{w['verdict']}" if (w["sub_skill"], w["verdict"]) in present else None
    return None


def _suppressed_gate_hits(
    hits: list[dict],
    sub_results: dict,
    modality: Optional[str],
    contracts_repo: Path | None = None,
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
    ctx_supps, msvs, src = _load_veto_suppressors(contracts_repo)
    if not ctx_supps and not msvs:
        return hits, []

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
        # (A) context-escape. A `when_present` trigger is EITHER a verdict-tuple form
        # ({sub_skill, verdict} — matched against the live sub-verdict set) OR a CARD-FIELD form
        # ({card_id, field, value} — matched against a composed card's summary field). The latter
        # (2026-08-21) lets a suppressor key on a signal that lives on a card under a GATELESS
        # sub-skill (verdict=None), e.g. the SL rescue after synthetic_lethal_partners consolidated
        # into combination_vulnerability. _trigger_label returns the match label or None.
        for s in ctx_supps:
            sup = s.get("suppresses", {})
            if (sup.get("sub_skill"), sup.get("verdict")) != key:
                continue
            label = next((lbl for w in s.get("when_present", [])
                          if (lbl := _trigger_label(w, present, sub_results))), None)
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
        if suppressed_by:
            suppressions.append({**h, "suppressed_by": suppressed_by, "policy_source": src})
        else:
            survivors.append(h)
    return survivors, suppressions


def _gate_recommendation(
    sub_results: dict, contracts_repo: Path | None = None,
    modality: Optional[str] = None,
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
                hits.append({"short": short, "verdict": "<malformed>",
                             "action": fc, "driving_rule_id": None,
                             "policy_source": policy_source,
                             "_fail_closed": True, "fail_closed_reason": "malformed_verdict"})
                print(f"[target-profile] recommendation GATE fail-closed: malformed verdict "
                      f"{v!r} on gating axis '{short}' → forced least-permissive '{fc}'.",
                      file=sys.stderr)
            continue
        verdict_str, driving_rule_id = v[0], (v[1] if len(v) > 1 else None)
        action = gate_verdicts.get((short, verdict_str))
        if action:
            hits.append({"short": short, "verdict": verdict_str,
                         "action": action, "driving_rule_id": driving_rule_id,
                         "policy_source": policy_source})
            continue
        # No gate action matched. FAIL-CLOSED: on a gating axis, an UNRECOGNIZED verdict
        # token (renamed kill, unknown enum) is NOT a silent permissive pass — if the token is not
        # in the axis's complete recognized vocabulary it may be a renamed veto, so route to the
        # axis's least-permissive action. Recognized-but-non-gating verdicts (positives, neutrals,
        # insufficient) fall through exactly as before (no forced action).
        if short in _GATING_AXES and verdict_str not in _RECOGNIZED_GATING_VERDICTS.get(short, frozenset()):
            fc = _GATING_AXIS_FAILCLOSED_ACTION[short]
            hits.append({"short": short, "verdict": verdict_str,
                         "action": fc, "driving_rule_id": driving_rule_id,
                         "policy_source": policy_source,
                         "_fail_closed": True, "fail_closed_reason": "unrecognized_verdict"})
            print(f"[target-profile] recommendation GATE fail-closed: unrecognized verdict "
                  f"'{verdict_str}' on veto-capable axis '{short}' (not in recognized set) → "
                  f"forced least-permissive '{fc}' (never a silent pass).", file=sys.stderr)
    # v1.2.0: apply veto suppression (context-escape + modality-scoped) before
    # resolving the forced action. A suppressed veto does not force — but is recorded.
    hits, suppressions = _suppressed_gate_hits(hits, sub_results, modality, contracts_repo)
    if not hits:
        return None, [], suppressions
    # .get(a, 0): an action outside {veto, hold} (a vocab typo or a new action a product owner adds —
    # the module comment explicitly invites editing this vocab "without a code change") must NOT crash
    # the run with a KeyError, which would defeat the "gate never crashes the run" contract. Unknown
    # actions rank LOWEST (0) so a real veto/hold always wins; the target-contracts CI test
    # (test_every_gate_well_formed) is the primary guard — this is defense-in-depth.
    forced = max((h["action"] for h in hits), key=lambda a: _GATE_ACTION_RANK.get(a, 0))
    return forced, hits, suppressions


def _hard_gates_status(
    sub_results: dict, hits: list[dict], suppressions: list[dict],
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
      opposing   — a `contradiction` verdict matched live (opposing measured evidence; blocks
                   `strong`, not a veto).
      blind      — the axis produced NO verdict this run (coverage gap — could not evaluate).
      latent     — the axis WAS evaluated but did not emit this kill verdict (declared, dormant).
    """
    registry, source = _load_kill_capable_verdicts(contracts_repo)
    fired_pairs = {(h["short"], h["verdict"]) for h in hits}
    suppressed_pairs = {(s["short"], s["verdict"]) for s in suppressions}

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
        matched = (live == verdict)
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
        elif matched and disposition == "contradiction":
            status = "opposing"
        elif matched and disposition == "gated":
            status = "fired"   # gated + matched but not in hits (defensive; normally in hits)
        else:
            status = "latent"
        rows.append({"short": short, "verdict": verdict, "disposition": disposition,
                     "status": status, "live_verdict": live, "policy_source": source})
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
    if "gates" in data:                      # v1 / v1.1.0 flat shape — every entry is a row.
        return {g["short"]: g for g in data["gates"]}
    by_short: dict = {}                      # v2 three-list shape.
    for key in _V2_GATE_LISTS:
        for g in data.get(key, []):
            if key == "biomarker_facets" and g.get("grain", "sub_skill") == "card":
                continue                     # card-grain facet → rendered in-section, not a row
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
        print(f"[target-profile] WARN: could not load gate_coverage vocab "
              f"({type(e).__name__}: {e}); deciding-axis router degrades to a bare note.",
              file=sys.stderr)
        return {}, "none"


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
        return "blind"          # every card for this gate was unavailable this run
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
        print(f"[target-profile] WARN: could not load positive_signals vocab "
              f"({type(e).__name__}: {e}); positive tier DISABLED (LLM confidence stands).",
              file=sys.stderr)
        return {}, set(), {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True}, "fallback"


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
    """
    pos_map, contra_set, cfg, _src = _load_positive_signals(contracts_repo, modality=modality)
    if not pos_map:
        return None, []
    hits: list[dict] = []
    contradicted = False
    for short, r in sub_results.items():
        v = r.get("verdict")
        if not v:
            continue
        verdict_str = v[0]
        if (short, verdict_str) in contra_set:
            contradicted = True
            continue
        weight = pos_map.get((short, verdict_str))
        if weight:
            hits.append({"short": short, "verdict": verdict_str, "weight": weight,
                         "driving_rule_id": v[1] if len(v) > 1 else None})
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
    strong_ok = (n_dims >= min_dims and (has_dominant or not require_dom)
                 and not contradicted)
    tier = "strong" if strong_ok else "moderate"
    return tier, hits


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
#   coverage_gap = insufficient / data_unavailable / None / gate absent this run (we didn't look)
_SCORECARD_STATUS_ORDER = {"opposing": 0, "supportive": 1, "coverage_gap": 2}
_COVERAGE_GAP_VERDICTS = {None, "insufficient", "data_unavailable", "not_implemented",
                          "phase_not_yet_wired"}


def _gate_scorecard(sub_results: dict, deciding_axis: Optional[dict] = None,
                    contracts_repo: Path | None = None, modality: str | None = None) -> list[dict]:
    """Build the 8-gate scorecard rows. Rows come from the gate_coverage REGISTRY (not from
    iterating sub_results), so gates we're blind on this run still render as greyed rows. Status
    reuses the nomination-gate policy so it cannot diverge from the deterministic verdict.
    `modality` is threaded so a modality-scoped surface positive classifies as `supportive`
    (not `coverage_gap`) under an explicit biologics modality — consistent with the gate."""
    baseline, _ = _load_gate_coverage(contracts_repo)
    kill_map, _ = _load_gate_verdicts(contracts_repo)          # {(short,verdict): action}
    positive_map, contradictions, _, _ = _load_positive_signals(contracts_repo, modality=modality)
    deciding_short = None
    if deciding_axis and deciding_axis.get("basis") == "gate_fired":
        deciding_short = (deciding_axis.get("deciding_axis") or {}).get("short")

    def _status(short: str, verdict: Optional[str]) -> str:
        if verdict in _COVERAGE_GAP_VERDICTS:
            return "coverage_gap"
        if (short, verdict) in kill_map or (short, verdict) in contradictions:
            return "opposing"
        if (short, verdict) in positive_map:
            return "supportive"
        # A measured verdict that is neither a gate kill nor a curated positive/contradiction
        # (e.g. a neutral 'broadly_dependent') — report it as measured-but-neutral, still on-scale,
        # NOT a coverage gap (we DID look). Treated as supportive-family for chip purposes only if
        # it's a positive; otherwise 'neutral'.
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
        rows.append({
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
        })
    # Sort AXIS-primary (biology before modality_fit) so grouping is stable even when v2 modality-fit
    # rows are letterless; then by gate letter (A..H; letterless → 'Z' last within its axis), then
    # band (necessity first) as a stable tiebreak.
    _AXIS_ORDER = {"biology": 0, "modality_fit": 1}
    rows.sort(key=lambda x: (_AXIS_ORDER.get(x.get("axis"), 2),
                             str(x.get("gate") or "Z"),
                             x.get("band") != "necessity"))
    return rows


__all__ = [
    '_BIOLOGICS_MODALITIES',
    '_CONFIDENCE_RANK',
    '_COVERAGE_GAP_VERDICTS',
    '_COVERAGE_RANK',
    '_FALLBACK_GATE_VERDICTS',
    '_FALLBACK_KILL_CAPABLE_VERDICTS',
    '_GATE_ACTION_RANK',
    '_GATING_AXES',
    '_GATING_AXIS_FAILCLOSED_ACTION',
    '_RECOGNIZED_GATING_VERDICTS',
    '_SCORECARD_STATUS_ORDER',
    '_TIER_TO_CONFIDENCE',
    '_V2_GATE_LISTS',
    '_flatten_gate_coverage',
    '_gate_recommendation',
    '_gate_scorecard',
    '_hard_gates_status',
    '_load_gate_coverage',
    '_load_gate_verdicts',
    '_load_kill_capable_verdicts',
    '_load_positive_signals',
    '_load_veto_suppressors',
    '_positive_tier',
    '_run_coverage_for_short',
    '_sub_result_has_signal',
    '_suppressed_gate_hits',
    '_trigger_label',
]
