#!/usr/bin/env python3
"""target-profile — composed target profile with Tier-3 LLM narrative synthesis.

Fans out to the 6 wired question-answering skills, collects their sub-
verdicts + fired rules, then invokes Bedrock (via _skills_common.llm) with
a forced structured tool_use to produce executive_summary + tension_analysis
+ recommendation. Emits target_profile.md + nomination.json + provenance.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common import (
    resolve_cards, fired_rules, modality_lens,
    synthesize_structured, render_composite_panel,
)
from _skills_common import ordinal_view
from _skills_common.rules_loader import load_interpretation_rules

SKILL_NAME = "target-profile"
SKILL_VERSION = "1.0.0"


def _framework_model_version() -> str | None:
    """The DECLARED framework model pin (governance item B). Read from the single
    source-of-truth constant in the bedrock client. Graceful None on import failure —
    provenance simply omits it rather than crashing the run (conservative fallback)."""
    try:
        wf = (Path(__file__).resolve().parent.parent.parent
              / "workflow-target-evaluation-onc" / "scripts" / "integrated_report")
        sys.path.insert(0, str(wf))
        from bedrock_client import FRAMEWORK_MODEL_VERSION  # type: ignore
        return FRAMEWORK_MODEL_VERSION
    except Exception:  # noqa: BLE001
        return None


# --- Sub-skill orchestration ------------------------------------------------

def _load_sub_skill_verdict_fn(skill_dir_name: str) -> Any:
    """Load a sub-skill's run.py module and return its `_verdict()` or
    `_snapshot()` function (whichever exists). Sub-skills follow the
    convention of exposing one such function; we grab it via importlib
    so target-profile doesn't hard-code each sub-skill's Python path.
    """
    run_py = SKILLS_DIR / skill_dir_name / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location(
        f"_subskill_{skill_dir_name.replace('-', '_')}", run_py,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, "_verdict", None) or getattr(module, "_snapshot", None)


# The wired question-answering skills to compose. Order matches phase A→K.
# RESTRUCTURED 2026-07-14 (scope deep-dive):
#   - tractability-and-modality SPLIT → tractability-small-molecule (SM
#     chemical-genetic verdict) + surface-modality-fit (biologics-modality call
#     the old skill only displayed).
#   - mutation-profile REFRAMED → genomic-alteration-profile (SNV + copy-number
#     + fusion placeholder).
#   - patient-population-and-access DELETED (thin re-projection of the
#     mutation-hotspot-frequency card; its prevalence fields folded into
#     genomic-alteration-profile).
#   - surfaceome-cohort-ranking DROPPED from the fan-out (per-indication scan,
#     not a per-target question-skill; its cohort_rank_class is now covered
#     inside surface-modality-fit). The scan skill still exists as a utility.
SUB_SKILLS = [
    ("tumor-presence",                 "expression"),
    ("tumor-selectivity",              "selectivity"),
    ("functional-requirement",         "dependency"),
    ("synthetic-lethal-partners",      "synthetic_lethal_partners"),  # gate-C SL veto-suppressor input
    ("mechanism-and-pharmacology",     "mechanism"),
    ("genomic-alteration-profile",     "genomic_alteration"),  # reframed from mutation-profile
    ("differentiation-landscape",      "differentiation"),
    ("tractability-small-molecule",    "tractability_sm"),     # split (SM half)
    ("surface-modality-fit",           "surface_modality"),    # split (biologics half)
    ("on-target-safety-liability",     "safety"),
]

# Card set for each sub-skill (must match SKILL.md composition.cards_used).
# RESTRUCTURED 2026-07-14 — keys track the SUB_SKILLS renames above.
SUB_SKILL_CARDS = {
    "tumor-presence": [
        "expression-distribution",
        "expression-tumor-vs-adjacent",
        "protein-presence-cptac",
    ],
    "tumor-selectivity": ["tumor-vs-normal-selectivity"],
    "functional-requirement": [
        "pan-cancer-crispr-dependency-distribution",
        "pan-cancer-rnai-dependency-distribution",
        "crispr-rnai-dependency-concordance",
        "dependency-lineage-selectivity",
        "paralog-buffering",
    ],
    "synthetic-lethal-partners": [
        "synthetic-lethal-partners",
    ],
    "mechanism-and-pharmacology": [
        "signaling-network-mechanism",
    ],
    "genomic-alteration-profile": [          # reframed from mutation-profile
        "mutation-type-counts",
        "mutation-stratified-dependency",
        "mutation-hotspot-frequency",
        "copy-number-distribution",          # CN axis wired 2026-07-14
        "fusion-rearrangement-landscape",    # placeholder (resolves _missing)
    ],
    "differentiation-landscape": [
        "co-mutation-and-mutual-exclusivity",
    ],
    "tractability-small-molecule": [         # split: SM chemical-genetic half
        "prism-compound-activity",
        "prism-crispr-concordance",
        "dependency-predictability",
    ],
    "surface-modality-fit": [                # split: biologics-modality half
        "surface-topology-and-ptm",
        "surfaceome-family-classification",
        "structure-features-static",
        "surface-abundance-density",
        "adc-tce-modality-fit",
    ],
    "on-target-safety-liability": [
        "gnomad-lof-constraint",
    ],
}


# --- Subtype tier (verdict-affecting, opt-in via --subtypes) ----------------
# The subtype sub-result is CONDITIONAL: it only enters sub_results when a
# subtype scope is requested. This preserves exact backward-compat — no
# --subtypes → sub_results is byte-identical to before → gate unchanged. It
# implements the design's "subtype channel terminal WHEN Scope.subtypes
# populated" as opt-in-by-scope.
SUBTYPE_SHORT = "subtype_fit"
SUBTYPE_CARDS = [
    "subgroup-stratified-dependency",
    "subgroup-stratified-mutation-frequency",
]


def _subtype_verdict(fired: list[dict]) -> tuple[str, str | None] | None:
    """Verdict producer for the subtype tier. NEGATIVE-SELECTION only.

    Fires the verdict that the nomination gate maps to `hold` iff a subtype-tier
    rule fired (the subtype-non-dependence-opposing rule, which only matches a
    MEASURED, floor-cleared, not-dependent stratum — an underpowered row cannot
    match, so admissibility is enforced upstream at rule-fire time). Returns None
    when no subtype rule fired — a POSITIVE/absent subtype finding produces no
    verdict, so it can never inflate a nomination (gate is one-directional).
    """
    subtype_hits = [f for f in fired
                    if f.get("tier") == "subtype"
                    and "opposing" in (f.get("signals") or {}).get("subtype_fit_genomic", "")]
    if not subtype_hits:
        return None
    # Name the driving rule + the matched stratum for provenance.
    hit = subtype_hits[0]
    return ("subtype_specific_non_dependence", hit.get("rule_id"))


def _run_sub_skills(target: str, indication: str,
                    subtypes: Optional[list[str]] = None) -> dict:
    """Invoke each sub-skill's verdict logic in-process. Returns dict keyed
    by short name (`expression`, `selectivity`, ...) with:
      - `skill_dir`
      - `cards`: card_outputs from resolve_cards
      - `fired`: fired-rules list
      - `verdict`: (verdict_str, driving_rule_id) tuple or None if the
        sub-skill doesn't expose a verdict function (e.g. patient-
        population-and-access has no rules; verdict is None)
    """
    # Fire BOTH rule axes and merge. load_interpretation_rules loads exactly
    # one axis file, so a sub-skill whose cards span axes (surface-modality-fit
    # fires surface_intrinsic; most others fire intracellular_intrinsic) would
    # otherwise silently fire nothing on the un-loaded axis. filter_by_card_ids
    # scopes each axis's rules to the sub-skill's cards, so firing both is safe
    # (no cross-contamination) and card-correct regardless of which file a
    # card's rules live in. (Fixed 2026-07-14 when the tractability split first
    # made a surface-only sub-skill a peer in the composer.)
    axes = ("intracellular_intrinsic", "surface_intrinsic")
    results: dict = {}
    for skill_dir, short in SUB_SKILLS:
        cards = resolve_cards(SUB_SKILL_CARDS[skill_dir], target, indication)
        fired: list[dict] = []
        for axis in axes:
            fired.extend(fired_rules(cards, axis=axis,
                                     card_id_filter=SUB_SKILL_CARDS[skill_dir]))
        verdict_fn = _load_sub_skill_verdict_fn(skill_dir)
        verdict_pair = verdict_fn(fired) if verdict_fn else None
        results[short] = {
            "skill_dir": skill_dir,
            "cards": cards,
            "fired": fired,
            "verdict": verdict_pair,  # (str, driving_rule_id) or None
        }

    # Subtype tier — ONLY when a subtype scope was requested. Panorama cards need
    # the resolved strata + assignments shard threaded via subgroup_context; the
    # subtype rule fires in_record on measured, floor-cleared, not-dependent rows.
    if subtypes:
        subgroup_context = {"resolved_strata_ids": list(subtypes),
                            "catalog_status": "resolved_active"}
        sub_cards = resolve_cards(SUBTYPE_CARDS, target, indication,
                                  subgroup_context=subgroup_context)
        sub_fired: list[dict] = []
        for axis in axes:
            sub_fired.extend(fired_rules(sub_cards, axis=axis,
                                         card_id_filter=SUBTYPE_CARDS))
        results[SUBTYPE_SHORT] = {
            "skill_dir": None,             # not a directory sub-skill; composed inline
            "cards": sub_cards,
            "fired": sub_fired,
            "verdict": _subtype_verdict(sub_fired),
            "scope_subtypes": list(subtypes),
        }
    return results


# --- Deterministic recommendation gate --------------------------------------
#
# The overall_recommendation was historically 100% LLM-chosen (the LLM saw the
# sub-verdicts as prompt text and picked nominate|hold|veto|insufficient_evidence).
# A killer sub-verdict must FORCE the call, not merely suggest it. This gate
# mirrors compose-dashboard/_synthesis.py's killer short-circuit (killers → not_viable
# first, before any positive logic), reimplemented on target-profile's sub-verdict
# tuples (the two engines take different inputs — card interpretation_calls vs.
# skill verdict strings — so the pattern is copied, not the code; sharing them is
# the separate two-engine-unification effort).
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
}
# Precedence when multiple gates fire: veto dominates hold.
_GATE_ACTION_RANK = {"veto": 2, "hold": 1}

_CONTRACTS_REPO = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)


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

    present = {(short, (r.get("verdict") or [None])[0]) for short, r in sub_results.items()}
    survivors: list[dict] = []
    suppressions: list[dict] = []
    for h in hits:
        key = (h["short"], h["verdict"])
        suppressed_by = None
        # (A) context-escape
        for s in ctx_supps:
            sup = s.get("suppresses", {})
            if (sup.get("sub_skill"), sup.get("verdict")) != key:
                continue
            trigger = next((w for w in s.get("when_present", [])
                            if (w["sub_skill"], w["verdict"]) in present), None)
            if trigger:
                suppressed_by = {"kind": "context_escape",
                                 "trigger": f"{trigger['sub_skill']}:{trigger['verdict']}"}
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
        if not v:
            continue
        verdict_str, driving_rule_id = v[0], (v[1] if len(v) > 1 else None)
        action = gate_verdicts.get((short, verdict_str))
        if action:
            hits.append({"short": short, "verdict": verdict_str,
                         "action": action, "driving_rule_id": driving_rule_id,
                         "policy_source": policy_source})
    # v1.2.0: apply veto suppression (context-escape + modality-scoped) before
    # resolving the forced action. A suppressed veto does not force — but is recorded.
    hits, suppressions = _suppressed_gate_hits(hits, sub_results, modality, contracts_repo)
    if not hits:
        return None, [], suppressions
    forced = max((h["action"] for h in hits), key=lambda a: _GATE_ACTION_RANK[a])
    return forced, hits, suppressions


# --- Deciding-axis router (L / KNOWN_TARGET_FRAMEWORK_REFRAMES Reframe 3) -----
#
# Turns a bare `insufficient_evidence` into a ROUTING statement: which gate is load-bearing
# for THIS run, and whether the framework can evidence it. HONESTY GUARDRAIL (Reframe 3 lines
# 103-106): this does NOT predict which gate WILL decide a target prospectively ("a mis-route
# fails more confidently than a portrait"). It only REPORTS, from the run's actual sub-verdicts:
#   - gate FIRED (veto/hold)  → the firing gate IS the deciding axis (known, not predicted);
#                               framework_can_evidence = captured (we evidenced it → it fired).
#   - abstaining (no gate)    → list the NECESSITY gates we could not evidence + their standing
#                               ("we can't decide because gates X,Y are the ones we're blind on").
#   - positive (no gate)      → the strongest positive dimension is the load-bearing axis.
# The gate_coverage.yaml baseline is the STATIC standing; the router DOWNGRADES it per-run to
# `blind`/`data_blocked` when a gate's own cards came back missing, and never upgrades past it.
_COVERAGE_RANK = {"captured": 3, "partial": 2, "license_blocked": 1, "blind": 0, "out_of_scope": 0}


def _load_gate_coverage(contracts_repo: Path | None = None) -> tuple[dict, str]:
    """Load the per-short gate_coverage map from the target-contracts vocab. Returns
    ({short: {gate, gate_name, band, framework_can_evidence, ...}}, source). EMPTY-on-failure
    (source='none'): the router then degrades to a bare abstention note rather than fabricating
    a coverage claim — a missing map must never invent a `captured`."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "gate_coverage.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        by_short = {g["short"]: g for g in data["gates"]}
        if not by_short:
            raise ValueError("empty gates list")
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


