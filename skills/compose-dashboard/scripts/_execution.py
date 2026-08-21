"""compose-dashboard phase-2 execution helpers.

Phase-2 takes a run_plan (from phase-1) and produces per-card outputs that phase-3
synthesizes. Two execution modes:

  - stub: emit pre-authored summary metrics from fixtures (auth-session-runnable;
          no R env, no real data needed). Used for testing the synthesis pipeline.
  - live: in-process import of the method module (`methods.<name>`) via the
          _live_readers dispatch layer (EXECUTION-session work; requires
          real data + pixi envs + method implementations). NOT a subprocess — the
          seam is a direct Python function call; see _live_readers.py.

For each card in run_plan.card_run_plan.to_run, this module:
  1. Loads the card_spec to access interpretation_hints + summary_fields
  2. Obtains a summary dict (from fixtures in stub mode; via the in-process live
     reader in live mode)
  3. Applies interpretation_hints (with any applied_threshold_overlays) → interpretation_call
  4. Evaluates warning_predicates → warning_ids
  5. Emits a card_output dict matching evidence_package.cards[] schema
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from ._resolution import load_card_spec, TARGET_CONTRACTS

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def execute_run_plan(
    run_plan: dict,
    execution_mode: str = "stub",
    fixtures_dir: Path = FIXTURES_DIR,
    contracts_root: Path = TARGET_CONTRACTS,
    out_path: Optional[Path] = None,
) -> dict:
    """Execute every card in the run_plan and return a dict with:
        cards:                list[dict]  (one entry per executed card)
        validation_summary:   dict        (n_passed, n_passed_with_warnings, n_failed, n_excluded)

    The cards list mixes card_present and card_excluded entries per evidence_package schema.

    execution_mode:
      - 'stub'        — read pre-authored summary fixtures (auth-session-friendly)
      - 'live'        — read real data products via _live_readers.CARD_READERS;
                        cards without a live reader fall through to None (marked failed)
      - 'live-stub-fallback' — try live first; if no live reader exists for a card,
                                fall back to its stub fixture. Useful while some cards
                                are live and others are still stub.

    Subgroup_resolution from the run_plan is now
    extracted and passed to live readers via the subgroup_context parameter, so
    cards like subgroup-stratified-expression actually receive the resolved strata
    set and can stratify their analyses. In stub mode, subgroup_context is currently
    not consumed (fixtures already encode stratified output); the execution
    session wires live readers that consume the context.
    """
    if execution_mode not in ("stub", "live", "live-stub-fallback"):
        raise ValueError(
            f"execution_mode must be 'stub', 'live', or 'live-stub-fallback', got {execution_mode!r}"
        )

    target = run_plan["input_context"]["target_symbol"]
    indication = run_plan["input_context"]["indication"]
    # Extract subgroup_resolution from the run_plan and make it available to dispatchers.
    # The subgroup_context carries the resolved strata + applicable data sources so
    # subgroup-aware cards (subgroup-stratified-expression, rwd-stratified-expression)
    # can wire to the correct assignment Parquets in live mode.
    subgroup_context = run_plan.get("subgroup_resolution", {}) or {}
    # 2026-08-11: extract data_mode + release_pin from the run_plan and
    # make them available to live readers as a data_context dict, so a reader/dispatcher can
    # resolve WHICH manifest version to read (via catalog_query.resolve_release). Previously these
    # flowed only into ID strings and never reached the data-access layer. Threaded the SAME way
    # subgroup_context is (kwarg + TypeError back-compat shim) so no existing dispatcher breaks.
    _ictx = run_plan.get("input_context", {}) or {}
    data_context = {
        "data_mode": _ictx.get("data_mode"),
        "release_pin": _ictx.get("release_pin"),
    }

    card_outputs: list[dict] = []
    unavailable_cards: list[dict] = []   # structured card_unavailable stubs (not synthesis inputs)
    n_passed = 0
    n_passed_with_warnings = 0
    n_failed = 0
    n_excluded = len(run_plan["card_run_plan"]["excluded_at_compose"])

    # 1. Include excluded entries (carry over from phase-1)
    for excl in run_plan["card_run_plan"]["excluded_at_compose"]:
        card_outputs.append({
            "card_id": excl["card_id"],
            "card_version": "n/a",
            "excluded_by_applies_when": True,
            "exclusion_reason": excl["exclusion_reason"],
        })

    # 2. Execute each card in to_run
    for plan_entry in run_plan["card_run_plan"]["to_run"]:
        card_id = plan_entry["card_id"]
        card_spec, _ = load_card_spec(card_id, contracts_root=contracts_root)

        # Obtain summary per execution_mode
        # Pass subgroup_context to live readers so subgroup-aware cards can
        # consume the resolved strata + assignment Parquet paths.
        summary = None
        if execution_mode == "stub":
            summary = _load_stub_summary(card_id, target, indication, fixtures_dir)
        elif execution_mode == "live":
            summary = _read_live_summary(card_id, target, indication, subgroup_context=subgroup_context, data_context=data_context)
        elif execution_mode == "live-stub-fallback":
            # Try live first; if no live reader OR live read errored, fall back to stub
            summary = _read_live_summary(card_id, target, indication, subgroup_context=subgroup_context, data_context=data_context)
            if summary is None or (isinstance(summary, dict) and "_live_read_error" in summary):
                summary = _load_stub_summary(card_id, target, indication, fixtures_dir)

        # 2026-08-11: a live reader that RAISED returns a
        # truthy {"_live_read_error": ...} sentinel (see _live_readers.read_live_summary).
        # In pure `live` mode that dict is non-None, so without this guard it flowed past
        # the `if summary is None` check below, through _evaluate_interpretation_hints, and
        # was emitted as a validation_state:"pass" card — a crashed method reading as a
        # GREEN verdict. Detect the sentinel in ALL live modes (live-stub-fallback already
        # tried the stub above; if it's STILL an error dict, the stub was absent too) and
        # route to a first-class card_unavailable stub with availability_state=read_error,
        # exactly like the not_wired path. An error is never a pass.
        if isinstance(summary, dict) and "_live_read_error" in summary:
            n_failed += 1
            unavailable_cards.append({
                "card_id": card_id,
                "card_version": plan_entry.get("card_version", "n/a"),
                "availability_state": "read_error",
                "availability_reason": str(summary.get("_live_read_error", "live_read_error")),
            })
            continue

        if summary is None:
            # No live dispatcher registered for this card_id (read_live_summary returns
            # None when CARD_DISPATCHERS.get(card_id) is None) — the card is UNWIRED (a
            # framework-coverage gap), e.g. fusion-rearrangement-landscape (placeholder card,
            # no method). Previously this was silently dropped to the n_cards_failed integer
            # with NO per-card reason. Now record a structured availability stub
            # (2026-07-20) carrying a typed availability_state, surfaced as a card_unavailable
            # envelope entry so a consumer can distinguish "not built yet" from a measured
            # absence. Kept SEPARATE from card_outputs (the synthesis-input stream): an
            # unwired card has no signal to interpret, so it must not enter card_call_map /
            # the signal matrix (and it is not a valid card_output per card_output.schema —
            # present-or-excluded only). Still counted in n_cards_failed for tally back-compat.
            n_failed += 1
            unavailable_cards.append({
                "card_id": card_id,
                "card_version": plan_entry.get("card_version", "n/a"),
                "availability_state": "not_wired",
                "availability_reason": "dispatcher_returned_none",
            })
            continue

        # Apply interpretation_hints (with applied_threshold_overlays)
        thresholds = plan_entry.get("applied_threshold_overlays", {}) or {}
        interpretation_call = _evaluate_interpretation_hints(card_spec, summary, thresholds)

        # Evaluate warning_predicates
        warning_ids = _evaluate_warning_predicates(card_spec, summary, thresholds)

        validation_state = "passed_with_warnings" if warning_ids else "pass"
        if validation_state == "pass":
            n_passed += 1
        else:
            n_passed_with_warnings += 1

        card_output = {
            "card_id": card_id,
            "card_version": plan_entry.get("card_version", "1.0.0"),
            "validation_state": validation_state,
            "summary": summary,
            "interpretation_call": interpretation_call,
            "caveats": card_spec.get("caveats", []) or [],
            "warning_ids": warning_ids,
            "provenance": {
                "method_calls": _provenance_method_calls(plan_entry, execution_mode=execution_mode),
                "input_manifest_ids": _provenance_input_manifests(card_spec),
            },
        }

        # Figure emission (best-effort augmentation; only when out_path is provided
        # AND a per-card emitter is registered AND the summary contains real data,
        # not a _live_read_error). Failures are absorbed — no figure ≠ no card.
        if out_path is not None:
            import sys as _sys
            _skills_dir = Path(__file__).resolve().parent.parent.parent  # scripts->compose-dashboard->skills
            if str(_skills_dir) not in _sys.path:
                _sys.path.insert(0, str(_skills_dir))
            from _skills_common._figure_emitters import emit_figures_for_card
            figures = emit_figures_for_card(card_id, summary, out_path, target, indication)
            if figures:
                card_output["figures"] = figures

        card_outputs.append(card_output)

    n_attempted = n_passed + n_passed_with_warnings + n_failed
    return {
        "cards": card_outputs,
        "unavailable_cards": unavailable_cards,   # reasoned absences → card_unavailable envelope entries
        "validation_summary": {
            "n_cards_attempted": n_attempted,
            "n_cards_passed": n_passed,
            "n_cards_passed_with_warnings": n_passed_with_warnings,
            "n_cards_failed": n_failed,
            "n_cards_excluded_by_applies_when": n_excluded,
        },
    }


def _load_stub_summary(card_id: str, target: str, indication: str,
                        fixtures_dir: Path) -> Optional[dict]:
    """Load a stub summary for (card_id, target, indication) from fixtures.

    Fixture layout: fixtures_dir/stubs/{target}_{indication}.yaml mapping card_id → summary dict.
    Returns None if no fixture is found OR the specific card_id is missing from an existing fixture.

    Emit a diagnostic to stderr naming the expected
    fixture path so users hitting "all cards failed" understand why and what to author.
    """
    import sys
    fixture_path = fixtures_dir / "stubs" / f"{target}_{indication}.yaml".lower()
    if not fixture_path.exists():
        print(
            f"[compose-dashboard:stub] MISSING FIXTURE for ({target}, {indication}). "
            f"Expected: {fixture_path}. To enable stub execution for this pair, author the "
            f"fixture as a YAML mapping card_id -> summary_dict. All cards will be marked "
            f"failed until the fixture exists.",
            file=sys.stderr,
        )
        return None
    with fixture_path.open() as f:
        all_stubs = yaml.safe_load(f) or {}
    summary = all_stubs.get(card_id)
    if summary is None:
        print(
            f"[compose-dashboard:stub] FIXTURE {fixture_path.name} EXISTS but is missing "
            f"card_id={card_id!r}. Card will be marked failed. Add this card to the fixture.",
            file=sys.stderr,
        )
    return summary


def _read_live_summary(card_id: str, target: str, indication: str,
                        subgroup_context: Optional[dict] = None,
                        data_context: Optional[dict] = None) -> Optional[dict]:
    """Live mode: dispatch to a card-specific live reader in _live_readers.CARD_READERS.

    Subgroup_context (the run_plan's subgroup_resolution)
    is now plumbed through so subgroup-aware cards can consume the resolved strata. Live
    readers that don't need it can ignore; readers like the subgroup-stratified-expression
    reader consume the catalog_ref + resolved_strata_ids fields.

    (2026-08-11): data_context {data_mode, release_pin} is plumbed the same way so a reader
    can resolve which manifest version to read (via catalog_query.resolve_release). Readers that
    don't accept it are called via the back-compat shim (unchanged behavior).

    Returns:
      - A summary dict when a live reader exists and succeeds
      - A dict with `_live_read_error` key when a live reader exists but errored
      - None when no live reader exists yet for this card_id (caller decides
        whether to fall back to stub or mark failed)
    """
    # _live_readers was rehomed to _skills_common (off the retiring compose-dashboard).
    import sys as _sys
    from pathlib import Path as _Path
    _skills_dir = _Path(__file__).resolve().parent.parent.parent  # scripts->compose-dashboard->skills
    if str(_skills_dir) not in _sys.path:
        _sys.path.insert(0, str(_skills_dir))
    from _skills_common._live_readers import read_live_summary
    return _call_live_reader(read_live_summary, card_id, target, indication,
                             subgroup_context, data_context)


def _call_live_reader(read_fn, card_id: str, target: str, indication: str,
                       subgroup_context: Optional[dict],
                       data_context: Optional[dict] = None) -> Optional[dict]:
    """Invoke a live reader, passing ONLY the optional context kwargs its signature actually
    declares. Readers are being migrated to accept subgroup_context / data_context; a
    legacy reader that accepts neither is called with just the 3 positional args.

    Uses signature INTROSPECTION (not blanket try/except TypeError) so that a TypeError raised
    *inside* the reader's own logic propagates as a real error instead of being silently masked by
    a retry with fewer kwargs — the failure mode the previous single-kwarg shim risked."""
    import inspect
    kwargs: dict = {}
    try:
        params = inspect.signature(read_fn).parameters
        accepts_var_kw = any(p.kind == p.VAR_KEYWORD for p in params.values())
        if accepts_var_kw or "subgroup_context" in params:
            kwargs["subgroup_context"] = subgroup_context
        if accepts_var_kw or "data_context" in params:
            kwargs["data_context"] = data_context
    except (ValueError, TypeError):
        # signature() can fail on some builtins/C callables — fall back to the safe legacy call.
        kwargs = {}
    return read_fn(card_id, target, indication, **kwargs)


def _evaluate_interpretation_hints(card_spec: dict, summary: dict, thresholds: dict) -> str:
    """Iterate interpretation_hints in order; return the `call` of the first matching predicate.
    Returns "uninterpreted" if no hint matches."""
    for hint in card_spec.get("interpretation_hints", []):
        predicate = hint.get("if", "")
        if _evaluate_predicate(predicate, summary, thresholds):
            return hint.get("call", "uninterpreted")
    return "uninterpreted"


def _evaluate_warning_predicates(card_spec: dict, summary: dict, thresholds: dict) -> list[str]:
    """Evaluate each warning_predicate; return list of warning_ids that fired."""
    fired = []
    for wp in card_spec.get("warning_predicates", []) or []:
        if _evaluate_predicate(wp.get("if", ""), summary, thresholds):
            fired.append(wp["warning_id"])
    return fired


def _evaluate_predicate(predicate: str, summary: dict, thresholds: dict) -> bool:
    """Evaluate a CEL-compatible predicate against summary fields + thresholds.

    Iter-1b minimal evaluator: substitute THRESHOLD.<name> from thresholds; substitute
    summary field references; evaluate using Python's `eval` in a restricted namespace.

    This is the MINIMAL evaluator; full CEL grammar parsing is iter-2 work. It supports:
      - comparison operators (==, !=, >=, <=, >, <)
      - logical (&&, ||, !)
      - membership (in)
      - dot-path access into summary fields
      - THRESHOLD.<name> substitution
      - abs(), len() helper functions
    """
    if not predicate or not predicate.strip():
        return False

    # Substitute THRESHOLD.<name> with actual values
    def sub_threshold(match: re.Match) -> str:
        name = match.group(1)
        if name not in thresholds:
            return "None"  # missing threshold → comparison vs None → false in most cases
        v = thresholds[name]
        if isinstance(v, str):
            return repr(v)
        return repr(v)
    expr = re.sub(r"THRESHOLD\.([a-z_][a-z0-9_]*)", sub_threshold, predicate)

    # Translate CEL operators to Python
    # Order matters: replace '&&' and '||' before evaluating
    expr = expr.replace("&&", " and ").replace("||", " or ")
    # CEL's `!` for negation is awkward to translate; iter-1b predicates avoid it where possible
    # (use `!=` for inequality which translates cleanly)

    # Build a namespace: each top-level summary field becomes a variable
    namespace = {
        "abs": abs,
        "len": len,
        "true": True,
        "false": False,
        "null": None,
        "None": None,
    }
    namespace.update(summary)

    try:
        return bool(eval(expr, {"__builtins__": {}}, namespace))
    except Exception:
        # Predicate evaluation failure → false (conservative; phase-2 in live mode
        # should log the parse error to validation_report)
        return False


def _provenance_method_calls(plan_entry: dict, execution_mode: str = "stub") -> list[dict]:
    """Convert run_plan method_invocations to evidence_package provenance method_calls.

    2026-08-11: `git_sha` now carries the REAL short SHA of the
    analysis-methods repo (where the invoked read functions live), not an execution-mode tag.
    The mode tag ("stub"/"live"/...) moves to its own `execution_mode` field, so a consumer
    can tell BOTH which code version ran AND whether it read real data or a fixture — instead
    of conflating them in one string. In stub mode there is no real method execution, so
    git_sha is the sentinel "0000000" (methods weren't run)."""
    if execution_mode == "stub":
        methods_sha = "0000000"   # no method code executed in stub mode
    else:
        methods_sha = _analysis_methods_sha()
    return [
        {
            "method": inv.get("call", "unknown"),
            "git_sha": methods_sha,
            "execution_mode": execution_mode,
            "args": inv.get("args", {}),
        }
        for inv in plan_entry.get("method_invocations", [])
    ]


def _analysis_methods_sha() -> str:
    """Short git SHA of the analysis-methods repo (the code that live readers dispatch into).
    Returns the gitmeta sentinel when unavailable. Best-effort — never blocks emit."""
    import sys
    try:
        skills_dir = Path(__file__).resolve().parent.parent.parent  # scripts->compose-dashboard->skills
        if str(skills_dir) not in sys.path:
            sys.path.insert(0, str(skills_dir))
        from _skills_common.gitmeta import git_sha
        from _skills_common._live_readers import METHODS_REPO
        return git_sha(str(METHODS_REPO))
    except Exception:  # noqa: BLE001 — provenance best-effort
        return "0000000"


def _provenance_input_manifests(card_spec: dict) -> list[str]:
    """Extract input manifest_ids from card_spec.required_inputs."""
    return [
        inp.get("product_id", "unknown")
        for inp in card_spec.get("required_inputs", [])
    ]
