"""_skills_common.cards — card resolution + per-card provenance stamping.

The card-reading half of the skill harness: `resolve_cards` fetches live
summaries for a card_id list via the shared live-reader dispatcher (rehomed off
the retired compose-dashboard), classifies each into its primary interpretation
call, and stamps the declared input-manifest / method-call provenance. The reads
are independent, so they run concurrently via a thread pool (library default) or
a forked process pool (SKILLS_READ_POOL=process) — byte-identical output across
paths.

Re-exported from the package root (`from _skills_common import resolve_cards`,
`_import_dispatcher`, …); import surface is unchanged by the 2026-10-01 split.
"""

from __future__ import annotations

import os
import sys
from contextlib import nullcontext as _nullcontext
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import yaml

import _skills_common as _skc  # the package root

from .rules_loader import TARGET_CONTRACTS

# Internal calls to `_import_dispatcher` / `card_input_manifest_ids` / `card_declared_method_calls`
# are routed through the package root (`_skc.<name>`), NOT this module's own globals. Tests
# monkeypatch these on the `_skills_common` package object (e.g. the per-skill replay harnesses do
# `mp.setattr(skc, "_import_dispatcher", _factory)` to inject frozen card summaries), and before the
# 2026-10-01 split (#2380) these functions + `resolve_cards` all lived in `__init__`, so a patch on
# the package attribute WAS the name `resolve_cards` resolved. Keeping the call-time lookup on the
# package namespace preserves that monkeypatch contract exactly after the move into this submodule.


def _import_dispatcher():
    """Import the shared live-reader dispatcher. Dispatch table is a framework-wide registry
    (16 wired cards) that lives in _skills_common (rehomed off the retiring compose-dashboard)."""
    from ._live_readers import read_live_summary  # noqa: F401

    return read_live_summary


@lru_cache(maxsize=512)
def card_input_manifest_ids(card_id: str) -> tuple[str, ...]:
    """The data-catalog manifest ids a card DECLARES as inputs — its `required_inputs[].product_id`
    from the card_spec (target-contracts). This is the SAME declarative card->manifest mapping the
    compose-dashboard path uses (_execution._provenance_input_manifests); reusing it here means the
    subskill default path (decision.json) records the same real manifest ids as the composed engine.

    Best-effort + fail-open: a missing/malformed card_spec or absent required_inputs → empty tuple
    (provenance must never block a run). Returns a tuple so the @lru_cache result is immutable.
    """
    try:
        path = TARGET_CONTRACTS / "cards" / f"{card_id}.card.yaml"
        spec = yaml.safe_load(path.read_text()) or {}
        return tuple(
            ri["product_id"]
            for ri in (spec.get("required_inputs") or [])
            if isinstance(ri, dict) and ri.get("product_id")
        )
    except Exception:  # noqa: BLE001 — provenance is best-effort; never break card resolution
        return ()


@lru_cache(maxsize=512)
def card_declared_method_calls(card_id: str) -> tuple:
    """The method calls a card DECLARES — its `methods[].call` + `args` from the card_spec, each
    stamped with the analysis-methods repo SHA (the code version that ran the method).

    This is the fact that fills evidence_package.schema's long-empty `provenance.method_calls`
    slot (`{method, git_sha, args}` — declared there since 2026-08-16, populated in 0 of the
    emitted cards because resolve_cards clobbered reader provenance). `git_sha` answers the
    question gitmeta.py was written for — "which code version produced this?" — which the static
    card yaml alone cannot: it is the analysis-methods HEAD, not this skills repo's. `args` are the
    card's DECLARED (still-templated, e.g. `{target.symbol}`) values; a downstream tool resolves
    them against thresholds — the runtime stamp faithfully copies the declaration rather than
    re-implementing threshold resolution in the read hot path.

    Best-effort + fail-open: a missing/malformed card_spec or absent `methods` → empty tuple. The
    SHA is resolved once (gitmeta.git_sha is lru_cached) and is the "0000000" sentinel when git is
    unreachable. Returns a tuple of dicts so the @lru_cache result is not mutated by a caller — each
    entry should be shallow-copied before mutation (resolve_cards does).
    """
    try:
        from .gitmeta import git_sha
        from .paths import analysis_methods_root

        path = TARGET_CONTRACTS / "cards" / f"{card_id}.card.yaml"
        spec = yaml.safe_load(path.read_text()) or {}
        methods = spec.get("methods") or []
        if not methods:
            return ()
        am_sha = git_sha(str(analysis_methods_root()))
        out = []
        for m in methods:
            if not isinstance(m, dict) or not m.get("call"):
                continue
            entry = {"method": m["call"], "git_sha": am_sha}
            if isinstance(m.get("args"), dict):
                entry["args"] = dict(m["args"])
            out.append(entry)
        return tuple(out)
    except Exception:  # noqa: BLE001 — provenance is best-effort; never break card resolution
        return ()


