#!/usr/bin/env python3
"""depmap-mutation-drug-response CLI — genotype × PRISM DRUG-RESPONSE biomarker.

The PHARMACOLOGICAL sibling of mutation-stratified-dependency. Instead of asking "are
mutant lines more genetically DEPENDENT (Chronos)?", it asks "are mutant lines more
SENSITIVE to a DRUG that targets this gene (PRISM Log2AUC)?" — closing the biomarker→
drug-response gap (every prior biomarker contrast used DepMap genetic dependency ONLY;
PRISM was genotype-blind by design).

Design: reuse the proven substrate-agnostic contrast verbatim. depmap_mutation_dependency.
_mannwhitney_stratification takes a {ModelID → score} vector + a {ModelID → bool} stratifier;
here the score is PRISM Log2AUC (lower = more drug-sensitive, SAME direction as lower Chronos
= more dependent), so the whole primitive (forward + second-pass reverse + BH + effect size +
classification-performance + uncomputable-flag) applies unchanged. Only the compound-selection
+ per-line aggregation is new (read.py).

On-target compound selection: PRISM CompoundList GeneSymbolOfTargets == target gene
(e.g. BRAF → VEMURAFENIB/DABRAFENIB/ENCORAFENIB, annotated "inhibitor of BRAF p.V600E").
Best-responder aggregation (min Log2AUC across on-target compounds) is the primary phenotype.

Emits a drug_response_stratification_class + the raw stat fields + the on-target compound
provenance. This is a DRUG-RESPONSE biomarker — a genotype predicting SENSITIVITY to a
target-directed compound — distinct from (and stronger evidence than) the CRISPR dependency
biomarker, because it reflects an actual pharmacologic agent, not gene knockout.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"
METHODS_REPO = METHOD_DIR.parent.parent
if str(METHODS_REPO) not in sys.path:
    sys.path.insert(0, str(METHODS_REPO))

from methods.depmap_mutation_drug_response.read import (
    load_drug_response_by_model,
    load_on_target_compounds,
)

# Drug-response effect-size thresholds on the Log2AUC scale. Log2AUC is compressed into
# (-inf, 0]; a MUTANT-more-sensitive shift is a negative delta (mutant median below WT).
# Calibrated to the precompute's documented anchors (BRAF Skin Log2AUC median ~ -0.50;
# near-flat/inactive > -0.05). We use delta thresholds MILDER than the Chronos ones
# (-0.5/-0.2) because Log2AUC dynamic range is narrower than Chronos.
STRONG_EFFECT_DELTA = -0.20  # mutant median Log2AUC >= 0.20 below WT → strong sensitivity shift
MODERATE_EFFECT_DELTA = -0.08
STRATIFICATION_ALPHA = 0.05
MIN_MUTANT_LINES = 5
MIN_WILDTYPE_LINES = 30


def classify_drug_response(
    delta: float | None,
    q: float | None,
    q_reverse: float | None,
    insufficient: bool,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
) -> str:
    """Map a computed mutant-vs-WT drug-response contrast to a class token.

    Pure threshold logic over the stratification kernel's outputs (``delta`` = mutant median minus
    WT median on the Log2AUC scale, ``q``/``q_reverse`` the forward/reverse one-sided significances,
    ``insufficient`` the kernel's power flag). Split out of ``compute_drug_response_stratification``
    so the classification DIRECTIONS can be tested without scipy — the kernel that produces
    ``delta``/``q`` needs scipy, but the boundary logic that turns them into a verdict does not, and
    a module-level ``importorskip('scipy')`` used to skip those assertions silently."""
    if insufficient:
        return "insufficient_mutant_or_drug_data"
    if delta is None:
        return "not_drug_response_stratified"
    # FORWARD: mutant more SENSITIVE (lower Log2AUC → negative delta).
    if q is not None and q < stratification_alpha:
        if delta <= strong_effect_delta:
            return "mutant_strongly_drug_sensitive"
        if delta <= moderate_effect_delta:
            return "mutant_moderately_drug_sensitive"
    # REVERSE (second pass): mutant more RESISTANT (WT more sensitive) — a real resistance-
    # biomarker signal. Gated on reverse q + a strong POSITIVE delta.
    if q_reverse is not None and q_reverse < stratification_alpha and delta >= -strong_effect_delta:
        return "mutant_drug_resistant"
    return "not_drug_response_stratified"


def compute_drug_response_stratification(
    drug_response_by_model: dict,
    hotspot_by_model: dict,
    damaging_by_model: dict,
    compound_records: list = None,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
    min_mutant: int = MIN_MUTANT_LINES,
    min_wildtype: int = MIN_WILDTYPE_LINES,
) -> dict:
    """Genotype × drug-response stratification via the shared Mann-Whitney primitive.

    Uses the 'any mutation' vector (hotspot OR damaging) — for a drug-SENSITIVITY biomarker the
    relevant question is 'does carrying an alteration predict drug sensitivity', and the hotspot/
    damaging distinction (which matters for oncogene-addiction GoF vs LoF in the dependency path)
    is less load-bearing here; the class name is direction-explicit regardless."""
    from methods.depmap_common.boolean_stratification import mannwhitney_stratification

    compound_records = compound_records or []
    any_by_model = {}
    for m in set(hotspot_by_model) | set(damaging_by_model):
        any_by_model[m] = bool(hotspot_by_model.get(m) or damaging_by_model.get(m))

    res = mannwhitney_stratification(
        drug_response_by_model,
        any_by_model,
        min_positive=min_mutant,
        min_comparator=min_wildtype,
    )
    q = res.get("p_value")  # single test → q == p (no multi-tier BH)
    q_reverse = res.get("p_value_reverse")
    delta = res.get("delta_mut_vs_wt")

    cls = classify_drug_response(
        delta,
        q,
        q_reverse,
        bool(res.get("_insufficient_data")),
        strong_effect_delta=strong_effect_delta,
        moderate_effect_delta=moderate_effect_delta,
        stratification_alpha=stratification_alpha,
    )
    return {
        "drug_response_stratification_class": cls,
        "n_mutant": res["n_mutant"],
        "n_wildtype": res["n_wildtype"],
        "median_log2auc_mutant": res["median_mutant"],
        "median_log2auc_wildtype": res["median_wildtype"],
        "delta_log2auc_mut_vs_wt": delta,
        "drug_response_mannwhitney_p": res.get("p_value"),
        "drug_response_mannwhitney_q": q,
        "drug_response_mannwhitney_q_reverse": q_reverse,
        "drug_response_effect_size": res.get("effect_size"),
        # drug-SENSITIVITY classification performance (reuses the primitive's confusion matrix;
        # here "responder" = Log2AUC <= the dependency_threshold -0.5 the primitive uses — a
        # deep-responder cut on the same scale). Labeled DRUG-RESPONSE, not dependency/clinical.
        "drug_response_ppv": res.get("dependency_ppv"),
        "drug_response_ppv_lift": res.get("dependency_ppv_lift"),
        "drug_response_sensitivity": res.get("dependency_sensitivity"),
        "drug_response_specificity": res.get("dependency_specificity"),
        "drug_response_base_rate": res.get("dependency_base_rate"),
        "_uncomputable": bool(res.get("_uncomputable")),
        # provenance: which PRISM compounds defined the on-target drug-response vector
        "n_on_target_compounds": len(compound_records),
        "on_target_compounds": [
            {"name": r.get("name"), "moa": r.get("target_or_mechanism")}
            for r in compound_records
            if not r.get("_live_read_error")
        ][:20],
    }


def _no_compound_summary(target: str, reason: str) -> dict:
    return {
        "drug_response_stratification_class": "no_on_target_compound",
        "n_on_target_compounds": 0,
        "on_target_compounds": [],
        "_note": reason,
    }


@click.command()
@click.option("--target", required=True)
@click.option("--indication", required=True)
@click.option("--release-pin", default="26q1")
@click.option("--out", required=True, type=click.Path())
@click.option("--aggregate", default="best", type=click.Choice(["best", "median"]))
def main(target, indication, release_pin, out, aggregate) -> int:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    click.echo(f"depmap-mutation-drug-response: {target} / {indication} ({release_pin})")

    # 1. select on-target PRISM compounds
    sample_ids, compound_records = load_on_target_compounds(release_pin, target)
    load_err = [r for r in compound_records if isinstance(r, dict) and r.get("_live_read_error")]
    if load_err:
        summary = _no_compound_summary(target, str(load_err[0]))
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        _emit_manifest(target, indication, release_pin, summary, out)
        return 2
    if not sample_ids:
        summary = _no_compound_summary(target, "no PRISM compound targets this gene")
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        _emit_manifest(target, indication, release_pin, summary, out)
        return 0

    # 2. per-ModelID drug-response vector
    drug_response_by_model, dr_errs = load_drug_response_by_model(release_pin, sample_ids, aggregate)
    if dr_errs or not drug_response_by_model:
        summary = _no_compound_summary(target, str(dr_errs[:1]) if dr_errs else "no measured drug response")
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        _emit_manifest(target, indication, release_pin, summary, out)
        return 2

    # 3. mutation status (reuse the dependency method's loader verbatim)
    from methods.depmap_mutation_dependency.cli import load_mutation_data

    hotspot, damaging, mut_errs = load_mutation_data(release_pin, target)
    if mut_errs:
        summary = _no_compound_summary(target, f"mutation load failed: {mut_errs[:1]}")
        summary["drug_response_stratification_class"] = "data_unavailable"
        (out / "summary.json").write_text(json.dumps(summary, indent=2))
        _emit_manifest(target, indication, release_pin, summary, out)
        return 2

    summary = compute_drug_response_stratification(drug_response_by_model, hotspot, damaging, compound_records)
    summary["aggregate_metric"] = aggregate
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _emit_manifest(target, indication, release_pin, summary, out)
    click.echo(
        f"  class={summary['drug_response_stratification_class']} "
        f"delta={summary.get('delta_log2auc_mut_vs_wt')} "
        f"n_compounds={summary['n_on_target_compounds']}"
    )
    return 0


def _emit_manifest(target, indication, release_pin, summary, out):
    import yaml

    (out / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "method": "depmap-mutation-drug-response",
                "method_version": METHOD_VERSION,
                "target": target,
                "indication": indication,
                "release_pin": release_pin,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "input_manifests": ["depmap-consortium-26q1", "prism-oncref-dmc-25q4"],
                "drug_response_stratification_class": summary.get("drug_response_stratification_class"),
                "n_on_target_compounds": summary.get("n_on_target_compounds"),
            },
            sort_keys=False,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
