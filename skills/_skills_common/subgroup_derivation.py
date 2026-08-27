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


# ── FIRST-CLASS SUBTYPE: generic per-stratum projection of each sub-group ──────────────────────────
# Fleet version of tumor-presence's _attach_subtype_firstclass. Reads the `tier: subtype` cards'
# per_subgroup_metrics for each sub-group and produces by_stratum {stratum: {signal, certainty, n,
# powered}}. Certainty = sample-size, 1-tier multiplicity haircut (k strata >= 5), POWER-GATED
# (evidence_state!=measured OR n<floor -> low/underpowered, never over-read). Subtype stays an
# orthogonal CONDITIONER: this REFINES a sub-group per stratum, it never mints a new sub-group.
_CERT = {"low": 0, "moderate": 1, "high": 2}
_CERT_INV = {0: "low", 1: "moderate", 2: "high"}
_STRATUM_ID_FIELDS = ("stratum_id", "stratum")
_STRATUM_N_FIELDS = ("n_tumor_samples", "subgroup_n", "n_cell_lines", "n")
_STRATUM_CLASS_FIELDS = ("tumor_expression_class", "protein_expression_class", "class", "expression_class")
_SUBGROUP_N_FLOOR = 30


def _multiplicity_haircut(cert: str, k: int) -> str:
    if cert not in _CERT or not isinstance(k, int) or k < 5:
        return cert
    return _CERT_INV[max(0, _CERT[cert] - 1)]


def _stratum_tier(row: dict, classify) -> str:
    for f in _STRATUM_CLASS_FIELDS:
        if row.get(f) is not None:
            return classify(row.get(f))
    med = row.get("median_log2tpm")
    if isinstance(med, (int, float)):
        return "strong" if med >= 5 else "moderate" if med >= 3.46 else "weak" if med >= 1 else "absent"
    return "absent"


def derive_stratified(hierarchy: dict, cards: list, classify=default_classify) -> dict:
    """{sub_group -> {stratum -> {signal, certainty, n, powered, multiplicity_strata_tested}}} from the
    sub-group's `tier: subtype` cards. Empty when no subtype cards / no per_subgroup_metrics."""
    type_sg = {}
    for sg in hierarchy.get("sub_groups", []):
        for q in sg.get("questions", []):
            for mt in q.get("measurement_types", []):
                type_sg.setdefault(mt, sg["id"])
    sg_rows: dict = {}
    for c in cards or []:
        summ = c.get("summary") or {}
        mt, tier = _card_meta(c.get("card_id"))
        sg = type_sg.get(mt)
        if not sg or tier != "subtype":
            continue
        rows = summ.get("per_subgroup_metrics")
        if isinstance(rows, list):
            sg_rows.setdefault(sg, []).extend(r for r in rows if isinstance(r, dict))

    out: dict = {}
    for sg, rows in sg_rows.items():
        by: dict = {}
        for r in rows:
            sid = next((r.get(f) for f in _STRATUM_ID_FIELDS if r.get(f)), None)
            if not sid:
                continue
            n = next((r.get(f) for f in _STRATUM_N_FIELDS if isinstance(r.get(f), (int, float))), None)
            powered = (r.get("evidence_state") == "measured" and isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR)
            by.setdefault(sid, []).append({"tier": _stratum_tier(r, classify), "n": n, "powered": powered})
        k = len(by)
        strata = {}
        for sid, reads in by.items():
            best = max(reads, key=lambda x: _TIERV.get(x["tier"], -1))
            n = best["n"]
            base = "high" if isinstance(n, (int, float)) and n >= 100 else "moderate" if isinstance(n, (int, float)) and n >= _SUBGROUP_N_FLOOR else "low"
            powered = any(x["powered"] for x in reads)
            cert = _multiplicity_haircut(base, k) if powered else "low"   # underpowered stratum never over-read
            strata[sid] = {"signal": best["tier"], "certainty": cert, "n": n, "powered": powered,
                           "multiplicity_strata_tested": k}
        if strata:
            out[sg] = strata
    return out