# --- Skill API -------------------------------------------------------------


def _is_data_unavailable(v) -> bool:
    """True if a summary value is the honest 'no data' sentinel."""
    return isinstance(v, str) and (v == "data_unavailable" or v.endswith("_data_unavailable"))


def _primary_class_value(summary: dict, card_id: Optional[str] = None):
    """The card's PRIMARY interpretation categorical — the value resolve_cards lifts into
    `interpretation_call`. CONTRACTS-FIRST: when `card_id` is given and its card declares a
    `capsule.primary_class`, that field's value wins (the same source `emit_capsules` reads) —
    so a card whose declared primary is NOT a `*_class` field (sc-normal's graded veto
    `sc_normal_essential_veto_grade`, alteration-role's `alteration_role`, …) is read as its
    author declared, not silently down-shifted to whatever `*_class` field happens to be first.

    Fallback heuristic (no declared primary, or the declared field is absent from the summary):
    legacy primaries (selectivity_class / class / interpretation_call) win; otherwise the card's
    primary answer lives in a topic-specific `*_class` field (dependency_class, fit_class,
    immune_context_class, copy_number_class, …), so return the first REAL (non-data_unavailable)
    `*_class` value — falling back to a data_unavailable one only when there is no real class
    answer anywhere.

    Only this PRIMARY decides availability; a data_unavailable value in a SECONDARY sub-field
    (a dual-layer card's protein sub-layer, copy-number's patient_* cross-check, gnomAD's
    human_ko_observed_class, …) must NOT mark the whole card missing.
    """
    if not isinstance(summary, dict):
        return None
    if card_id:
        # Lazy import: subgroup_derivation triggers this package's __init__, so a module-level
        # import would be circular. Cached + verdict-inert; never raises.
        from _skills_common.subgroup_derivation import _card_capsule_contract

        declared = _card_capsule_contract(card_id)[0]
        if declared and isinstance(summary.get(declared), str):
            return summary[declared]
    for f in ("selectivity_class", "class", "interpretation_call"):
        v = summary.get(f)
        if v is not None:
            return v
    class_vals = [summary[k] for k in summary if k.endswith("_class") and isinstance(summary[k], str)]
    if not class_vals:
        return None
    real = [v for v in class_vals if not _is_data_unavailable(v)]
    return real[0] if real else class_vals[0]


def _data_unavailable_field(summary: dict, card_id: Optional[str] = None) -> Optional[str]:
    """If this summary's PRIMARY answer is an honest `data_unavailable`, return the
    field name carrying it, else None.

    CONTRACTS-FIRST (mirrors `_primary_class_value`, #1541): when `card_id` is given and its card
    declares a `capsule.primary_class`, that field ALONE decides availability — so a card whose
    declared primary is NOT a `*_class` field (sc-normal's graded veto `sc_normal_essential_veto_grade`,
    alteration-role's `alteration_role`, …) is judged available/unavailable on the SAME field
    `_primary_class_value` reads its value from. Without this branch the two helpers key on different
    fields for such cards: the value helper reads the declared graded field while this one scans only
    `*_class` fields, so a card whose declared primary is `data_unavailable` while a secondary `*_class`
    still carries a value would be judged AVAILABLE here yet report a no-data primary value — the exact
    drift #1541 closed on the value side.

    Fallback heuristic (no declared primary, or the declared field is absent from the summary):
    a card answers in a topic-specific `*_class` field (dependency_class, fit_class,
    immune_context_class, copy_number_class, …), not just the legacy three — so a genuinely
    no-data PRIMARY must be detected there too (M2, 2026-08-11). BUT a `data_unavailable` in a
    SECONDARY facet (antigen_high_immune_context_class, patient_copy_number_class,
    patient_focal_cn_class, human_ko_observed_class, dep_control_position_class, …) is a NORMAL
    partial-data state and must NOT flag the whole card. So:
      - if a legacy primary field is present, it ALONE decides;
      - otherwise the card is data_unavailable only when EVERY present `*_class` categorical is
        data_unavailable (i.e. there is no real class answer anywhere).
    This restores the invariant `_primary_class_value` documents; the previous "sentinel on ANY
    `*_class`" scan violated it and falsely degraded multi-class cards (immune-context on every
    run, genomic-instability-state / copy-number-distribution / gnomad-lof-constraint on common
    indications — real primary, data-less secondary).
    """
    if not isinstance(summary, dict):
        return None
    if card_id:
        # Lazy import (circular otherwise — see _primary_class_value). Cached; verdict-inert.
        from _skills_common.subgroup_derivation import _card_capsule_contract

        declared = _card_capsule_contract(card_id)[0]
        if declared and isinstance(summary.get(declared), str):
            return declared if _is_data_unavailable(summary[declared]) else None
    for f in ("selectivity_class", "class", "interpretation_call"):
        if f in summary:
            return f if _is_data_unavailable(summary.get(f)) else None
    class_fields = [k for k in summary if k.endswith("_class") and isinstance(summary.get(k), str)]
    if class_fields and all(_is_data_unavailable(summary[k]) for k in class_fields):
        return class_fields[0]
    return None


