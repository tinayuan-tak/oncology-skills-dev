"""evidence_capsule — a COMPLETE-but-LIMITED per-card data package for the LLM consumers.

Unifies the SIGNAL layer (sub-verdict + claim axis — already flowing via the narrator-input contract)
with a bounded DATA layer: 6 fixed deterministic SELECTOR SHAPES over each card's already-computed
fields. ONE emitter, read by BOTH the single-lens narrators and the retrieve-don't-recall cross-evidence
agent (each capsule row is a citable atom).

COMPLETE  : every verdict-feeding card emits a capsule; required-field-or-explicit-null; a card-floor
            manifest lists every card {full|thin|absent+reason} so completeness is auditable.
LIMITED   : fixed shapes, top-k, rounded, deduped, token-budgeted (verdict cards full, others thin).
HASH-STABLE: sorted card order, sorted rows, rounded floats, sorted-key JSON — plugs into the spine
            without perturbing prompt_hash.

Pure selection over resolved cards — no LLM, no network, no new computation. VERDICT-INERT.

The 6 selector shapes:
  1 top_k_strata       — a card's per-lineage/oncotree/stratum array → indication row + argmin + argmax
  2 numeric_anchors    — the load-bearing scalar(s) behind each class (effect/q/CI/percentile/n)
  3 categorical_anchors— config-declared salient non-numeric fields (stage labels, class enums, agent
                         lists) a numeric shape can't carry; None unless the card opts in
  4 conflict_pairs     — two cards on one measurement_type disagreeing in tier (with precedence)
  5 sibling_caveats    — caveat fields that qualify a favorable headline (escape/variability/…)
  6 provenance_keys    — distinct contributing sources + distinct_provenance_count
plus data_quality_flags — generic mis-bind / direction-inversion contradictions surfaced, not hidden.
"""

from __future__ import annotations

from _skills_common.display_gloss import gloss
from _skills_common.evidence_salience import (
    indication_stratum_aliases,
    round_keep_tiny,
    scale_for_field,
    sig_round,
    spec_for,
)
from _skills_common.subgroup_derivation import (
    _TIERV,
    _card_capsule_contract,
    _card_meta,
    default_classify,
    is_measured,
)

_R = 4  # float precision (hash-stability)
_STRATUM_LABELS = ("oncotree_code", "lineage", "stratum_id", "stratum", "subgroup", "cohort", "subtype")
_STRATUM_METRICS = (
    "median_chronos",
    "median_dep_score",
    "frac_dependent",
    "fraction_strongly_dependent",
    "median_log2fc",
    "log2_fc",
    "effect_size",
    "r2",
    "median",
    "value",
    "median_gene_effect",
)
_ANCHOR_HINTS = (
    "effect_size",
    "cohens_d",
    "q_value",
    "bh_q",
    "pvalue",
    "p_value",
    "percentile",
    "median",
    "fraction",
    "pearson_r",
    "spearman_r",
    "r_squared",
    "r2",
    "ci_lo",
    "ci_hi",
    "log2_fc",
    "log2fc",
    "frac_dependent",
    "variance_explained",
    "selectivity_index",
    "copies_per_cell",
    "pchembl",
    "ppv",
    "sensitivity",
    "specificity",
    "base_rate",
)
_N_HINTS = (
    "n_",
    "_n",
    "_samples",
    "_lines",
    "_cells",
    "_donors",
    "_models",
    "_evaluated",
    "_paired",
    "n_patient",
    "n_compounds",
    "n_ligands",
)
_CAVEAT_HINTS = (
    "escape",
    "variability",
    "consistency",
    "coverage",
    "buffering",
    "shed",
    "fragile",
    "heterogen",
    "purity",
    "confound",
    "conflict",
    "underpowered",
    "instability",
)
_PROV_HINTS = ("_source", "_data_source", "screens_contributing", "consortium", "product_id", "release_pin")
# Tier-3 echo/provenance denylist — request-echo + housekeeping fields that carry no evidence and must
# never masquerade as an anchor/caveat/categorical. Applied to the HEURISTIC selector branches only; a
# card that explicitly DECLARES a field (config / capsule contract) is honored verbatim.
_ECHO_DENYLIST = (
    "target",
    "indication",
    "method_version",
    "_method_version",
    "uniprot_ac",
    "uniprot_ac_resolved",
    "ensembl_gene_id",
    "entrez_gene_id",
    "source",
    "_source",
    "_data_source",
    "release_pin",
    "schema_version",
    "vocabulary_phase",
)


def _denied(k):
    kl = k.lower()
    return kl in _ECHO_DENYLIST or kl.startswith("_")


