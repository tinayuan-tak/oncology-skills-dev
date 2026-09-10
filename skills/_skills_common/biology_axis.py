"""biology_axis — resolve a target's curated biology axis + its plausible modalities.

The framework curates, per target, a BIOLOGY AXIS (intracellular_intrinsic /
surface_intrinsic / extrinsic / mixed / unknown) in target-contracts:
  vocabularies/target_biology_axis_lookup.yaml   (target -> axis, ~20 curated)
  vocabularies/biology_axis.enum.yaml            (axis -> plausible_modalities)

This axis drove deterministic dashboard selection in the now-retired compose-dashboard
skill (_resolution.py). It was NOT reaching the LLM synthesis prompt — so the narration
discussed surface modalities (ADC/TCE/CAR) for intracellular targets and vice
versa, regardless of the target's biology. This module makes the axis available
to the synthesis layer as an EMPHASIS STEER (never a verdict — SLOT-2 only).

DESIGN — de-emphasize, do not erase (honest multi-axis handling):
  Multi-axis targets (EGFR, ERBB2, MET) carry a single PRIMARY axis plus an
  `iter2_note` saying they are genuinely dual (EGFR: intracellular kinase AND
  surface antigen). So this loader surfaces the primary axis + its plausible
  modalities AND the multi_axis note, so the prompt can tell the LLM to FOREGROUND
  the primary-axis modalities and de-emphasize (not delete) the others. A target
  not in the lookup resolves to `unknown` with EMPTY plausible modalities — the
  honest "we haven't curated this" state, which the prompt surfaces as "axis
  uncurated; do not assume a modality class."

Read-only, lru-cached. No network, no S3 — pure local vocabulary read. If the
vocabulary files are unreadable, resolves to `unknown` and never raises (synthesis
is never allowed to break on a missing steer).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from _skills_common.paths import target_contracts_root

# target-contracts is a sibling repo; paths.target_contracts_root() honors TARGET_CONTRACTS_ROOT.
_DEFAULT_CONTRACTS_ROOT = str(target_contracts_root())
_LOOKUP_REL = "vocabularies/target_biology_axis_lookup.yaml"
_ENUM_REL = "vocabularies/biology_axis.enum.yaml"

# The five axis values (mirrors biology_axis.enum.yaml); used only for a safe default.
_UNKNOWN_AXIS = "unknown"


@lru_cache(maxsize=4)
def _load_enum(contracts_root: str) -> dict:
    """axis_value -> {plausible_modalities: [...], iter1b_status, base_dashboard}."""
    path = Path(contracts_root) / _ENUM_REL
    try:
        import yaml

        doc = yaml.safe_load(path.read_text())
    except Exception:  # noqa: BLE001 — never break synthesis on a vocab read
        return {}
    out: dict[str, dict] = {}
    for v in (doc or {}).get("values", []) or []:
        val = v.get("value")
        if not val:
            continue
        out[val] = {
            "plausible_modalities": list(v.get("plausible_modalities_iter1b", []) or []),
            "iter1b_status": v.get("iter1b_status"),
            "base_dashboard": v.get("base_dashboard"),
            "label": v.get("label"),
        }
    return out


@lru_cache(maxsize=4)
def _load_lookup(contracts_root: str) -> dict:
    """UPPER symbol (incl. aliases) -> {axis, rationale, iter2_note, primary_symbol}."""
    path = Path(contracts_root) / _LOOKUP_REL
    try:
        import yaml

        doc = yaml.safe_load(path.read_text())
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for t in (doc or {}).get("targets", []) or []:
        sym = t.get("hgnc_symbol")
        axis = t.get("biology_axis")
        if not sym or not axis:
            continue
        entry = {
            "axis": axis,
            "rationale": t.get("rationale"),
            "iter2_note": t.get("iter2_note"),  # present only on multi-axis targets
            "primary_symbol": sym,
        }
        out[sym.strip().upper()] = entry
        for alias in t.get("hgnc_symbol_aliases", []) or []:
            out[str(alias).strip().upper()] = entry
    return out


def resolve_biology_axis(target: str, contracts_root: Optional[str] = None) -> dict:
    """Resolve a target's curated biology axis + plausible modalities.

    Returns a dict (NEVER raises):
      {
        "target": <as given>,
        "biology_axis": "intracellular_intrinsic" | ... | "unknown",
        "curated": bool,                       # False => not in the lookup
        "plausible_modalities": [...],         # from the enum for this axis ([] for unknown)
        "multi_axis": bool,                    # True when an iter2_note flags a dual-axis target
        "multi_axis_note": <str or None>,      # the iter2_note, verbatim, for honest de-emphasis
        "rationale": <str or None>,            # the curated one-liner
      }

    A target not in the lookup resolves to axis=unknown, curated=False, empty
    plausible_modalities — the prompt surfaces this as "axis uncurated" rather than
    assuming a modality class.
    """
    root = contracts_root or _DEFAULT_CONTRACTS_ROOT
    sym = (target or "").strip().upper()
    lookup = _load_lookup(root)
    enum = _load_enum(root)

    entry = lookup.get(sym)
    if entry is None:
        return {
            "target": target,
            "biology_axis": _UNKNOWN_AXIS,
            "curated": False,
            "plausible_modalities": list(enum.get(_UNKNOWN_AXIS, {}).get("plausible_modalities", [])),
            "multi_axis": False,
            "multi_axis_note": None,
            "rationale": None,
        }
    axis = entry["axis"]
    return {
        "target": target,
        "biology_axis": axis,
        "curated": True,
        "plausible_modalities": list(enum.get(axis, {}).get("plausible_modalities", [])),
        "multi_axis": bool(entry.get("iter2_note")),
        "multi_axis_note": entry.get("iter2_note"),
        "rationale": entry.get("rationale"),
    }


def format_axis_governance_block(axis_info: dict) -> str:
    """Render the resolved axis into a compact prompt GOVERNANCE block that steers
    modality EMPHASIS (never the verdict). De-emphasizes, does not erase: for a
    multi-axis target it names the primary modalities AND the dual-axis note.

    The block is deterministic given axis_info, so it is byte-stable + hashable in
    the _prompt_hash provenance."""
    axis = axis_info.get("biology_axis", _UNKNOWN_AXIS)
    plausible = axis_info.get("plausible_modalities") or []
    lines = [
        "MODALITY GOVERNANCE (constrains modality talk to stay biologically honest; SECONDARY to "
        "the integrated relevance case; does NOT change the verdict):"
    ]
    if not axis_info.get("curated"):
        lines.append(
            f"  biology_axis: unknown (target '{axis_info.get('target')}' is not curated in the "
            f"biology-axis lookup). If modality comes up, do NOT assume a class — do not assert surface "
            f"(ADC/TCE/CAR) OR small-molecule/degrader on the basis of axis; reason only from the "
            f"fired-rule evidence, and note the axis is uncurated."
        )
        return "\n".join(lines)
    plausible_str = ", ".join(plausible) if plausible else "(none defined for this axis)"
    lines.append(f"  biology_axis: {axis}")
    lines.append(f"  plausible_modalities for this axis: {plausible_str}")
    if axis == "intracellular_intrinsic":
        lines.append(
            "  → WHEN modality is discussed, keep it to small-molecule / degrader. Do NOT "
            "assert surface modalities (ADC / T-cell-engager / CAR / antibody) UNLESS a "
            "surface-accessibility rule fired that overrides the axis — if none did, surface "
            "modalities are not applicable to this intracellular target."
        )
    elif axis == "surface_intrinsic":
        lines.append(
            "  → WHEN modality is discussed, surface modalities (ADC / T-cell-engager / "
            "antibody) are the plausible set; small-molecule framing needs a tractability rule."
        )
    elif axis in ("extrinsic", "mixed"):
        lines.append(
            f"  → axis '{axis}' is deferred (microenvironment biology); if modality comes up, "
            "reason from the fired-rule evidence and avoid asserting a single tumor-intrinsic class."
        )
    if axis_info.get("multi_axis") and axis_info.get("multi_axis_note"):
        lines.append(
            f"  MULTI-AXIS: this target is genuinely dual — {axis_info['multi_axis_note']} "
            "Treat the non-primary modality as secondary (do not erase it)."
        )
    return "\n".join(lines)
