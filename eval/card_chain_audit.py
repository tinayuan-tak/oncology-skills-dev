#!/usr/bin/env python3
"""card_chain_audit.py — per-card ``declared → measured → re-derived`` audit for one skill run.

The card→method→product→column chain is *declared* across three sibling repos and never joined:

    skill run.py CARDS
      → target-contracts/cards/<id>.card.yaml   (methods[].call, required_inputs[].product_id,
                                                  outputs.summary_fields, thresholds)
      → analysis-methods/methods/<mod>/read.py
      → data-catalog/manifests/…                (s3_uri, parquet_schema, primary_filter_column)

This tool joins that declared wiring against what a run *actually read* (the opt-in ``read_trace.json``
emitted by ``--trace``) and, for an explicitly listed subset of fields, an independent re-derivation.
It is a read-only DEV tool: it writes ``<out>/card_chain_audit.{json,html}`` and is not wired into the
report/dashboard render path, so it moves no golden. Every finding is a reported DIMENSION, never a
gate — the process exits 0 unless its own inputs are unreadable.

Two honesty rules the plan pins:
  * **Unmeasured ⇒ null, not 0.** A card absent from the trace reads as ``measured: null`` (unmeasured);
    a card present in the trace with no read events reads as ``measured: []`` (traced, zero reads — a
    real signal, e.g. a card whose declared ``call`` never resolved to a reader). The two are distinct.
  * **Re-derivation may not lie about coverage.** A field is re-derived only when the recipe is
    unambiguous over the traced object; anything method-internal is emitted ``rederivable: false`` with a
    reason, never guessed.

Findings (per card, never gated):
  declared_call_unresolved         — card declares methods[].call but none resolve to an importable reader
  declared_input_not_read_this_run — a declared input neither read nor reached via lineage on THIS run.
                                     A per-run COVERAGE dimension, not a defect: mostly benign (an input
                                     for another target/indication). A declared SOURCE counts as read when
                                     a read object is derived_from it (source→derived reprojection). True
                                     dead wiring only shows as read-by-zero across a CORPUS of runs.
  read_object_not_in_any_manifest  — a traced s3 object no catalog manifest owns
  field_declared_but_absent_from_summary — an outputs.summary_fields entry missing from the emitted summary
  rederived_mismatch               — an independently recomputed value disagrees with the emitted one
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import yaml

_SKILLS = Path(__file__).resolve().parents[1] / "skills"  # eval/ is repo-root; skills/ is its sibling
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

from _skills_common.paths import analysis_methods_root, target_contracts_root  # noqa: E402

_AM = analysis_methods_root()
if str(_AM) not in sys.path:
    sys.path.insert(0, str(_AM))


# ── catalog access (lazy; the exact lru_cache kwargs the plan pins) ────────────────────────────────
def _load_catalog() -> Any:
    """Load the catalog index once, with the EXACT kwargs the framework caches on.

    ``envelope.py`` documents that a bare ``load_catalog()`` is a different ``lru_cache`` key that
    re-parses ~450 files (~15s); calling with ``root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS``
    reuses the framework's own cached index.
    """
    from methods.catalog_query import read as cq

    return cq.load_catalog(root=cq.DATA_CATALOG, contracts_root=cq.TARGET_CONTRACTS)


# ── uri normalisation / classification ─────────────────────────────────────────────────────────────
def _norm_uri(uri: str) -> str:
    """Strip the ``s3://`` scheme so a ``bucket/key`` trace uri and an ``s3://bucket/key`` manifest uri
    compare on equal footing."""
    return uri[len("s3://") :] if uri.startswith("s3://") else uri


def _uri_class(uri: str | None) -> str:
    """Classify a read target so the manifest-membership check only runs on s3 objects.

    A local cache path (``/home/.../.cache/...``) is a *derived* copy of a source object, not an
    uncataloged S3 object — firing ``read_object_not_in_any_manifest`` on it would be a false alarm."""
    if not uri:
        return "unknown"
    if uri.startswith("/") or uri.startswith("file://"):
        return "local_cache"
    return "s3_object"


def _manifest_owns(trace_uri: str, manifest_s3_uri: str | None) -> bool:
    """True if ``manifest_s3_uri`` names the traced object: exact match for a single-file (derived)
    manifest, or directory-prefix match for a source/multi-file manifest (trailing ``/``)."""
    if not manifest_s3_uri:
        return False
    m = _norm_uri(manifest_s3_uri)
    t = _norm_uri(trace_uri)
    if t == m:
        return True
    if m.endswith("/") and t.startswith(m):
        return True
    return False


def _upstream_ids(manifest_id: str, catalog: Any) -> set[str]:
    """Transitive upstream lineage of a manifest via ``derived_from`` (BFS, cycle-safe; excludes the
    starting id). Empty when the catalog or the record is unknown. Used so a declared SOURCE reads as
    satisfied when a read object is derived from it — the reader opens the derived reprojection, not the
    raw source the card declares."""
    if catalog is None:
        return set()
    seen: set[str] = set()
    stack = [manifest_id]
    while stack:
        rec = catalog.manifests.get(stack.pop())
        if rec is None:
            continue
        for up in getattr(rec, "derived_from", None) or []:
            if up not in seen:
                seen.add(up)
                stack.append(up)
    return seen


# ── declared side ───────────────────────────────────────────────────────────────────────────────────
def _call_resolvable(method: dict) -> bool:
    """A declared ``methods[].call`` resolves if the naming-convention module imports, or the method
    dict carries an explicit ``module``/``entrypoint``. This is the machine-checkable binding the card
    label lacks (only 45/95 call-ids appear in their convention module)."""
    if method.get("entrypoint") or method.get("module"):
        return True
    call = method.get("call") or ""
    mod = call.replace("-", "_")
    if not mod:
        return False
    try:
        return importlib.util.find_spec(f"methods.{mod}") is not None
    except (ModuleNotFoundError, ValueError):
        # a parent package that itself fails to import — treat as unresolved, not a crash
        return False


def _summary_schema(card_id: str, tc_root: Path) -> dict[str, dict]:
    """Load ``schemas/methods/<card>.summary.schema.json`` → {field: {type, enum}}. Opt-in (~46 exist);
    a missing schema yields ``{}`` (declared field types simply unknown, not a finding)."""
    p = tc_root / "schemas" / "methods" / f"{card_id}.summary.schema.json"
    if not p.exists():
        return {}
    try:
        schema = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    props = schema.get("properties") or {}
    out: dict[str, dict] = {}
    for field, spec in props.items():
        if isinstance(spec, dict):
            out[field] = {"type": spec.get("type"), "enum": spec.get("enum")}
    return out


def _manifest_view(manifest_id: str, catalog: Any) -> dict:
    """Project a catalog ManifestRecord into the audit's declared view (best-effort; unknown ⇒ null)."""
    rec = catalog.manifests.get(manifest_id) if catalog is not None else None
    if rec is None:
        return {"manifest_id": manifest_id, "in_catalog": False}
    schema = getattr(rec, "parquet_schema", None) or []
    qo = getattr(rec, "query_optimization", None) or {}
    return {
        "manifest_id": manifest_id,
        "in_catalog": True,
        "type": getattr(rec, "type", None),
        "s3_uri": getattr(rec, "s3_uri", None),
        "license": getattr(rec, "license", None),
        "columns": [c.get("name") for c in schema if isinstance(c, dict)] or None,
        "primary_filter_column": qo.get("primary_filter_column") if isinstance(qo, dict) else None,
    }


