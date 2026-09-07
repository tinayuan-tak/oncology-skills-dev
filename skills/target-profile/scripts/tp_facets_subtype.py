"""tp_facets — subtype / subgroup facet cluster (split out of tp_facets.py for readability; byte-identical).
Re-exported by tp_facets, so `from tp_facets import *` and existing imports are unaffected."""

from __future__ import annotations

from pathlib import Path


from tp_common import _CONTRACTS_REPO
from tp_fanout import SUBTYPE_SHORT


_SUBTYPE_INPUTS = [
    ("expression", "tumor-rna-distribution-by-subtype", "expression"),
    ("dependency", "subgroup-stratified-dependency", "dependency"),
    ("genomic_alteration", "subgroup-stratified-mutation-frequency", "mutation_frequency"),
]


def _first_card_per_subgroup(sub_result: dict, card_id: str) -> list:
    """Return the named card's per_subgroup_metrics list (records per molecular subtype), or []."""
    for c in sub_result.get("cards") or []:
        if c.get("card_id") == card_id:
            return (c.get("summary") or {}).get("per_subgroup_metrics") or []
    return []


def _subtype_rows(sub_results: dict, short: str, card_id: str) -> list:
    """The per-molecular-subtype panorama rows for one axis, read spine-first (contract §197-223): a
    sub-skill that carries its subtype sub-vector on the skill_report[] SPINE
    (`synthesis_facet.skill_report.claim_chips_by_subtype`) is preferred; otherwise fall back to the
    card `per_subgroup_metrics` under the per-gate short, then the composed subtype tier (SUBTYPE_SHORT,
    where the target-profile fan-out centralizes the subtype cards — that tier carries no skill_report).
    Byte-identical: the spine sub-vector is the SAME per_subgroup rows the card emits."""
    r = sub_results.get(short) or {}
    spine = ((r.get("synthesis_facet") or {}).get("skill_report") or {}).get("claim_chips_by_subtype")
    if spine:
        return list(spine)
    for _src in (short, SUBTYPE_SHORT):
        rr = sub_results.get(_src)
        if rr:
            rows = _first_card_per_subgroup(rr, card_id)
            if rows:
                return rows
    return []


def _backfill_subtype_spine(sub_results: dict) -> None:
    """Composed-path fast-follow (contract §197-223, fast-follow to the #953 spine re-point): populate
    each OWNING skill's `skill_report.claim_chips_by_subtype` from the resolved subtype-grain rows, so the
    per-skill spine carries its own subtype sub-vector in the COMPOSED profile — not only the
    `target_report.subtype_convergence` rollup. Mutates sub_results in place; VERDICT-INERT; idempotent.

    WHY a composer-side back-fill (not per-skill emission): the target-profile fan-out resolves the
    dependency + mutation-frequency subtype cards CENTRALLY under `subtype_fit` (they are not re-run inside
    functional-requirement / genomic-alteration), so those skills' own `_synthesis_facet` has no subtype
    rows to emit — per-skill emission cannot fix the composed path. The expression subtype card DOES resolve
    inside tumor-presence, but its `skill_report` still leaves the slot None. This reads each axis's rows via
    the SINGLE source of truth (`_subtype_rows`, spine-first with the card fallback) and writes them onto the
    OWNING short's `skill_report`, so `_subtype_rows`' spine-first branch fires in production rather than the
    `SUBTYPE_SHORT` card fallback.

    BYTE-IDENTICAL: the written rows EQUAL what `_subtype_facet` already reads via `_subtype_rows` (the
    card fallback), so `subtype_convergence` + the nomination are unchanged; only the previously-None
    per-skill slot fills. No-op without a `--subtypes` scope (no subtype rows resolve → nothing written).
    Idempotent: a short whose skill_report already carries a sub-vector (e.g. a standalone-emitting skill)
    is left untouched (`_subtype_rows` would return that same spine anyway)."""
    for short, card_id, _axis in _SUBTYPE_INPUTS:
        r = sub_results.get(short)
        if not isinstance(r, dict):
            continue
        sr = (r.get("synthesis_facet") or {}).get("skill_report")
        if not isinstance(sr, dict) or sr.get("claim_chips_by_subtype"):
            continue  # no skill_report to fill, or a sub-vector already present (idempotent)
        rows = _subtype_rows(sub_results, short, card_id)
        if rows:
            sr["claim_chips_by_subtype"] = list(rows)


