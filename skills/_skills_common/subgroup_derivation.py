"""Hierarchy-driven sub-group derivation (signals-first spec v0.1).

DERIVES per-sub-group {signal, confidence, sources} for a skill from its question_hierarchy.yaml + the
resolved cards — replacing hand-wired card-ids. Sources bind by `measurement_type` (× entity_grain: a
`tier: subtype` card is a CONDITIONER, not a whole-cohort source). Confidence = agreement × sample-size
over the sources, capped by conflict — NOT weakest-link. Generic + reusable fleet-wide: a skill supplies
a per-measurement_type reader spec; this module does the binding + aggregation.

Verdict-INERT: a one-way projection over resolved cards; never feeds a verdict/resolver. Best-effort —
if target-contracts is unavailable (no measurement_type lookup), returns {} (spine unaffected).
"""
from __future__ import annotations
import functools
import os
from pathlib import Path
from typing import Callable, Optional

_CT = Path(os.environ.get("TARGET_CONTRACTS_ROOT",
                          "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
_TIERV = {"strong": 3, "moderate": 2, "weak": 1, "absent": 0}
_POW = ["low", "moderate", "high", "very high"]


@functools.lru_cache(maxsize=1024)
def _card_meta(card_id: str) -> tuple:
    """(measurement_type, tier) from the card contract; ('', '') if unresolvable. Cached."""
    p = _CT / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return (None, None)
    try:
        import yaml
        y = yaml.safe_load(p.read_text()) or {}
    except Exception:  # noqa: BLE001 — verdict-inert projection; never break the spine
        return (None, None)
    return (y.get("measurement_type"), y.get("tier"))


def default_classify(v) -> str:
    """Ordinal presence tier from a categorical card value (token heuristic; a skill may pass its own)."""
    s = str(v or "").lower()
    if any(t in s for t in ("broadly_high", "strong", "malignant_broadly", "top_1pct", "adequate", "__present__")):
        return "strong" if "__present__" not in s else "moderate"
    if any(t in s for t in ("broadly_moderate", "moderate", "multi", "partial", "lineage_restricted", "mid")):
        return "moderate"
    if any(t in s for t in ("broadly_low", "sparse", "single", "poor", "bottom_decile")):
        return "weak"
    return "absent"


def _nbucket(n) -> str:
    if not isinstance(n, (int, float)):
        return "low"
    return "very high" if n >= 1e5 else "high" if n >= 100 else "moderate" if n >= 20 else "low"


def derive_subgroups(hierarchy: dict, cards: list, reader_spec: dict,
                     classify: Callable = default_classify) -> dict:
    """{sub_group -> {signal, confidence, n_sources, n_agree, power, conflict, sources[]}}.

    reader_spec: {measurement_type: {"class": field, "n": [fields], "label": str,
                                     "present_synonyms": (...)}}  — how to read each source card.
    """
    type_sg = {}
    for sg in hierarchy.get("sub_groups", []):
        for q in sg.get("questions", []):
            for mt in q.get("measurement_types", []):
                type_sg.setdefault(mt, sg["id"])

    per: dict = {}
    for c in cards or []:
        cid = c.get("card_id")
        summ = c.get("summary") or {}
        mt, tier = _card_meta(cid)
        sg = type_sg.get(mt)
        if not sg or mt not in reader_spec or tier == "subtype":
            continue                      # not a source for a whole-cohort sub-group signal
        spec = reader_spec[mt]
        raw = summ.get(spec["class"])
        if raw in spec.get("present_synonyms", ()):   # e.g. protein ns = quantified/present, not low
            raw = "__present__"
        t = classify(raw)
        n = next((summ.get(f) for f in spec.get("n", []) if isinstance(summ.get(f), (int, float))), None)
        conflict = summ.get("allgene_percentile_class") == "bottom_decile"   # level != breadth
        per.setdefault(sg, []).append({"card": cid, "tier": t, "n": n, "power": _nbucket(n),
                                       "label": spec.get("label", mt), "conflict": conflict,
                                       "value": summ.get(spec["class"])})

    out: dict = {}
    for sg, srcs in per.items():
        present = [s for s in srcs if _TIERV[s["tier"]] >= 2]
        signal = max(srcs, key=lambda s: _TIERV[s["tier"]])["tier"]
        best_power = max((s["power"] for s in srcs), key=lambda p: _POW.index(p))
        conflicts = [s for s in srcs if s["conflict"]]
        # confidence = agreement × sample-size, capped by conflict (NOT weakest-link)
        conf = ("high" if len(present) == len(srcs) and best_power in ("high", "very high")
                else "moderate" if len(present) >= max(1, len(srcs) // 2) else "low")
        if conflicts and conf == "high":
            conf = "moderate"
        out[sg] = {"signal": signal, "confidence": conf, "n_sources": len(srcs), "n_agree": len(present),
                   "power": best_power, "conflict": bool(conflicts),
                   "sources": [{"card": s["card"], "tier": s["tier"], "n": s["n"], "label": s["label"],
                                "conflict": s["conflict"], "value": s["value"]} for s in srcs]}
    return out