def _deciding_axis(sub_results: dict, gate_action: Optional[str],
                   gate_hits: list[dict], positive_hits: list[dict],
                   contracts_repo: Path | None = None) -> dict:
    """Build the deciding_axis block (see module comment above). Deterministic; never predicts."""
    baseline, source = _load_gate_coverage(contracts_repo)

    def _row(short: str) -> dict:
        b = baseline.get(short, {})
        return {
            "short": short,
            "gate": b.get("gate"),
            "gate_name": b.get("gate_name"),
            "band": b.get("band"),
            "framework_can_evidence": _run_coverage_for_short(short, sub_results.get(short, {}), baseline),
        }

    # (1) A gate FIRED → the deciding axis is KNOWN (the firing gate). captured by definition.
    if gate_action and gate_hits:
        top = gate_hits[0]["short"]
        row = _row(top)
        row["framework_can_evidence"] = "captured"   # it fired → we evidenced it
        return {"basis": "gate_fired", "coverage_source": source,
                "deciding_axis": row,
                "routing": f"decided by gate {row.get('gate')} ({row.get('gate_name')}): "
                           f"{top} forced '{gate_action}'."}

    # (2) A positive tier exists → the load-bearing axis is the strongest positive dimension.
    if positive_hits:
        shorts = sorted({h["short"] for h in positive_hits})
        rows = [_row(s) for s in shorts]
        return {"basis": "positive_signal", "coverage_source": source,
                "deciding_axes": rows,
                "routing": f"supported by {', '.join(shorts)} (necessity biology evidenced)."}

    # (3) Abstaining → report the NECESSITY gates we could NOT evidence this run + their standing.
    # This is the routing instruction: "the decision lives in a gate we're blind on."
    unevidenced = []
    for short, r in sub_results.items():
        if short not in baseline:
            continue
        if not _sub_result_has_signal(r):
            unevidenced.append(_row(short))
    # necessity first, then by weakest coverage (blind before partial) — the gates most likely
    # to be the reason we can't decide.
    unevidenced.sort(key=lambda x: (x.get("band") != "necessity",
                                    _COVERAGE_RANK.get(x.get("framework_can_evidence"), 0)))
    return {"basis": "abstention_coverage_gaps", "coverage_source": source,
            "unevidenced_gates": unevidenced,
            "routing": ("cannot decide from framework evidence; unevidenced gates (necessity "
                        "first): " + ", ".join(
                            f"{g['short']}[{g.get('gate')}/{g.get('framework_can_evidence')}]"
                            for g in unevidenced) if unevidenced else
                        "cannot decide; no gate produced a signal and no coverage map available.")}


# --- Ordinal matrix VIEW (gap #3 "now" / gap #4 demo) ------------------------
#
# A gate × modality signal matrix, projected onto the ordinal scale for DISPLAY + RANKING.
# This is the "evidence matrix" made concrete for a single (target, indication) run: rows = the
# gates (sub-skills), columns = the 5 delivery modalities, cells = the strongest signal that
# gate's fired rules emit for that modality, shown as its ordinal.
#
# HONESTY (ordinal_view module contract): this is a labeled VIEW, NOT measurement and NOT a
# verdict input. It reads already-resolved fired-rule signals and never feeds back into any
# rule/resolver/gate. insufficient/not_applicable cells are off-scale (coverage), not low scores.
_MATRIX_MODALITIES = ("small_molecule", "degrader", "adc", "bite_tce", "antibody")


def _strongest_signal_for_modality(fired: list[dict], modality: str) -> Optional[str]:
    """The most-decisive signal a gate's fired rules emit for one modality channel. 'Most
    decisive' = lowest ordinal (killer < opposing < neutral < supportive); off-scale
    (insufficient/not_applicable) only when NO on-scale signal was emitted. Mirrors the
    display convention that a killer dominates a co-fired supportive in the same cell."""
    on_scale: list[tuple[int, str]] = []
    off_scale: Optional[str] = None
    for r in fired:
        sig = (r.get("signals") or {}).get(modality)
        if sig is None:
            continue
        o = ordinal_view.ordinal_of(sig)
        if o is None:
            off_scale = off_scale or sig      # remember an off-scale signal as a fallback
        else:
            on_scale.append((o, sig))
    if on_scale:
        return min(on_scale, key=lambda t: t[0])[1]   # most-negative wins the cell
    return off_scale                                   # else an off-scale coverage marker (or None)


def _ordinal_matrix(sub_results: dict) -> dict:
    """Build the gate × modality ordinal-view matrix for this run (see section comment).
    Returns {rows: [{short, gate signals+ordinals per modality}], legend, _disclaimer}."""
    rows = []
    for short, r in sub_results.items():
        fired = r.get("fired") or []
        by_mod = {m: _strongest_signal_for_modality(fired, m) for m in _MATRIX_MODALITIES}
        view = ordinal_view.project_signals(by_mod)
        rows.append({
            "short": short,
            "verdict": (r.get("verdict") or [None])[0],
            "cells": view["cells"],          # {modality: {signal, ordinal, on_scale}}
        })
    return {
        "axes": {"rows": "gate (sub-skill)", "columns": list(_MATRIX_MODALITIES),
                 "cell": "strongest signal for (gate, modality), ordinal-projected"},
        "rows": rows,
        "legend": ordinal_view.scale_legend(),
        "_disclaimer": ordinal_view.scale_legend()["_disclaimer"],
    }


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


