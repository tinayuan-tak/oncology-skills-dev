#!/usr/bin/env python3
"""compose_dashboard — top-level orchestrator chaining phases 1, 2, 3 into one invocation.

Produces a complete evidence_package.json (validating against evidence_package.schema.json)
from a single user input (target + indication + optional modality + data_mode + release_pin).

Phase ordering per the layer-distinction discipline:
  Phase 1 (compose)   — emit run_plan.yaml
  Phase 2 (execute)   — invoke methods (or stubs); emit per-card outputs
  Phase 3 (synthesize) — apply modality synthesis_emphasis; emit synthesis block
  Final               — assemble evidence_package.json + validate

Output persistence (2026-07-02):
  --out defaults to the data-products repo:
    ~/rnd-computational-biology-oncology-data-products/{target}/{indication}/{package_id}/
  Per the data-products architecture (README, schemas/*, dashboard specs'
  destination: data-products/{target}/{indication}/{package_id}/), evidence
  packages and rendered dashboards land in that repo as the canonical
  provenance record. Users can still pass --out /tmp/... for scratch runs.

  After a successful landing (any run that produced an evidence_package.json,
  even with validation warnings), an INDEX.md at the target's directory root
  is upserted with a row summarizing (date, indication, package_id, class
  calls per fired card, headline). This gives a lightweight per-target
  provenance index without requiring a full database.

Usage:
    python -m scripts.compose_dashboard \\
        --target KRAS --indication COADREAD \\
        --data-mode latest_approved --execution-mode live
    (writes to data-products by default; add --out /tmp/... to override)
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml
from jsonschema import Draft202012Validator

SCRIPT_DIR = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(SCRIPT_DIR.parent))
    from scripts.compose_phase1 import build_run_plan, FRAMEWORK_VERSION, SKILL_VERSION  # type: ignore
    from scripts._execution import execute_run_plan, FIXTURES_DIR  # type: ignore
    from scripts._synthesis import synthesize  # type: ignore
    from scripts._resolution import TARGET_CONTRACTS  # type: ignore
else:
    from .compose_phase1 import build_run_plan, FRAMEWORK_VERSION, SKILL_VERSION
    from ._execution import execute_run_plan, FIXTURES_DIR
    from ._synthesis import synthesize
    from ._resolution import TARGET_CONTRACTS


# Data-products repo path — default persistence destination for evidence packages.
# See schemas/*.schema.json and dashboards/*.dashboard_spec.yaml `destination:` fields.
DATA_PRODUCTS_REPO = Path.home() / "rnd-computational-biology-oncology-data-products"


def _default_output_path(target: str, indication: str, package_id: str) -> Path:
    """Compute default --out per the data-products/{target}/{indication}/{package_id}/
    convention. package_id follows the schema's ep-{target}-{indication}-{release_pin}-
    {data_mode}-NNN.lower() format."""
    return DATA_PRODUCTS_REPO / target.upper() / indication.upper() / package_id


def _compute_package_id(target: str, indication: str, release_pin: Optional[str], data_mode: str) -> str:
    """Package id formation — mirrors _assemble_evidence_package's convention exactly.
    Extracted so --out can be computed BEFORE compose() runs (needed for the default)."""
    pin = release_pin or "unpinned"
    return f"ep-{target}-{indication}-{pin}-{data_mode}-001".lower()


def _upsert_target_index(
    target: str, indication: str, package_id: str, evidence_package: dict,
    out_path: Path, data_products_root: Path,
) -> Optional[Path]:
    """Upsert a row into INDEX.md at data-products/{target}/INDEX.md.

    One row per (indication, package_id) — later runs of the same package_id
    replace the earlier row. Row summarizes headline + per-card class calls.
    Returns the INDEX.md path (or None if not applicable — e.g. --out is
    outside the data-products tree, meaning the caller opted for scratch).
    """
    try:
        rel = out_path.resolve().relative_to(data_products_root.resolve())
    except (ValueError, RuntimeError):
        # --out is not inside the data-products tree; skip index update
        return None

    target_dir = data_products_root / target.upper()
    target_dir.mkdir(parents=True, exist_ok=True)
    index_path = target_dir / "INDEX.md"

    # Extract class calls from the evidence_package cards. Card outputs live under
    # `summary` (not `summary_fields` — that's the card SPEC's field, not the
    # evidence_package's card OUTPUT key). Excluded cards have no summary; skip.
    class_calls: dict[str, str] = {}
    for c in evidence_package.get("cards", []):
        if c.get("excluded_by_applies_when"):
            continue
        cid = c.get("card_id")
        summary = c.get("summary") or {}
        for key in ("dependency_class", "rnai_dependency_class", "concordance_class",
                     "expression_class", "cn_class", "mutation_class",
                     "correlation_class", "predictability_class",
                     "prism_activity_class", "prism_lineage_selectivity",
                     "crispr_prism_concordance_class", "enrichment_class"):
            if key in summary:
                class_calls[cid] = f"{key}={summary[key]}"
                break

    headline = (evidence_package.get("synthesis") or {}).get("headline") or ""
    generated_at = evidence_package.get("generated_at") or ""
    rel_str = str(rel).replace("\\", "/")

    # Read existing INDEX rows (if any)
    rows: list[dict] = []
    if index_path.exists():
        rows = _parse_existing_index(index_path)
    # Upsert (dedup on package_id)
    rows = [r for r in rows if r.get("package_id") != package_id]
    rows.append({
        "package_id": package_id,
        "indication": indication.upper(),
        "generated_at": generated_at,
        "headline": headline,
        "class_calls": class_calls,
        "path": rel_str,
    })
    # Sort newest-first by generated_at
    rows.sort(key=lambda r: r.get("generated_at", ""), reverse=True)

    # Render
    lines = [
        f"# {target.upper()} — evidence-package index",
        "",
        f"Per-run summary of framework outputs for `{target.upper()}` (target × indication).",
        f"Autogenerated by `compose_dashboard.py` on each successful run — do not edit by hand.",
        "",
        "| Generated | Indication | Package | Path | Class calls | Headline |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        calls = "; ".join(f"{cid}: {cc}" for cid, cc in r["class_calls"].items())
        # Pipe-escape to keep markdown table valid
        headline_esc = (r["headline"] or "").replace("|", "\\|")
        calls_esc = calls.replace("|", "\\|")
        lines.append(
            f"| {r['generated_at']} | {r['indication']} | `{r['package_id']}` | "
            f"[`{r['path']}`]({r['path']}/) | {calls_esc} | {headline_esc} |"
        )
    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def _parse_existing_index(index_path: Path) -> list[dict]:
    """Parse rows out of an existing INDEX.md. Table-row lines only; ignore
    header + separator. Best-effort — malformed rows are dropped silently
    (they'll be regenerated on the next run)."""
    rows: list[dict] = []
    for line in index_path.read_text().splitlines():
        if not line.startswith("| ") or line.startswith("| Generated") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != 6:
            continue
        gen_at, ind, pkg, path, calls, headline = cells
        pkg = pkg.strip("`")
        class_calls = {}
        for tok in calls.split(";"):
            tok = tok.strip()
            if ":" in tok:
                cid, cc = tok.split(":", 1)
                class_calls[cid.strip()] = cc.strip()
        # Path cell is written as [`rel/path`](rel/path/) — extract the content
        # between the first pair of backticks. The old strip("`").split("`")[0]
        # returned the literal "[" because strip only removes leading/trailing chars.
        m = re.search(r'`([^`]+)`', path)
        parsed_path = m.group(1) if m else path
        rows.append({
            "package_id": pkg,
            "indication": ind,
            "generated_at": gen_at,
            "headline": headline.replace("\\|", "|"),
            "class_calls": class_calls,
            "path": parsed_path,
        })
    return rows


def compose(
    target: str,
    indication: str,
    data_mode: str,
    release_pin: Optional[str],
    modality: Optional[str] = None,
    subgroup_spec: object = None,
    execution_mode: str = "stub",
    fixtures_dir: Path = FIXTURES_DIR,
    contracts_root: Path = TARGET_CONTRACTS,
    deterministic_timestamps: bool = False,
    out_path: Optional[Path] = None,
) -> tuple[dict, dict, list[str]]:
    """Run all 3 phases. Returns (run_plan, evidence_package, errors).

    If phase-1 produces an unresolved run_plan (axis unknown / modality incompatible),
    phase-2 still runs (executes 0 cards), and phase-3 emits the unresolved-synthesis.
    The evidence_package validates either way.
    """
    # Phase 1 — compose
    run_plan, phase1_errors = build_run_plan(
        target=target, indication=indication, data_mode=data_mode,
        release_pin=release_pin, modality=modality, subgroup_spec=subgroup_spec,
        contracts_root=contracts_root,
        deterministic_timestamps=deterministic_timestamps,
    )
    if phase1_errors:
        return run_plan, {}, [f"phase1: {e}" for e in phase1_errors]

    # Phase 2 — execute
    phase2_result = execute_run_plan(
        run_plan=run_plan,
        execution_mode=execution_mode,
        fixtures_dir=fixtures_dir,
        contracts_root=contracts_root,
        out_path=out_path,
    )

    # C3 fix (post-adversarial-review): validate each card output against
    # card_output.schema.json BEFORE phase-3 reads it. This closes the layer-
    # orthogonality gap — phase-3 cannot consume malformed phase-2 output.
    card_output_errors = _validate_card_outputs(
        phase2_result["cards"], contracts_root=contracts_root
    )
    if card_output_errors:
        # T6 fix (2026-08-11 engineering review): the errors used to be collected here and
        # then dropped into a bare `pass`, only reappearing (prefixed "phase2:") in the
        # returned list — easy to miss. Surface them to stderr the moment they're detected so
        # a malformed phase-2 output is visible even when a caller ignores the returned list.
        # We still assemble + synthesize (the errors propagate to the final errors list, and
        # main() writes .invalid artifacts + exits non-zero), but the failure is no longer silent.
        print(
            f"[compose-dashboard] {len(card_output_errors)} card_output(s) failed "
            f"card_output.schema validation BEFORE synthesis:",
            file=sys.stderr,
        )
        for e in card_output_errors:
            print(f"  - {e}", file=sys.stderr)

    # Phase 3 — synthesize
    # EG4 (iter-2): pass contracts_root so synthesis can read each card_spec's
    # interpretation_hints[i].dominant declarations for dominant-signal-plus-confirmation scoring.
    synthesis_block = synthesize(
        run_plan=run_plan,
        card_outputs=phase2_result["cards"],
        contracts_root=contracts_root,
    )

    # Final — assemble evidence_package
    evidence_package = _assemble_evidence_package(
        run_plan=run_plan,
        card_outputs=phase2_result["cards"],
        unavailable_cards=phase2_result.get("unavailable_cards", []),
        validation_summary=phase2_result["validation_summary"],
        synthesis_block=synthesis_block,
        deterministic_timestamps=deterministic_timestamps,
    )

    # Validate the evidence_package
    errors = _validate_evidence_package(evidence_package, contracts_root=contracts_root)
    # Append card_output validation errors (C3 fix) so they propagate to the caller
    if card_output_errors:
        errors = list(errors) + [f"phase2: {e}" for e in card_output_errors]
    return run_plan, evidence_package, errors


def _validate_card_outputs(card_outputs: list, contracts_root: Path) -> list[str]:
    """Validate each card output against card_output.schema.json.
    Returns list of error strings (empty if all valid). C3 fix (post-adversarial-review)."""
    schema_path = contracts_root / "schemas" / "card_output.schema.json"
    if not schema_path.exists():
        # T6 fix (2026-08-11 engineering review): card_output.schema.json is a COMMITTED
        # contract artifact — its absence is a broken checkout / misconfigured contracts_root,
        # not a backward-compat path. Previously this returned [] silently, disabling the whole
        # gate with no signal. Warn loudly; still return [] so a genuinely partial checkout
        # degrades rather than hard-crashes, but the disabled gate is now visible.
        print(
            f"[compose-dashboard] WARNING: card_output validation SKIPPED — schema not found "
            f"at {schema_path}. Card-output structural validation is DISABLED for this run.",
            file=sys.stderr,
        )
        return []
    with schema_path.open() as f:
        schema = json.load(f)
    v = Draft202012Validator(schema)
    errors = []
    for i, card in enumerate(card_outputs):
        for e in v.iter_errors(card):
            card_id = card.get("card_id", f"<index_{i}>")
            errors.append(f"[card_outputs[{i}] card_id={card_id}] {e.message}")
    return errors


def _assemble_evidence_package(
    run_plan: dict,
    card_outputs: list[dict],
    validation_summary: dict,
    synthesis_block: dict,
    deterministic_timestamps: bool,
    unavailable_cards: "list[dict] | None" = None,
) -> dict:
    """Build the evidence_package envelope from phase outputs.

    `unavailable_cards` (F, 2026-07-20): reasoned absences (unwired / data-blocked / etc.)
    collected by phase-2 separately from the synthesis-input card_outputs; emitted as
    card_unavailable envelope entries so a consumer can see WHY a card is absent instead of
    an opaque n_cards_failed integer.
    """
    ctx = run_plan["input_context"]
    target = ctx["target_symbol"]
    indication = ctx["indication"]
    data_mode = ctx["data_mode"]
    release_pin = ctx.get("release_pin") or "unpinned"

    package_id = f"ep-{target}-{indication}-{release_pin}-{data_mode}-001".lower()

    # Determine concurrence absence — iter-1b ships without concurrence by default.
    # 2026-08-10 REVIEW FIX (L3): do NOT advertise governance.lockfile_ref="lockfile.yaml" —
    # nothing in the pipeline ever WROTE that file, so the envelope pointed at a nonexistent
    # provenance artifact (phantom reproducibility claim). lockfile_ref is optional in the
    # evidence_package schema and the renderer guards it (`if gov.get("lockfile_ref")`), so
    # omitting it drops the phantom "Lockfile:" markdown line cleanly. When a real lockfile
    # writer lands, repopulate this key and the field/rendering return automatically.
    governance = {
        "data_mode": data_mode,
        "release_pin": release_pin,
        "validation_summary": validation_summary,
    }

    # Build context block — extract target identity from the target-identity-summary card if present
    target_identity_card = next(
        (c for c in card_outputs if c.get("card_id") == "target-identity-summary" and not c.get("excluded_by_applies_when")),
        None
    )
    if target_identity_card:
        s = target_identity_card.get("summary", {})
        target_block = {
            "symbol": s.get("resolved_hgnc_symbol", target),
            "hgnc_id": s.get("resolved_hgnc_id", 0) or 0,
        }
        if s.get("resolved_ensembl_id"):
            target_block["ensembl"] = s["resolved_ensembl_id"]
        if s.get("resolved_uniprot_canonical"):
            target_block["uniprot"] = s["resolved_uniprot_canonical"]
    else:
        # L4 fix (post-adversarial-review): no more hgnc_id=1 placeholder. When
        # target-identity-summary is missing/failed/excluded, the framework MUST NOT
        # fabricate an identity. We emit a clearly-marked placeholder hgnc_id that
        # downstream consumers can detect (-1 means "not resolved"; downstream renderer
        # and any consumer reading the package can branch on the negative value).
        # The evidence_package schema requires hgnc_id >= 1, so a value of -1 will
        # FAIL evidence_package validation — which is the right behavior: a package
        # missing target identity is not a valid governance-grade artifact.
        target_block = {"symbol": target, "hgnc_id": -1}

    context_block = {
        "target": target_block,
        "indication": {"oncotree_code": indication},
        "subgroup_spec": ctx.get("subgroup_spec"),
        "scope": "cancer_type",
    }

    # Build cards array — normalize each card_output into the evidence_package schema shape
    cards = []
    for c in card_outputs:
        if c.get("excluded_by_applies_when"):
            cards.append({
                "card_id": c["card_id"],
                "card_version": c.get("card_version", "n/a"),
                "excluded_by_applies_when": True,
                "exclusion_reason": c["exclusion_reason"],
            })
        else:
            entry = {
                "card_id": c["card_id"],
                "card_version": c.get("card_version", "1.0.0"),
                "validation_state": c["validation_state"],
                "summary": c.get("summary", {}),
                "interpretation_call": c.get("interpretation_call", "uninterpreted"),
                "caveats": c.get("caveats", []),
                "provenance": c.get("provenance", {"method_calls": [], "input_manifest_ids": []}),
            }
            if c.get("warning_ids"):
                entry["warning_ids"] = c["warning_ids"]
            if c.get("figures"):
                entry["figures"] = c["figures"]
            cards.append(entry)

    # Append reasoned-absence entries (F, 2026-07-20): the card_unavailable envelope variant.
    # A card whose live reader returned None (unwired) is no longer silently dropped to the
    # n_cards_failed integer — it appears here with a typed availability_state so a consumer
    # (and the deciding-axis router) can distinguish "not built yet" from a measured absence.
    for u in (unavailable_cards or []):
        cards.append({
            "card_id": u["card_id"],
            "card_version": u.get("card_version", "n/a"),
            "availability_state": u["availability_state"],
            "availability_reason": u.get("availability_reason", "unavailable"),
        })

    # Build the top-level evidence_package
    timestamp = "2026-06-26T00:00:00Z" if deterministic_timestamps else (
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    return {
        "package_id": package_id,
        "framework_version": FRAMEWORK_VERSION,
        "generated_at": timestamp,
        "generated_by": f"skills/compose-dashboard@{SKILL_VERSION}",
        "context": context_block,
        "governance": governance,
        "dashboard_spec_ref": run_plan["axis_resolution"].get("selected_base_dashboard") or "unresolved",
        "cards": cards,
        "synthesis": synthesis_block,
        # 2026-08-10 REVIEW FIX (L4): the pointer said "renderings/dashboard.md" but main() writes
        # the rendering to the package ROOT (out / "dashboard.md") — no renderings/ subdir is ever
        # created, so the self-describing pointer was wrong on every emitted package. Point at the
        # actual file. (Keeping the file at root; only the pointer was inconsistent.)
        "renderings": {"markdown": "dashboard.md"},
        "schema_version": 1,
    }


def _invoke_renderer(evidence_package: dict) -> str:
    """Load the render-evidence-package skill's renderer by explicit path and call it.

    The renderer lives in a sibling skill; we do not depend on its package layout.
    This is the decoupling discipline: evidence_package is the contract between
    compose-dashboard and any renderer.
    """
    import importlib.util
    renderer_path = (
        Path(__file__).resolve().parent.parent.parent
        / "render-evidence-package" / "scripts" / "render_markdown.py"
    )
    if not renderer_path.exists():
        raise FileNotFoundError(
            f"render-evidence-package skill not found at {renderer_path}. "
            "Install the renderer skill before invoking compose_dashboard."
        )
    spec = importlib.util.spec_from_file_location("_renderer_loaded", str(renderer_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.render_evidence_package(evidence_package)


def _validate_evidence_package(ep: dict, contracts_root: Path) -> list[str]:
    """Validate an evidence_package against evidence_package.schema.json."""
    schema_path = contracts_root / "schemas" / "evidence_package.schema.json"
    with schema_path.open() as f:
        schema = json.load(f)
    v = Draft202012Validator(schema)
    errors = []
    for e in v.iter_errors(ep):
        path_str = ".".join(str(p) for p in e.absolute_path) or "<root>"
        errors.append(f"[{path_str}] {e.message}")
    return errors


@click.command()
@click.option("--target", required=True)
@click.option("--indication", required=True)
@click.option("--data-mode", required=True, type=click.Choice(["latest_approved", "pinned", "exploratory"]))
@click.option("--release-pin", default=None)
@click.option("--modality", default=None,
              type=click.Choice(["small_molecule", "degrader", "adc", "bite_tce", "antibody"]))
@click.option("--subgroup-spec", default=None)
@click.option("--execution-mode", type=click.Choice(["stub", "live", "live-stub-fallback"]), default="stub",
              help="stub = fixtures; live = real data via _live_readers; live-stub-fallback = live first, stub for cards without live readers (iter-1b transitional mode)")
@click.option("--out", required=False, default=None, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory. Defaults to ~/rnd-computational-biology-oncology-data-products/"
                   "{target}/{indication}/{package_id}/ — the framework's canonical persistence path. "
                   "Pass an explicit path (e.g. /tmp/scratch/) for scratch runs.")
@click.option("--deterministic-timestamps", is_flag=True)
def main(target: str, indication: str, data_mode: str, release_pin: Optional[str],
         modality: Optional[str], subgroup_spec: Optional[str], execution_mode: str,
         out: Optional[Path], deterministic_timestamps: bool) -> int:
    """Full 3-phase orchestrator. Produces run_plan.yaml + evidence_package.json."""
    if subgroup_spec is None or subgroup_spec == "":
        sg = None
    elif subgroup_spec == "all":
        sg = "all"
    else:
        sg = [s.strip() for s in subgroup_spec.split(",") if s.strip()]

    # Compute default output path (data-products/{target}/{indication}/{package_id}/)
    # when --out not supplied. package_id formation MUST mirror _assemble_evidence_package
    # exactly so the resolved path == the package_id inside the evidence_package.
    if out is None:
        package_id = _compute_package_id(target, indication, release_pin, data_mode)
        out = _default_output_path(target, indication, package_id)
    out.mkdir(parents=True, exist_ok=True)
    run_plan, evidence_package, errors = compose(
        target=target, indication=indication, data_mode=data_mode,
        release_pin=release_pin, modality=modality, subgroup_spec=sg,
        execution_mode=execution_mode,
        deterministic_timestamps=deterministic_timestamps,
        out_path=out,
    )
    # C3 fix (post-adversarial-review): when validation errors are present, write artifacts
    # with .invalid suffix so downstream tools can structurally detect the broken state.
    # The CLI still exits non-zero, but disk artifacts no longer LIE about their validity.
    has_errors = bool(errors)
    plan_suffix = ".invalid.yaml" if has_errors else ".yaml"
    ep_suffix = ".invalid.json" if has_errors else ".json"
    plan_path = out / f"run_plan{plan_suffix}"
    ep_path = out / f"evidence_package{ep_suffix}"
    with plan_path.open("w") as f:
        yaml.safe_dump(run_plan, f, sort_keys=False, default_flow_style=False)
    with ep_path.open("w") as f:
        json.dump(evidence_package, f, indent=2, default=str)

    # Invoke render-evidence-package skill to produce the Stage-1 markdown rendering.
    # Per the decoupling discipline, the renderer is loaded by explicit path —
    # the orchestrator does not depend on render-evidence-package's package layout.
    md_path = out / "dashboard.md"
    try:
        md = _invoke_renderer(evidence_package)
        md_path.write_text(md, encoding="utf-8")
        rendering_status = f"rendered → {md_path}"
    except Exception as e:
        rendering_status = f"renderer failed: {e}"

    click.echo(f"=== compose_dashboard (3-phase orchestrator) ===")
    click.echo(f"  target:        {target}")
    click.echo(f"  indication:    {indication}")
    click.echo(f"  modality:      {modality or '(enumerate plausible)'}")
    click.echo(f"  execution:     {execution_mode}")
    click.echo(f"  axis:          {run_plan['axis_resolution']['status']} → {run_plan['axis_resolution']['resolved_axis']}")
    vs = evidence_package.get("governance", {}).get("validation_summary", {})
    click.echo(f"  cards:         {vs.get('n_cards_passed', 0)} pass, "
               f"{vs.get('n_cards_passed_with_warnings', 0)} warn, "
               f"{vs.get('n_cards_failed', 0)} fail, "
               f"{vs.get('n_cards_excluded_by_applies_when', 0)} excluded")
    syn = evidence_package.get("synthesis", {})
    click.echo(f"  headline:      {syn.get('headline', '(none)')[:120]}")
    click.echo(f"  → run_plan:    {plan_path}")
    click.echo(f"  → ev_package:  {ep_path}")
    click.echo(f"  → markdown:    {rendering_status}")

    # 2026-08-10 REVIEW FIX (L5): the INDEX upsert previously ran BEFORE the error gate, so a
    # package that FAILED validation (written as evidence_package.invalid.json) was still recorded
    # in the per-target INDEX.md as a successful landed product — the index header claims
    # "on each successful run", and a consumer following the link hit a dir with no valid
    # evidence_package.json. Gate the upsert on validation success: on errors, skip the index and
    # exit non-zero. (Still best-effort — index failure does not change exit status.)
    if errors:
        click.echo(f"\nEVIDENCE_PACKAGE VALIDATION ERRORS ({len(errors)}):", err=True)
        for e in errors:
            click.echo(f"  {e}", err=True)
        click.echo("  → index:       skipped (package failed validation)", err=True)
        return 1

    # Upsert per-target INDEX.md when writing inside the data-products tree (successful runs only).
    # Best-effort — index update failure does not affect exit status.
    try:
        pkg_id = evidence_package.get("package_id") or _compute_package_id(
            target, indication, release_pin, data_mode
        )
        index_path = _upsert_target_index(
            target=target, indication=indication, package_id=pkg_id,
            evidence_package=evidence_package, out_path=out,
            data_products_root=DATA_PRODUCTS_REPO,
        )
        if index_path is not None:
            click.echo(f"  → index:       {index_path}")
    except Exception as e:
        click.echo(f"  → index:       skipped ({type(e).__name__}: {e})", err=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