def build_declared(card_id: str, input_manifest_ids: list[str], catalog: Any, tc_root: Path) -> dict:
    """Assemble the DECLARED column: card yaml + resolved catalog manifests + summary schema."""
    card_path = tc_root / "cards" / f"{card_id}.card.yaml"
    if not card_path.exists():
        return {"card_yaml_found": False, "manifests": [_manifest_view(m, catalog) for m in input_manifest_ids]}
    spec = yaml.safe_load(card_path.read_text()) or {}
    methods = spec.get("methods") or []
    required = spec.get("required_inputs") or []
    outputs = spec.get("outputs") or {}
    return {
        "card_yaml_found": True,
        "method_calls": [
            {"call": m.get("call"), "args": m.get("args") or {}, "resolvable": _call_resolvable(m)} for m in methods
        ],
        "required_product_ids": [r.get("product_id") for r in required if isinstance(r, dict)],
        "thresholds": spec.get("thresholds") or {},
        "threshold_roles": spec.get("threshold_roles") or {},
        "summary_fields": list(outputs.get("summary_fields") or []),
        "summary_field_types": _summary_schema(card_id, tc_root),
        # resolved from the RUN's own input_manifest_ids (already concrete manifest ids — no release guess)
        "manifests": [_manifest_view(m, catalog) for m in input_manifest_ids],
    }