def _load_positive_signals(contracts_repo: Path | None = None) -> tuple[dict, set, dict, str]:
    """Load the positive-tier policy. Returns
    (positive_map: {(short,verdict): weight}, contradiction_set: {(short,verdict)},
     config: dict, source). EMPTY-on-failure (never permissive)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        pos = {(p["sub_skill"], p["verdict"]): p["weight"] for p in data["positive_signals"]}
        contra = {(c["sub_skill"], c["verdict"]) for c in data["positive_contradictions"]}
        cfg = data["positive_tier_config"]
        if not pos:
            raise ValueError("empty positive_signals")
        return pos, contra, cfg, "vocab"
    except Exception as e:  # noqa: BLE001 — any failure → EMPTY (no positive tier)
        print(f"[target-profile] WARN: could not load positive_signals vocab "
              f"({type(e).__name__}: {e}); positive tier DISABLED (LLM confidence stands).",
              file=sys.stderr)
        return {}, set(), {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True}, "fallback"


def _positive_tier(
    sub_results: dict, contracts_repo: Path | None = None
) -> tuple[Optional[str], list[dict]]:
    """Deterministic confidence tier from graded positive sub-verdicts.

    Returns (tier | None, hits). tier ∈ {strong, moderate}. None = no positive
    signal (LLM confidence stands). MUST be called only when no kill fired (caller
    guards this) — but it is also self-safe: it reads only positive_signals and
    never emits an action. A contradiction (opposing MEASURED verdict on a
    positive-eligible axis) blocks `strong`. insufficient/data_unavailable are NOT
    contradictions (measured-vs-null).
    """
    pos_map, contra_set, cfg, _src = _load_positive_signals(contracts_repo)
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
    n_dims = len({h["short"] for h in hits})
    has_dominant = any(h["weight"] == "dominant" for h in hits)
    min_dims = cfg.get("min_dimensions_for_strong", 2)
    require_dom = cfg.get("require_dominant_for_strong", True)
    strong_ok = (n_dims >= min_dims and (has_dominant or not require_dom)
                 and not contradicted)
    tier = "strong" if strong_ok else "moderate"
    return tier, hits


# --- LLM synthesis ----------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are synthesizing a target-profile summary for a drug-discovery "
    "scientist at a major pharma. You will be given deterministic, rule-"
    "derived sub-verdicts from up to 10 evidence dimensions (expression, "
    "selectivity, dependency, mechanism, mutation, differentiation, "
    "tractability, safety, population, cohort_rank). Your job is to (a) "
    "write a concise executive summary, (b) surface any tension across "
    "the sub-verdicts, (c) list top arguments for and against pursuing "
    "this target, and (d) recommend a nomination action. Base every "
    "claim on the provided evidence. Do NOT invent biology. If evidence "
    "is thin or missing for a dimension, say so explicitly rather than "
    "filling with generalities. Note (arch A2): the tractability sub-"
    "verdict emits letter grades (adc_grade, tce_grade) ONLY when the "
    "modality lens was invoked at runtime — if those fields are absent, "
    "reason from the biology-agnostic fit_class categorical instead. "
    "Note (arch A3): the mechanism sub-verdict flags isoform-selective "
    "targets (e.g., ERBB2/p95HER2, AR/AR-V7, MET/exon14, EGFR/vIII); if "
    "isoform_selective_warning is true, gene-level modality claims should "
    "be qualified with isoform-resolution caveats. "
    "Note (matrix view): you are also given a modality-scoped evidence matrix "
    "(gate x modality). It is a REPROJECTION of the same signals, NOT new "
    "evidence and NOT a score — use it to reason about WHICH MODALITY each gate "
    "favors (e.g. a degrader-preferred vs small-molecule split) and to ground the "
    "modality framing of your recommendation. The ordinals are order-preserving, "
    "NOT calibrated: never sum or average them, and treat off-scale cells "
    "(insufficient/not_applicable) as coverage gaps, not low scores. When a matrix "
    "cell disagrees with a gate's resolved verdict, the VERDICT is the decision — "
    "the cell is the raw per-modality signal behind it."
)


def _build_synthesis_tool() -> dict:
    """Tool schema for the LLM synthesis call. Enums are the audit-critical
    fields — LLM cannot free-form the recommendation."""
    return {
        "description": (
            "Emit a structured target-profile summary composed of one "
            "executive summary paragraph, tension analysis, top "
            "arguments for/against, and an overall recommendation."
        ),
        "type": "object",
        "required": [
            "executive_summary", "tension_analysis",
            "top_arguments_for", "top_arguments_against",
            "overall_recommendation", "confidence",
        ],
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": (
                    "3-5 sentence synthesis of what the (up to 10) sub-verdicts "
                    "collectively imply for this (target, indication)."
                ),
            },
            "tension_analysis": {
                "type": "string",
                "description": (
                    "Where sub-verdicts disagree and why — e.g. tumor-"
                    "selectivity says discordant while functional-"
                    "requirement says lineage_selective. If there's no "
                    "meaningful tension, say so briefly (do not invent)."
                ),
            },
            "top_arguments_for": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest positive arguments.",
            },
            "top_arguments_against": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest negative arguments.",
            },
            "overall_recommendation": {
                "type": "string",
                "enum": ["nominate", "hold", "veto", "insufficient_evidence"],
                "description": (
                    "Nomination action: nominate = pursue; hold = "
                    "revisit after specific evidence gaps close; veto = "
                    "do not pursue; insufficient_evidence = cannot call."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "insufficient"],
                "description": (
                    "Analyst-facing confidence in the recommendation. "
                    "'insufficient' iff overall_recommendation is "
                    "insufficient_evidence."
                ),
            },
        },
    }


def _render_matrix_slice_for_prompt(ordinal_matrix: dict) -> list[str]:
    """The gate × modality ordinal matrix as prompt text (gap #4b): lets synthesis reason over
    the MATRIX-SLICE (which modality does each gate favor?) instead of only the flat verdict list.
    Emphatically labeled a REPROJECTION of the same signals — not new evidence, not a score."""
    cols = ordinal_matrix["axes"]["columns"]
    leg = ordinal_matrix["legend"]
    lines = [
        "### Modality-scoped evidence matrix (a VIEW — reprojection, NOT new evidence)",
        "Each cell is the STRONGEST signal a gate emits for that modality, on an ORDER-PRESERVING "
        "ordinal scale (NOT calibrated — gaps are not metric). Use it to see WHICH MODALITY each "
        "gate favors (e.g. a degrader-preferred vs small-molecule-opposing split) — a nuance the "
        "flat verdict list flattens. A cell can differ from the resolved verdict (the cell is the "
        "raw signal; the verdict is the ordered-precedence decision). The verdict is the decision; "
        "the matrix is for modality reasoning only. Do NOT sum or average the ordinals.",
        "Scale: " + ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(),
                                                               key=lambda t: -t[1]))
        + f"; off-scale (coverage, not a low score): {', '.join(leg['off_scale'])}; `·` = no signal.",
        "",
        "| gate | " + " | ".join(cols) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]
    for row in ordinal_matrix["rows"]:
        cells = row["cells"]
        glyphs = " | ".join(ordinal_view._cell_glyph(cells[m]) for m in cols)
        lines.append(f"| {row['short']} | {glyphs} |")
    lines.append("")
    return lines


def _build_user_prompt(
    target: str,
    indication: str,
    sub_results: dict,
    modality: Optional[str] = None,
    therapeutic_hypothesis: Optional[str] = None,
    ordinal_matrix: Optional[dict] = None,
) -> str:
    """Compose the user-message text: sub-verdicts + modality-scoped matrix slice + card
    summaries + optional lens context."""
    lines = [
        f"Target: {target}",
        f"Indication: {indication}",
    ]
    if modality:
        lines.append(f"Modality lens (post-hoc, reweight narrative): {modality}")
    if therapeutic_hypothesis:
        lines.append(f"Therapeutic hypothesis (post-hoc, reweight narrative): "
                     f"{therapeutic_hypothesis}")
    lines.append("")
    lines.append("### Sub-verdicts (deterministic, rule-fired)")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"no rule-fired verdict (skill relies on raw metrics)")
        else:
            verdict_str, driving_rule = v
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"`{verdict_str}` (driving rule: {driving_rule})")
    lines.append("")
    if ordinal_matrix is not None:
        lines.extend(_render_matrix_slice_for_prompt(ordinal_matrix))
    lines.append("### Card summaries (raw, per-card)")
    for short, r in sub_results.items():
        lines.append(f"\n#### {short} ({r['skill_dir']})")
        for c in r["cards"]:
            cid = c["card_id"]
            if c.get("_missing"):
                lines.append(f"- {cid}: MISSING (no dispatcher)")
                continue
            summary = c.get("summary") or {}
            # Strip out oversized nested lists; keep scalars + short lists.
            trimmed = {}
            for k, v in summary.items():
                if k.startswith("_"):
                    continue
                if isinstance(v, list) and len(v) > 5:
                    trimmed[f"{k}_len"] = len(v)
                    trimmed[f"{k}_sample"] = v[:3]
                else:
                    trimmed[k] = v
            lines.append(f"- {cid}: {json.dumps(trimmed, default=str)[:1200]}")
    lines.append("")
    lines.append("### Fired rules (across all sub-skills, biology-first)")
    for short, r in sub_results.items():
        for f in r["fired"]:
            lines.append(f"- [{short}] {f['rule_id']} on "
                         f"{f['card_id']}.{f['field']} = {f['value']}")
    return "\n".join(lines)


# --- Rendering --------------------------------------------------------------

# --- Per-phase evidence rows -----------------------------------------------
# For each sub-skill's "short" key, name the 2-4 key metric fields to inline
# in the per-phase evidence table. Field names must match those actually
# exposed by each sub-skill's underlying card summaries (audited empirically).
PHASE_METRIC_FIELDS: dict[str, list[tuple[str, str]]] = {
    "expression": [
        ("median_log2tpm_panel",    "median log2TPM (pan-cancer)"),
        ("fraction_expressed",       "fraction expressed"),
        ("log2_fc",                  "log2FC tumor vs adj"),
        ("q_value",                  "q-value (tumor vs adj)"),
    ],
    "selectivity": [
        ("cells_supporting",         "cells supporting"),
        ("cells_ran",                "cells ran"),
        ("dominant_direction",       "dominant direction"),
        ("max_abs_log2fc",           "max |log2FC|"),
        ("discordant",               "discordant"),
    ],
    "dependency": [
        ("median_chronos_indication", "median CRISPR score"),
        ("pct_dependent_indication",  "pct cell lines dependent"),
        ("lineage_selectivity_class", "lineage selectivity"),
        ("concordance_class",         "CRISPR-RNAi concordance"),
    ],
    # Keys MUST match SUB_SKILLS shorts (run.py:65) or the per-phase evidence table
    # silently doesn't render (PHASE_METRIC_FIELDS.get(short, []) misses). Fixed
    # 2026-07-17: `mutation`→`genomic_alteration`, `tractability`→`tractability_sm`
    # (renamed in the 2026-07-14 restructure but this dict was missed — same
    # rename-drift class as the _risk_by_category fix); `population` DROPPED (skill
    # deleted, prevalence folded into genomic_alteration).
    "genomic_alteration": [
        ("mutation_landscape_class",      "landscape class"),
        ("mutation_stratification_class", "stratification class"),
        ("copy_number_class",             "copy-number class"),
        ("overall_mutation_frequency",    "cohort mutation frequency (indication)"),
    ],
    "tractability_sm": [
        ("prism_activity_class",            "PRISM activity class"),
        ("crispr_prism_concordance_class",  "PRISM-CRISPR concordance"),
        ("predictability_class",            "predictability"),
    ],
}


def _first_card_summary_field(sub_result: dict, field: str):
    """Search each card in the sub-result for a summary field; return the
    first non-None value found. Cards each expose different summary shapes,
    so a targeted search is more robust than positional assumption."""
    for c in sub_result.get("cards") or []:
        s = (c.get("summary") or {})
        if field in s and s[field] is not None:
            return s[field]
    return None


def _fmt_metric(value):
    """Human-render a metric value for the markdown table."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if abs(value) < 1e-3 or abs(value) >= 1e6:
            return f"{value:.3g}"
        return f"{value:.3f}"
    if isinstance(value, int):
        return str(value)
    s = str(value)
    return s if len(s) <= 60 else s[:57] + "..."


def _risk_by_category_from_sub_verdicts(sub_results: dict) -> list[tuple[str, str, str]]:
    """Map sub-verdicts onto the 6-category risk framing (biological /
    druggability / translational / clinical / safety / commercial),
    producing (category, level, driver) triples. Categories with no
    wired coverage return level=insufficient_evidence — honest coverage
    signal for governance readers used to the 6-category shape.

    This is a NON-LLM mapping — deterministic reshape of the deterministic
    sub-verdicts. The v1 risk-assessment framing lives here as an output
    convention, not as a re-derivation via literature.
    """
    def _v(short):
        r = sub_results.get(short) or {}
        v = r.get("verdict")
        return v if v else (None, None)

    exp_v, exp_r = _v("expression")
    sel_v, sel_r = _v("selectivity")
    dep_v, dep_r = _v("dependency")
    # Short keys MUST match SUB_SKILLS (run.py:65). Fixed 2026-07-17: the
    # 2026-07-14 restructure renamed these two shorts (mutation→genomic_alteration,
    # tractability→tractability_sm) but this reshape wasn't updated, so _v() silently
    # returned (None,None) — druggability was dead-wired to insufficient_evidence and
    # the mutation signal was dropped from _biological(). A display bug (this feeds the
    # 6-category render table, not the gate), but a real one.
    mut_v, mut_r = _v("genomic_alteration")
    trk_v, trk_r = _v("tractability_sm")
    saf_v, saf_r = _v("safety")

    # Biological: strongest positive across A/B/C/mut wins
    # Simple mapping: at least one strong-supportive → LOW risk; not_selective
    # or non_dependent → HIGH; discordant / not_informative → MEDIUM
    def _biological():
        signals = [exp_v, sel_v, dep_v, mut_v]
        if any(s in ("strong_tumor_selective", "concordant_dependent",
                      "biomarker_stratified_dependency",
                      "broadly_high_expression") for s in signals):
            return "LOW", "strong support across A/B/C/mut sub-verdicts"
        if any(s in ("not_selective", "non_dependent",
                      "broadly_low_expression") for s in signals):
            return "HIGH", "negative signal in A/B/C sub-verdicts"
        if any(s == "discordant_across_comparators" for s in signals):
            return "MEDIUM", "comparator-dependent expression/selectivity signal"
        if all(s in (None, "insufficient", "not_informative") for s in signals):
            return "insufficient_evidence", "no rule-fired verdicts across A/B/C"
        return "MEDIUM", "mixed signals across A/B/C"

    def _druggability():
        if trk_v in ("well_covered", "chemically_confirmed_genetic"):
            return "LOW", trk_r or "PRISM-CRISPR triangulated"
        if trk_v in ("chemically_active",):
            return "LOW-MEDIUM", trk_r or "clinically-active compounds"
        if trk_v in ("tool_compound_only", "weakly_active"):
            return "MEDIUM-HIGH", trk_r or "tool compounds only"
        if trk_v in ("chemically_unhit", "discordant"):
            return "HIGH", trk_r or "no compound hits or discordant"
        return "insufficient_evidence", "tractability sub-verdict absent"

    def _safety():
        # on-target-safety-liability IS wired (gnomAD LoF-constraint). Fixed
        # 2026-07-17: this row was hardcoded insufficient_evidence with a stale
        # "gnomAD cards not wired" note, contradicting the wired safety sub-skill
        # that already feeds the nomination gate. Map its verdict here too.
        # Higher germline constraint → higher on-target (full-KO) safety RISK.
        if saf_v == "highly_constrained_safety_concern":
            return "HIGH", saf_r or "highly LoF-constrained gene (full-KO liability)"
        if saf_v == "moderately_constrained_safety":   # C2c: middle band → MEDIUM
            return "MEDIUM", saf_r or "moderately LoF-constrained gene (equivocal safety)"
        if saf_v == "tolerant_reduced_safety_risk":
            return "LOW", saf_r or "LoF-tolerant gene (reduced full-KO liability)"
        return "insufficient_evidence", "gnomAD constraint sub-verdict absent"

    # For phases we still have no wired data on, report insufficient_evidence
    # honestly rather than fabricate:
    return [
        ("biological",   *_biological()),
        ("druggability", *_druggability()),
        ("translational", "insufficient_evidence",
            "Phase-J (translational-readiness) placeholder — data not wired"),
        ("clinical",      "insufficient_evidence",
            "Phase-E (clinical precedent) placeholder — data feed not wired"),
        ("safety",        *_safety()),
        ("commercial",    "insufficient_evidence",
            "Phase-E (competitive/IP) placeholder — Cortellis/IQVIA not licensed"),
    ]


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
                    contracts_repo: Path | None = None) -> list[dict]:
    """Build the 8-gate scorecard rows. Rows come from the gate_coverage REGISTRY (not from
    iterating sub_results), so gates we're blind on this run still render as greyed rows. Status
    reuses the nomination-gate policy so it cannot diverge from the deterministic verdict."""
    baseline, _ = _load_gate_coverage(contracts_repo)
    kill_map, _ = _load_gate_verdicts(contracts_repo)          # {(short,verdict): action}
    positive_map, contradictions, _, _ = _load_positive_signals(contracts_repo)
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
    # Registry order = gate letter A..H. gate_coverage rows carry gate/gate_name/band.
    for short, meta in baseline.items():
        r = sub_results.get(short) or {}
        v = r.get("verdict")
        verdict_str = v[0] if v else None
        driving = v[1] if (v and len(v) > 1) else None
        rows.append({
            "short": short,
            "gate": meta.get("gate"),
            "gate_name": meta.get("gate_name"),
            "band": meta.get("band"),
            "verdict": verdict_str,
            "driving_rule_id": driving,
            "status": _status(short, verdict_str),
            "framework_can_evidence": _run_coverage_for_short(short, r, baseline),
            "is_deciding": short == deciding_short,
        })
    # Sort by gate letter (A..H), then band (necessity first) as a stable tiebreak.
    rows.sort(key=lambda x: (str(x.get("gate") or "Z"), x.get("band") != "necessity"))
    return rows