def _summary_is_unavailable(summary: dict, card_id: Optional[str] = None) -> Optional[str]:
    """Return a short reason string if this dispatcher summary represents a
    NON-answer (error or data-unavailable) at the PRIMARY level, else None.

    A card is NOT genuinely available if the dispatcher:
      - raised and returned a `{"_live_read_error": ...}` sentinel, OR
      - a PRIMARY class field carries a data-unavailable marker.

    2026-08-11: detection now spans any `*_class` field (see
    _data_unavailable_field), not the 3 hardcoded primaries. NOTE this flags the card
    for COVERAGE accounting (`_missing`), but resolve_cards separately marks it
    `_data_unavailable` so fired_rules still evaluates its dedicated data_unavailable
    rung — an honest no-data answer is a real, rule-fireable signal, not a silent drop.
    """
    if not isinstance(summary, dict):
        return "non_dict_summary"
    if "_live_read_error" in summary:
        return f"live_read_error: {summary['_live_read_error']}"
    field = _data_unavailable_field(summary, card_id)
    if field is not None:
        return f"{field}={summary.get(field)}"
    return None


def _resolve_one_card(
    card_id: str,
    target: str,
    indication: str,
    subgroup_context: "Optional[dict]",
    plot_data_root: "Optional[Path]" = None,
    trace: "Optional[Any]" = None,
) -> dict:
    """Read + classify ONE card into its card_output dict. MODULE-LEVEL (picklable) so it can run in
    either a thread or a FORKED worker process. Imports the live-reader dispatcher internally (cached
    — a no-op in a forked child, which inherits the parent's already-imported modules). Returns a
    fresh dict per card (no shared mutable state), and read exceptions propagate to the caller exactly
    as in the sequential path.

    plot_data_root (figure Stage 1): OPT-IN. When set, forwarded to the dispatcher so the method
    persists its plot_data under <plot_data_root>/cards/<card_id>/ DURING resolution. None => the
    exact former scalar call (byte-identical).

    trace (chain-audit dev tooling): OPT-IN ReadTrace. When set, the reader's data IO for THIS card is
    captured under `trace.capture(card_id)` (the trace's patches must already be installed by the
    caller). None => no capture (byte-identical). Only honoured on the sequential path — resolve_cards
    forces SKILLS_READ_WORKERS=1 under a trace so per-card attribution is unambiguous."""
    read_live = _skc._import_dispatcher()
    _read_kw = {}
    if subgroup_context is not None:
        _read_kw["subgroup_context"] = subgroup_context
    if plot_data_root is not None:
        _read_kw["plot_data_root"] = plot_data_root
    _capture = trace.capture(card_id) if trace is not None else _nullcontext()
    with _capture:
        try:
            summary = read_live(card_id, target, indication, **_read_kw)
        except TypeError:
            # Dispatcher predates one of these kwargs — scalar fallback (backward-compat).
            summary = read_live(card_id, target, indication)
    if summary is None:
        return {
            "card_id": card_id,
            "summary": {},
            "interpretation_call": "not_implemented",
            "_missing": True,
            "_missing_reason": "dispatcher_returned_none",
        }
    unavailable = _summary_is_unavailable(summary, card_id)
    if unavailable is not None:
        # Distinguish an HONEST data_unavailable answer (the card ran and reported no data) from a
        # genuine absence (dispatcher None / live_read_error). Both count against COVERAGE (`_missing`),
        # but the honest-data_unavailable card is flagged `_data_unavailable` so fired_rules still
        # evaluates its dedicated `equals: data_unavailable` rung (M2, 2026-08-11).
        is_honest_du = "_live_read_error" not in summary and _data_unavailable_field(summary, card_id) is not None
        return {
            "card_id": card_id,
            "summary": summary,
            "interpretation_call": "data_unavailable",
            "_missing": True,
            "_missing_reason": unavailable,
            "_data_unavailable": is_honest_du,
        }
    return {
        "card_id": card_id,
        "summary": summary,
        "interpretation_call": _primary_class_value(summary, card_id),
    }


