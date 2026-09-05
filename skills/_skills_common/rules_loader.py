"""rules_loader — single canonical entry point for Tier-2 interpretation rules.

Both compose-dashboard (Macro synthesis) and compositional skills load
rules from the same YAML files under target-contracts/interpretation-rules/.
Previously, each side had its own loader:

  - Macro: compose-dashboard.scripts._synthesis._load_interpretation_rules
  - Skills: reached into Macro's private helper via cross-skill import

That coupling meant every compositional-skill Python module needed
compose-dashboard's scripts/ package on sys.path. This module extracts the
loader into a shared home so both sides import from one canonical location
— de-couples the runtime layers and makes the rules file the single source
of truth its architecture intends.

Rules file location:
  <target-contracts-repo>/interpretation-rules/{axis-kebab}.rules.yaml

Expected top-level YAML keys: `axis` (must match caller's requested axis),
`rules_id`, `rules` (list). See intracellular-intrinsic.rules.yaml for the
reference shape.
"""

from __future__ import annotations
import os

import functools
from pathlib import Path
from typing import Optional

import yaml

from _skills_common.paths import target_contracts_root

# Prefer the libyaml C loader — ~10x faster parsing the per-axis rules files (the
# intracellular-intrinsic axis is ~200 KB and sits on the compute critical path of every wired
# skill run). Fall back to the pure-Python loader if libyaml is not built into the local PyYAML;
# the parse result is byte-identical either way. Mirrors methods/catalog_query/read.py.
try:
    _SafeLoader = yaml.CSafeLoader
except AttributeError:  # pragma: no cover - depends on local libyaml build
    _SafeLoader = yaml.SafeLoader


# Same TARGET_CONTRACTS constant compose-dashboard uses. We duplicate rather
# than import so this module has no compose-dashboard dependency — that's the
# point of the extraction.
TARGET_CONTRACTS = target_contracts_root()


@functools.lru_cache(maxsize=None)
def load_interpretation_rules(
    axis: str,
    contracts_root: Optional[Path] = None,
) -> Optional[list[dict]]:
    """Load the Tier-2 rules file for a given biology axis.

    Arguments:
        axis: biology axis name (e.g. "intracellular_intrinsic",
            "surface_intrinsic"). Underscores are converted to kebab-case for
            the filename lookup.
        contracts_root: optional override; defaults to TARGET_CONTRACTS.

    Returns:
        A list of rule dicts on success. None when:
          - axis is empty
          - target-contracts/interpretation-rules/ directory missing
          - {axis}.rules.yaml file missing
          - YAML unreadable or malformed
          - file's declared axis doesn't match the requested axis
          - rules key missing or empty

    Callers should treat None as "no rules available for this axis" and fall
    back to whatever their legacy or graceful-degradation path is. This mirrors
    the original _synthesis._load_interpretation_rules contract exactly.
    """
    if not axis:
        return None
    root = Path(contracts_root) if contracts_root is not None else TARGET_CONTRACTS
    rules_dir = root / "interpretation-rules"
    if not rules_dir.is_dir():
        return None
    axis_kebab = axis.replace("_", "-")
    rules_path = rules_dir / f"{axis_kebab}.rules.yaml"
    if not rules_path.is_file():
        return None
    try:
        doc = yaml.load(rules_path.read_text(), Loader=_SafeLoader)
    except Exception:
        return None
    if not isinstance(doc, dict) or doc.get("axis") != axis:
        return None
    rules = doc.get("rules")
    if not isinstance(rules, list) or not rules:
        return None
    return rules


def filter_rules_by_card_ids(
    rules: list[dict],
    card_ids: list[str],
) -> list[dict]:
    """Filter a rules list to those whose when.card_id is in the given set.

    Useful for compositional skills that consume a card subset. Mirrors the
    filter logic previously inline in _micro_common.fired_rules().
    """
    if not card_ids:
        return rules
    keep = set(card_ids)
    return [r for r in rules if (r.get("when") or {}).get("card_id") in keep]


@functools.lru_cache(maxsize=8)
def rule_text_index(contracts_root: Optional[Path] = None) -> dict:
    """A GLOBAL {rule_id: {rationale, killer_message, card_id, axis}} index across every
    interpretation-rules/*.rules.yaml file — the rule_id -> human-sentence path.

    Unlike ``load_interpretation_rules`` (per-axis, verdict/fire-time), this indexes ALL rules
    regardless of axis so a caller can look up the human text of ANY rule_id — crucially including
    the ~majority of display/inert rules that never fire and whose ``rationale`` therefore never
    reaches ``fired_rules`` output. The narrative builder uses it to caption counterfactual flip
    rules (a rule that WOULD flip the verdict if toggled is, by definition, not in the fired set).

    Iterates the exact glob ``reachability._rule_id_to_card`` walks, so the two derive the same
    rule universe. Memoized like ``load_interpretation_rules``. Returns {} when the directory is
    absent (caller then has no sentences — never a hard failure).
    """
    root = Path(contracts_root) if contracts_root is not None else TARGET_CONTRACTS
    rules_dir = root / "interpretation-rules"
    out: dict[str, dict] = {}
    if not rules_dir.is_dir():
        return out
    for f in sorted(rules_dir.glob("*.rules.yaml")):
        try:
            doc = yaml.load(f.read_text(), Loader=_SafeLoader)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        axis = doc.get("axis")
        for r in doc.get("rules", []) or []:
            rid = r.get("rule_id")
            if not rid:
                continue
            when = r.get("when") or {}
            out[rid] = {
                "rationale": (r.get("rationale") or "").strip(),
                "killer_message": r.get("killer_message"),
                "card_id": when.get("card_id") if isinstance(when, dict) else None,
                "axis": axis,
            }
    return out