def _render_target_profile_md(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    composite_figure_relpath: Optional[str] = None,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
) -> str:
    """Render target_profile.md with clearly-tagged LLM sections + per-phase
    evidence tables + risk-by-category summary + deciding-axis routing + the
    ordinal evidence matrix + embedded composite figure. deciding_axis + ordinal_matrix
    are DETERMINISTIC (not LLM) — surfaced so a human reader sees the same routing +
    modality view that land in nomination.json, not only the LLM narrative."""
    lines = [
        f"# Target profile — {target} in {indication}",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if invoked_lenses:
        lines.append(f"Invoked lenses: `{invoked_lenses}`")
    lines.append("")

    # --- Composite figure (Shape C) ----------------------------------------
    if composite_figure_relpath:
        lines.append(f"![Target profile at a glance]({composite_figure_relpath})")
        lines.append("")

    # --- Executive summary (LLM) -------------------------------------------
    exec_summary = llm_output.get("executive_summary", {}).get("value", "")
    lines.append("## Executive summary *(LLM-synthesized)*")
    lines.append("")
    lines.append(exec_summary)
    lines.append("")

    # --- Recommendation (LLM) — pulled up front for governance readers -----
    def _val(field: str, default: str = "—") -> str:
        raw = llm_output.get(field)
        if isinstance(raw, dict):
            return str(raw.get("value", default))
        return str(raw) if raw is not None else default

    rec = _val("overall_recommendation")
    conf = _val("confidence")
    lines.append("## Recommendation *(LLM-synthesized, enum-constrained)*")
    lines.append("")
    lines.append(f"- **Action:** `{rec}`")
    lines.append(f"- **Confidence:** `{conf}`")
    lines.append("")

    # --- Deciding axis (deterministic router; reports, never predicts) -----
    if deciding_axis:
        lines.append("## Deciding axis *(deterministic — what the call hinges on)*")
        lines.append("")
        basis = deciding_axis.get("basis")
        lines.append(f"_{deciding_axis.get('routing', '')}_")
        lines.append("")
        if basis == "gate_fired":
            da = deciding_axis.get("deciding_axis", {})
            lines.append(f"- **Load-bearing gate:** {da.get('gate')} ({da.get('gate_name')}) "
                         f"— `{da.get('short')}`")
            lines.append(f"- **Framework coverage of that gate:** `{da.get('framework_can_evidence')}`")
        elif basis == "abstention_coverage_gaps":
            lines.append("The framework cannot decide from its own evidence. Gates it could not "
                         "evidence this run (necessity first — these are the routing targets):")
            lines.append("")
            lines.append("| gate | short | band | framework can evidence |")
            lines.append("|---|---|---|---|")
            for g in deciding_axis.get("unevidenced_gates", []):
                lines.append(f"| {g.get('gate')} | `{g.get('short')}` | {g.get('band')} "
                             f"| `{g.get('framework_can_evidence')}` |")
        elif basis == "positive_signal":
            axes = ", ".join(f"`{r.get('short')}`" for r in deciding_axis.get("deciding_axes", []))
            lines.append(f"- **Supporting axes (necessity biology evidenced):** {axes}")
        lines.append("")

    # --- Risk-by-category summary (deterministic, from sub-verdicts) -------
    lines.append("## Risk-by-category summary *(deterministic reshape "
                 "of sub-verdicts)*")
    lines.append("")
    lines.append("Governance-facing 6-category framing mapped from the rule-"
                 "fired sub-verdicts below. Categories with no wired data "
                 "return `insufficient_evidence` rather than fabricated risk "
                 "levels.")
    lines.append("")
    lines.append("| Category | Risk level | Driver |")
    lines.append("|---|---|---|")
    for cat, level, driver in _risk_by_category_from_sub_verdicts(sub_results):
        lines.append(f"| **{cat}** | `{level}` | {driver} |")
    lines.append("")

    # --- Tension analysis (LLM) --------------------------------------------
    tension = llm_output.get("tension_analysis", {}).get("value", "")
    lines.append("## Tension analysis *(LLM-synthesized)*")
    lines.append("")
    lines.append(tension)
    lines.append("")

    # --- Sub-verdicts (rule-fired) -----------------------------------------
    lines.append("## Sub-verdicts *(deterministic, rule-fired)*")
    lines.append("")
    lines.append("| Dimension | Verdict | Driving rule |")
    lines.append("|---|---|---|")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"| {short} | — | (raw metrics; no rule verdict) |")
        else:
            verdict_str, driving_rule = v
            lines.append(f"| {short} | `{verdict_str}` | `{driving_rule}` |")
    lines.append("")

    # --- Ordinal evidence matrix (deterministic VIEW; gate × modality) -----
    if ordinal_matrix:
        cols = ordinal_matrix["axes"]["columns"]
        leg = ordinal_matrix["legend"]
        lines.append("## Modality-scoped evidence matrix *(deterministic VIEW — not a score)*")
        lines.append("")
        lines.append(f"> {ordinal_matrix.get('_disclaimer', '')}")
        lines.append("")
        lines.append("| gate | " + " | ".join(cols) + " | verdict |")
        lines.append("|" + "---|" * (len(cols) + 2))
        for row in ordinal_matrix["rows"]:
            cells = row["cells"]
            glyphs = " | ".join(ordinal_view._cell_glyph(cells[m]) for m in cols)
            lines.append(f"| {row['short']} | {glyphs} | {row.get('verdict') or '—'} |")
        on = ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(), key=lambda t: -t[1]))
        lines.append("")
        lines.append(f"_Scale (order-preserving, NOT metric): {on}; off-scale (coverage, not a "
                     f"low score): {', '.join(leg['off_scale'])} (`insf`/`n/a`); `·` = no signal. "
                     f"A cell shows the strongest raw signal for that (gate, modality); when it "
                     f"differs from the resolved verdict, the verdict is the decision._")
        lines.append("")

    # --- Per-phase evidence tables (Shape A enrichment) --------------------
    lines.append("## Per-phase evidence *(deterministic, from card summaries)*")
    lines.append("")
    lines.append("Key metrics inlined from each sub-skill's underlying card "
                 "summaries. Use these to trace a verdict back to its "
                 "supporting data.")
    lines.append("")
    for short, r in sub_results.items():
        fields = PHASE_METRIC_FIELDS.get(short, [])
        if not fields:
            continue
        v = r["verdict"]
        header = f"### {short}"
        if v:
            header += f" — `{v[0]}`"
        lines.append(header)
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|---|---|")
        any_value = False
        for field, label in fields:
            value = _first_card_summary_field(r, field)
            if value is None:
                continue
            lines.append(f"| {label} | `{_fmt_metric(value)}` |")
            any_value = True
        if not any_value:
            lines.append("| (no metrics available) | — |")
        lines.append("")

    # --- Top arguments (LLM) -----------------------------------------------
    for_args = llm_output.get("top_arguments_for", {}).get("value", []) or []
    against_args = llm_output.get("top_arguments_against", {}).get("value", []) or []
    lines.append("## Top arguments *(LLM-synthesized)*")
    lines.append("")
    lines.append("**For:**")
    for a in for_args:
        lines.append(f"- {a}")
    lines.append("")
    lines.append("**Against:**")
    for a in against_args:
        lines.append(f"- {a}")
    lines.append("")

    # --- Provenance footer -------------------------------------------------
    lines.append("---")
    lines.append("")
    lines.append("*LLM-synthesized sections carry `_source: llm_synthesized` "
                 "provenance (see `nomination.json`). Sub-verdicts + "
                 "per-phase evidence + risk-by-category are deterministic "
                 "and reproducible from the same inputs. The composite "
                 "figure is rendered from the same sub-verdicts and can be "
                 "regenerated identically.*")

    return "\n".join(lines)


# ============================================================================
# HTML renderer — static, self-contained governance artifact (2026-07-20)
# ============================================================================
# A projection of the SAME nomination data the .md carries: adds NO computation, NO new LLM
# surface, NO client-side JS (nothing can recompute → the "renderer adds nothing" rule is
# structural). The honesty distinctions become visual STRUCTURE: LLM sections are tinted; the
# 4-state scorecard distinguishes measured-negative (🔴) from coverage-gap (⚪); the ordinal
# matrix carries its "not a score" disclaimer. Colors mirror composite_panel.VERDICT_COLORS +
# the Takeda palette so the page matches the inlined figure.
import html as _html

_HTML_STATUS = {   # 4-state scorecard chip → (glyph, css class, human label)
    "supportive":   ("●", "chip-pos",  "Supports"),
    "neutral":      ("○", "chip-neu",  "Measured — neutral"),
    "opposing":     ("◆", "chip-neg",  "Counts against"),
    "coverage_gap": ("□", "chip-gap",  "Not evaluated"),
}