def _resolve_one_card_star(args: tuple) -> dict:
    """tuple-unpacking wrapper so multiprocessing.Pool.map (single-arg) can call _resolve_one_card."""
    return _resolve_one_card(*args)


def _read_cards_threaded(card_ids, target, indication, subgroup_context, max_workers, plot_data_root=None) -> list:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=min(max_workers, len(card_ids))) as ex:
        return list(
            ex.map(lambda c: _resolve_one_card(c, target, indication, subgroup_context, plot_data_root), card_ids)
        )


def _read_cards_process(card_ids, target, indication, subgroup_context, max_workers, plot_data_root=None) -> list:
    """DEFAULT (SKILLS_READ_POOL unset or =process): read cards in FORKED worker processes to bypass the GIL.
    The reader CPU (pandas assembly, per-row dict builds) is GIL-bound, so a thread pool serializes it
    — profiling showed the cold parallel read is GIL-limited, and a fork pool did 12.8s -> 8.7s.

    Safety (fork-from-clean-state + degrade-never-break):
      - MAIN THREAD ONLY — forking a MULTITHREADED process can deadlock: the child inherits copies of
        locks held by threads that do not exist in it. The composed target-profile fans its sub-skills
        out over a ThreadPoolExecutor, and each worker thread calls resolve_cards; if SKILLS_READ_POOL=
        process is set globally, those calls would fork from a worker thread. So we fork ONLY when
        resolve_cards runs on the main thread of a single-threaded process; off the main thread we use
        the thread pool (safe + still parallel). This makes SKILLS_READ_POOL=process safe to export
        globally — a standalone skill run forks; a composed fan-out silently stays on threads.
      - fork ONLY — children inherit the parent's warm imports at ~zero cost. If the `fork` start
        method is unavailable (non-Linux), fall back to threads. Forking AFTER boto3/SSL client init
        can deadlock; resolve_cards is the run's FIRST S3 touch and we pre-warm only IMPORTS (no
        client) in the parent, so at fork time the parent holds no live S3/SSL state.
      - ANY pool failure (fork error, pickling, worker death) degrades to the thread path — a read
        must never break because of the pool.
    Order preserved (Pool.map); results are the same fresh card_output dicts, pickled back."""
    import multiprocessing as mp
    import threading

    # Fork-safety guard (see docstring): fork ONLY from the MAIN thread of a SINGLE-threaded process.
    # Forking a multithreaded process risks a child deadlock (it inherits copies of locks held by
    # threads that don't exist in it — CPython even emits a DeprecationWarning). Two ways that arises:
    #   (a) OFF the main thread — the composed target-profile fans its sub-skills out over a
    #       ThreadPoolExecutor, so resolve_cards runs on a worker thread there; and
    #   (b) on the main thread but with OTHER live threads (a Jupyter kernel, an agent host, pytest).
    # Since process is now the DEFAULT (not an opt-in flag whose caller accepted the risk), we require
    # BOTH conditions and otherwise fall back to the thread pool (safe + still parallel). A standalone
    # skill CLI run is single-threaded on main (verified), so the fork pool still engages and keeps the
    # speedup; a multithreaded host silently and safely stays on threads.
    if threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
        return _read_cards_threaded(card_ids, target, indication, subgroup_context, max_workers, plot_data_root)
    try:
        ctx = mp.get_context("fork")
    except ValueError:
        # No fork on this platform — thread pool is the safe equivalent.
        return _read_cards_threaded(card_ids, target, indication, subgroup_context, max_workers, plot_data_root)
    args = [(c, target, indication, subgroup_context, plot_data_root) for c in card_ids]
    try:
        with ctx.Pool(processes=min(max_workers, len(card_ids))) as pool:
            return pool.map(_resolve_one_card_star, args)
    except Exception as e:  # noqa: BLE001 — the pool is an optimization; never break the run
        print(
            f"[resolve_cards] SKILLS_READ_POOL=process failed ({type(e).__name__}: {e}); "
            f"falling back to the thread pool.",
            file=sys.stderr,
        )
        return _read_cards_threaded(card_ids, target, indication, subgroup_context, max_workers, plot_data_root)