def _num(v):
    # `round(v, _R)` alone ANNIHILATED every p/q-value the capsule surfaces (round(2.25e-51, 4) == 0.0),
    # so the number shown as a card's decisive datum read "0" for its most significant results. Delegated
    # to ONE helper shared with the evidence_graph's key_evidence rounding rather than reimplemented here:
    # two roundings of the same numbers WILL drift, and they are compared side by side in the report.
    return round_keep_tiny(v, _R) if isinstance(v, float) else v


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


# significance keys a stratum row may carry, in preference order (the per-mt spec's field wins). Pinned
# because a strata row's q/p is the most-dropped decisive field (Stage-0 F1); _ANCHOR_HINTS never saw it.
_ROW_SIG_KEYS = ("q_value", "bh_q_value", "q", "gi_ttest_pvalue", "p_value", "pvalue", "p", "fdr")


def _row_significance(row, sig_field):
    """The significance value on a stratum row: the spec-named field first, then common q/p keys.
    Rounded to SIGNIFICANT figures (not decimals) so a tiny q like 3.8e-16 survives (round(_,4)==0.0)."""
    if sig_field and isinstance(row.get(sig_field), (int, float)) and not isinstance(row.get(sig_field), bool):
        return sig_round(row.get(sig_field))
    for k in _ROW_SIG_KEYS:
        if isinstance(row.get(k), (int, float)) and not isinstance(row.get(k), bool):
            return sig_round(row.get(k))
    return None


def _top_k_strata(summary, indication, cfg, spec=None, label_aliases=frozenset()):
    """Indication + strongest + weakest strata rows, each carrying its effect, n, and q. The array is
    pinned by the per-measurement_type salience spec (the significance-bearing one, e.g. enriched_lineages
    which carries q_value — NOT per_lineage_stats which doesn't), with the first-list-of-dicts heuristic as
    fallback. The INDICATION row is resolved via the crosswalk aliases (label_aliases) — a superset of the
    substring match that COADREAD⊄Bowel silently dropped."""
    spec = spec or {}
    key = (cfg.get("strata_array") if cfg else None) or spec.get("strata_array")
    if key and isinstance(summary.get(key), list) and summary.get(key):
        lab = (cfg or {}).get("strata_label") or spec.get("label_field")
        met = (cfg or {}).get("strata_metric") or spec.get("effect_field")
        arr = summary[key]
        sample = arr[0] if arr and isinstance(arr[0], dict) else {}
        lab = lab if lab in sample else next((L for L in _STRATUM_LABELS if L in sample), None)
        met = (
            met
            if isinstance(sample.get(met), (int, float))
            else next((M for M in _STRATUM_METRICS if isinstance(sample.get(M), (int, float))), None)
        )
    else:
        key, lab, met = _first_stratum_array(summary)
    if not (key and lab and met):
        return []
    sig_field = (cfg or {}).get("significance_field") or spec.get("significance_field")
    ind = (indication or "").upper()
    keyed = [
        (
            str(r.get(lab)),
            _num(r.get(met)),
            r.get("n") or r.get("n_in_lineage") or r.get("n_models_screened") or r.get("subgroup_n"),
            _row_significance(r, sig_field),
        )
        for r in summary[key]
        if isinstance(r, dict) and isinstance(r.get(met), (int, float))
    ]
    if not keyed:
        return []
    # Orient strongest/weakest. Apply the spec's `direction` ONLY when the array's metric IS the spec's
    # effect_field — otherwise (a sibling card that fell back to a DIFFERENT metric, e.g. crispr_lof_
    # dependency's spec is median_chronos=lower_is_stronger but organoid falls back to frac_dependent=
    # higher_is_stronger) the spec polarity would invert the ranking. Fall back to the metric-name heuristic.
    if met == spec.get("effect_field") and spec.get("direction") in ("lower_is_stronger", "higher_is_stronger"):
        lower_is_stronger = spec["direction"] == "lower_is_stronger"
    else:
        lower_is_stronger = met in ("median_chronos", "median_dep_score", "median_gene_effect")
    strongest = (min if lower_is_stronger else max)(keyed, key=lambda k: k[1])
    weakest = (max if lower_is_stronger else min)(keyed, key=lambda k: k[1])
    ind_row = next(
        (k for k in keyed if k[0].upper() in label_aliases or k[0].upper() == ind or (ind and ind in k[0].upper())),
        None,
    )
    rows, seen = [], set()
    for role, k in (("INDICATION", ind_row), ("extreme_strongest", strongest), ("extreme_weakest", weakest)):
        if k and k[0] not in seen:
            seen.add(k[0])
            row = {"stratum": k[0], "metric": met, "value": k[1], "n": k[2], "role": role}
            if k[3] is not None:
                row["q"] = k[3]
            rows.append(row)
    return rows