# --- Plain-English label layer (reader-facing; raw tokens stay in nomination.json) -----------
# The internal vocabulary (verdict strings, gate shorts, coverage terms) leaks jargon to a human
# reader. These maps turn it into plain English for the HTML report. Curated overrides for the
# load-bearing terms; a snake_case→Title-Case fallback for the rest so nothing renders as a raw id.
_GATE_SHORT_LABEL = {
    "expression": "Expression (is it present?)",
    "selectivity": "Tumor selectivity (vs normal)",
    "dependency": "Functional dependency (is it required?)",
    "synthetic_lethal_partners": "Synthetic-lethal partners",
    "mechanism": "Mechanism / mode of action",
    "genomic_alteration": "Genomic alteration",
    "differentiation": "Differentiation (co-mutation)",
    "tractability_sm": "Small-molecule druggability",
    "surface_modality": "Surface / biologics fit",
    "safety": "On-target safety",
    "subtype_fit": "Subtype-specific fit",
}
_COVERAGE_LABEL = {
    "captured": "Well covered",
    "partial": "Partially covered",
    "blind": "Not covered (framework blind)",
    "license_blocked": "License-blocked data",
    "out_of_scope": "Out of scope (Tier-2)",
}
# Plain-English band labels (reader-facing) — the "necessity/sufficiency" jargon is dropped in
# favor of the question each band actually asks.
_BAND_LABEL = {"necessity": "Is it real biology?",
               "sufficiency": "Will it become a drug?"}
# Nomination action → (display term, plain-English gloss). Shown as "Term — gloss" in the header.
_ACTION_GLOSS = {
    "nominate": ("Nominate", "advance this target"),
    "hold": ("Hold", "do not advance yet — a concern must be resolved first"),
    "veto": ("Veto", "do not pursue — a disqualifying finding"),
    "insufficient_evidence": ("Insufficient evidence", "the framework cannot make a call"),
}
# Load-bearing verdict humanizations (the ones a reader most needs unambiguous).
_VERDICT_LABEL = {
    "lineage_selective": "Selective dependency (lineage-restricted)",
    "concordant_dependent": "Strong dependency (CRISPR + RNAi agree)",
    "selective_dependent": "Selective dependency",
    "chemical_genetic_confirmed_dependent": "Dependency confirmed (chemical + genetic)",
    "non_dependent": "Not a dependency (pooled)",
    "pan_essential_killer": "Pan-essential (no therapeutic window)",
    "broadly_dependent": "Broadly dependent",
    "strong_tumor_selective": "Strongly tumor-selective",
    "modest_tumor_selective": "Modestly tumor-selective",
    "not_selective": "Not tumor-selective",
    "discordant_across_comparators": "Discordant across comparators",
    "highly_constrained_safety_concern": "High on-target safety concern",
    "biomarker_stratified_dependency": "Biomarker-stratified dependency",
    "well_covered": "Well-covered by compounds",
    "well_characterized": "Well-characterized mechanism",
    "both_patterns_present": "Co-mutation + mutual-exclusivity present",
    "broadly_moderate_expression": "Broadly moderate expression",
    "has_experimental_sl_partner": "Has an experimental SL partner",
    "insufficient": "Insufficient evidence",
    "data_unavailable": "Data unavailable",
    None: "Not evaluated",
}


def _humanize(token: Optional[str]) -> str:
    """snake_case / lowercase identifier → readable Title Case, with curated overrides."""
    if token is None:
        return "Not evaluated"
    if token in _VERDICT_LABEL:
        return _VERDICT_LABEL[token]
    return str(token).replace("_", " ").replace("-", " ").strip().capitalize()

# CSS design system (dataviz-skill method; Takeda Okabe-Ito palette as the brand parameters).
# Color roles as CSS custom properties. Status chips use VALIDATED constructions — dark status-ink
# on a pale same-hue tint + a glyph + a label (never color-alone) — WCAG 4.8-6.3:1 (computed with
# the dataviz validator, NOT eyeballed; the validator caught that saturated status colors on white
# fail contrast, so chips are tinted backgrounds). The ordinal heatmap uses a DIVERGING blue↔red
# ramp (a magnitude), deliberately distinct from the status chips so the two color languages don't
# collide (dataviz rule: status colors are reserved, never reused as a scale).
_HTML_CSS = """
:root{
  --surface:#ffffff; --surface-2:#f7f9fb; --surface-3:#eef2f6;
  --ink:#141c26; --ink-2:#4a5763; --muted:#6b7783; --line:#e2e8ee; --line-2:#cfd8e0;
  --brand:#0a2540; --brand-accent:#0072B2;                 /* Takeda deep navy + Okabe-Ito blue */
  --pos-ink:#1a6b1a; --pos-bg:#e6f4e6;                      /* status: good */
  --neg-ink:#a1231d; --neg-bg:#fbe6e4;                      /* status: critical */
  --neu-ink:#8a5a00; --neu-bg:#fcf1db;                      /* status: warning */
  --gap-ink:#5b6b7b; --gap-bg:#eef1f4;                      /* coverage gap (hatched) */
  --llm-bg:#f5f2fb; --llm-bd:#d9ccf0; --llm-ink:#5b3fa0;    /* AI-generated section tint */
  --div-p2:#2166ac; --div-p0:#e9eef3; --div-n1:#f4a582; --div-n3:#b2182b;  /* diverging blue↔red */
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
  color:var(--ink);background:var(--surface-3);margin:0;padding:0}
/* Header band — full-bleed; inner content aligned to the same max-width as the shell */
header{background:linear-gradient(100deg,var(--brand),#123a5e);color:#fff;
  padding:24px 40px;border-bottom:3px solid var(--brand-accent)}
header>*{max-width:1560px;margin-left:auto;margin-right:auto}
header h1{font-size:25px;font-weight:650;margin:0;letter-spacing:-.01em;line-height:1.25}
header .rec{font-size:14px;margin-top:10px;opacity:.95;display:flex;flex-wrap:wrap;align-items:center;gap:8px}
header .pill{display:inline-block;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.32);
  border-radius:999px;padding:2px 12px;font-weight:650}
.badge-rule{display:inline-block;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.3);
  border-radius:6px;padding:2px 9px;font-size:12px;font-weight:600;cursor:help}
/* 2-column shell: sticky left nav + content. Wide — uses the full viewport up to a large cap. */
.shell{display:flex;gap:36px;max-width:1560px;margin:0 auto;padding:26px 40px 64px;align-items:flex-start}
nav.toc{position:sticky;top:20px;flex:0 0 220px;font-size:13px;line-height:1.3}
nav.toc .h{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
  font-weight:700;margin:0 0 8px}
nav.toc a{display:block;padding:6px 10px;border-radius:7px;color:var(--ink-2);text-decoration:none;
  border-left:2px solid transparent}
nav.toc a:hover{background:var(--surface);color:var(--brand);border-left-color:var(--brand-accent)}
.content{flex:1 1 auto;min-width:0}
.sub{color:var(--muted);font-size:13px;margin:0 0 10px}
/* Responsive inline SVG — strip matplotlib's fixed pt size, scale to the card (viewBox holds ratio) */
section svg{width:100%!important;height:auto!important;display:block}
/* Section cards */
section{background:var(--surface);border:1px solid var(--line);border-radius:12px;
  padding:18px 20px;margin:0 0 18px;box-shadow:0 1px 2px rgba(20,28,38,.04)}
h2{font-size:16px;font-weight:650;margin:0 0 12px;color:var(--brand);letter-spacing:-.005em}
h2 .n{color:var(--muted);font-weight:500;font-size:13px}
/* Tables */
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{padding:8px 11px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{background:var(--surface-2);font-weight:600;color:var(--ink-2);font-size:12px;
  text-transform:uppercase;letter-spacing:.03em;border-bottom:1.5px solid var(--line-2)}
tr:last-child td{border-bottom:0}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  background:var(--surface-3);padding:1px 5px;border-radius:4px;color:var(--ink-2)}
/* LLM vs deterministic provenance tags */
.llm{background:var(--llm-bg);border:1px solid var(--llm-bd);border-radius:12px;padding:16px 20px;margin:0 0 18px}
.llm h2{color:var(--llm-ink)}
.tag{display:inline-block;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;font-weight:700;
  padding:2px 8px;border-radius:5px;margin-bottom:8px}
.llm .tag{color:var(--llm-ink);background:rgba(91,63,160,.1)}
.det .tag{color:var(--muted);background:var(--surface-3)}
/* Status chips — validated: tinted bg + dark ink + glyph + label */
.chip{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;
  font-size:12px;font-weight:650;white-space:nowrap;line-height:1.3}
.chip .g{font-size:11px}
.chip-pos{background:var(--pos-bg);color:var(--pos-ink)}
.chip-neu{background:var(--neu-bg);color:var(--neu-ink)}
.chip-neg{background:var(--neg-bg);color:var(--neg-ink)}
.chip-gap{background:var(--gap-bg);color:var(--gap-ink);
  background-image:repeating-linear-gradient(45deg,transparent,transparent 5px,rgba(91,107,123,.13) 5px,rgba(91,107,123,.13) 6px)}
/* Scorecard hero */
.scorecard th:first-child,.scorecard td:first-child{text-align:center;font-weight:700;color:var(--brand);width:38px}
.scorecard tr.gate-start td{border-top:2px solid var(--line-2)}
.scorecard tr.deciding{background:#fff9ec}
.scorecard tr.deciding td:first-child{box-shadow:inset 3px 0 0 var(--neu-ink)}
.badge-deciding{display:inline-block;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
  color:var(--neu-ink);background:var(--neu-bg);padding:1px 6px;border-radius:4px;margin-left:6px}
/* Deciding-axis banner */
.banner{background:linear-gradient(90deg,#eef4f8,var(--surface));border-left:4px solid var(--brand-accent);
  padding:12px 16px;border-radius:8px;margin:0 0 12px;font-size:14px}
/* Ordinal matrix heatmap */
.mtx{font-size:12.5px}
.mtx td{text-align:center;font-variant-numeric:tabular-nums;font-weight:600;border:2px solid var(--surface)}
.mtx td:first-child,.mtx td:last-child{text-align:left;font-weight:400;background:var(--surface)!important}
.mtx th{text-align:center}
.mtx .p2{background:var(--div-p2);color:#fff}.mtx .p0{background:var(--div-p0);color:var(--ink-2)}
.mtx .n1{background:var(--div-n1);color:#3a1207}.mtx .n3{background:var(--div-n3);color:#fff}
.mtx .off{background:var(--gap-bg);color:var(--gap-ink);font-style:italic}
.disclaimer{font-size:12px;color:var(--muted);font-style:italic;margin:6px 0}
details{margin-top:10px;border-top:1px solid var(--line);padding-top:10px}
summary{cursor:pointer;font-weight:600;color:var(--ink-2);font-size:13px}
footer{color:var(--muted);font-size:12px;text-align:center;padding-top:8px}
/* Interactive figures (Phase B) */
.plotly-fig{width:100%;min-height:340px;margin:8px 0 4px}
"""


# Vanilla-JS bootstrap: draw every embedded Plotly spec. No framework, DISPLAY-only (Plotly's own
# hover/zoom) — it re-derives NO evidence (honesty spine: light JS renders, never recomputes). Each
# spec rides in a <script type=application/json class=plotly-spec data-target=...> block next to its
# div; we parse + Plotly.newPlot into the target. Responsive; guarded so one bad spec can't blank the
# page.
_PLOTLY_BOOTSTRAP_JS = """<script>
(function(){
  if(typeof Plotly==='undefined')return;
  var specs=document.querySelectorAll('script.plotly-spec');
  for(var i=0;i<specs.length;i++){
    try{
      var el=specs[i], fig=JSON.parse(el.textContent),
          tgt=document.getElementById(el.getAttribute('data-target'));
      if(!tgt)continue;
      (fig.layout=fig.layout||{}).autosize=true;
      Plotly.newPlot(tgt,fig.data,fig.layout,{responsive:true,displaylogo:false,
        modeBarButtonsToRemove:['lasso2d','select2d']});
    }catch(e){if(window.console)console.warn('plotly spec draw failed',e);}
  }
})();
</script>"""


