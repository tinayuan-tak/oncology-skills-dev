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
# _synthesis.py fit_level scorer. That second engine was removed in Phase D (#377) —
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
}
# Precedence when multiple gates fire: veto dominates hold.
_GATE_ACTION_RANK = {"veto": 2, "hold": 1}


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
    # .get(a, 0): an action outside {veto, hold} (a vocab typo or a new action a product owner adds —
    # the module comment explicitly invites editing this vocab "without a code change") must NOT crash
    # the run with a KeyError, which would defeat the "gate never crashes the run" contract. Unknown
    # actions rank LOWEST (0) so a real veto/hold always wins; the target-contracts CI test
    # (test_every_gate_well_formed) is the primary guard — this is defense-in-depth.
    forced = max((h["action"] for h in hits), key=lambda a: _GATE_ACTION_RANK.get(a, 0))
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
    '_GATE_ACTION_RANK',
    '_SCORECARD_STATUS_ORDER',
    '_TIER_TO_CONFIDENCE',
    '_V2_GATE_LISTS',
    '_flatten_gate_coverage',
    '_gate_recommendation',
    '_gate_scorecard',
    '_load_gate_coverage',
    '_load_gate_verdicts',
    '_load_positive_signals',
    '_load_veto_suppressors',
    '_positive_tier',
    '_run_coverage_for_short',
    '_sub_result_has_signal',
    '_suppressed_gate_hits',
]