def _scale_for(measurement_type, field):
    """The machine-readable unit (`scale`) for an emitted numeric-anchor `field`, so the number is NEVER a
    bare scalar whose unit is knowable only from the metric NAME (Arm A gap 1, #1860). Resolution, most-
    authoritative first:
      1. the salience reference-frame RULER `scale` — the first-class unit token (log2FC, loeuf, percentile,
         copies_per_cell, fraction, …) the display graph already gauges against, wired here onto the emitted
         value (`evidence_salience.scale_for_field`);
      2. the `display_gloss` units hint — the framework's existing field→units registry for the L3 tail the
         rulers do not reach (a fraction/percentile/count/q-value whose unit is unambiguous from convention);
      3. `None` — an EXPLICIT 'unit not yet first-class' for the residual (e.g. a `median_*` effect the gloss
         deliberately leaves unitless). The `scale` KEY is still emitted, so the value carries a declared unit
         SLOT rather than being silently bare — the capsule-grain form of the claim_record no-bare-numbers
         invariant, enforced by `assert_no_bare_numbers`."""
    return scale_for_field(measurement_type, field) or gloss(field)[1] or None


def _numeric_anchors(summary, cfg, contract_anchors=(), measurement_type=None):
    """The capsule's numbers, in PRECEDENCE order: a per-card `config['anchor_fields']` runtime override
    first, then the card contract's `capsule.numeric_anchors` declaration, then the `_ANCHOR_HINTS`
    substring scan as the guess of last resort.

    The scan is a guess in three ways a declaration fixes, and all three were live on the genomic axis:
    it is ALPHABETICAL, so the class-setting number is surfaced only by luck; it is CAPPED AT 4, so
    mutation-stratified-dependency's 11 hint-matching fields crowded out its own headline gauges; and it
    cannot reach a field matching no hint at all, which made `cn_recurrent_deletion_score` — the value the
    `copy_number_class` cut is actually taken against — structurally unreachable.

    A declared list is honored VERBATIM: not re-sorted (declared order is reading order — effect, then the
    arms it separates, then significance, then the denominator) and not capped (the card schema caps it at
    8). A declared field that is missing or non-numeric in THIS run's summary is dropped rather than
    back-filled from the scan, because re-entering the scan would restore the very guess the declaration
    exists to replace — a card that declared would then show hint-picked numbers on exactly the runs where
    its own were unavailable, which is the silent failure this whole path is fixing."""
    fields = (cfg or {}).get("anchor_fields") or contract_anchors
    if fields:
        # Declared → honored verbatim in ORDER, but a declaration is trusted for SELECTION only, so the
        # same two floors as the scan still apply: the value must be a real number (a declaration naming a
        # categorical would otherwise render a class token — `splice_exon_skip_class = exon_skip` — or a
        # bool flag as a number), and `_denied` internals stay internal.
        picked = [
            f
            for f in fields
            if not _denied(f) and isinstance(summary.get(f), (int, float)) and not isinstance(summary.get(f), bool)
        ]
    else:
        picked = sorted(
            k
            for k, v in summary.items()
            if isinstance(v, (int, float)) and not _denied(k) and any(h in k.lower() for h in _ANCHOR_HINTS)
        )[:4]
    return [{"metric": f, "value": _num(summary.get(f)), "scale": _scale_for(measurement_type, f)} for f in picked]


def assert_no_bare_numbers(numeric_anchors):
    """The capsule-grain form of the claim_record schema's no-bare-numbers invariant (`magnitude.value`
    non-null ⇒ a unit is declared): every emitted numeric anchor that carries a `value` MUST also carry a
    `scale` KEY (its declared unit slot — a resolved token, or an explicit null for the not-yet-first-class
    tail). A `{metric, value}` entry with no `scale` key at all is a BARE NUMBER and is refused. Returns the
    anchors unchanged so it can wrap an emission; raises ValueError on the first bare number."""
    for a in numeric_anchors or ():
        if not isinstance(a, dict):
            continue
        if a.get("value") is not None and "scale" not in a:
            raise ValueError(
                f"capsule numeric_anchor {a.get('metric')!r} carries a value with no scale (no bare numbers)"
            )
    return numeric_anchors


def _n_basis(summary):
    ns = sorted(
        k
        for k, v in summary.items()
        if isinstance(v, (int, float)) and not _denied(k) and any(h in k.lower() for h in _N_HINTS)
    )
    return {k: summary[k] for k in ns[:3]}