def _esc(x) -> str:
    return _html.escape(str(x if x is not None else "—"), quote=True)


def _inline_svg(svg_path: Optional[Path]) -> Optional[str]:
    """Read an emitted matplotlib SVG (svg.fonttype:none → text-preserving) and return its
    <svg>...</svg> body for inline embedding. Strips the XML/doctype preamble so it drops into
    the page. Returns None on any failure (render never blocks on the figure)."""
    if not svg_path or not Path(svg_path).exists():
        return None
    try:
        raw = Path(svg_path).read_text()
        i = raw.find("<svg")
        if i < 0:
            return None
        body = raw[i:]
        # Strip matplotlib's fixed pt width/height on the root <svg> so it scales to the card
        # (the viewBox preserves the aspect ratio). Belt-and-suspenders with the CSS rule.
        end = body.find(">")
        head, rest = body[:end], body[end:]
        head = re.sub(r'\s(width|height)="[^"]*"', "", head)
        return head + rest
    except Exception:  # noqa: BLE001
        return None


def _mtx_cell_class(cell: dict) -> str:
    if cell.get("signal") is None:
        return ""
    o = cell.get("ordinal")
    if o is None:
        return "off"
    return {2: "p2", 0: "p0", -1: "n1", -3: "n3"}.get(o, "p0")


def _prettify_field(key: str) -> str:
    """A summary-field key → readable label (snake/camel → words)."""
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
    return k[:1].upper() + k[1:]


def _plotly_bundle() -> Optional[str]:
    """The plotly.js source, for INLINING into the self-contained report (no CDN, no external src).
    ~4.6 MB — the deliberate weight of the dynamic dashboard. Cached; None if plotly is absent (the
    report then degrades to static SVG/table). NOTE: an inlined-plotly report is too large for the
    VS Code Simple Browser to render — download + open in a real browser to review it."""
    global _PLOTLY_JS_CACHE
    try:
        return _PLOTLY_JS_CACHE
    except NameError:
        pass
    try:
        from plotly.offline import get_plotlyjs
        _PLOTLY_JS_CACHE = get_plotlyjs()
    except Exception:  # noqa: BLE001
        _PLOTLY_JS_CACHE = None
    return _PLOTLY_JS_CACHE


def _read_card_plotly_specs(card_figures: Optional[dict], figures_dir: Optional[Path],
                            card_id: str) -> list[dict]:
    """For a card, load its interactive Plotly specs (the `dynamic: True` descriptors produced this
    run) from disk. Returns [{id, title, spec_json(str)}], newest-schema-safe. Empty when no dynamic
    figure was produced (→ the card renders its static table only — the fallback)."""
    if not card_figures or not figures_dir:
        return []
    out = []
    for f in card_figures.get(card_id) or []:
        if not f.get("dynamic"):
            continue
        spec_path = figures_dir / f["path"]
        try:
            spec_json = spec_path.read_text()
        except Exception:  # noqa: BLE001 — a missing spec just drops to the static view
            continue
        out.append({"id": f["id"], "spec_json": spec_json})
    return out


def _render_card_data_html(sub_results: dict, card_figures: Optional[dict] = None,
                           figures_dir: Optional[Path] = None) -> tuple[list[str], int]:
    """Per-question 'Evidence' section: render each sub-skill's card SUMMARY metrics (already in
    sub_results from resolve_cards) as clean data, PLUS — when a run produced them (Phase B) —
    the card's interactive Plotly figure(s) embedded inline. Leads with the PHASE_METRIC_FIELDS
    curated key metrics; otherwise shows the card's scalar summary fields.

    Returns (html_lines, n_plotly_embedded). A card with a dynamic spec shows the interactive chart
    above its data table; a card without one shows the table alone (the static fallback). The plot
    is a computed, provenanced artifact (drawn by the method from the same series as the SVG) — the
    renderer only EMBEDS it, never re-plots (honesty spine: renderer adds nothing)."""
    out = ["<section id=s-evidence class=det><span class=tag>Computed from the evidence</span>"
           "<h2>Evidence by question <span class=n>— the card data behind each call</span></h2>"]
    n_plotly = 0
    for short, r in sub_results.items():
        cards = r.get("cards") or []
        # gather scalar summary fields across this sub-skill's cards (skip private _ + nested)
        rows: list[tuple[str, str]] = []
        curated = PHASE_METRIC_FIELDS.get(short, [])
        seen = set()
        for field, label in curated:
            val = _first_card_summary_field(r, field)
            if val is not None:
                rows.append((label, _fmt_metric(val))); seen.add(field)
        for c in cards:
            if c.get("_missing"):
                continue
            for k, v in (c.get("summary") or {}).items():
                if k.startswith("_") or k in seen or isinstance(v, (list, dict)):
                    continue
                rows.append((_prettify_field(k), _fmt_metric(v))); seen.add(k)
        label = _GATE_SHORT_LABEL.get(short, _humanize(short))
        # Interactive figures produced for this sub-skill's cards this run (Phase B). Embedded as a
        # <div> + JSON <script>; the bootstrap at page end calls Plotly.newPlot. Absent → table only.
        plot_divs: list[str] = []
        for c in cards:
            if c.get("_missing"):
                continue
            for spec in _read_card_plotly_specs(card_figures, figures_dir, c.get("card_id")):
                dom_id = f"plt-{short}-{spec['id']}"
                plot_divs.append(
                    f"<div class=plotly-fig id={dom_id}></div>"
                    f"<script type='application/json' class=plotly-spec data-target={dom_id}>"
                    f"{spec['spec_json']}</script>")
                n_plotly += 1
        if not rows and not plot_divs:
            missing = [c["card_id"] for c in cards if c.get("_missing")]
            note = ("no card data (cards not available this run: "
                    + ", ".join(f"<code>{_esc(m)}</code>" for m in missing) + ")") if missing \
                    else "no scalar metrics emitted"
            out.append(f"<details><summary>{_esc(label)}</summary>"
                       f"<p class=sub>{note}.</p></details>")
            continue
        out.append(f"<details open><summary>{_esc(label)}</summary>")
        out.extend(plot_divs)                          # interactive chart(s) lead
        if rows:
            out.append("<table>")
            for lab, val in rows[:18]:   # cap to keep the section scannable
                out.append(f"<tr><td style='color:var(--muted);width:45%'>{_esc(lab)}</td>"
                           f"<td>{_esc(val)}</td></tr>")
            out.append("</table>")
        out.append("</details>")
    out.append("</section>")
    return out, n_plotly