def resolve_cards(
    card_ids: list[str],
    target: str,
    indication: str,
    subgroup_context: Optional[dict] = None,
    plot_data_root: Optional[Path] = None,
    trace: Optional[Any] = None,
) -> list[dict]:
    """Fetch live summaries for a list of card_ids via the shared
    dispatcher registry (rehomed off the retired compose-dashboard).
    Returns one card_output dict per card_id.

    Cards that are missing (dispatcher returns None), errored
    (`_live_read_error`), or explicitly data-unavailable are all tagged
    `_missing: True` with a `_missing_reason`, so `cards_available` reflects
    only cards that returned a real, usable signal. (Previously an errored
    dispatcher returned a dict and was silently counted as available —
    overstating coverage on every skill.)

    subgroup_context (optional): when provided, threaded to the dispatcher so
    panorama cards (subgroup-stratified-*) fan out across the resolved strata.
    Scalar cards ignore it. None → scalar-only (backward-compat).

    plot_data_root (optional, figure Stage 1): when provided, forwarded to each dispatcher so the
    method persists its plot_data under <plot_data_root>/cards/<card_id>/ AS AN ARTIFACT OF
    RESOLUTION (not a figure re-read). Only readers whose signature declares plot_data_out receive
    it (signature-introspected, like data_context); all others are untouched. None → no persistence
    (byte-identical to the former call).

    trace (optional, chain-audit dev tooling): a ReadTrace. When provided, the reader data IO is
    captured per card and each card's provenance gains a `datasets` list ({s3_uri, columns_read,
    filters, rows_returned, op, ms}). A trace FORCES the sequential read path (no thread/process pool)
    so per-card IO attribution is unambiguous — this mirrors the `--trace` contract at the CLI, which
    also sets SKILLS_READ_WORKERS=1. None → no capture, no `datasets` key (byte-identical).

    FRAMEWORK_HEALTH_SMOKE (env flag): when set, SKIP all live dispatcher reads and
    return a synthetic minimal card output per card_id. This lets the framework-health
    harness run each subskill's REAL run.py end-to-end (authentic axis/verdict/headline
    → run_health) DETERMINISTICALLY and OFFLINE — proving "does the compute path execute
    cleanly?" without any S3/network read. Off by default: unset → zero production impact
    (this branch is not entered). Not a data source — a liveness-of-the-pipeline probe.
    """
    if os.environ.get("FRAMEWORK_HEALTH_SMOKE"):
        # Synthetic stub per card — a well-formed but empty summary. Rules that need real
        # values simply don't fire (fired=[]); the point is that resolve→rules→verdict→
        # run_health executes without error, which is the "runs clean?" health signal.
        return [
            {
                "card_id": cid,
                "summary": {},
                "_missing": False,
                "_smoke": True,
                "provenance": {"input_manifest_ids": list(_skc.card_input_manifest_ids(cid))},
            }
            for cid in card_ids
        ]

    # Pre-warm the live-reader import in the PARENT so a forked worker (SKILLS_READ_POOL=process)
    # inherits it at ~zero cost. This imports modules only — it opens no S3/SSL client — so it is
    # safe to do before a fork. The per-card readers re-derive it via _import_dispatcher() (cached).
    _skc._import_dispatcher()

    # PERF (2026-08-18): the per-card reads are INDEPENDENT, so run them concurrently instead of
    # summing their latencies. Two pool modes:
    #   process (SKILLS_READ_POOL=process) — a FORKED process pool that ALSO parallelizes the readers'
    #     GIL-bound CPU (pandas assembly), which a thread pool serializes. Measured uniformly faster:
    #     tumor-presence 12.8s->8.7s, tumor-selectivity ~5.3s->~3.9s — byte-identical output. Fork is
    #     gated to the main thread of a SINGLE-threaded process (see _read_cards_process). Any fork/
    #     pickling failure degrades to threads.
    #   thread (LIBRARY DEFAULT) — a bounded ThreadPoolExecutor. The reads' S3/pyarrow I/O releases
    #     the GIL so it still collapses wall-clock toward the slowest read for I/O-bound cards.
    # The library default here is the CONSERVATIVE thread pool, so a direct/embedded resolve_cards
    # caller (a notebook, an agent host, the composed target-profile fan-out — which calls resolve_cards
    # from ThreadPoolExecutor WORKER threads) never forks unexpectedly. Standalone skill CLI runs opt
    # INTO process at the run_wired_skill entrypoint (os.environ.setdefault), where the process is known
    # single-threaded on main — that's where the S3->output runtime win lands.
    # Output is byte-identical across all three paths: order preserved, _resolve_one_card returns a
    # fresh dict per card. Sequential fallback for a single card or SKILLS_READ_WORKERS<=1 (kill-switch)
    # keeps the exact former code path.
    try:
        _max_workers = int(os.environ.get("SKILLS_READ_WORKERS", "8"))
    except ValueError:
        _max_workers = 8
    _pool_mode = os.environ.get("SKILLS_READ_POOL", "thread").strip().lower()
    if trace is not None:
        # A trace forces the sequential path: per-card IO attribution requires each card's reads to run
        # start-to-finish on one thread, and a ReadTrace (threading.Lock) is not picklable into a fork
        # pool. The trace's patches are installed for the whole loop; _resolve_one_card scopes each
        # card's capture. This is the library-level twin of the CLI's --trace => SKILLS_READ_WORKERS=1.
        with trace.installed():
            outputs = [
                _resolve_one_card(cid, target, indication, subgroup_context, plot_data_root, trace) for cid in card_ids
            ]
    elif len(card_ids) <= 1 or _max_workers <= 1:
        outputs = [_resolve_one_card(cid, target, indication, subgroup_context, plot_data_root) for cid in card_ids]
    elif _pool_mode == "process":
        outputs = _read_cards_process(card_ids, target, indication, subgroup_context, _max_workers, plot_data_root)
    else:
        outputs = _read_cards_threaded(card_ids, target, indication, subgroup_context, _max_workers, plot_data_root)
    # PROVENANCE (2026-08-13): stamp each card_output with the manifest ids it DECLARES as inputs
    # (card_spec.required_inputs[].product_id), so the subskill default path carries the same real
    # per-card data provenance as the composed engine — the basis for the decision.json governance
    # block + the resolved_release_digest. Applied to available AND missing cards: the digest is the
    # run's DECLARED input set (stable across transient read misses), not only successful reads.
    #
    # 2026-09-20: MERGE, do not clobber. The former `o["provenance"] = {...}` discarded any provenance
    # a reader had already attached — which is why evidence_package.schema's `provenance.method_calls`
    # slot (declared since 2026-08-16) was populated in 0 of 5015 emitted cards. We now (a) preserve
    # whatever the reader supplied, (b) keep `input_manifest_ids` = the DECLARED ids byte-for-byte (the
    # old behavior — declared ids win over a reader value, so the governance digest is unchanged), and
    # (c) stamp the DECLARED `method_calls` ({method, git_sha, args}) so the package answers "which code
    # produced this." Verdict-inert: provenance feeds governance/render, never a rule. Both envelope
    # card_present builders already merge `{**defaults, **card.provenance}` (dispatcher/envelope), so a
    # stamped method_calls flows through to the evidence_package and overrides the `[]` default there.
    for o in outputs:
        prov = dict(o.get("provenance") or {})
        prov["input_manifest_ids"] = list(_skc.card_input_manifest_ids(o["card_id"]))
        prov["method_calls"] = [dict(mc) for mc in _skc.card_declared_method_calls(o["card_id"])]
        # TRACE (chain-audit dev tooling): when tracing, surface the MEASURED reads this card performed
        # as provenance.datasets. Present ONLY under a trace (a normal run never grows this key), so the
        # decision.json / evidence_package remain byte-identical off the trace path.
        if trace is not None:
            prov["datasets"] = [_trace_event_to_dataset(ev) for ev in trace.events_for(o["card_id"])]
        o["provenance"] = prov
    return outputs


def _trace_event_to_dataset(ev: dict) -> dict:
    """Project one ReadTrace event onto the card-provenance `datasets` shape. Keeps the audit-relevant
    facts (object, columns, row filter, rows returned) and drops timing internals; carries the
    uri_attribution label when the URI was inferred rather than observed."""
    ds = {
        "s3_uri": ev.get("uri"),
        "op": ev.get("op"),
        "columns_read": ev.get("columns"),
        "filters": ev.get("filters"),
        "rows_returned": ev.get("rows"),
        "cols_returned": ev.get("cols"),
        "ms": ev.get("ms"),
    }
    if ev.get("uri_attribution"):
        ds["uri_attribution"] = ev["uri_attribution"]
    if ev.get("error"):
        ds["error"] = ev["error"]
    return ds
