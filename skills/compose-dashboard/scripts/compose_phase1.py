#!/usr/bin/env python3
"""compose_phase1 CLI — produce the deterministic run_plan.yaml for a target+indication+context.

Phase 1 of the compose-dashboard skill, per plan § Dashboard, Interpretation, Inference Layers.
NO method execution, NO synthesis — just resolution + composition + validation.

Usage:
    python -m skills.compose-dashboard.scripts.compose_phase1 \
        --target KRAS \
        --indication COADREAD \
        --data-mode pinned \
        --release-pin 2026-Q2 \
        --out /tmp/run_plan_kras_coadread/

Library use:
    from skills.compose_dashboard.scripts.compose_phase1 import build_run_plan
    plan, errors = build_run_plan(target='KRAS', indication='COADREAD', ...)
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml

# Support being invoked both as `python -m skills.compose-dashboard.scripts.compose_phase1`
# AND as `python scripts/compose_phase1.py` from the skill directory.
SCRIPT_DIR = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(SCRIPT_DIR.parent))
    from scripts._resolution import (  # type: ignore
        load_target_biology_axis, resolve_modality, load_dashboard_spec,
        load_modality_module, resolve_subgroup_catalog,
        TARGET_CONTRACTS, DATA_CATALOG,
    )
    from scripts._composition import compose_card_run_plan  # type: ignore
    from scripts._validation import validate_run_plan  # type: ignore
else:
    from ._resolution import (
        load_target_biology_axis, resolve_modality, load_dashboard_spec,
        load_modality_module, resolve_subgroup_catalog,
        TARGET_CONTRACTS, DATA_CATALOG,
    )
    from ._composition import compose_card_run_plan
    from ._validation import validate_run_plan


FRAMEWORK_VERSION = "2.0.0"


def _resolve_skill_version() -> str:
    """2026-08-11: populate the real short git SHA of the
    claude-oncology-skills repo instead of the hardcoded "0a1b2c3" placeholder, so
    evidence_package.generated_by identifies the code version that produced it. Falls back to
    the gitmeta UNKNOWN_SHA sentinel ("0000000") when git is unavailable — never blocks emit."""
    try:
        skills_dir = SCRIPT_DIR.parent.parent  # scripts/ -> compose-dashboard/ -> skills/
        if str(skills_dir) not in sys.path:
            sys.path.insert(0, str(skills_dir))
        from _skills_common.gitmeta import skills_repo_sha
        return skills_repo_sha()
    except Exception:  # noqa: BLE001 — provenance best-effort
        return "0000000"


SKILL_VERSION = _resolve_skill_version()   # real short git SHA (was hardcoded "0a1b2c3")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_run_plan(
    target: str,
    indication: str,
    data_mode: str,
    release_pin: Optional[str],
    modality: Optional[str] = None,
    subgroup_spec: object = None,
    contracts_root: Path = TARGET_CONTRACTS,
    catalog_root: Path = DATA_CATALOG,
    deterministic_timestamps: bool = False,
) -> tuple[dict, list[str]]:
    """Build the run_plan dict + return any validation errors.

    Returns (run_plan, errors). If errors is non-empty, the plan is still returned
    (for inspection) but is not schema-valid.
    """
    # 1. Axis resolution
    axis = load_target_biology_axis(target, contracts_root=contracts_root)

    # 2. Modality resolution
    modality_res = resolve_modality(axis, modality, contracts_root=contracts_root)

    # 3. If axis is unresolved/incompatible, emit a minimal run_plan and stop
    if axis.status != "resolved":
        plan = _build_minimal_unresolved_plan(
            target=target, indication=indication, data_mode=data_mode,
            release_pin=release_pin, modality=modality, subgroup_spec=subgroup_spec,
            axis=axis, modality_res=modality_res,
            deterministic_timestamps=deterministic_timestamps,
        )
        errors = validate_run_plan(plan, contracts_root=contracts_root)
        return plan, errors

    # 4. Modality incompatibility: same minimal-plan path
    if modality_res.mode == "incompatible_modality_for_axis":
        plan = _build_minimal_unresolved_plan(
            target=target, indication=indication, data_mode=data_mode,
            release_pin=release_pin, modality=modality, subgroup_spec=subgroup_spec,
            axis=axis, modality_res=modality_res,
            deterministic_timestamps=deterministic_timestamps,
        )
        errors = validate_run_plan(plan, contracts_root=contracts_root)
        return plan, errors

    # 5. Load the base dashboard_spec
    dashboard_spec = load_dashboard_spec(axis.selected_base_dashboard, contracts_root=contracts_root)

    # 6. Load each modality module (one for user_specified, multiple for enumerated_plausible)
    loaded_modules = []
    for mod_name in modality_res.plausible_modalities:
        try:
            mod = load_modality_module(mod_name, contracts_root=contracts_root)
            loaded_modules.append(mod)
        except FileNotFoundError as e:
            # Module path missing — record as loaded with a note (phase-2 will fail loudly)
            click.echo(f"WARNING: modality module for {mod_name!r} not found: {e}", err=True)

    # 7. Resolve subgroup catalog
    sg_resolution = resolve_subgroup_catalog(indication, subgroup_spec, catalog_root=catalog_root)

    # 8. Compose card run plan
    card_plan = compose_card_run_plan(
        dashboard_spec=dashboard_spec,
        loaded_modules=loaded_modules,
        subgroup_spec=subgroup_spec,
        subgroup_resolution=sg_resolution,
        contracts_root=contracts_root,
    )

    # 9. Assemble synthesis_directives
    synthesis_prompts = dashboard_spec.get("synthesis_prompts", [])
    per_modality_emphasis = [
        {"modality": m["modality_module"], "emphasis": m.get("synthesis_emphasis", {})}
        for m in loaded_modules
    ]

    # 10. Build the final run_plan
    plan = {
        "run_plan_id": f"rp-{target.lower()}-{indication.lower()}-{(release_pin or 'unpinned').lower()}-{data_mode}-001",
        "framework_version": FRAMEWORK_VERSION,
        "generated_at": "2026-06-26T00:00:00Z" if deterministic_timestamps else _now_iso(),
        "generated_by": f"skills/compose-dashboard@{SKILL_VERSION}",
        "input_context": {
            "target_symbol": target,
            "indication": indication,
            "modality": modality,
            "subgroup_spec": subgroup_spec,
            "data_mode": data_mode,
            "release_pin": release_pin,
        },
        "axis_resolution": _axis_to_dict(axis),
        "modality_resolution": _modality_to_dict(modality_res),
        "loaded_modality_modules": [_module_summary(m) for m in loaded_modules],
        "subgroup_resolution": sg_resolution,
        "card_run_plan": card_plan,
        "synthesis_directives": {
            "synthesis_prompts": synthesis_prompts,
            "per_modality_emphasis": per_modality_emphasis,
        },
        "schema_version": 1,
    }

    errors = validate_run_plan(plan, contracts_root=contracts_root)
    return plan, errors


def _build_minimal_unresolved_plan(
    target, indication, data_mode, release_pin, modality, subgroup_spec,
    axis, modality_res, deterministic_timestamps: bool,
) -> dict:
    """Build a minimal valid run_plan when axis is unknown/incompatible OR modality
    is incompatible with axis. Records the failure state structurally for audit."""
    return {
        "run_plan_id": f"rp-{target.lower()}-{indication.lower()}-{(release_pin or 'unpinned').lower()}-{data_mode}-unresolved",
        "framework_version": FRAMEWORK_VERSION,
        "generated_at": "2026-06-26T00:00:00Z" if deterministic_timestamps else _now_iso(),
        "generated_by": f"skills/compose-dashboard@{SKILL_VERSION}",
        "input_context": {
            "target_symbol": target,
            "indication": indication,
            "modality": modality,
            "subgroup_spec": subgroup_spec,
            "data_mode": data_mode,
            "release_pin": release_pin,
        },
        "axis_resolution": _axis_to_dict(axis),
        "modality_resolution": _modality_to_dict(modality_res),
        "loaded_modality_modules": [],
        "subgroup_resolution": {
            "subgroup_catalog_ref": None,
            "catalog_status": "not_requested",
            "resolved_strata_ids": [],
            "applicable_data_sources": [],
        },
        "card_run_plan": {
            "to_run": [],
            "excluded_at_compose": [],
            "failed_at_compose": [],
        },
        "synthesis_directives": {
            "synthesis_prompts": [],
            "per_modality_emphasis": [],
        },
        "schema_version": 1,
    }


def _axis_to_dict(axis) -> dict:
    return {
        "status": axis.status,
        "resolved_axis": axis.resolved_axis,
        "lookup_source": axis.lookup_source,
        **({"lookup_rationale": axis.lookup_rationale} if axis.lookup_rationale else {}),
        **({"selected_base_dashboard": axis.selected_base_dashboard} if axis.selected_base_dashboard else {"selected_base_dashboard": None}),
        **({"fallback_reason": axis.fallback_reason} if axis.fallback_reason else {}),
    }


def _modality_to_dict(mr) -> dict:
    d = {
        "mode": mr.mode,
        "compatibility_source": mr.compatibility_source,
    }
    if mr.user_specified_modality is not None:
        d["user_specified_modality"] = mr.user_specified_modality
    if mr.plausible_modalities:
        d["plausible_modalities"] = mr.plausible_modalities
    if mr.incompatibility_reason:
        d["incompatibility_reason"] = mr.incompatibility_reason
    return d


def _module_summary(module: dict) -> dict:
    additional = module.get("additional_cards") or []
    return {
        "modality": module["modality_module"],
        "module_path": f"target-contracts/dashboards/modality-modules/{module['modality_module']}.module.yaml",
        "module_version": module.get("version", "unknown"),
        "headline_decision_question": module.get("headline_decision_question", ""),
        "additional_card_ids": [a["card_id"] for a in additional],
        "threshold_overlays_summary": [
            {"card_id": k, "overlay": v}
            for k, v in (module.get("threshold_overlays") or {}).items()
        ],
        "synthesis_emphasis": module.get("synthesis_emphasis", {}),
        # 2026-08-11: carry the module's modality_specific_caveats
        # into the run_plan so phase-3 synthesis can actually aggregate them. Previously this
        # field was dropped here, so _build_caveats_summary's "for module in
        # loaded_modality_modules" loop had nothing to read (its body was a no-op `pass`).
        "modality_specific_caveats": module.get("modality_specific_caveats", []) or [],
    }


@click.command()
@click.option("--target", required=True, help="HGNC symbol (e.g., KRAS, TROP2).")
@click.option("--indication", required=True, help="OncoTree code (e.g., COADREAD, PDAC, NSCLC).")
@click.option("--data-mode", required=True, type=click.Choice(["latest_approved", "pinned", "exploratory"]))
@click.option("--release-pin", default=None, help="Catalog release_pin (required for pinned mode).")
@click.option("--modality", default=None,
              type=click.Choice(["small_molecule", "degrader", "adc", "bite_tce", "antibody"]),
              help="Optional modality. If unspecified, framework enumerates plausible modalities.")
@click.option("--subgroup-spec", default=None,
              help="Either 'all', null (omit flag), or a comma-separated list of subgroup_ids.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory; run_plan.yaml lands here.")
@click.option("--deterministic-timestamps", is_flag=True,
              help="Use fixed timestamp '2026-06-26T00:00:00Z' for reproducible test fixtures.")
def main(target: str, indication: str, data_mode: str, release_pin: Optional[str],
         modality: Optional[str], subgroup_spec: Optional[str], out: Path,
         deterministic_timestamps: bool) -> int:
    """Phase-1 CLI: emit run_plan.yaml for a target+indication+context."""
    # Parse subgroup_spec
    if subgroup_spec is None or subgroup_spec == "":
        sg = None
    elif subgroup_spec == "all":
        sg = "all"
    else:
        sg = [s.strip() for s in subgroup_spec.split(",") if s.strip()]

    plan, errors = build_run_plan(
        target=target, indication=indication, data_mode=data_mode,
        release_pin=release_pin, modality=modality, subgroup_spec=sg,
        deterministic_timestamps=deterministic_timestamps,
    )

    out.mkdir(parents=True, exist_ok=True)
    plan_path = out / "run_plan.yaml"
    with plan_path.open("w") as f:
        yaml.safe_dump(plan, f, sort_keys=False, default_flow_style=False)

    click.echo(f"=== compose_phase1 ===")
    click.echo(f"  target:     {target}")
    click.echo(f"  indication: {indication}")
    click.echo(f"  modality:   {modality or '(unspecified — enumerate plausible)'}")
    click.echo(f"  axis:       {plan['axis_resolution']['status']} → {plan['axis_resolution']['resolved_axis']}")
    click.echo(f"  modality mode: {plan['modality_resolution']['mode']}")
    n_run = len(plan["card_run_plan"]["to_run"])
    n_excl = len(plan["card_run_plan"]["excluded_at_compose"])
    n_fail = len(plan["card_run_plan"]["failed_at_compose"])
    click.echo(f"  cards: {n_run} to run, {n_excl} excluded, {n_fail} failed")
    click.echo(f"  → wrote: {plan_path}")

    if errors:
        click.echo(f"\nRUN_PLAN VALIDATION ERRORS ({len(errors)}):", err=True)
        for e in errors:
            click.echo(f"  {e}", err=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