def _render_target_profile_html(
    target: str,
    indication: str,
    sub_results: dict,
    llm_output: dict,
    invoked_lenses: dict,
    deciding_axis: Optional[dict] = None,
    ordinal_matrix: Optional[dict] = None,
    scorecard: Optional[list[dict]] = None,
    composite_svg_path: Optional[Path] = None,
    catalogue_rows: Optional[list[dict]] = None,
    recommendation_gate: Optional[dict] = None,
    show_deciding_axis: bool = False,
    card_figures: Optional[dict] = None,
    figures_dir: Optional[Path] = None,
) -> str:
    """Render a self-contained target_profile.html — the governance artifact. Pure projection of the
    same nomination data the .md carries; no recompute. All structured outputs (scorecard,
    deciding-axis, ordinal matrix) are DETERMINISTIC sections, visually distinct from the
    AI-generated ones.

    DYNAMIC vs STATIC (Phase B): when a run produced per-card interactive figures (`card_figures` +
    `figures_dir`), their Plotly specs are EMBEDDED inline (plotly.js inlined once, a small vanilla-JS
    bootstrap draws them) — the dashboard reads like the GI team's interactive charts while staying a
    single archivable file with zero external deps. When no figure was produced (the default / a
    data-blocked run / plotly absent), the report degrades to the STATIC card tables — same file, no
    JS. The renderer only EMBEDS the method-drawn spec; it never re-plots (honesty spine intact).
    NOTE: an inlined-plotly report is ~4.6 MB and won't render in the VS Code Simple Browser —
    download + open in a real browser to review."""
    def _val(field, default="—"):
        raw = llm_output.get(field)
        return raw.get("value", default) if isinstance(raw, dict) else (raw if raw is not None else default)

    p: list[str] = ["<!DOCTYPE html><html lang=en><head><meta charset=utf-8>",
                    "<meta name=viewport content='width=device-width,initial-scale=1'>",
                    f"<title>Target profile — {_esc(target)} × {_esc(indication)}</title>",
                    f"<style>{_HTML_CSS}</style></head><body>"]

    # --- Header band: title + the headline recommendation ------------------
    action = str(_val("overall_recommendation"))
    term, gloss = _ACTION_GLOSS.get(action, (action, ""))
    action_html = f"<b>{_esc(term)}</b>" + (f" — {_esc(gloss)}" if gloss else "")
    # "Rule-checked" badge: when a deterministic gate overrode the AI's choice, say so on hover.
    rg = recommendation_gate or {}
    if rg.get("fired"):
        forced = rg.get("forced_recommendation", action)
        llm_said = rg.get("llm_recommendation")
        tip = (f"A deterministic safety/quality rule set this call. "
               f"The AI suggested '{llm_said}'; a rule required '{forced}'."
               if rg.get("overridden") else
               "A deterministic rule confirmed the AI's call.")
        checked = f"<span class=badge-rule title=\"{_esc(tip)}\">✓ rule-checked</span>"
    else:
        checked = ("<span class=badge-rule title=\"No override rule fired; the AI's recommendation "
                   "stands, checked against the deterministic gate.\">✓ rule-checked</span>")
    p.append("<header>"
             f"<h1>{_esc(target)} <span style='opacity:.7;font-weight:400'>in</span> {_esc(indication)}"
             " — target profile</h1>"
             f"<div class=rec>Recommendation: {action_html}"
             f" · confidence <span class=pill>{_esc(_val('confidence'))}</span> {checked}"
             f" <span style='opacity:.7;font-size:12px'>· AI-generated</span></div>"
             "</header>")

    # --- 2-column shell: sticky left nav (jump-links) + content ---
    # NOTE: the composite-panel SVG is deliberately NOT embedded here — it is a matplotlib
    # text-badge grid sized for a slide (~1583px) that renders poorly in a web card. The
    # scorecard below IS the native-HTML "at a glance". The SVG remains a .md/PPT slide asset.
    nav = ["<div class=shell><nav class=toc><p class=h>Sections</p>",
           "<a href='#s-exec'>Executive summary</a>"]
    if scorecard:
        nav.append("<a href='#s-scorecard'>Gate scorecard</a>")
    if deciding_axis and show_deciding_axis:
        nav.append("<a href='#s-deciding'>Deciding axis</a>")
    nav.append("<a href='#s-risk'>Risk by category</a>")
    nav.append("<a href='#s-tension'>Conflicting signals</a>")
    nav.append("<a href='#s-evidence'>Evidence by question</a>")
    if ordinal_matrix:
        nav.append("<a href='#s-matrix'>Modality fit</a>")
    nav.append("</nav><div class=content>")
    p.append("".join(nav))

    # --- Executive summary (LLM) — TOP, the lead the reader needs first ----
    p.append("<div class=llm id=s-exec><span class=tag>AI-generated</span>"
             f"<h2>Executive summary</h2><p>{_esc(_val('executive_summary'))}</p></div>")

    # --- Gate scorecard (deterministic, top-of-report) ---------------------
    # Rows are the sub-skills GROUPED under their A–H gate letter (a gate can have several
    # sub-skills — C has dependency + SL-partner + subtype). Grouping shows the 8-gate structure
    # WITHOUT collapsing: each sub-skill keeps its own honest status (a gate-letter roll-up that
    # merged them could hide a disagreeing sub-skill — the same information-loss the 4-state
    # design refuses). A greyed row = coverage gap (we didn't/couldn't look), NOT a negative.
    if scorecard:
        p.append("<section id=s-scorecard class=scorecard><h2>Gate scorecard</h2>")
        p.append("<p class=sub>One row per evidence question, grouped A–H. "
                 "<span class='chip chip-gap'><span class=g>□</span> Not evaluated</span> = a gap, "
                 "not a negative. Deciding question highlighted.</p>")
        p.append("<table><tr><th>Gate</th><th>Question</th><th>Status</th>"
                 "<th>Finding</th><th>Coverage</th></tr>")
        _last = object()
        for row in scorecard:
            glyph, cls, label = _HTML_STATUS.get(row["status"], _HTML_STATUS["coverage_gap"])
            gate = row.get("gate")
            new_gate = gate != _last
            gate_cell = f"<td>{_esc(gate)}</td>" if new_gate else "<td></td>"
            _last = gate
            finding = _esc(_humanize(row.get("verdict")))
            if row.get("driving_rule_id"):
                finding += f" <span class=sub><code>{_esc(row['driving_rule_id'])}</code></span>"
            # Display cross-references (logic unchanged; these clarify signals that live under one
            # gate but FEED another — logged as wiring backlog, surfaced honestly here):
            vtok = (row.get("verdict") or "")
            if row.get("short") == "genomic_alteration" and "biomarker_stratified" in vtok:
                finding += " <span class=sub>→ feeds Dependency (C)</span>"
            if row.get("short") == "tractability_sm":
                finding += " <span class=sub>(also confirms Dependency)</span>"
            qname = _esc(_GATE_SHORT_LABEL.get(row.get("short"), _humanize(row.get("short"))))
            if row.get("is_deciding"):
                qname += " <span class=badge-deciding>deciding</span>"
            trcls = [c for c in (("deciding" if row.get("is_deciding") else ""),
                                 ("gate-start" if new_gate else "")) if c]
            rowcls = f" class='{' '.join(trcls)}'" if trcls else ""
            p.append(f"<tr{rowcls}>{gate_cell}"
                     f"<td>{qname}</td>"
                     f"<td><span class='chip {cls}'><span class=g>{glyph}</span> {label}</span></td>"
                     f"<td>{finding}</td>"
                     f"<td class=sub>{_esc(_COVERAGE_LABEL.get(row.get('framework_can_evidence'), row.get('framework_can_evidence')))}</td></tr>")
        p.append("</table></section>")

    # --- Deciding axis (deterministic router) ------------------------------
    # HIDDEN by default (show_deciding_axis=False): the router can over-claim confidence when a
    # deciding gate rests on one thin input (e.g. gate F on gnomAD alone) — a known LOGIC issue on
    # the backlog. Data still lands in nomination.json; the section is re-enabled once the router
    # logic factors gate coverage into what it asserts as "deciding".
    if deciding_axis and show_deciding_axis:
        p.append("<section id=s-deciding><span class=tag>Deterministic router</span>"
                 "<h2>Deciding axis <span class=n>— what the call hinges on</span></h2>")
        p.append(f"<div class=banner>{_esc(deciding_axis.get('routing',''))}</div>")
        if deciding_axis.get("basis") == "abstention_coverage_gaps" and deciding_axis.get("unevidenced_gates"):
            p.append("<p class=sub>Can't decide from framework evidence — questions left unassessed:</p>")
            p.append("<table><tr><th>Gate</th><th>Question</th><th>Coverage</th></tr>")
            for g in deciding_axis["unevidenced_gates"]:
                p.append(f"<tr><td>{_esc(g.get('gate'))}</td>"
                         f"<td>{_esc(_GATE_SHORT_LABEL.get(g.get('short'), _humanize(g.get('short'))))}</td>"
                         f"<td class=sub>{_esc(_COVERAGE_LABEL.get(g.get('framework_can_evidence'), g.get('framework_can_evidence')))}</td></tr>")
            p.append("</table>")
        p.append("</section>")

    # --- Risk-by-category (deterministic) ----------------------------------
    p.append("<section id=s-risk class=det><span class=tag>Computed from the evidence</span>"
             "<h2>Risk by category</h2>")
    p.append("<table><tr><th>Category</th><th>Risk level</th><th>Driver</th></tr>")
    for cat, level, driver in _risk_by_category_from_sub_verdicts(sub_results):
        p.append(f"<tr><td><b>{_esc(str(cat).capitalize())}</b></td>"
                 f"<td>{_esc(_humanize(level))}</td><td>{_esc(driver)}</td></tr>")
    p.append("</table></section>")

    # --- Tension analysis (LLM) → reader-facing "Conflicting signals & trade-offs" ---
    p.append("<div class=llm id=s-tension><span class=tag>AI-generated</span>"
             "<h2>Conflicting signals &amp; trade-offs</h2>"
             f"<p>{_esc(_val('tension_analysis'))}</p></div>")

    # --- Evidence by question (deterministic; the actual card data + interactive figures) ---
    # NOTE: the standalone "Sub-verdicts" table was removed as redundant — the scorecard above
    # already carries the per-question verdict + rule + status. One source, not two.
    evidence_html, n_plotly = _render_card_data_html(sub_results, card_figures, figures_dir)
    p.extend(evidence_html)

    # --- Ordinal matrix heatmap (deterministic VIEW) -----------------------
    if ordinal_matrix:
        cols = ordinal_matrix["axes"]["columns"]
        p.append("<section id=s-matrix class=det><span class=tag>Ordering, not a score</span>"
                 "<h2>Modality fit by question <span class=n>— strongest signal per (question, "
                 "modality); the verdict, not a cell, is the call</span></h2>")
        col_lbl = {"small_molecule": "Small mol.", "degrader": "Degrader", "adc": "ADC",
                   "bite_tce": "BiTE/TCE", "antibody": "Antibody"}
        p.append("<table class=mtx><tr><th>Question</th>"
                 + "".join(f"<th>{_esc(col_lbl.get(c, c))}</th>" for c in cols) + "<th>Verdict</th></tr>")
        for row in ordinal_matrix["rows"]:
            cells = row["cells"]
            tds = "".join(f"<td class='{_mtx_cell_class(cells[m])}'>{_esc(ordinal_view._cell_glyph(cells[m]))}</td>"
                          for m in cols)
            p.append(f"<tr><td>{_esc(_GATE_SHORT_LABEL.get(row['short'], _humanize(row['short'])))}</td>{tds}"
                     f"<td>{_esc(_humanize(row.get('verdict')))}</td></tr>")
        p.append("</table>")
        p.append(f"<p class=disclaimer>{_esc(ordinal_matrix.get('_disclaimer',''))}</p>")
        # --- Data-catalogue summary tucked into the same deterministic card ---
        if catalogue_rows:
            p.append("<details><summary>Data catalogue — what backed this run</summary>")
            p.append("<table><tr><th>Manifest / source</th><th>Consumed by</th></tr>")
            for cr in catalogue_rows:
                p.append(f"<tr><td><code>{_esc(cr.get('manifest_id'))}</code></td>"
                         f"<td>{_esc(', '.join(cr.get('consumed_by', [])) or '—')}</td></tr>")
            p.append("</table></details>")
        p.append("</section>")
    elif catalogue_rows:
        p.append("<section class=det><h2>Data catalogue</h2>"
                 "<table><tr><th>Manifest / source</th><th>Consumed by</th></tr>")
        for cr in catalogue_rows:
            p.append(f"<tr><td><code>{_esc(cr.get('manifest_id'))}</code></td>"
                     f"<td>{_esc(', '.join(cr.get('consumed_by', [])) or '—')}</td></tr>")
        p.append("</table></section>")

    kind = "Interactive" if n_plotly else "Static"
    p.append("<footer>"
             f"Generated {_esc(datetime.now(timezone.utc).isoformat(timespec='seconds'))}"
             + (f" · lenses <code>{_esc(invoked_lenses)}</code>" if invoked_lenses else "")
             + f"<br>{kind} self-contained governance artifact — a projection of nomination.json. "
             + ("Charts are pre-computed by the methods (drawn from the same series as the static "
                "figures) and embedded, not re-plotted here. " if n_plotly else "")
             + "AI-generated sections are tinted; all other sections are deterministic and "
             "reproducible from the same inputs. No content is recomputed at render time.</footer>")
    p.append("</div>")   # close .wrap

    # --- Interactive layer (Phase B): inline plotly.js + a small vanilla-JS bootstrap that draws
    # every embedded spec. Emitted ONLY when ≥1 figure was produced — the no-figure report stays
    # pure static HTML (no JS, no 4.6 MB payload). Self-contained: plotly.js is INLINED, never a CDN.
    if n_plotly:
        bundle = _plotly_bundle()
        if bundle:
            p.append(f"<script>{bundle}</script>")
            p.append(_PLOTLY_BOOTSTRAP_JS)
    p.append("</body></html>")
    return "".join(p)


def _catalogue_rows_from_sub_results(sub_results: dict) -> list[dict]:
    """Distill a manifest→consumers lineage table from the per-card provenance already in the run.
    Envelope-only (no live catalog read → keeps the renderer a pure projection)."""
    by_manifest: dict[str, set] = {}
    for short, r in sub_results.items():
        for c in r.get("cards") or []:
            prov = (c.get("provenance") or {}) if isinstance(c, dict) else {}
            for mid in prov.get("input_manifest_ids", []) or []:
                by_manifest.setdefault(mid, set()).add(short)
    return [{"manifest_id": m, "consumed_by": sorted(v)} for m, v in sorted(by_manifest.items())]


def _load_figure_registry():
    """Import compose-dashboard's figure-emission registry (emit_figures_for_card).

    Both engines share ONE figure registry (the gap-#5 one-source-many-consumers lesson): the same
    per-card emitters that draw compose-dashboard's SVGs + Plotly specs draw them for target-profile.
    Graceful None on import failure — a run without per-card figures still emits every other artifact.
    """
    try:
        fe_dir = SKILLS_DIR / "compose-dashboard" / "scripts"
        if str(fe_dir) not in sys.path:
            sys.path.insert(0, str(fe_dir))
        import _figure_emitters  # type: ignore
        return _figure_emitters
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: figure registry unavailable: {e}", file=sys.stderr)
        return None