def _subtype_stratum_key(rec: dict) -> str | None:
    """The molecular-subtype identity of a per_subgroup_metrics record. subgroup_common panorama rows
    (dependency / mutation-frequency) use `stratum`; the tumor-rna-distribution-by-subtype reader
    (tcga_gtex_expression_distribution) uses `stratum_id`. Both must be recognized or the expression
    axis silently drops from the convergence facet. Tolerates a few further historical aliases. None if
    unidentifiable."""
    for k in ("stratum", "stratum_id", "subgroup_id", "subgroup_label", "subgroup"):
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _load_subtype_crosswalk(indication: str, contracts_repo: Path | None = None) -> dict:
    """Load the indication's block from vocabularies/subtype_crosswalk.yaml. Returns
    {associations: [...], axis_of: {stratum: axis}, cohorts_of: {stratum: [cohorts]}} or empty dicts
    when the registry / indication is absent (graceful — the facet degrades to exact-match only)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "subtype_crosswalk.yaml"
    out = {"associations": [], "axis_of": {}, "cohorts_of": {}}
    if not path.exists():
        return out
    try:
        import yaml

        doc = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return out
    for ind in doc.get("indications", []) or []:
        if ind.get("canonical_code") != indication:
            continue
        out["associations"] = ind.get("associations", []) or []
        for ax in ind.get("axes", []) or []:
            for s in ax.get("strata", []) or []:
                out["axis_of"][s] = ax.get("axis")
                out["cohorts_of"][s] = ax.get("cohorts", []) or []
        break
    return out


def _subtype_facet(sub_results: dict, indication: str = None, contracts_repo: Path | None = None) -> dict:
    """Assemble the per-molecular-subtype CONVERGENCE facet. Deterministic;
    additive; VERDICT-INERT (a synthesis facet, never a gate — informs patient-selection confidence,
    never mints a nominate). Converges the three subtype-grain panoramas BY SUBTYPE:

      per_subtype: {subtype: {axes_measured: [...], axes_present: [...], n_axes_measured, metrics:{}}}
      convergent_subtypes: subtypes with >= 2 MEASURED axes on the SAME stratum id (the strong claim)
      associated_subtypes: pairs of DIFFERENT strata (each measured on its own axis) linked by a
        subtype_crosswalk association (enriched_in / co_defining) — the WEAK, cohort-bridged claim
        that lets MSI_H(dependency, DepMap) relate to CMS1(expression, TCGA) WITHOUT claiming they
        are the same stratum. Each carries the relationship + a cohort_bridge flag when the two axes
        live on different cohorts (e.g. DepMap dependency vs TCGA expression).
      verdict:
        convergent_stratification  — >=1 subtype with >=2 measured axes on the SAME id (strongest)
        associated_stratification  — no same-id convergence, but >=1 registry-linked measured pair
        single_axis_stratification — measured subtype signal on only one axis, no association
        no_subtype_signal          — panoramas present but no measured stratum on any axis
        subtype_axis_unavailable   — no subtype shard reached for this indication (coverage gap)

    Absence is HONEST: a subtype/axis with no measured record contributes nothing (never fabricated).
    The association tier NEVER collapses two strata into one — it reports them as related, with the
    relationship type + cohort bridge explicit, so a CMS finding is never mislabeled an MSI finding."""
    xwalk = (
        _load_subtype_crosswalk(indication, contracts_repo)
        if indication
        else {"associations": [], "axis_of": {}, "cohorts_of": {}}
    )
    per_subtype: dict = {}
    axes_seen: set = set()
    any_rows = False
    chips_by_subtype: dict = {}  # {axis: rows} — the per-axis subtype spine (exposed for the renderer)
    for short, card_id, axis in _SUBTYPE_INPUTS:
        # Read the axis's subtype panorama SPINE-FIRST (`skill_report.claim_chips_by_subtype`), falling
        # back to the card `per_subgroup_metrics` under the per-gate short, then SUBTYPE_SHORT where the
        # target-profile fan-out centralizes the subtype cards (that composed tier carries no
        # skill_report). See `_subtype_rows`. Byte-identical to the former direct card reach-in.
        rows = _subtype_rows(sub_results, short, card_id)
        if rows:
            any_rows = True
            axes_seen.add(axis)
            chips_by_subtype[axis] = rows
        for rec in rows:
            subtype = _subtype_stratum_key(rec)
            if not subtype:
                continue
            state = rec.get("evidence_state")
            block = per_subtype.setdefault(subtype, {"axes_measured": [], "axes_present": [], "metrics": {}})
            block["axes_present"].append(axis)
            # carry the axis metric (whatever numeric/class the panorama row exposes beyond bookkeeping)
            metric = {
                k: v
                for k, v in rec.items()
                if k
                not in (
                    "stratum",
                    "stratum_id",
                    "subgroup_id",
                    "subgroup_label",
                    "subgroup",
                    "subgroup_n",
                    "subgroup_n_floor_met",
                    "evidence_state",
                    "source_cohort",
                )
                and v is not None
            }
            if metric:
                block["metrics"][axis] = metric
            if state == "measured":
                block["axes_measured"].append(axis)

    for block in per_subtype.values():
        block["axes_measured"] = sorted(set(block["axes_measured"]))
        block["axes_present"] = sorted(set(block["axes_present"]))
        block["n_axes_measured"] = len(block["axes_measured"])

    convergent = sorted(st for st, b in per_subtype.items() if b["n_axes_measured"] >= 2)
    any_measured = any(b["n_axes_measured"] >= 1 for b in per_subtype.values())

    # ── Association tier (registry-bridged, WEAK): different strata each measured on their own axis,
    # linked by a subtype_crosswalk enriched_in / co_defining association. This is what lets
    # MSI_H(dependency) relate to CMS1(expression) across the vocabulary/cohort gap WITHOUT claiming
    # they are the same stratum. Only strata that are actually MEASURED here participate.
    measured_axes_of = {st: set(b["axes_measured"]) for st, b in per_subtype.items() if b["n_axes_measured"] >= 1}
    associated_pairs = []
    for assoc in xwalk["associations"]:
        a, b_, rel = assoc.get("from"), assoc.get("to"), assoc.get("relationship")
        if rel not in ("enriched_in", "co_defining"):
            continue
        # both endpoints must be measured, and on DIFFERENT axes (else it's not a cross-axis bridge)
        if a not in measured_axes_of or b_ not in measured_axes_of:
            continue
        axes_a, axes_b = measured_axes_of[a], measured_axes_of[b_]
        cross_axis = bool(axes_a - axes_b) or bool(axes_b - axes_a)
        if not cross_axis:
            continue
        # cohort bridge: the two strata's registry cohorts don't overlap (e.g. DepMap dep vs TCGA expr)
        coh_a, coh_b = set(xwalk["cohorts_of"].get(a, [])), set(xwalk["cohorts_of"].get(b_, []))
        cohort_bridge = bool(coh_a and coh_b and not (coh_a & coh_b))
        associated_pairs.append(
            {
                "from": a,
                "to": b_,
                "relationship": rel,
                "from_axes_measured": sorted(axes_a),
                "to_axes_measured": sorted(axes_b),
                "cohort_bridge": cohort_bridge,
                "note": assoc.get("note", ""),
            }
        )

    if not any_rows:
        verdict = "subtype_axis_unavailable"
    elif convergent:
        verdict = "convergent_stratification"
    elif associated_pairs:
        verdict = "associated_stratification"
    elif any_measured:
        verdict = "single_axis_stratification"
    else:
        verdict = "no_subtype_signal"

    return {
        "verdict": verdict,
        "convergent_subtypes": convergent,
        "associated_subtypes": associated_pairs,
        "n_subtypes_evaluated": len(per_subtype),
        "axes_available": sorted(axes_seen),
        "per_subtype": per_subtype,
        # the per-axis subtype spine that fed the convergence JOIN ({axis: per_subgroup rows}), exposed so
        # the renderer + roll-up provenance read the SAME rows off target_report.subtype_convergence
        # rather than re-reaching into cards (contract §197-223). Empty when no subtype panorama reached.
        "claim_chips_by_subtype": chips_by_subtype,
        "_disclaimer": (
            "Subtype is a FACET, not a gate: it converges the per-molecular-subtype "
            "panoramas (expression / dependency / mutation-frequency) BY SUBTYPE to "
            "surface cross-axis patient-selection strata. It informs confidence + "
            "patient-selection, never mints a nominate. convergent_subtypes = subtypes "
            "with >=2 MEASURED axes on the SAME stratum id (strong). associated_subtypes "
            "= DIFFERENT strata each measured on its own axis, linked by a "
            "subtype_crosswalk enriched_in/co_defining association (weak, cohort-bridged) "
            "— reported as RELATED, never as the same stratum (a CMS finding is never "
            "relabeled an MSI finding); cohort_bridge=true flags a DepMap-vs-TCGA cross. "
            "subtype_axis_unavailable = no shard for this indication (coverage gap), not "
            "a measured negative."
        ),
    }


def _subgroup_flip_view(sub_results: dict) -> dict:
    """Descriptive per-stratum heterogeneity view (only under --subtypes). Reports the POOLED
    dependency verdict alongside the subtype panorama's per-stratum rows, so a reader can see when a
    pooled call hides a stratified pattern ("pooled non_dependent, but stratum X shows a measured
    dependency"). DESCRIPTIVE, not a re-resolved per-stratum verdict: it surfaces the panorama's own
    per_subgroup_metrics (evidence_state + metric); the resolver-backed subtype call is
    subtype_fit_verdict. (A full per-stratum re-resolution is the deferred Tier-1 heterogeneity work.)"""
    dep = sub_results.get("dependency") or {}
    dep_v = dep.get("verdict")
    subtype_r = sub_results.get(SUBTYPE_SHORT) or {}
    subtype_v = subtype_r.get("verdict")
    rows = []
    for rec in _first_card_per_subgroup(subtype_r, "subgroup-stratified-dependency"):
        st = _subtype_stratum_key(rec)
        if not st:
            continue
        rows.append(
            {
                "stratum": st,
                "evidence_state": rec.get("evidence_state"),
                "subgroup_n_floor_met": rec.get("subgroup_n_floor_met"),
                "metric": {
                    k: v
                    for k, v in rec.items()
                    if k
                    not in (
                        "stratum",
                        "subgroup_id",
                        "subgroup_label",
                        "subgroup",
                        "subgroup_n",
                        "subgroup_n_floor_met",
                        "evidence_state",
                        "source_cohort",
                    )
                    and v is not None
                },
            }
        )
    return {
        "pooled_dependency_verdict": dep_v[0] if dep_v else None,
        "subtype_fit_verdict": subtype_v[0] if subtype_v else None,
        "per_stratum_dependency": rows,
        "_note": (
            "Descriptive per-stratum view (--subtypes): the subtype panorama's own "
            "per_subgroup_metrics beside the POOLED dependency verdict, to expose a stratified "
            "pattern the pooled call hides. NOT a re-resolved per-stratum verdict; the "
            "resolver-backed subtype call is subtype_fit_verdict."
        ),
    }


def _rollup_subtype_block(subtype_facet: "Optional[dict]") -> dict:
    """A PROMINENT subtype block for the roll-up headline: which molecular strata carry convergent
    multi-axis signal, which axes are stratified (honest coverage), and a one-line headline. Subtype
    is a FACET not a gate — this surfaces it prominently without letting it move the block/verdict."""
    sf = subtype_facet or {}
    convergent = sf.get("convergent_subtypes") or []
    axes_avail = sf.get("axes_available") or []
    n_eval = sf.get("n_subtypes_evaluated") or 0
    status = sf.get("verdict") or ("no_subtype_signal" if not n_eval else None)
    if convergent:
        headline = (
            f"{len(convergent)} convergent subtype stratum"
            f"{'a' if len(convergent) != 1 else ''}: {', '.join(convergent[:4])}"
            + (" …" if len(convergent) > 4 else "")
            + f" (multi-axis agreement; stratified axes: {', '.join(axes_avail) or '—'})"
        )
        prominence = "convergent"
    elif n_eval:
        headline = (
            f"{n_eval} subtype stratum{'a' if n_eval != 1 else ''} evaluated; no multi-axis "
            f"convergence yet (stratified axes: {', '.join(axes_avail) or '—'})"
        )
        prominence = "evaluated_no_convergence"
    else:
        headline = "Whole-cohort — no molecular-subtype stratification wired for this target-indication"
        prominence = "whole_cohort"
    return {
        "prominence": prominence,
        "headline": headline,
        "status": status,
        "convergent_subtypes": convergent,
        "associated_subtypes": sf.get("associated_subtypes") or [],
        "stratified_axes": axes_avail,
        "n_subtypes_evaluated": n_eval,
        "_note": "Subtype is a FACET, not a gate — surfaced prominently; never moves block/verdict. Only "
        "the expression axis is stratified today (coverage gap flagged in stratified_axes).",
    }