def _categorical_anchors(summary, fields):
    """Emit the DECLARED salient non-numeric fields (stage labels, class enums, agent lists) verbatim.
    The numeric-anchor / n_basis shapes only surface floats/ints, so a card whose decision-relevant datum
    is a STRING (e.g. clinical-precedent.highest_clinical_stage='approved') or a LIST (approved_agents)
    was invisible to the capsule DATA layer. `fields` is the union of the card contract's `capsule.
    categorical_fields` (contracts-first) and any legacy config override; None/empty → None (byte-stable
    for every card that has not declared). List values are top-k capped for token budget; order preserved."""
    if not fields:
        return None
    out, seen = [], set()
    for f in fields:
        if f in seen or f not in summary:
            continue
        seen.add(f)
        v = summary[f]
        if isinstance(v, list):
            v = v[:6]
        out.append({"field": f, "value": v})
    return out or None


def _sibling_caveats(summary, cfg):
    allow = (cfg or {}).get("caveat_fields")
    out = {}
    for k, v in sorted(summary.items()):
        if _denied(k) or v is None or isinstance(v, (list, dict)):
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


def _cited_statements(summary, k: int = 3):
    """Surface a card's EXEMPLAR cited statements — the pmid/year/(truncated)sentence behind a literature
    card — from a `top_cited` summary list of statement dicts. This is the ONE piece of RAW SUBSTANCE a
    citation card carries that the numeric/categorical/provenance selectors above cannot express, so the
    narrator can LEAD with (and attribute to) the card's OWN cited statements rather than reporting them
    DATA_UNAVAILABLE. Data-shape gated: fires ONLY for a card whose summary has a non-empty `top_cited` list
    (today only cited-literature-evidence), so every other card's capsule is byte-identical. None when absent."""
    tc = summary.get("top_cited")
    if not isinstance(tc, list) or not tc:
        return None
    out = []
    for s in tc[:k]:
        if not isinstance(s, dict):
            continue
        pmid = s.get("pmid") or s.get("PMID")
        sent = s.get("sentence") or s.get("text") or ""
        if isinstance(sent, str) and len(sent) > 240:
            sent = sent[:237].rstrip() + "…"
        row = {
            "pmid": str(pmid) if pmid is not None else None,
            "year": s.get("year"),
            "section": s.get("section"),
            "sentence": sent or None,
        }
        out.append({kk: vv for kk, vv in row.items() if vv is not None})
    return out or None


def _data_quality_flags(cid, summary, cfg):
    flags = []
    # generic: activating-direction field vs an inactivation/LoF state label on the same card
    direction = str(summary.get("functional_direction") or summary.get("patient_event_state") or "").lower()
    for k, v in summary.items():
        if k.endswith("_class") and isinstance(v, str) and "inactivation" in v.lower() and "activating" in direction:
            flags.append(
                {
                    "field": k,
                    "value": v,
                    "contradicts": f"functional_direction/state='{direction}'",
                    "flag": "activating-direction card carries a loss-of-function state label — do NOT narrate as LoF",
                }
            )
    # config-supplied explicit checks: {"field": <name>, "expect_gt": n} style mis-bind guards
    for chk in (cfg or {}).get("dq_checks", []):
        f = chk.get("field")
        if f in summary and summary.get(f) is None:
            flags.append(
                {
                    "field": f,
                    "value": None,
                    "flag": chk.get("note", f"{f} is null on a scored card — possible mis-bind"),
                }
            )
    return flags


def _conflict_pairs(cards, classify):
    """Cross-card: same measurement_type, tier disagreement >=2 levels. Returns list keyed for each mt."""
    by_mt = {}
    for c in cards:
        cid = c.get("card_id")
        summ = c.get("summary") or {}
        mt, tier = _card_meta(cid)
        if not mt or tier == "subtype":
            continue
        cls = next((summ.get(k) for k in summ if k.endswith("_class") and isinstance(summ.get(k), str)), None)
        if cls is None:
            continue
        by_mt.setdefault(mt, []).append((cid, cls, classify(cls)))
    out = {}
    for mt, members in by_mt.items():
        # A card that did not MEASURE cannot DISAGREE. Abstentions are dropped before the spread test,
        # and two cards must still remain, or a single measured card would "conflict" with a coverage
        # gap. (This is why `unmeasured` is off the presence ordinal rather than a 5th rung of _TIERV:
        # any number here — including a below-`absent` -1 — makes every non-measurement a contradiction.)
        members = [m for m in members if is_measured(m[2])]
        if len(members) < 2:
            continue
        tiers = {_TIERV[m[2]] for m in members}
        if max(tiers) - min(tiers) >= 2:
            for cid, cls, t in members:
                out.setdefault(cid, []).append(
                    {
                        "measurement_type": mt,
                        "other_sources": [{"card": m[0], "class": m[1], "tier": m[2]} for m in members if m[0] != cid],
                        "this_class": cls,
                        "this_tier": t,
                        "conflict": True,
                    }
                )
    return out