def _emit_card_figures(sub_results: dict, figures_dir: Path,
                       target: str, indication: str) -> dict:
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
                figs = fe.emit_figures_for_card(
                    card_id, c.get("summary") or {}, figures_dir, target, indication)
            except Exception as e:  # noqa: BLE001 — figure emission never blocks the run
                print(f"[target-profile] WARN: figure emit failed for {card_id}: {e}",
                      file=sys.stderr)
                figs = []
            if figs:
                by_card[card_id] = figs
    n_plotly = sum(1 for figs in by_card.values() for f in figs if f.get("dynamic"))
    print(f"[target-profile] per-card figures: {len(by_card)} cards, "
          f"{n_plotly} interactive Plotly specs", file=sys.stderr)
    return by_card


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--subtypes", default=None,
                    help="Comma-separated molecular subgroup ids to scope the "
                         "profile to (e.g. 'MSI_H,MSS'). When set, the subtype "
                         "tier is evaluated: a MEASURED, floor-cleared subtype "
                         "that is NOT a dependency holds the nomination. Omit for "
                         "a whole-cohort profile (backward-compatible default).")
    ap.add_argument("--modality", default=None,
                    help="OPTIONAL post-hoc modality lens.")
    ap.add_argument("--therapeutic-hypothesis", default=None,
                    help="OPTIONAL therapeutic hypothesis (line-of-therapy, "
                         "patient state, clinical goal). Reshapes LLM "
                         "narrative; sub-verdicts unchanged.")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    invoked_lenses: dict = {}
    if args.modality:
        invoked_lenses["modality"] = args.modality
    if args.therapeutic_hypothesis:
        invoked_lenses["therapeutic_hypothesis"] = args.therapeutic_hypothesis

    # 1. Fan out to sub-skills.
    print(f"[target-profile] Running {len(SUB_SKILLS)} sub-skills for "
          f"{args.target} in {args.indication}...", file=sys.stderr)
    subtypes = [s.strip() for s in args.subtypes.split(",") if s.strip()] if args.subtypes else None
    sub_results = _run_sub_skills(args.target, args.indication, subtypes=subtypes)
    for short, r in sub_results.items():
        v = r["verdict"]
        verdict_str = v[0] if v else "(no verdict)"
        print(f"  - {short:15s} -> {verdict_str}", file=sys.stderr)

    # Ordinal matrix VIEW (gap #3 "now"): gate × modality signals projected onto the ordinal
    # scale. Labeled, additive, NOT a verdict input (ordinal_view contract). Computed BEFORE the
    # prompt so synthesis can reason over the matrix-SLICE (gap #4b), not only the flat verdict
    # list; also emitted in nomination.json for downstream consumers.
    ordinal_matrix = _ordinal_matrix(sub_results)

    # 2. LLM synthesis via Bedrock (structured tool_use).
    print(f"[target-profile] Invoking Bedrock synthesis...", file=sys.stderr)
    tool_schema = _build_synthesis_tool()
    user_prompt = _build_user_prompt(
        args.target, args.indication, sub_results,
        modality=args.modality,
        therapeutic_hypothesis=args.therapeutic_hypothesis,
        ordinal_matrix=ordinal_matrix,
    )
    llm_output = synthesize_structured(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        tool_name="target_profile_synthesis",
        tool_schema=tool_schema,
    )

    # 2b. Deterministic recommendation gate. A killer sub-verdict FORCES the
    # recommendation regardless of what the LLM chose — the auditable rule wins.
    # We clamp the wrapped {value, _source, ...} in place and record the override
    # in nomination.json + provenance so the gate is never silent.
    gate_action, gate_hits, gate_suppressions = _gate_recommendation(
        sub_results, modality=args.modality)
    recommendation_gate = {"fired": bool(gate_action),
                           "suppressed_vetoes": gate_suppressions}
    if gate_suppressions:
        print(f"[target-profile] recommendation gate SUPPRESSED "
              f"{[s['short']+':'+s['verdict']+' via '+s['suppressed_by']['kind'] for s in gate_suppressions]}",
              file=sys.stderr)
    confidence_tier = {"tier": None}
    if gate_action:
        rec = llm_output.get("overall_recommendation")
        llm_value = rec.get("value") if isinstance(rec, dict) else rec
        recommendation_gate = {
            "fired": True,
            "forced_recommendation": gate_action,
            "llm_recommendation": llm_value,
            "overridden": llm_value != gate_action,
            "triggered_by": gate_hits,
            "suppressed_vetoes": gate_suppressions,
        }
        if isinstance(rec, dict):
            rec["value"] = gate_action
            rec["_gated"] = True  # mark the value as rule-forced, not LLM-chosen
        else:
            llm_output["overall_recommendation"] = {
                "value": gate_action, "_source": "recommendation_gate"}
        print(f"[target-profile] recommendation GATE fired: forced '{gate_action}' "
              f"(LLM said '{llm_value}') via {[h['short']+':'+h['verdict'] for h in gate_hits]}",
              file=sys.stderr)
    else:
        # NO kill fired → the positive tier may raise a deterministic confidence
        # FLOOR. F1-safe: this branch is unreachable when a kill fired; it touches
        # ONLY `confidence`, never `overall_recommendation` (never forces nominate).
        tier, pos_hits = _positive_tier(sub_results)
        confidence_tier = {"tier": tier, "hits": pos_hits}
        if tier:
            floor = _TIER_TO_CONFIDENCE[tier]  # strong→high, moderate→medium
            conf = llm_output.get("confidence")
            llm_conf = conf.get("value") if isinstance(conf, dict) else conf
            # Apply as a floor: never lower the LLM's confidence, only raise it.
            if _CONFIDENCE_RANK.get(floor, 0) > _CONFIDENCE_RANK.get(llm_conf, 0):
                if isinstance(conf, dict):
                    conf["value"] = floor
                    conf["_floored_by_positive_tier"] = True
                else:
                    llm_output["confidence"] = {
                        "value": floor, "_source": "positive_tier"}
                confidence_tier["floored_from"] = llm_conf
                confidence_tier["floored_to"] = floor
            print(f"[target-profile] positive tier: {tier} "
                  f"(dims={sorted({h['short'] for h in pos_hits})}); "
                  f"confidence floor {floor}", file=sys.stderr)

    # Deciding-axis router (L): name the load-bearing gate + whether the framework can
    # evidence it. Reports (never predicts): a fired gate is the deciding axis; on abstention,
    # the unevidenced necessity gates are the routing instruction. Purely additive — reads the
    # already-resolved gate/positive state, touches no verdict.
    deciding_axis = _deciding_axis(
        sub_results, gate_action, gate_hits,
        positive_hits=confidence_tier.get("hits", []) or [],
    )
    print(f"[target-profile] deciding axis [{deciding_axis['basis']}]: "
          f"{deciding_axis.get('routing', '')}", file=sys.stderr)

    # Gate scorecard (deterministic, top-of-report): 8-gate rows from the gate registry, 4-state
    # status reusing the nomination-gate policy. Also emitted in nomination.json.
    scorecard = _gate_scorecard(sub_results, deciding_axis)
    catalogue_rows = _catalogue_rows_from_sub_results(sub_results)

    # 3a. Render composite panel PNG + SVG (Shape C — slide-drop artefact).
    figures_dir = args.out / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    composite_png = figures_dir / "target_profile_at_a_glance.png"
    try:
        render_composite_panel(
            out_path=composite_png,
            target=args.target,
            indication=args.indication,
            sub_results=sub_results,
            llm_output=llm_output,
        )
        composite_rel = f"figures/{composite_png.name}"
        print(f"[target-profile] wrote {composite_png} (+ .svg companion)",
              file=sys.stderr)
    except Exception as e:
        # Panel rendering must never block artefact emission. Log + continue
        # with no image reference in the markdown.
        composite_rel = None
        print(f"[target-profile] WARN: composite panel render failed: {e}",
              file=sys.stderr)

    # 3a-bis. Produce per-card distribution figures (SVG + interactive .plotly.json) via the shared
    # figure registry. This is the dynamic-dashboard Phase B change: a run now PRODUCES the per-card
    # charts (previously rules/summary-only). Best-effort — never blocks artefact emission.
    card_figures = _emit_card_figures(sub_results, figures_dir, args.target, args.indication)

    # 3b. Render + emit markdown artefact (Shape A — enriched).
    md = _render_target_profile_md(
        args.target, args.indication, sub_results, llm_output, invoked_lenses,
        composite_figure_relpath=composite_rel,
        deciding_axis=deciding_axis,
        ordinal_matrix=ordinal_matrix,
    )
    (args.out / "target_profile.md").write_text(md)

    # 3c. Render + emit the static HTML governance artifact (self-contained; inlines the
    # composite SVG). Pure projection — never blocks emission on failure.
    try:
        composite_svg = composite_png.with_suffix(".svg") if composite_rel else None
        htmldoc = _render_target_profile_html(
            args.target, args.indication, sub_results, llm_output, invoked_lenses,
            deciding_axis=deciding_axis, ordinal_matrix=ordinal_matrix,
            scorecard=scorecard, composite_svg_path=composite_svg,
            catalogue_rows=catalogue_rows, recommendation_gate=recommendation_gate,
            card_figures=card_figures, figures_dir=figures_dir,
        )
        (args.out / "target_profile.html").write_text(htmldoc)
        print(f"[target-profile] wrote {args.out}/target_profile.html", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[target-profile] WARN: HTML render failed: {e}", file=sys.stderr)

    nomination = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "invoked_lenses": invoked_lenses,
        "sub_verdicts": {
            short: {
                "skill_dir": r["skill_dir"],
                "verdict": r["verdict"][0] if r["verdict"] else None,
                "driving_rule_id": r["verdict"][1] if r["verdict"] else None,
                "fired_rule_ids": [f["rule_id"] for f in r["fired"]],
                "cards_missing": [c["card_id"] for c in r["cards"] if c.get("_missing")],
            }
            for short, r in sub_results.items()
        },
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "gate_scorecard": scorecard,
        "ordinal_matrix_view": ordinal_matrix,
        # Per-card figures produced this run (SVG + interactive .plotly.json siblings), keyed by
        # card_id, paths relative to figures/. The dynamic HTML renderer (Phase B PR-2) embeds the
        # `dynamic: True` Plotly specs; falls back to the SVG otherwise.
        "card_figures": card_figures,
        "llm_synthesis": llm_output,
    }
    (args.out / "nomination.json").write_text(
        json.dumps(nomination, indent=2, default=str)
    )

    provenance = {
        "skill": SKILL_NAME,
        "skill_version": SKILL_VERSION,
        "target": args.target,
        "indication": args.indication,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "invoked_lenses": invoked_lenses,
        "sub_skills_ran": [s for s, _ in SUB_SKILLS],
        "recommendation_gate": recommendation_gate,
        "confidence_tier": confidence_tier,
        "deciding_axis": deciding_axis,
        "llm_prompt_hash": llm_output.get("executive_summary", {}).get("_prompt_hash"),
        "llm_model_id": llm_output.get("executive_summary", {}).get("_model_id"),
        # Governance item B (2026-07-20): the DECLARED framework model pin. Distinct
        # from llm_model_id (the model that actually ran) — when the two diverge, an
        # env override was used. Auditors compare them to detect per-run drift.
        "framework_model_version": _framework_model_version(),
        "artefacts": [
            "target_profile.md",
            "target_profile.html",
            "nomination.json",
            "figures/target_profile_at_a_glance.png",
            "figures/target_profile_at_a_glance.svg",
        ],
    }
    (args.out / "provenance.yaml").write_text(yaml.safe_dump(provenance, sort_keys=False))

    print(f"[target-profile] wrote {args.out}/target_profile.md")
    print(f"[target-profile] wrote {args.out}/nomination.json")
    print(f"[target-profile] wrote {args.out}/provenance.yaml")
    print()
    def _unwrap(raw):
        return raw.get("value") if isinstance(raw, dict) else raw
    print(f"Recommendation: {_unwrap(llm_output.get('overall_recommendation'))}")
    print(f"Confidence:     {_unwrap(llm_output.get('confidence'))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