# ── measured side ─────────────────────────────────────────────────────────────────────────────────────
def build_measured(card_id: str, trace: dict | None) -> list[dict] | None:
    """The MEASURED column: read events for this card, or ``None`` if the run was not traced / the card
    is absent from the trace (UNMEASURED — distinct from a traced card with zero reads, which is ``[]``)."""
    if trace is None:
        return None
    cards = trace.get("cards") or {}
    if card_id not in cards:
        return None
    events = []
    for e in cards[card_id]:
        uri = e.get("uri")
        events.append(
            {
                "op": e.get("op"),
                "uri": uri,
                "uri_class": _uri_class(uri),
                "columns": e.get("columns"),
                "filters": e.get("filters"),
                "rows": e.get("rows"),
                "cols": e.get("cols"),
                "ms": e.get("ms"),
                "uri_attribution": e.get("uri_attribution"),
            }
        )
    return events


# ── findings (dimensions, never gates) ──────────────────────────────────────────────────────────────
def detect_findings(declared: dict, measured: list[dict] | None, summary: dict, catalog: Any) -> list[dict]:
    findings: list[dict] = []

    # declared_call_unresolved — declares calls but none resolve to an importable reader
    calls = declared.get("method_calls") or []
    if calls and not any(c["resolvable"] for c in calls):
        findings.append(
            {
                "kind": "declared_call_unresolved",
                "detail": "no declared method call resolves to an importable reader",
                "calls": [c["call"] for c in calls],
            }
        )

    # field_declared_but_absent_from_summary — declared output field missing from the emitted summary
    declared_fields = declared.get("summary_fields") or []
    if isinstance(summary, dict):
        missing = [f for f in declared_fields if f not in summary]
        for f in missing:
            findings.append({"kind": "field_declared_but_absent_from_summary", "field": f})

    # the next two are MEASURED-dependent: emit nothing when unmeasured (null, not a false clean)
    if measured is None:
        return findings

    read_owner_ids: set[str] = set()
    for ev in measured:
        if ev["uri_class"] != "s3_object" or not ev["uri"]:
            continue
        owner = None
        if catalog is not None:
            for rec in catalog.manifests.values():
                if _manifest_owns(ev["uri"], getattr(rec, "s3_uri", None)):
                    owner = rec.id
                    break
        if owner is None:
            findings.append({"kind": "read_object_not_in_any_manifest", "uri": ev["uri"], "op": ev["op"]})
        else:
            read_owner_ids.add(owner)

    # A declared input is satisfied if a read object owns it directly OR is DERIVED from it: cards
    # routinely declare a raw source (e.g. depmap-consortium-26q1) while the reader opens the derived
    # reprojection (depmap-26q1-parquet-v1, derived_from that source). Walk upstream lineage so that
    # source→derived hop is not mis-reported as unread.
    reachable = set(read_owner_ids)
    for oid in read_owner_ids:
        reachable |= _upstream_ids(oid, catalog)

    # declared_input_not_read_this_run — a per-run COVERAGE dimension, never a defect: a declared input
    # neither read nor reached via lineage on THIS run. Mostly benign (an input for another
    # target/indication, e.g. one of many subgroup-assignment products); genuine dead wiring only shows
    # as read-by-zero across a CORPUS of runs, which a single-run audit cannot see.
    for man in declared.get("manifests") or []:
        s3 = man.get("s3_uri")
        if not man.get("in_catalog") or not s3:
            continue
        mid = man["manifest_id"]
        read = mid in reachable or any(_manifest_owns(ev["uri"], s3) for ev in measured if ev["uri"])
        if not read:
            findings.append({"kind": "declared_input_not_read_this_run", "manifest_id": mid, "s3_uri": s3})

    return findings