def emit_capsules(cards, indication=None, verdict_card_ids=None, config=None, classify=default_classify):
    """Return {'capsules': {card_id: capsule}, 'manifest': [...]}. Field selection is CONTRACTS-FIRST: a
    card's optional `capsule:` block (primary_class + categorical_fields + numeric_anchors, read via
    _card_capsule_contract) drives the class-pick, the categorical_anchors AND the numeric_anchors; the hint
    heuristics + `config` overrides are the fallback for un-migrated cards. `config` maps card_id -> per-card selector overrides (strata_array/label/metric,
    anchor_fields, caveat_fields, categorical_fields, dq_checks). `verdict_card_ids` (set) get FULL capsules;
    others get THIN (signal + one anchor). Deterministic + hash-stable."""
    config = config or {}
    _aliases = indication_stratum_aliases(indication)  # crosswalk-resolved indication stratum labels (F2)
    cards_sorted = sorted((c for c in cards if isinstance(c, dict)), key=lambda c: c.get("card_id") or "")
    conflicts = _conflict_pairs(cards_sorted, classify)
    capsules, manifest = {}, []
    for c in cards_sorted:
        cid = c.get("card_id")
        summ = c.get("summary") or {}
        mt, tier = _card_meta(cid)
        missing = bool(c.get("_missing")) or not summ
        if missing:
            manifest.append(
                {"card_id": cid, "status": "absent", "reason": "data_unavailable" if c.get("_missing") else "not_wired"}
            )
            capsules[cid] = {
                "card_id": cid,
                "measurement_type": mt,
                "evidence_state": "data_unavailable",
                "_complete": True,
            }
            continue
        cfg = config.get(cid, {})
        # Contracts-first field selection: the card's optional `capsule:` block declares its verdict-driving
        # primary_class + salient categorical_fields. `primary_class` OVERRIDES the alphabetical-first *_class
        # heuristic (which mis-picks on multi-class cards — e.g. structure-features-static's
        # alphafold_confidence_class over structural_ligandability_class); the heuristic remains the fallback
        # for un-migrated cards. categorical_fields unions with any legacy config override (contract first),
        # and numeric_anchors REPLACES the alphabetical, cap-of-4 `_ANCHOR_HINTS` scan (see _numeric_anchors).
        primary_class, contract_cat, contract_anchors = _card_capsule_contract(cid)
        cls = None
        if primary_class and isinstance(summ.get(primary_class), str):
            cls = summ[primary_class]
        else:
            cls = next(
                (summ.get(k) for k in sorted(summ) if k.endswith("_class") and isinstance(summ.get(k), str)), None
            )
        cat_fields = list(contract_cat) + [f for f in (cfg.get("categorical_fields") or []) if f not in contract_cat]
        full = verdict_card_ids is None or cid in verdict_card_ids
        cap = {
            "card_id": cid,
            "measurement_type": mt,
            "tier": tier,
            "evidence_state": "measured",
            "class": cls,
            "numeric_anchors": (assert_no_bare_numbers(_numeric_anchors(summ, cfg, contract_anchors, mt)) or None),
            "categorical_anchors": _categorical_anchors(summ, cat_fields),
            "n_basis": (_n_basis(summ) or None),
            "_complete": True,
        }
        if full:
            cap.update(
                {
                    "top_k_strata": (_top_k_strata(summ, indication, cfg, spec_for(mt), _aliases) or None),
                    "conflict_pairs": conflicts.get(cid) or None,
                    "sibling_caveats": (_sibling_caveats(summ, cfg) or None),
                    "provenance_keys": (_provenance_keys(summ) or None),
                    "data_quality_flags": (_data_quality_flags(cid, summ, cfg) or None),
                    # RAW SUBSTANCE of a citation card — the exemplar cited statements (pmid/year/sentence) so the
                    # narrator can LEAD with the card's OWN cited statements. Data-shape gated (only a card with a
                    # `top_cited` summary list): every other card's capsule stays byte-identical.
                    "cited_statements": _cited_statements(summ),
                }
            )
        manifest.append({"card_id": cid, "status": "full" if full else "thin"})
        capsules[cid] = cap
    return {"capsules": capsules, "manifest": sorted(manifest, key=lambda m: m["card_id"])}
