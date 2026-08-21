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

# Shared evidence-package envelope writer. Extracted byte-preserving from the
# former local `_assemble_evidence_package` so sibling subskills can reuse it. Import via the
# skills/ dir on sys.path (same convention as compose_phase1/_execution/_synthesis use for
# _skills_common) — never a hardcoded /home path.
_SKILLS_DIR = SCRIPT_DIR.parent.parent  # scripts/ -> compose-dashboard/ -> skills/
if str(_SKILLS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILLS_DIR))
from _skills_common.envelope import assemble_evidence_package  # noqa: E402


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
        # Split on UNESCAPED pipes (the writer escapes a literal '|' in headline/class-calls as
        # '\|' to keep the markdown table valid), then unescape — otherwise a row whose headline
        # or class-calls contain a pipe splits into >6 cells and is silently dropped (and lost on
        # the next full re-render, since _upsert re-reads + re-writes the whole table).
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line)[1:-1]]
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

    # Validate each card output against card_output.schema.json BEFORE phase-3 reads it.
    # This closes the layer-orthogonality gap — phase-3 cannot consume malformed phase-2 output.
    card_output_errors = _validate_card_outputs(
        phase2_result["cards"], contracts_root=contracts_root
    )
    if card_output_errors:
        # 2026-08-11: the errors used to be collected here and
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
    # Pass contracts_root so synthesis can read each card_spec's
    # interpretation_hints[i].dominant declarations for dominant-signal-plus-confirmation scoring.
    # 2026-08-15 (safety fail-open): thread phase-2's reasoned-absence stubs
    # (read_error / not_wired) into synthesis so a modality killer-veto card that CRASHED
    # or is UNWIRED blocks the modality (non-concludable) instead of silently evaluating
    # fired=False and letting positive primary cards score it viable.
    synthesis_block = synthesize(
        run_plan=run_plan,
        card_outputs=phase2_result["cards"],
        contracts_root=contracts_root,
        unavailable_cards=phase2_result.get("unavailable_cards", []),
    )

    # Final — assemble evidence_package (shared writer in _skills_common/envelope.py).
    # compose-dashboard owns its producer identity: it passes FRAMEWORK_VERSION + its own
    # generated_by ("skills/compose-dashboard@<sha>") so the extracted writer stays reusable.
    evidence_package = assemble_evidence_package(
        input_context=run_plan["input_context"],
        dashboard_spec_ref=(run_plan["axis_resolution"].get("selected_base_dashboard") or "unresolved"),
        card_outputs=phase2_result["cards"],
        unavailable_cards=phase2_result.get("unavailable_cards", []),
        validation_summary=phase2_result["validation_summary"],
        synthesis_block=synthesis_block,
        deterministic_timestamps=deterministic_timestamps,
        framework_version=FRAMEWORK_VERSION,
        generated_by=f"skills/compose-dashboard@{SKILL_VERSION}",
    )

    # Validate the evidence_package
    errors = _validate_evidence_package(evidence_package, contracts_root=contracts_root)
    # Append card_output validation errors so they propagate to the caller
    if card_output_errors:
        errors = list(errors) + [f"phase2: {e}" for e in card_output_errors]
    return run_plan, evidence_package, errors


def _validate_card_outputs(card_outputs: list, contracts_root: Path) -> list[str]:
    """Validate each card output against card_output.schema.json (envelope) AND, when present, the
    card's per-card summary schema. Returns list of error strings (empty if all valid)."""
    schema_path = contracts_root / "schemas" / "card_output.schema.json"
    if not schema_path.exists():
        # 2026-08-11: card_output.schema.json is a COMMITTED
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
        card_id = card.get("card_id", f"<index_{i}>")
        for e in v.iter_errors(card):
            errors.append(f"[card_outputs[{i}] card_id={card_id}] {e.message}")
        # 2026-08-11: per-card summary-schema validation. OPT-IN — only cards that HAVE
        # a schemas/methods/<card_id>.summary.schema.json are checked, so partial rollout never
        # breaks unschematized cards. This is the "drift fails compose-time validation" gate that
        # DEVELOPMENT_GUIDELINES promised but that never existed. Skips excluded/unavailable
        # entries (they carry no summary).
        if isinstance(card, dict) and "summary" in card and not card.get("excluded_by_applies_when"):
            errors.extend(_validate_summary(card_id, card["summary"], contracts_root))
    return errors


def _validate_summary(card_id: str, summary: dict, contracts_root: Path) -> list[str]:
    """Validate one card's summary dict against schemas/methods/<card_id>.summary.schema.json,
    IF that schema exists (opt-in). Returns [] when the schema is absent (unschematized card)."""
    summary_schema_path = contracts_root / "schemas" / "methods" / f"{card_id}.summary.schema.json"
    if not summary_schema_path.exists():
        return []   # opt-in: card has no summary schema yet → not validated (current behavior)
    with summary_schema_path.open() as f:
        summary_schema = json.load(f)
    v = Draft202012Validator(summary_schema)
    return [f"[summary card_id={card_id}] {e.message}" for e in v.iter_errors(summary)]


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
    # When validation errors are present, write artifacts
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

    # 2026-08-10: the INDEX upsert previously ran BEFORE the error gate, so a
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