# ── re-derivation (honestly scoped; opt-in live re-read) ────────────────────────────────────────────
def _rederive_cellline_rna_distribution(measured: list[dict] | None, summary: dict, do_read: bool) -> dict:
    """Independently recompute the panel scalars of ``cellline-rna-distribution`` from the traced
    OmicsExpression object, diffing against the emitted summary. Method-internal fields (per-lineage,
    isoform, allgene-percentile, distribution_pattern) are declared ``rederivable: false``."""
    internal = {
        "distribution_pattern": "method-internal categorical over per-lineage stats",
        "per_lineage_stats": "method-internal grouping",
        "allgene_percentile": "requires the allgene-rank product join, not the panel column alone",
        "isoform_expression_class": "derived from a separate isoform product",
    }
    scalars = [
        "n_cell_lines_evaluated",
        "median_log2tpm_panel",
        "p25_log2tpm_panel",
        "p75_log2tpm_panel",
        "p5_log2tpm_panel",
        "p95_log2tpm_panel",
        "fraction_expressed",
        "fraction_highly_expressed",
        "fraction_not_expressed",
    ]
    out: dict[str, dict] = {}
    for f, reason in internal.items():
        out[f] = {"rederivable": False, "reason": reason, "emitted": summary.get(f)}

    def _unmeasured(reason: str) -> dict:
        for f in scalars:
            out[f] = {"rederivable": True, "measured": False, "emitted": summary.get(f), "reason": reason}
        return out

    # locate the traced OmicsExpression read (the panel column source)
    event = None
    if measured:
        for ev in measured:
            if ev["op"] == "pyarrow.read_table" and ev["uri"] and "OmicsExpression" in ev["uri"]:
                event = ev
                break
    if event is None:
        return _unmeasured("panel-column read not found in trace")
    if not do_read:
        return _unmeasured("pass --rederive to re-read the object and recompute")

    values = _read_panel_scores(event)
    if not values:
        return _unmeasured("re-read failed / no rows (no creds, object moved, or empty after dedup)")

    import numpy as np

    scores = np.asarray(values, dtype=float)
    recomputed = {
        "n_cell_lines_evaluated": int(scores.size),
        "median_log2tpm_panel": float(np.median(scores)),
        "p25_log2tpm_panel": float(np.percentile(scores, 25)),
        "p75_log2tpm_panel": float(np.percentile(scores, 75)),
        "p5_log2tpm_panel": float(np.percentile(scores, 5)),
        "p95_log2tpm_panel": float(np.percentile(scores, 95)),
        "fraction_expressed": float(np.mean(scores >= 1.0)),
        "fraction_highly_expressed": float(np.mean(scores >= 5.0)),
        "fraction_not_expressed": float(np.mean(scores < 1.0)),
    }
    for f in scalars:
        emitted = summary.get(f)
        rederived = recomputed[f]
        out[f] = {
            "rederivable": True,
            "measured": True,
            "emitted": emitted,
            "rederived": rederived,
            "match": _close(emitted, rederived),
        }
    return out


# the DepMap default-entry flag is a STRING column ("Yes"/"No"), NOT a boolean — the 2700→2446 dedup
# that n_cell_lines_evaluated reflects is `== "Yes"`. Comparing `== True` silently matches zero rows.
_DEFAULT_ENTRY_COL = "IsDefaultEntryForModel"
_NON_SCORE_COLS = {"ModelID", "IsDefaultEntryForModel", "IsDefaultEntryForMC"}


def _read_panel_scores(event: dict) -> list[float] | None:
    """Re-read the traced OmicsExpression object independently of the method: keep default-entry models
    only (the dedup evidenced by the traced ``IsDefaultEntryForModel`` column), return the target score
    column. Returns ``None`` if the object cannot be read or yields no rows."""
    import pyarrow.parquet as pq
    import s3fs

    uri = _norm_uri(event["uri"])
    cols = event.get("columns") or []
    score_col = next((c for c in cols if c not in _NON_SCORE_COLS), None)
    if score_col is None:
        return None
    try:
        fs = s3fs.S3FileSystem()
        table = pq.read_table(uri, columns=cols, filesystem=fs)
    except Exception:
        return None
    df = table.to_pandas()
    if _DEFAULT_ENTRY_COL in df.columns:
        df = df[df[_DEFAULT_ENTRY_COL] == "Yes"]
    series = df[score_col].dropna()
    return [float(v) for v in series.tolist()]


def _close(a: Any, b: Any, rel: float = 1e-6, abs_: float = 1e-9) -> bool | None:
    """Numeric closeness with an integer-exact path; ``None`` when either side is non-numeric/absent."""
    if a is None or b is None or isinstance(a, bool) or isinstance(b, bool):
        return None
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return None
    if fa.is_integer() and fb.is_integer():
        return int(fa) == int(fb)
    return abs(fa - fb) <= max(abs_, rel * max(abs(fa), abs(fb)))


_REDERIVERS = {"cellline-rna-distribution": _rederive_cellline_rna_distribution}


def build_rederived(card_id: str, measured: list[dict] | None, summary: dict, do_read: bool) -> dict | None:
    fn = _REDERIVERS.get(card_id)
    if fn is None:
        return None
    return fn(measured, summary, do_read)


