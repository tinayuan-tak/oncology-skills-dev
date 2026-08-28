"""evidence_capsule — a COMPLETE-but-LIMITED per-card data package for the LLM consumers.

Unifies the SIGNAL layer (sub-verdict + claim axis — already flowing via the narrator-input contract)
with a bounded DATA layer: 5 fixed deterministic SELECTOR SHAPES over each card's already-computed
fields. ONE emitter, read by BOTH the single-lens narrators and the retrieve-don't-recall cross-evidence
agent (each capsule row is a citable atom).

COMPLETE  : every verdict-feeding card emits a capsule; required-field-or-explicit-null; a card-floor
            manifest lists every card {full|thin|absent+reason} so completeness is auditable.
LIMITED   : fixed shapes, top-k, rounded, deduped, token-budgeted (verdict cards full, others thin).
HASH-STABLE: sorted card order, sorted rows, rounded floats, sorted-key JSON — plugs into the spine
            without perturbing prompt_hash.

Pure selection over resolved cards — no LLM, no network, no new computation. VERDICT-INERT.

The 5 selector shapes:
  1 top_k_strata     — a card's per-lineage/oncotree/stratum array → indication row + argmin + argmax
  2 numeric_anchors  — the load-bearing scalar(s) behind each class (effect/q/CI/percentile/n)
  3 conflict_pairs   — two cards on one measurement_type disagreeing in tier (with precedence)
  4 sibling_caveats  — caveat fields that qualify a favorable headline (escape/variability/…)
  5 provenance_keys  — distinct contributing sources + distinct_provenance_count
plus data_quality_flags — generic mis-bind / direction-inversion contradictions surfaced, not hidden.
"""
from __future__ import annotations

from _skills_common.subgroup_derivation import _card_meta, default_classify, _TIERV

_R = 4                               # float precision (hash-stability)
_STRATUM_LABELS = ("oncotree_code", "lineage", "stratum_id", "stratum", "subgroup", "cohort", "subtype")
_STRATUM_METRICS = ("median_chronos", "median_dep_score", "frac_dependent", "fraction_strongly_dependent",
                    "median_log2fc", "log2_fc", "effect_size", "r2", "median", "value", "median_gene_effect")
_ANCHOR_HINTS = ("effect_size", "cohens_d", "q_value", "bh_q", "pvalue", "p_value", "percentile",
                 "median", "fraction", "pearson_r", "spearman_r", "r_squared", "r2", "ci_lo", "ci_hi",
                 "log2_fc", "log2fc", "frac_dependent", "variance_explained", "selectivity_index",
                 "copies_per_cell", "pchembl", "ppv", "sensitivity", "specificity", "base_rate")
_N_HINTS = ("n_", "_n", "_samples", "_lines", "_cells", "_donors", "_models", "_evaluated", "_paired",
            "n_patient", "n_compounds", "n_ligands")
_CAVEAT_HINTS = ("escape", "variability", "consistency", "coverage", "buffering", "shed", "fragile",
                 "heterogen", "purity", "confound", "conflict", "underpowered", "instability")
_PROV_HINTS = ("_source", "_data_source", "screens_contributing", "consortium", "product_id", "release_pin")


def _num(v):
    return round(v, _R) if isinstance(v, float) else v


def _first_stratum_array(summary):
    """The first summary field that is a list of dicts carrying a stratum label + a numeric metric."""
    for k, v in summary.items():
        if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            sample = v[0]
            lab = next((L for L in _STRATUM_LABELS if L in sample), None)
            met = next((M for M in _STRATUM_METRICS if isinstance(sample.get(M), (int, float))), None)
            if lab and met:
                return k, lab, met
    return None, None, None


def _top_k_strata(summary, indication, cfg):
    key = cfg.get("strata_array") if cfg else None
    if key and isinstance(summary.get(key), list):
        lab = cfg.get("strata_label"); met = cfg.get("strata_metric")
        arr = summary[key]
        sample = arr[0] if arr and isinstance(arr[0], dict) else {}
        lab = lab or next((L for L in _STRATUM_LABELS if L in sample), None)
        met = met or next((M for M in _STRATUM_METRICS if isinstance(sample.get(M), (int, float))), None)
    else:
        key, lab, met = _first_stratum_array(summary)
    if not (key and lab and met):
        return []
    ind = (indication or "").upper()
    keyed = [(str(r.get(lab)), _num(r.get(met)), r.get("n") or r.get("n_in_lineage") or r.get("n_models_screened"))
             for r in summary[key] if isinstance(r, dict) and isinstance(r.get(met), (int, float))]
    if not keyed:
        return []
    lower_is_stronger = met in ("median_chronos", "median_dep_score", "median_gene_effect")
    strongest = (min if lower_is_stronger else max)(keyed, key=lambda k: k[1])
    weakest = (max if lower_is_stronger else min)(keyed, key=lambda k: k[1])
    ind_row = next((k for k in keyed if k[0].upper() == ind or ind in k[0].upper()), None)
    rows, seen = [], set()
    for role, k in (("INDICATION", ind_row), ("extreme_strongest", strongest), ("extreme_weakest", weakest)):
        if k and k[0] not in seen:
            seen.add(k[0]); rows.append({"stratum": k[0], "metric": met, "value": k[1], "n": k[2], "role": role})
    return rows


def _numeric_anchors(summary, cfg):
    fields = (cfg or {}).get("anchor_fields")
    if fields:
        picked = [f for f in fields if f in summary]
    else:
        picked = sorted(k for k, v in summary.items()
                        if isinstance(v, (int, float)) and any(h in k.lower() for h in _ANCHOR_HINTS))[:4]
    return [{"metric": f, "value": _num(summary.get(f))} for f in picked]


def _n_basis(summary):
    ns = sorted(k for k, v in summary.items()
                if isinstance(v, (int, float)) and any(h in k.lower() for h in _N_HINTS))
    return {k: summary[k] for k in ns[:3]}


def _sibling_caveats(summary, cfg):
    allow = (cfg or {}).get("caveat_fields")
    out = {}
    for k, v in sorted(summary.items()):
        if k.startswith("_") or v is None or isinstance(v, (list, dict)):
            continue
        hit = (k in allow) if allow else any(h in k.lower() for h in _CAVEAT_HINTS)
        if hit:
            out[k] = _num(v)
    return out


def _provenance_keys(summary):
    prov = []
    for k, v in sorted(summary.items()):
        if any(h in k.lower() for h in _PROV_HINTS) and isinstance(v, (str, int, float)):
            prov.append({"key": k, "value": _num(v)})
    return prov[:5]


def _data_quality_flags(cid, summary, cfg):
    flags = []
    # generic: activating-direction field vs an inactivation/LoF state label on the same card
    direction = str(summary.get("functional_direction") or summary.get("patient_event_state") or "").lower()
    for k, v in summary.items():
        if k.endswith("_class") and isinstance(v, str) and "inactivation" in v.lower() and "activating" in direction:
            flags.append({"field": k, "value": v, "contradicts": f"functional_direction/state='{direction}'",
                          "flag": "activating-direction card carries a loss-of-function state label — do NOT narrate as LoF"})
    # config-supplied explicit checks: {"field": <name>, "expect_gt": n} style mis-bind guards
    for chk in (cfg or {}).get("dq_checks", []):
        f = chk.get("field")
        if f in summary and summary.get(f) is None:
            flags.append({"field": f, "value": None, "flag": chk.get("note", f"{f} is null on a scored card — possible mis-bind")})
    return flags


def _conflict_pairs(cards, classify):
    """Cross-card: same measurement_type, tier disagreement >=2 levels. Returns list keyed for each mt."""
    by_mt = {}
    for c in cards:
        cid = c.get("card_id"); summ = c.get("summary") or {}
        mt, tier = _card_meta(cid)
        if not mt or tier == "subtype":
            continue
        cls = next((summ.get(k) for k in summ if k.endswith("_class") and isinstance(summ.get(k), str)), None)
        if cls is None:
            continue
        by_mt.setdefault(mt, []).append((cid, cls, classify(cls)))
    out = {}
    for mt, members in by_mt.items():
        if len(members) < 2:
            continue
        tiers = {_TIERV[m[2]] for m in members}
        if max(tiers) - min(tiers) >= 2:
            for cid, cls, t in members:
                out.setdefault(cid, []).append({"measurement_type": mt, "other_sources":
                    [{"card": m[0], "class": m[1], "tier": m[2]} for m in members if m[0] != cid],
                    "this_class": cls, "this_tier": t, "conflict": True})
    return out


def emit_capsules(cards, indication=None, verdict_card_ids=None, config=None, classify=default_classify):
    """Return {'capsules': {card_id: capsule}, 'manifest': [...]}. `config` maps card_id -> per-card
    selector overrides (strata_array/label/metric, anchor_fields, caveat_fields, dq_checks). `verdict_card_ids`
    (set) get FULL capsules; others get THIN (signal + one anchor). Deterministic + hash-stable."""
    config = config or {}
    cards_sorted = sorted((c for c in cards if isinstance(c, dict)), key=lambda c: c.get("card_id") or "")
    conflicts = _conflict_pairs(cards_sorted, classify)
    capsules, manifest = {}, []
    for c in cards_sorted:
        cid = c.get("card_id")
        summ = c.get("summary") or {}
        mt, tier = _card_meta(cid)
        missing = bool(c.get("_missing")) or not summ
        if missing:
            manifest.append({"card_id": cid, "status": "absent",
                             "reason": "data_unavailable" if c.get("_missing") else "not_wired"})
            capsules[cid] = {"card_id": cid, "measurement_type": mt, "evidence_state": "data_unavailable",
                             "_complete": True}
            continue
        cls = next((summ.get(k) for k in sorted(summ) if k.endswith("_class") and isinstance(summ.get(k), str)), None)
        cfg = config.get(cid, {})
        full = verdict_card_ids is None or cid in verdict_card_ids
        cap = {
            "card_id": cid, "measurement_type": mt, "tier": tier, "evidence_state": "measured",
            "class": cls,
            "numeric_anchors": (_numeric_anchors(summ, cfg) or None),
            "n_basis": (_n_basis(summ) or None),
            "_complete": True,
        }
        if full:
            cap.update({
                "top_k_strata": (_top_k_strata(summ, indication, cfg) or None),
                "conflict_pairs": conflicts.get(cid) or None,
                "sibling_caveats": (_sibling_caveats(summ, cfg) or None),
                "provenance_keys": (_provenance_keys(summ) or None),
                "data_quality_flags": (_data_quality_flags(cid, summ, cfg) or None),
            })
        manifest.append({"card_id": cid, "status": "full" if full else "thin"})
        capsules[cid] = cap
    return {"capsules": capsules, "manifest": sorted(manifest, key=lambda m: m["card_id"])}