# ── orchestration ─────────────────────────────────────────────────────────────────────────────────────
def audit_run(run_dir: Path, skill: str, do_rederive: bool) -> dict:
    decision = json.loads((run_dir / "decision.json").read_text())
    trace_path = run_dir / "read_trace.json"
    trace = json.loads(trace_path.read_text()) if trace_path.exists() else None

    catalog = None
    try:
        catalog = _load_catalog()
    except Exception as e:  # catalog optional — the tool still reports declared-yaml + measured legs
        print(
            f"[card-chain-audit] WARNING: catalog unavailable ({type(e).__name__}: {e}); manifest resolution skipped",
            file=sys.stderr,
        )

    tc_root = target_contracts_root()
    cards_out = []
    for card in decision.get("cards") or []:
        card_id = card.get("card_id")
        if not card_id:
            continue
        summary = card.get("summary") or {}
        input_manifest_ids = list(card.get("input_manifest_ids") or [])
        declared = build_declared(card_id, input_manifest_ids, catalog, tc_root)
        measured = build_measured(card_id, trace)
        findings = detect_findings(declared, measured, summary, catalog)
        rederived = build_rederived(card_id, measured, summary, do_rederive)
        # surface rederived_mismatch as a first-class finding
        if rederived:
            for field, rec in rederived.items():
                if rec.get("match") is False:
                    findings.append(
                        {
                            "kind": "rederived_mismatch",
                            "field": field,
                            "emitted": rec.get("emitted"),
                            "rederived": rec.get("rederived"),
                        }
                    )
        cards_out.append(
            {
                "card_id": card_id,
                "measured_state": "unmeasured" if measured is None else f"{len(measured)} read(s)",
                "declared": declared,
                "measured": measured,
                "rederived": rederived,
                "findings": findings,
            }
        )

    return {
        "schema": "card_chain_audit/v1",
        "skill": skill,
        "target": decision.get("target"),
        "indication": decision.get("indication"),
        "run_dir": str(run_dir),
        "traced": trace is not None,
        "rederive_read": do_rederive,
        "n_cards": len(cards_out),
        "cards": cards_out,
    }


# ── HTML render (compact; not the report dashboard) ─────────────────────────────────────────────────
def _esc(v: Any) -> str:
    return html.escape(str(v))


def render_html(report: dict) -> str:
    rows = []
    for c in report["cards"]:
        finds = c["findings"]
        if finds:
            items = "".join(
                f"<li><b>{_esc(f['kind'])}</b>: {_esc({k: v for k, v in f.items() if k != 'kind'})}</li>" for f in finds
            )
            find_html = f"<ul>{items}</ul>"
        else:
            find_html = "<span class='ok'>—</span>"
        man = ", ".join(
            f"{m['manifest_id']}{'' if m.get('in_catalog') else ' (not in catalog)'}"
            for m in (c["declared"].get("manifests") or [])
        )
        if c["measured"] is None:
            reads = "unmeasured"
        else:
            reads = (
                "".join(
                    f"<div>{_esc(e['op'])} · {_esc(e['uri'])} · rows={_esc(e['rows'])} cols={_esc(e['cols'])}</div>"
                    for e in c["measured"]
                )
                or "traced, 0 reads"
            )
        rows.append(f"<tr><td>{_esc(c['card_id'])}</td><td>{man}</td><td>{reads}</td><td>{find_html}</td></tr>")
    return (
        "<!doctype html><meta charset='utf-8'><title>card chain audit</title>"
        "<style>body{font:13px system-ui;margin:2rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top;text-align:left}"
        "th{background:#f4f4f4}.ok{color:#888}code{background:#f4f4f4}</style>"
        f"<h1>card chain audit — {_esc(report['skill'])}</h1>"
        f"<p>{_esc(report['target'])}/{_esc(report['indication'])} · run <code>{_esc(report['run_dir'])}</code> · "
        f"traced={_esc(report['traced'])} · {_esc(report['n_cards'])} cards</p>"
        "<table><tr><th>card</th><th>declared inputs</th><th>measured reads</th><th>findings</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", required=True, help="skill name (labels the report)")
    ap.add_argument("--run", required=True, type=Path, help="run dir containing decision.json (+ read_trace.json)")
    ap.add_argument("--out", type=Path, default=None, help="output dir (default: the run dir)")
    ap.add_argument("--rederive", action="store_true", help="live-re-read traced objects to recompute scalars")
    args = ap.parse_args(argv)

    run_dir: Path = args.run
    if not (run_dir / "decision.json").exists():
        print(f"[card-chain-audit] ERROR: {run_dir / 'decision.json'} not found", file=sys.stderr)
        return 2
    out_dir: Path = args.out or run_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    report = audit_run(run_dir, args.skill, args.rederive)
    (out_dir / "card_chain_audit.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "card_chain_audit.html").write_text(render_html(report))

    n_find = sum(len(c["findings"]) for c in report["cards"])
    print(
        f"[card-chain-audit] {report['n_cards']} cards, {n_find} findings "
        f"(traced={report['traced']}) → {out_dir / 'card_chain_audit.json'}"
    )
    for c in report["cards"]:
        for f in c["findings"]:
            print(f"  {c['card_id']}: {f['kind']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
