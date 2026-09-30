#!/usr/bin/env python3
"""card_chain_audit.py — per-card ``declared → measured → re-derived`` audit for one skill run.

The card→method→product→column chain is *declared* across three sibling repos and never joined:

    skill run.py CARDS
      → target-contracts/cards/<id>.card.yaml   (methods[].call, required_inputs[].product_id,
                                                  outputs.summary_fields, thresholds)
      → analysis-methods/onc_methods/<mod>/read.py
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
    unambiguous over the traced object; anything else is emitted ``rederivable: false`` (or
    ``measured: false``) with a ``reason_class`` that says WHY, never guessed. The reason classes keep
    two states the audit must not conflate apart: ``input_absent_from_trace`` (the object needed to check
    the value was not read in this run — genuinely uncheckable) vs ``method_internal`` (a threshold /
    classification choice, not mechanically re-derivable even when the input IS present); plus
    ``not_requested`` (--rederive not passed), ``read_failed``, and ``matched`` / ``mismatch``.

Findings (per card, never gated):
  declared_call_unresolved         — card declares methods[].call but none resolve to an importable reader
  declared_input_not_read_this_run — a declared input neither read nor reached via lineage on THIS run.
                                     A per-run COVERAGE dimension, not a defect: mostly benign (an input
                                     for another target/indication). A declared SOURCE counts as read when
                                     a read object is derived_from it (source→derived reprojection). True
                                     dead wiring only shows as read-by-zero across a CORPUS of runs.
  read_object_not_in_any_manifest  — a traced s3 object no catalog manifest owns

The corpus mode (``--runs DIR…``) turns the per-run ``declared_input_not_read_this_run`` dimension into the
genuine dead-wiring signal it can only *approximate* on one run:
  declared_input_dead — a declared in-catalog input read in ZERO of the traced runs that declared it, and
                        declared+traced in at least ``--min-runs`` runs (default 2). Stacking the per-run
                        read/unread brick across a MATRIX of targets/indications rules out the "not
                        exercised by THIS target" confound that makes the single-run signal benign. Below
                        the breadth floor the input is reported with its counts but NOT flagged dead —
                        one traced observation is no better evidence than the single-run dimension.
                        The per-run brick scores "read" at the RUN-LEVEL UNION grain (read by ANY traced
                        card in the run), because process-level ``lru_cache`` sharing across the fan-out
                        credits a shared substrate's physical read to only the first card to miss the cache
                        — see ``_card_read_status``.
  field_declared_but_absent_from_summary — an outputs.summary_fields entry missing from the emitted summary
  rederived_mismatch               — an independently recomputed value disagrees with the emitted one

Each card also carries the EMITTED output values (``emitted.scalars`` = field→value pairs, plus the names
of complex list/dict fields) and a HEALTH roll-up answering "did this card extract data as expected?"
(worst-wins over the signals):
  ok · partial_output · off_contract_read · value_mismatch · no_output · unmeasured
  opaque — emitted a full summary yet shows no traced reads (untraced run, or the reader's IO was not
           captured): an AUDIT BLIND SPOT, not a broken card. This is why emitted values sit next to the
           chain — they reveal the tool being blind to a card that in fact ran.
"""

from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_SKILLS = Path(__file__).resolve().parents[1] / "skills"  # eval/ is repo-root; skills/ is its sibling
if str(_SKILLS) not in sys.path:
    sys.path.insert(0, str(_SKILLS))

from _skills_common.paths import target_contracts_root


# ── catalog access (lazy; the exact lru_cache kwargs the plan pins) ────────────────────────────────
def _load_catalog() -> Any:
    """Load the catalog index once, with the EXACT kwargs the framework caches on.

    ``envelope.py`` documents that a bare ``load_catalog()`` is a different ``lru_cache`` key that
    re-parses ~450 files (~15s); calling with ``root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS``
    reuses the framework's own cached index.
    """
    from onc_methods.catalog_query import read as cq

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


# ── owner resolution (uri → owning manifest id) ─────────────────────────────────────────────────────
# Cached reverse index, keyed by id(catalog): building it walks ~450 records, so do it once.
_OWNER_INDEX_CACHE: dict[int, dict] = {}


def _dirname(u: str) -> str:
    return u.rsplit("/", 1)[0] if "/" in u else u


def _basename(u: str) -> str:
    return u.rsplit("/", 1)[-1] if u else u


def _owner_index(catalog: Any) -> dict:
    """Build (once per catalog) the reverse index resolving a traced uri to its owning manifest id.

    Beyond the primary ``s3_uri``, a manifest may OWN sibling objects under the same derived prefix that a
    reader actually opens: ``parameters.companion_summary_path`` (a convenience summary parquet — e.g. the
    paralog-GI ``*_summary.parquet`` companions, whose primary object is the per-line table) and
    ``sidecar_s3_uri``. Those are indexed as exact single-file matches so a read of the companion is not
    mis-reported as unread / uncatalogued. A ``basenames`` map (basename → owning mids) backs the
    unique-basename fallback for local-cache reads (see ``_owning_manifest``)."""
    key = id(catalog)
    cached = _OWNER_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    exact: dict[str, str] = {}  # normalized single-file uri → mid
    prefixes: list[tuple[str, str]] = []  # (normalized dir-prefix, mid) for source/multi-file manifests
    basenames: dict[str, set[str]] = {}  # basename → {mid} for the unique-basename local-cache fallback
    if catalog is not None:
        for rec in catalog.manifests.values():
            mid = rec.id
            s3 = getattr(rec, "s3_uri", None)
            if not s3:
                continue
            n = _norm_uri(s3)
            if n.endswith("/"):
                prefixes.append((n, mid))
                continue
            exact.setdefault(n, mid)
            basenames.setdefault(_basename(n), set()).add(mid)
            raw = getattr(rec, "raw", None) or {}
            params = raw.get("parameters") if isinstance(raw, dict) else None
            params = params or {}
            comp = params.get("companion_summary_path")
            if comp:
                cu = _dirname(n) + "/" + comp
                exact.setdefault(cu, mid)
                basenames.setdefault(_basename(cu), set()).add(mid)
            sidecar = params.get("sidecar_s3_uri") or (raw.get("sidecar_s3_uri") if isinstance(raw, dict) else None)
            if sidecar:
                su = _norm_uri(sidecar)
                exact.setdefault(su, mid)
                basenames.setdefault(_basename(su), set()).add(mid)
    idx = {"exact": exact, "prefixes": prefixes, "basenames": basenames}
    _OWNER_INDEX_CACHE[key] = idx
    return idx


def _owning_manifest(uri: str | None, catalog: Any) -> str | None:
    """Resolve a traced read uri to the id of the manifest that owns the object, or ``None``.

    Order, most specific first: exact single-file match (primary ``s3_uri``, its companion summary, or a
    sidecar); directory-prefix match (source/multi-file manifest, trailing ``/``); then — for a read that
    matched none of those, typically a LOCAL ``.cache`` copy whose path is not an s3 uri — a UNIQUE
    basename match against the indexed object basenames. The basename fallback credits ONLY when exactly
    one manifest owns that basename, so an ambiguous name (e.g. ``per_sample_maf.parquet``, owned by
    several MAF products) is never mis-credited."""
    if not uri or catalog is None:
        return None
    idx = _owner_index(catalog)
    n = _norm_uri(uri)
    hit = idx["exact"].get(n)
    if hit:
        return hit
    for pfx, mid in idx["prefixes"]:
        if n.startswith(pfx):
            return mid
    cand = idx["basenames"].get(_basename(n))
    if cand and len(cand) == 1:
        return next(iter(cand))
    return None


def _reachable_from_events(events: list[dict] | None, catalog: Any) -> set[str]:
    """Manifest ids TOUCHED by a set of read events: for each event with a uri, the owning manifest plus
    its transitive upstream lineage (``derived_from``). Local-cache reads are included (via the
    unique-basename fallback in ``_owning_manifest``) so a manifest's own cached object counts. This is the
    owner+lineage grain the corpus detector unions across ALL cards in a run: a declared input is
    'reached' when the run physically read the object it owns OR any object derived from it — even when the
    read was attributed to a *different* card (``lru_cache`` sharing) or the reader opened a *derived*
    reprojection of the declared source (a card declares raw ``tcga-mc3-public``; a sibling reads the
    derived ``tcga-mc3-per-sample-maf-v1`` whose lineage walks back to it)."""
    reached: set[str] = set()
    for ev in events or []:
        mid = _owning_manifest(ev.get("uri"), catalog)
        if mid is None:
            continue
        reached.add(mid)
        reached |= _upstream_ids(mid, catalog)
    return reached


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
        return importlib.util.find_spec(f"onc_methods.{mod}") is not None
    except (ModuleNotFoundError, ValueError):
        # a parent package that itself fails to import — treat as unresolved, not a crash
        return False


@lru_cache(maxsize=None)
def _reader_source_for_call(call: str) -> str:
    """Combined source text of the analysis-methods reader package a card's ``methods[].call`` resolves to
    (convention module ``methods.<call_underscored>``), PLUS the source of any sibling ``methods.<pkg>`` it
    imports (ONE hop). This answers a single question: does the reader that runs this card contain code
    that references a given product id? A declared input whose manifest id appears here yet was read 0× is
    plausibly a warm-``lru_cache`` capture artifact (a PARTIAL blind spot) — the reader demonstrably has
    code to open it — NOT demonstrated dead wiring. The one-hop follow is load-bearing: a card's own package
    often only ``from onc_methods.<sibling>.read import …`` the loader that holds the id literal (e.g.
    ``pathway_node_leverage`` reads the buffering product via ``onc_methods.depmap_paralog_aggregator``).
    Best-effort: an unresolvable call / missing sibling repo yields ``""`` ⇒ no reclassification ⇒ the input
    stays flagged (the honest OVER-report direction, never a mask). Source mention is a HEURISTIC that the
    product is wired into reader code, not proof this card read it on any run."""
    mod = (call or "").replace("-", "_")
    if not mod:
        return ""

    def _pkg_text(module: str) -> str:
        try:
            spec = importlib.util.find_spec(f"onc_methods.{module}")
        except (ModuleNotFoundError, ValueError):
            return ""
        if spec is None or not spec.origin:
            return ""
        parts: list[str] = []
        for p in sorted(Path(spec.origin).parent.glob("*.py")):
            try:
                parts.append(p.read_text())
            except OSError:
                continue
        return "\n".join(parts)

    root = _pkg_text(mod)
    if not root:
        return ""
    texts = [root]
    seen = {mod}
    # one hop only: follow `from onc_methods.X …` / `import onc_methods.X` to the sibling reader package
    for sib in sorted(set(re.findall(r"(?:from|import)\s+onc_methods\.(\w+)", root))):
        if sib not in seen:
            texts.append(_pkg_text(sib))
            seen.add(sib)
    return "\n".join(texts)


def _reader_references(call: str, manifest_id: str) -> bool:
    """True if the reader ``call`` resolves to (or a sibling method it imports one hop out) mentions
    ``manifest_id`` as a source literal — the signal that a 0-read declared input is a capture artifact
    (input loaded via a warmed cache), not dead wiring. See ``_reader_source_for_call``."""
    return bool(manifest_id) and manifest_id in _reader_source_for_call(call)


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


def _field_name(f: Any) -> str | None:
    """A ``outputs.summary_fields`` entry is either a bare name string or a dict carrying ``name`` (some
    cards attach ``description`` / ``lens_conditional_on`` metadata, e.g. adc-tce-modality-fit). Return the
    field name in both shapes (None if unnameable — dropped by the caller)."""
    if isinstance(f, dict):
        return f.get("name") or f.get("field") or f.get("id")
    return f


def _conditional_field_names(raw_fields: list) -> set[str]:
    """Names of declared fields emitted only under a lens (``lens_conditional_on``). These are
    legitimately absent when that lens was not invoked, so they must NOT fire
    ``field_declared_but_absent_from_summary`` (a false positive on every non-lensed run)."""
    return {_field_name(f) for f in raw_fields if isinstance(f, dict) and f.get("lens_conditional_on")}


def build_declared(card_id: str, input_manifest_ids: list[str], catalog: Any, tc_root: Path) -> dict:
    """Assemble the DECLARED column: card yaml + resolved catalog manifests + summary schema."""
    card_path = tc_root / "cards" / f"{card_id}.card.yaml"
    if not card_path.exists():
        return {"card_yaml_found": False, "manifests": [_manifest_view(m, catalog) for m in input_manifest_ids]}
    spec = yaml.safe_load(card_path.read_text()) or {}
    methods = spec.get("methods") or []
    required = spec.get("required_inputs") or []
    outputs = spec.get("outputs") or {}
    raw_fields = outputs.get("summary_fields") or []
    return {
        "card_yaml_found": True,
        "method_calls": [
            {"call": m.get("call"), "args": m.get("args") or {}, "resolvable": _call_resolvable(m)} for m in methods
        ],
        "required_product_ids": [r.get("product_id") for r in required if isinstance(r, dict)],
        "thresholds": spec.get("thresholds") or {},
        "threshold_roles": spec.get("threshold_roles") or {},
        # normalized to NAME strings — a card may declare either bare names or {name, description, ...} dicts
        "summary_fields": [n for n in (_field_name(f) for f in raw_fields) if n],
        "conditional_summary_fields": sorted(n for n in _conditional_field_names(raw_fields) if n),
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
def detect_findings(
    declared: dict,
    measured: list[dict] | None,
    summary: dict,
    catalog: Any,
    reachable: set[str] | None = None,
) -> list[dict]:
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
    conditional = set(declared.get("conditional_summary_fields") or [])
    if isinstance(summary, dict):
        # a lens-conditional field absent from a non-lensed run is expected, not a defect
        missing = [f for f in declared_fields if f not in summary and f not in conditional]
        for f in missing:
            findings.append({"kind": "field_declared_but_absent_from_summary", "field": f})

    # the next two are MEASURED-dependent: emit nothing when unmeasured (null, not a false clean)
    if measured is None:
        return findings

    # read_object_not_in_any_manifest — a traced s3 object that resolves to no owning manifest. Owner
    # resolution now credits a manifest's companion/sidecar objects (see _owning_manifest), so a read of a
    # documented companion parquet no longer false-fires here. Local-cache reads are skipped: a
    # /home/.../.cache copy is a derived local artifact, not an uncatalogued S3 object.
    for ev in measured:
        if ev["uri_class"] != "s3_object" or not ev["uri"]:
            continue
        if _owning_manifest(ev["uri"], catalog) is None:
            findings.append({"kind": "read_object_not_in_any_manifest", "uri": ev["uri"], "op": ev["op"]})

    # A declared input is satisfied if a read object owns it directly OR is DERIVED from it (cards routinely
    # declare a raw source while the reader opens the derived reprojection), OR the object was read from a
    # local cache copy — _reachable_from_events folds all three in. Computed here unless the caller passed a
    # precomputed set (audit_run does, so it can also stamp it for the corpus union).
    if reachable is None:
        reachable = _reachable_from_events(measured, catalog)

    # declared_input_not_read_this_run — a per-run COVERAGE dimension, never a defect: a declared input
    # neither read nor reached via lineage on THIS run. Mostly benign (an input for another
    # target/indication, e.g. one of many subgroup-assignment products); genuine dead wiring only shows
    # as read-by-zero across a CORPUS of runs, which a single-run audit cannot see.
    for man in declared.get("manifests") or []:
        s3 = man.get("s3_uri")
        if not man.get("in_catalog") or not s3:
            continue
        mid = man["manifest_id"]
        if mid not in reachable:
            findings.append({"kind": "declared_input_not_read_this_run", "manifest_id": mid, "s3_uri": s3})

    return findings


# ── re-derivation (honestly scoped; opt-in live re-read) ────────────────────────────────────────────
# A non-rederived record carries a ``reason_class`` so a reviewer knows WHY a field is not checked —
# the honest distinction the audit must keep, not conflate:
#   method_internal          — value is a method choice (threshold/classification); not mechanically
#                              re-derivable even when the input object IS present in the trace.
#   input_absent_from_trace  — the object needed to re-derive was NOT read in this run; genuinely
#                              uncheckable here (distinct from "the recompute is not implemented").
#   not_requested            — re-derivable + input present, but --rederive was not passed.
#   read_failed              — tried to re-read the traced object but got nothing (no creds / moved /
#                              empty after dedup).
#   matched / mismatch       — re-derived and (agrees | disagrees) with the emitted value.
_RNA_SCALARS = [
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
# per_lineage_stats grouping parameters — mirror depmap_expression_distribution.compute_summary_stats so
# an independent recompute matches the method's DEFINITIONS (not its code): expressed at log2(TPM+1)>=1.0,
# lineages with fewer than 5 default-entry models dropped.
_EXPRESSED_THRESHOLD = 1.0
_HIGHLY_EXPRESSED_THRESHOLD = 5.0
_MIN_LINEAGE_SIZE = 5


def _rederive_cellline_rna_distribution(measured: list[dict] | None, summary: dict, do_read: bool) -> dict:
    """Independently recompute the panel scalars AND the per-lineage table of ``cellline-rna-distribution``
    from the traced OmicsExpression object (+ the traced Model.csv lineage map), diffing against the
    emitted summary. Genuinely method-internal fields (``distribution_pattern``, ``isoform_expression_class``)
    are ``rederivable: false`` with ``reason_class="method_internal"``; ``allgene_percentile`` needs a
    different object never read by this card (``reason_class="input_absent_from_trace"``)."""
    out: dict[str, dict] = {
        "distribution_pattern": {
            "rederivable": False,
            "reason_class": "method_internal",
            "reason": "categorical shape label from a method-internal gap heuristic over the score array",
            "emitted": summary.get("distribution_pattern"),
        },
        "isoform_expression_class": {
            "rederivable": False,
            "reason_class": "method_internal",
            "reason": "classification cutoffs over a separate isoform product are method-internal "
            "(the product may be read, but the class label is a method choice)",
            "emitted": summary.get("isoform_expression_class"),
        },
        "allgene_percentile": {
            "rederivable": False,
            "reason_class": "input_absent_from_trace",
            "reason": "requires the allgene-rank product join (not read by this card); the panel column "
            "alone cannot give a genome-wide percentile",
            "emitted": summary.get("allgene_percentile"),
        },
    }

    def _scalars_unmeasured(reason_class: str, reason: str) -> dict:
        for f in _RNA_SCALARS:
            out[f] = {
                "rederivable": True,
                "measured": False,
                "reason_class": reason_class,
                "emitted": summary.get(f),
                "reason": reason,
            }
        out["per_lineage_stats"] = {
            "rederivable": True,
            "measured": False,
            "reason_class": reason_class,
            "emitted_n_lineages": len(summary.get("per_lineage_stats") or []),
            "reason": reason,
        }
        return out

    # locate the traced OmicsExpression read (the panel column source)
    event = None
    if measured:
        for ev in measured:
            if ev["op"] == "pyarrow.read_table" and ev["uri"] and "OmicsExpression" in ev["uri"]:
                event = ev
                break
    if event is None:
        return _scalars_unmeasured("input_absent_from_trace", "panel-column read not found in trace")
    if not do_read:
        return _scalars_unmeasured("not_requested", "pass --rederive to re-read the object and recompute")

    values = _read_panel_scores(event)
    if not values:
        return _scalars_unmeasured(
            "read_failed", "re-read failed / no rows (no creds, object moved, or empty after dedup)"
        )

    import numpy as np

    scores = np.asarray(values, dtype=float)
    recomputed = {
        "n_cell_lines_evaluated": int(scores.size),
        "median_log2tpm_panel": float(np.median(scores)),
        "p25_log2tpm_panel": float(np.percentile(scores, 25)),
        "p75_log2tpm_panel": float(np.percentile(scores, 75)),
        "p5_log2tpm_panel": float(np.percentile(scores, 5)),
        "p95_log2tpm_panel": float(np.percentile(scores, 95)),
        "fraction_expressed": float(np.mean(scores >= _EXPRESSED_THRESHOLD)),
        "fraction_highly_expressed": float(np.mean(scores >= _HIGHLY_EXPRESSED_THRESHOLD)),
        "fraction_not_expressed": float(np.mean(scores < _EXPRESSED_THRESHOLD)),
    }
    for f in _RNA_SCALARS:
        emitted = summary.get(f)
        rederived = recomputed[f]
        match = _close(emitted, rederived)
        out[f] = {
            "rederivable": True,
            "measured": True,
            "reason_class": "mismatch" if match is False else "matched",
            "emitted": emitted,
            "rederived": rederived,
            "match": match,
        }
    out["per_lineage_stats"] = _rederive_per_lineage(event, measured, summary.get("per_lineage_stats") or [])
    return out


def _rederive_per_lineage(event: dict, measured: list[dict] | None, emitted_rows: list[dict]) -> dict:
    """Recompute each emitted per-lineage row (n / median_log2tpm / fraction_expressed) by re-reading the
    panel column keyed by ModelID and joining the traced Model.csv OncotreeLineage map, then verifying
    every emitted lineage reproduces. Checks the reported VALUES; it does not re-assert the method's
    top-20 truncation boundary (an ordering detail, not a data claim)."""
    if not emitted_rows:
        # nothing to check (card emitted no per-lineage table) — never a spurious mismatch
        return {
            "rederivable": True,
            "measured": True,
            "reason_class": "matched",
            "n_lineages_checked": 0,
            "match": None,
        }
    model_scores = _read_panel_scores_by_model(event)
    if not model_scores:
        return {
            "rederivable": True,
            "measured": False,
            "reason_class": "read_failed",
            "emitted_n_lineages": len(emitted_rows),
            "reason": "re-read of the panel column keyed by ModelID failed / no rows",
        }
    lineage_map = _read_lineage_map(measured)
    if not lineage_map:
        return {
            "rederivable": True,
            "measured": False,
            "reason_class": "input_absent_from_trace",
            "emitted_n_lineages": len(emitted_rows),
            "reason": "Model.csv OncotreeLineage map not found in trace / unreadable",
        }

    import numpy as np

    by_lineage: dict[str, list[float]] = {}
    for mid, score in model_scores.items():
        lineage = lineage_map.get(mid) or "unknown"
        by_lineage.setdefault(lineage, []).append(score)
    recomputed: dict[str, dict] = {}
    for lineage, vals in by_lineage.items():
        if len(vals) < _MIN_LINEAGE_SIZE:
            continue
        arr = np.asarray(vals, dtype=float)
        recomputed[lineage] = {
            "n": int(arr.size),
            "median_log2tpm": float(np.median(arr)),
            "fraction_expressed": float(np.mean(arr >= _EXPRESSED_THRESHOLD)),
        }

    mismatches: list[dict] = []
    checked = 0
    for row in emitted_rows:
        lineage = row.get("lineage")
        rec = recomputed.get(lineage)
        if rec is None:
            mismatches.append({"lineage": lineage, "field": "presence", "emitted": row.get("n"), "rederived": None})
            continue
        checked += 1
        for fld in ("n", "median_log2tpm", "fraction_expressed"):
            if _close(row.get(fld), rec.get(fld)) is False:
                mismatches.append(
                    {"lineage": lineage, "field": fld, "emitted": row.get(fld), "rederived": rec.get(fld)}
                )
    match = not mismatches and checked > 0
    result = {
        "rederivable": True,
        "measured": True,
        "reason_class": "matched" if match else "mismatch",
        "n_lineages_checked": checked,
        "match": match,
    }
    if mismatches:
        result["emitted"] = "; ".join(f"{m['lineage']}.{m['field']}={m['emitted']}" for m in mismatches[:5])
        result["rederived"] = "; ".join(f"{m['lineage']}.{m['field']}={m['rederived']}" for m in mismatches[:5])
    return result


# the DepMap default-entry flag is a STRING column ("Yes"/"No"), NOT a boolean — the 2700→2446 dedup
# that n_cell_lines_evaluated reflects is `== "Yes"`. Comparing `== True` silently matches zero rows.
_DEFAULT_ENTRY_COL = "IsDefaultEntryForModel"
_NON_SCORE_COLS = {"ModelID", "IsDefaultEntryForModel", "IsDefaultEntryForMC"}


def _read_panel_scores_by_model(event: dict) -> dict[str, float] | None:
    """Re-read the traced OmicsExpression object independently of the method, keyed by ``ModelID``: keep
    default-entry models only (the dedup evidenced by the traced ``IsDefaultEntryForModel`` column) and
    return ``{ModelID: score}``. Returns ``None`` if the object cannot be read or yields no rows."""
    import pyarrow.parquet as pq
    import s3fs

    uri = _norm_uri(event["uri"])
    cols = event.get("columns") or []
    score_col = next((c for c in cols if c not in _NON_SCORE_COLS), None)
    if score_col is None or "ModelID" not in cols:
        return None
    try:
        fs = s3fs.S3FileSystem()
        table = pq.read_table(uri, columns=cols, filesystem=fs)
    except Exception:
        return None
    df = table.to_pandas()
    if _DEFAULT_ENTRY_COL in df.columns:
        df = df[df[_DEFAULT_ENTRY_COL] == "Yes"]
    df = df[["ModelID", score_col]].dropna(subset=[score_col])
    return {str(mid): float(v) for mid, v in zip(df["ModelID"], df[score_col])}


def _read_panel_scores(event: dict) -> list[float] | None:
    """The panel score array (default-entry deduped), independent of ModelID. ``None`` if unreadable."""
    by_model = _read_panel_scores_by_model(event)
    if not by_model:
        return None
    return list(by_model.values())


def _read_lineage_map(measured: list[dict] | None) -> dict[str, str | None] | None:
    """Build ``{ModelID: OncotreeLineage}`` from the traced ``Model.csv`` read (local cache path or S3).
    Returns ``None`` if no Model.csv read is in the trace or the object cannot be read."""
    if not measured:
        return None
    event = next((e for e in measured if (e.get("uri") or "").endswith("Model.csv")), None)
    if event is None:
        return None
    uri = event["uri"]
    try:
        import pandas as pd

        if uri.startswith("/"):
            df = pd.read_csv(uri, usecols=["ModelID", "OncotreeLineage"])
        else:
            import s3fs

            fs = s3fs.S3FileSystem()
            with fs.open(_norm_uri(uri)) as fh:
                df = pd.read_csv(fh, usecols=["ModelID", "OncotreeLineage"])
    except Exception:
        return None
    import pandas as pd

    return {
        str(mid): (lineage if pd.notna(lineage) else None) for mid, lineage in zip(df["ModelID"], df["OncotreeLineage"])
    }


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


# ── emitted values + health ───────────────────────────────────────────────────────────────────────────
def _split_summary(summary: dict) -> dict:
    """Split an emitted card summary into scalar field→value pairs (the actual output data) and the
    NAMES of complex (list/dict) fields, which are shown by name only. ``n_fields`` counts everything."""
    scalars: dict = {}
    complex_fields: list[str] = []
    for k, v in summary.items():
        if isinstance(v, (list, dict)):
            complex_fields.append(k)
        else:
            scalars[k] = v
    return {"scalars": scalars, "complex_fields": complex_fields, "n_fields": len(summary)}


# worst-wins order (index 0 = worst); a card's health is the worst state any signal implies.
_HEALTH_SEVERITY = [
    "value_mismatch",
    "no_output",
    "opaque",
    "off_contract_read",
    "partial_output",
    "unmeasured",
    "ok",
]


def _card_health(summary: dict, measured: list[dict] | None, findings: list[dict], declared: dict) -> dict:
    """Per-card roll-up answering "did this card extract data as expected?". Worst-wins over the
    observable signals. ``declared_input_not_read_this_run`` is a benign per-run coverage dimension and
    never downgrades health. The ``opaque`` state is the load-bearing one: a card that emitted a full
    summary yet shows no traced reads is an AUDIT BLIND SPOT (the reader's IO was not captured / the run
    was not traced), not a broken card — distinct from ``no_output``."""
    kinds = {f["kind"] for f in findings}
    has_output = bool(summary)
    # single source of truth: reuse detect_findings' absent-field verdict (normalized + lens-aware)
    missing = [f for f in findings if f["kind"] == "field_declared_but_absent_from_summary"]

    if "rederived_mismatch" in kinds:
        return {
            "status": "value_mismatch",
            "reason": "an independently re-derived value disagrees with the emitted number",
        }
    if not has_output:
        if measured is None:
            return {"status": "unmeasured", "reason": "not traced and no summary emitted — nothing to assess"}
        return {"status": "no_output", "reason": "traced but the card emitted no summary fields"}
    # the card DID emit output below
    if measured is None:
        return {
            "status": "opaque",
            "reason": "emitted output but the run was not traced — extraction chain unverifiable",
        }
    if not measured:
        return {
            "status": "opaque",
            "reason": "emitted output but 0 reads were traced — the reader's IO was not captured",
        }
    if "read_object_not_in_any_manifest" in kinds:
        return {"status": "off_contract_read", "reason": "read an S3 object no catalog manifest declares"}
    if missing:
        return {"status": "partial_output", "reason": f"{len(missing)} declared summary field(s) not emitted"}
    return {"status": "ok", "reason": "traced reads present; declared outputs emitted; re-derivations (if any) match"}


# ── orchestration ─────────────────────────────────────────────────────────────────────────────────────
# A run's per-card facts live in a focused-skill decision.json OR a target-profile evidence_package.json
# (the composed fan-out emits the latter under `--emit evidence-package`). They differ in two ways the
# audit cares about: input_manifest_ids sits at the card top level in decision.json but under
# `provenance` in evidence_package.json, and target/indication are top-level strings in decision.json but
# structured under `context` in evidence_package.json. _load_run normalizes both to a single shape.
RUN_ARTIFACTS = ("decision.json", "evidence_package.json")


def _run_artifact(run_dir: Path) -> "Path | None":
    """The run artifact to audit: decision.json if present, else evidence_package.json, else None."""
    for name in RUN_ARTIFACTS:
        p = run_dir / name
        if p.exists():
            return p
    return None


def _load_run(run_dir: Path) -> "tuple[list[dict], Any, Any]":
    """Normalize a run's per-card records + (target, indication) from decision.json or
    evidence_package.json. Each returned card carries card_id, summary, input_manifest_ids at the top
    level regardless of source. Prefers decision.json when both exist."""
    art = _run_artifact(run_dir)
    if art is None:
        raise FileNotFoundError(f"no {' or '.join(RUN_ARTIFACTS)} in {run_dir}")
    d = json.loads(art.read_text())
    cards = []
    for c in d.get("cards") or []:
        prov = c.get("provenance") or {}
        # decision.json lifts input_manifest_ids to the card top level; evidence_package.json keeps it
        # under provenance. Take the top level when present, else fall back to provenance.
        mids = c.get("input_manifest_ids")
        if mids is None:
            mids = prov.get("input_manifest_ids")
        cards.append(
            {
                "card_id": c.get("card_id"),
                "summary": c.get("summary") or {},
                "input_manifest_ids": list(mids or []),
            }
        )
    if art.name == "decision.json":
        return cards, d.get("target"), d.get("indication")
    # evidence_package.json: target/indication are structured under context.
    ctx = d.get("context") or {}
    tgt = ctx.get("target") or {}
    ind = ctx.get("indication") or {}
    target = tgt.get("symbol") if isinstance(tgt, dict) else tgt
    indication = ind.get("oncotree_code") if isinstance(ind, dict) else ind
    return cards, target, indication


def audit_run(run_dir: Path, skill: str, do_rederive: bool) -> dict:
    run_cards, run_target, run_indication = _load_run(run_dir)
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
    for card in run_cards:
        card_id = card.get("card_id")
        if not card_id:
            continue
        summary = card.get("summary") or {}
        input_manifest_ids = list(card.get("input_manifest_ids") or [])
        declared = build_declared(card_id, input_manifest_ids, catalog, tc_root)
        measured = build_measured(card_id, trace)
        # owner+lineage ids this card's reads TOUCHED — stamped so the corpus union (_card_read_status)
        # can credit a declared input read by ANY card in the run (lru_cache sharing / derived reprojection)
        reachable = _reachable_from_events(measured, catalog) if measured is not None else set()
        findings = detect_findings(declared, measured, summary, catalog, reachable)
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
                "health": _card_health(summary, measured, findings, declared),
                "measured_state": "unmeasured" if measured is None else f"{len(measured)} read(s)",
                "reachable_manifest_ids": sorted(reachable) if measured is not None else None,
                "declared": declared,
                "measured": measured,
                "emitted": _split_summary(summary),
                "rederived": rederived,
                "findings": findings,
            }
        )

    return {
        "schema": "card_chain_audit/v1",
        "skill": skill,
        "target": run_target,
        "indication": run_indication,
        "run_dir": str(run_dir),
        "traced": trace is not None,
        "rederive_read": do_rederive,
        "n_cards": len(cards_out),
        "cards": cards_out,
    }


# ── HTML render (compact; not the report dashboard) ─────────────────────────────────────────────────
def _esc(v: Any) -> str:
    return html.escape(str(v))


# health status → CSS colour class (green ok · amber caution · red broken · grey unknown)
_HEALTH_CSS = {
    "ok": "h-ok",
    "partial_output": "h-warn",
    "off_contract_read": "h-warn",
    "opaque": "h-opaque",
    "no_output": "h-bad",
    "value_mismatch": "h-bad",
    "unmeasured": "h-grey",
}


def _emitted_cell(c: dict) -> str:
    """Scalar emitted field=value pairs (the actual output data); complex fields listed by name. Fields
    with a re-derivation carry a ✓ (match) / ✗ (mismatch) marker so the number's provenance is visible."""
    emitted = c.get("emitted") or {}
    scalars = emitted.get("scalars") or {}
    rederived = c.get("rederived") or {}
    if not scalars and not emitted.get("complex_fields"):
        return "<span class='ok'>—</span>"
    lines = []
    for k, v in scalars.items():
        mark = ""
        rec = rederived.get(k) if isinstance(rederived, dict) else None
        if isinstance(rec, dict) and rec.get("rederivable") and rec.get("measured"):
            mark = " <b class='h-ok'>✓</b>" if rec.get("match") else " <b class='h-bad'>✗</b>"
        val = _esc(v)
        if len(val) > 80:
            val = val[:77] + "…"
        lines.append(f"<div><code>{_esc(k)}</code> = {val}{mark}</div>")
    cf = emitted.get("complex_fields") or []
    if cf:
        parts = []
        for name in cf:
            rec = rederived.get(name) if isinstance(rederived, dict) else None
            mk = ""
            if (
                isinstance(rec, dict)
                and rec.get("rederivable")
                and rec.get("measured")
                and rec.get("match") is not None
            ):
                mk = " <b class='h-ok'>✓</b>" if rec.get("match") else " <b class='h-bad'>✗</b>"
            parts.append(_esc(name) + mk)
        lines.append(f"<div class='ok'>+{len(cf)} complex: {', '.join(parts)}</div>")
    return "".join(lines)


def render_html(report: dict) -> str:
    rows = []
    tally: dict[str, int] = {}
    for c in report["cards"]:
        health = c.get("health") or {"status": "unmeasured", "reason": ""}
        tally[health["status"]] = tally.get(health["status"], 0) + 1
        badge = (
            f"<span class='badge {_HEALTH_CSS.get(health['status'], 'h-grey')}' "
            f"title='{_esc(health['reason'])}'>{_esc(health['status'])}</span>"
        )
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
        rows.append(
            f"<tr><td>{_esc(c['card_id'])}<br>{badge}</td><td>{man}</td><td>{reads}</td>"
            f"<td>{_emitted_cell(c)}</td><td>{find_html}</td></tr>"
        )
    legend = " · ".join(f"{k}={v}" for k, v in sorted(tally.items()))
    return (
        "<!doctype html><meta charset='utf-8'><title>card chain audit</title>"
        "<style>body{font:13px system-ui;margin:2rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top;text-align:left}"
        "th{background:#f4f4f4}.ok{color:#888}code{background:#f4f4f4}"
        ".badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:11px;font-weight:600}"
        ".h-ok{color:#0a0}.badge.h-ok{background:#e3f6e3;color:#060}"
        ".h-bad{color:#c00}.badge.h-bad{background:#fbe3e3;color:#900}"
        ".badge.h-warn{background:#fff2d6;color:#7a5200}.badge.h-opaque{background:#e5e9fb;color:#334}"
        ".badge.h-grey{background:#eee;color:#666}</style>"
        f"<h1>card chain audit — {_esc(report['skill'])}</h1>"
        f"<p>{_esc(report['target'])}/{_esc(report['indication'])} · run <code>{_esc(report['run_dir'])}</code> · "
        f"traced={_esc(report['traced'])} · {_esc(report['n_cards'])} cards · health: {_esc(legend)}</p>"
        "<table><tr><th>card / health</th><th>declared inputs</th><th>measured reads</th>"
        "<th>emitted values</th><th>findings</th></tr>" + "".join(rows) + "</table>"
    )


# ── corpus mode: read-by-zero-across-a-matrix = the genuine dead-wiring signal ────────────────────────
def _card_read_status(report: dict) -> dict[str, dict[str, bool]]:
    """From ONE per-run audit report, map each TRACED card → {declared in-catalog manifest_id: was_read}.

    This is the per-run brick the corpus detector stacks. Untraced cards (``measured is None``) are OMITTED,
    never recorded as unread: an unread declared input is only evidence of dead wiring on a run that
    actually captured that card's IO.

    ``was_read`` is evaluated against a **run-level union** of the owner+lineage ids every traced card
    physically TOUCHED (``reachable_manifest_ids``, stamped by ``audit_run`` via ``_reachable_from_events``:
    the owning manifest of each read object plus its ``derived_from`` lineage, local-cache and companion
    reads folded in). A declared input counts as read when it is in that run-wide touched set. The union is
    required because per-card *physical* read attribution is confounded by process-level ``lru_cache``
    sharing across the fan-out: the analysis-methods loaders are ``@lru_cache``d and a composed run resolves
    many cards that share them, so a substrate is physically read by ONLY the first card to miss the cache
    (e.g. the DepMap Gygi matrix is read once by ``cellline-protein-abundance``) while every sibling that
    CONSUMES the warm cache (``abundance-dependency`` …) records zero events. It also credits a card that
    declares a raw SOURCE while a *different* card reads a DERIVED reprojection of it (mc3, Open Targets).
    Dead WIRING means "no path in the run touches the declared input", so the union grain — not per-card
    physical IO — is the honest denominator; the softer per-card view remains available as the benign
    ``declared_input_not_read_this_run`` dimension.

    Reports predating ``reachable_manifest_ids`` fall back to the earlier ``declared − not_read`` per-card
    read set, so an older corpus still aggregates (at the coarser, declared-id-keyed grain)."""
    per_card: dict[str, list[str]] = {}  # cid → declared in-catalog manifest ids
    run_touched: set[str] = set()  # run-level union of owner+lineage ids physically touched
    for card in report.get("cards") or []:
        if card.get("measured") is None:  # untraced ⇒ no evidence either way, omit
            continue
        declared = [
            m["manifest_id"]
            for m in (card.get("declared", {}).get("manifests") or [])
            if m.get("in_catalog") and m.get("s3_uri")
        ]
        reachable = card.get("reachable_manifest_ids")
        if reachable is None:  # older report — reconstruct the per-card read set from findings
            not_read = {
                f["manifest_id"]
                for f in (card.get("findings") or [])
                if f.get("kind") == "declared_input_not_read_this_run"
            }
            reachable = [mid for mid in declared if mid not in not_read]
        per_card[card["card_id"]] = declared
        run_touched |= set(reachable)
    return {cid: {mid: (mid in run_touched) for mid in declared} for cid, declared in per_card.items()}


def _card_opacity(report: dict) -> dict[str, bool]:
    """From ONE per-run audit report, map each TRACED card → whether it is ``opaque`` (emitted a full
    summary yet the tracer captured 0 reads). Mirrors ``_card_read_status`` inclusion: untraced
    (``measured is None``) cards are omitted (they are not in the corpus matrix at all).

    An opaque card RAN — it produced output — but its reader IO was never observed, because its
    ``@lru_cache``d analysis-methods loader was warmed outside any ``capture()`` block before the traced
    fan-out (the read hits ``read_trace``'s ``sink is None`` drop) or its call path was unresolved. For such
    a card we have NO read evidence at all, so a declared input read by nobody is an audit BLIND SPOT, not
    demonstrated dead wiring — ``_aggregate_read_matrices`` uses this to reclassify. Reading the stamped
    ``health.status`` keeps this in lock-step with ``_card_health`` (for in-matrix cards, ``opaque`` ⟺
    emitted output with an empty trace; ``no_output`` — emitted nothing — is deliberately NOT opaque, so a
    genuinely silent card stays flagged)."""
    out: dict[str, bool] = {}
    for card in report.get("cards") or []:
        if card.get("measured") is None:  # untraced ⇒ not in the matrix, no opacity to record
            continue
        status = (card.get("health") or {}).get("status")
        out[card["card_id"]] = status == "opaque"
    return out


def _family_key(mid: str) -> tuple[tuple[str, ...], str] | None:
    """Group a card's per-cohort declared inputs into a prefix-family: ``(first three dash-tokens, last
    token)``. Per-indication shard menus (``tcga-subgroup-assignments-{coadread,hnsc,…}-v1``,
    ``sc-normal-celltype-<organ>-v1``) collapse to one family; the ``(first3, last)`` key keeps a
    co-required pair like ``tcga-tumor-tpm-{recount3-long,per-sample}-v1`` in its OWN family, separate
    from ``tcga-subgroup-assignments-*`` on the same card. Ids with <4 tokens have no distinct varying
    middle and are never grouped (``None`` ⇒ treated as a singleton)."""
    toks = mid.split("-")
    if len(toks) < 4:
        return None
    return (tuple(toks[:3]), toks[-1])


def _aggregate_read_matrices(
    matrices: list[dict[str, dict[str, bool]]],
    min_runs: int,
    opacities: list[dict[str, bool]] | None = None,
    reader_refs: dict[str, set[str]] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Stack per-run read bricks (``_card_read_status`` outputs) into a corpus verdict.

    For each (card, manifest) counts ``declared_traced_runs`` (traced runs where the card declared it) and
    ``read_runs`` (of those, where it was read). Flags ``dead`` only when ``read_runs == 0`` AND
    ``declared_traced_runs >= min_runs`` — the breadth floor is what separates genuine dead wiring from a
    single unlucky run. Sub-floor inputs are still listed with their counts, ``dead=False``.

    **Blind spots (opaque owner).** ``opacities`` (parallel to ``matrices``, from ``_card_opacity``) marks,
    per run, cards that emitted output but traced 0 reads. When a would-be-dead input's owning card was
    opaque in EVERY declared-traced run (``opaque_runs == declared_traced_runs``), the tool never once
    observed that card reading anything, so a read-by-nobody input is an audit BLIND SPOT, not demonstrated
    dead wiring — it is tagged ``blind_spot_opaque`` and kept OUT of ``dead_inputs``. Requiring opacity in
    ALL runs is what keeps this honest: a card observed reading other objects in even one run (non-opaque
    there) still yields a genuine ``dead`` for an input its reader never touched.

    **Partial blind spots (referenced-but-unread).** A card can be ``health=ok`` — some per-target read WAS
    captured — while a SPECIFIC declared input is loaded through a process-wide ``lru_cache`` warmed before
    the capture window (so its read is never recorded). That input reads as 0× on a non-opaque owner, so the
    ``blind_spot_opaque`` guard above (which needs opacity in ALL runs) misses it. ``reader_refs`` (per card,
    the declared manifest ids that appear as literals in the reader the card's ``call`` resolves to — see
    ``_reader_references``) supplies the discriminator: a would-be-dead input the reader demonstrably HAS
    code to open is tagged ``blind_spot_partial`` and kept OUT of ``dead_inputs``. The tag records what is
    KNOWN (the reader references the id yet it read 0×) without asserting WHY — the two mechanisms it covers
    are a warmed cache (read outside the capture window) and a conditional path the corpus never triggered
    (e.g. a per-cohort shard whose indication no run exercised). It never masks the two genuine wiring gaps
    this arc found (a card that recomputes from raw and never references the reviewed derived product it
    declares, and an aspirational additive declaration wired to nothing) — both have zero reader-code
    references, so they stay ``dead``. Absent ``reader_refs`` (or the sibling repo), nothing is reclassified
    and every would-be-dead input stays flagged (the honest over-report direction).

    **Cohort-conditionality.** A per-cohort shard menu (many declared inputs of which each run reads a
    mutually-exclusive subset) would otherwise flag every unselected shard as dead. A member of a
    prefix-family (``_family_key``) read SELECTIVELY — some run reads the family but no single run reads
    the whole family (``max_coread < family_size``) — is tagged ``conditional_unselected`` (its
    ``read_runs`` still shown, but kept OUT of ``dead_inputs``). This requires POSITIVE selective-read
    evidence within the same family, so it never masks a genuinely dead input: a co-required family
    (every read run opens the whole family, ``max_coread == family_size``) and a never-read family (no
    evidence of a live menu vs genuine dead wiring) are both left flagged. Returns
    ``(cards_out, dead_inputs)``."""
    agg: dict[str, dict[str, dict[str, int]]] = {}
    for i, mat in enumerate(matrices):
        op = opacities[i] if opacities is not None else {}
        for cid, mans in mat.items():
            card_opaque = bool(op.get(cid, False))
            for mid, was_read in mans.items():
                st = agg.setdefault(cid, {}).setdefault(
                    mid, {"declared_traced_runs": 0, "read_runs": 0, "opaque_runs": 0}
                )
                st["declared_traced_runs"] += 1
                if was_read:
                    st["read_runs"] += 1
                if card_opaque:
                    st["opaque_runs"] += 1
    # Prefix-family co-occurrence: members ever declared, whether any member was ever read, and the max
    # members read TOGETHER in a single run — the mutual-exclusivity discriminator.
    fam_members: dict[tuple[str, tuple], set[str]] = {}
    for cid in agg:
        for mid in agg[cid]:
            fk = _family_key(mid)
            if fk is not None:
                fam_members.setdefault((cid, fk), set()).add(mid)
    fam_any_read: dict[tuple[str, tuple], bool] = {}
    fam_max_coread: dict[tuple[str, tuple], int] = {}
    for mat in matrices:
        run_fam_reads: dict[tuple[str, tuple], int] = {}
        for cid, mans in mat.items():
            for mid, was_read in mans.items():
                if not was_read:
                    continue
                fk = _family_key(mid)
                if fk is None:
                    continue
                key = (cid, fk)
                run_fam_reads[key] = run_fam_reads.get(key, 0) + 1
                fam_any_read[key] = True
        for key, cnt in run_fam_reads.items():
            fam_max_coread[key] = max(fam_max_coread.get(key, 0), cnt)

    cards_out: list[dict] = []
    dead_inputs: list[dict] = []
    for cid in sorted(agg):
        inputs = []
        for mid in sorted(agg[cid]):
            st = agg[cid][mid]
            base_dead = st["read_runs"] == 0 and st["declared_traced_runs"] >= min_runs
            # blind spot: the owning card emitted output but traced 0 reads in EVERY declared run ⇒ its IO
            # was never observed ⇒ read-by-nobody is unverifiable, not demonstrated dead wiring.
            blind_spot = base_dead and st["opaque_runs"] == st["declared_traced_runs"]
            fk = _family_key(mid)
            key = (cid, fk)
            members = fam_members.get(key, set())
            in_family = fk is not None and len(members) >= 2
            selective = in_family and fam_any_read.get(key, False) and fam_max_coread.get(key, 0) < len(members)
            conditional_unselected = base_dead and not blind_spot and selective
            # partial blind spot: owner is not opaque (a captured read exists) but the reader HAS code to
            # open this specific input ⇒ its 0-read is a warm-cache capture artifact, not dead wiring.
            referenced = bool(reader_refs) and mid in (reader_refs or {}).get(cid, set())
            blind_spot_partial = base_dead and not blind_spot and not conditional_unselected and referenced
            dead = base_dead and not (blind_spot or conditional_unselected or blind_spot_partial)
            rec = {"manifest_id": mid, **st, "dead": dead}
            if in_family:
                rec["family"] = "-".join(fk[0]) + "-*-" + fk[1]
                rec["family_size"] = len(members)
                rec["family_read_members"] = sum(1 for mm in members if agg[cid][mm]["read_runs"] > 0)
            if blind_spot:
                rec["blind_spot_opaque"] = True
            if blind_spot_partial:
                rec["blind_spot_partial"] = True
            if conditional_unselected:
                rec["conditional_unselected"] = True
            inputs.append(rec)
            if dead:
                dead_inputs.append({"kind": "declared_input_dead", "card_id": cid, **rec})
        cards_out.append({"card_id": cid, "inputs": inputs})
    return cards_out, dead_inputs


def audit_corpus(run_dirs: list[Path], skill: str, min_runs: int) -> dict:
    """Run the per-card audit over a MATRIX of runs and roll the per-run read/unread bricks up into the
    corpus-level ``declared_input_dead`` verdict. Re-derivation is off (this mode is about wiring coverage,
    not value re-computation)."""
    runs_meta: list[dict] = []
    matrices: list[dict[str, dict[str, bool]]] = []
    opacities: list[dict[str, bool]] = []
    # reader_refs: per card, the declared manifest ids that appear as literals in the reader its call
    # resolves to (union across runs — declared calls/manifests are static). Powers blind_spot_partial.
    reader_refs: dict[str, set[str]] = {}
    for rd in run_dirs:
        rep = audit_run(rd, skill, do_rederive=False)
        runs_meta.append(
            {
                "run_dir": str(rd),
                "target": rep.get("target"),
                "indication": rep.get("indication"),
                "traced": rep.get("traced"),
            }
        )
        matrices.append(_card_read_status(rep))
        opacities.append(_card_opacity(rep))
        for card in rep.get("cards") or []:
            cid = card.get("card_id")
            decl = card.get("declared") or {}
            calls = [c.get("call") for c in (decl.get("method_calls") or []) if c.get("call")]
            mids = [m.get("manifest_id") for m in (decl.get("manifests") or []) if m.get("manifest_id")]
            refs = reader_refs.setdefault(cid, set())
            for mid in mids:
                if mid not in refs and any(_reader_references(call, mid) for call in calls):
                    refs.add(mid)
    cards_out, dead_inputs = _aggregate_read_matrices(matrices, min_runs, opacities, reader_refs)
    n_traced = sum(1 for r in runs_meta if r["traced"])
    n_cond = sum(1 for c in cards_out for inp in c["inputs"] if inp.get("conditional_unselected"))
    n_blind = sum(1 for c in cards_out for inp in c["inputs"] if inp.get("blind_spot_opaque"))
    n_partial = sum(1 for c in cards_out for inp in c["inputs"] if inp.get("blind_spot_partial"))
    return {
        "schema": "card_chain_audit_corpus/v1",
        "skill": skill,
        "n_runs": len(run_dirs),
        "n_traced_runs": n_traced,
        "min_runs": min_runs,
        "runs": runs_meta,
        "n_cards": len(cards_out),
        "n_dead_inputs": len(dead_inputs),
        "n_conditional_unselected": n_cond,
        "n_blind_spot_opaque": n_blind,
        "n_blind_spot_partial": n_partial,
        "cards": cards_out,
        "dead_inputs": dead_inputs,
    }


def render_corpus_html(report: dict) -> str:
    rows = []
    for c in report["cards"]:
        for i, inp in enumerate(c["inputs"]):
            card_cell = f"<td rowspan='{len(c['inputs'])}'>{_esc(c['card_id'])}</td>" if i == 0 else ""
            if inp["dead"]:
                cls, verdict = "h-bad", "<b class='h-bad'>DEAD</b>"
            elif inp.get("blind_spot_opaque"):
                cls = "blind"
                verdict = (
                    f"blind spot — opaque owner ({_esc(inp.get('opaque_runs', '?'))}"
                    f"/{_esc(inp.get('declared_traced_runs', '?'))} runs 0-read)"
                )
            elif inp.get("blind_spot_partial"):
                cls = "partial"
                verdict = (
                    f"blind spot — partial (reader references id; read 0/"
                    f"{_esc(inp.get('declared_traced_runs', '?'))} — warm-cache artifact or untriggered path)"
                )
            elif inp.get("conditional_unselected"):
                cls = "cond"
                verdict = (
                    f"cond. unselected ({_esc(inp.get('family_read_members', '?'))}"
                    f"/{_esc(inp.get('family_size', '?'))} read)"
                )
            else:
                cls, verdict = "ok", "read"
            rows.append(
                f"<tr>{card_cell}<td><code>{_esc(inp['manifest_id'])}</code></td>"
                f"<td>{_esc(inp['read_runs'])}/{_esc(inp['declared_traced_runs'])}</td>"
                f"<td class='{cls}'>{verdict}</td></tr>"
            )
    runs_list = "".join(
        f"<li><code>{_esc(r['run_dir'])}</code> — {_esc(r['target'])}/{_esc(r['indication'])}"
        f"{'' if r['traced'] else ' (untraced — excluded)'}</li>"
        for r in report["runs"]
    )
    return (
        "<!doctype html><meta charset='utf-8'><title>card chain audit — corpus</title>"
        "<style>body{font:13px system-ui;margin:2rem}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top;text-align:left}"
        "th{background:#f4f4f4}.ok{color:#888}code{background:#f4f4f4}"
        ".cond{color:#a60}.blind{color:#559}.partial{color:#786}.h-bad{color:#c00;font-weight:600}</style>"
        f"<h1>card chain audit — corpus dead-wiring — {_esc(report['skill'])}</h1>"
        f"<p>{_esc(report['n_runs'])} runs ({_esc(report['n_traced_runs'])} traced) · "
        f"min-runs floor={_esc(report['min_runs'])} · "
        f"<b class='h-bad'>{_esc(report['n_dead_inputs'])} dead input(s)</b> · "
        f"{_esc(report.get('n_blind_spot_opaque', 0))} blind-spot (opaque owner) · "
        f"{_esc(report.get('n_blind_spot_partial', 0))} blind-spot (partial — warm-cache) · "
        f"{_esc(report.get('n_conditional_unselected', 0))} conditional-unselected (per-cohort menu) "
        f"across {_esc(report['n_cards'])} cards</p>"
        f"<ul>{runs_list}</ul>"
        "<table><tr><th>card</th><th>declared input</th><th>read / declared-traced runs</th>"
        "<th>verdict</th></tr>" + "".join(rows) + "</table>"
    )


def _main_corpus(args: argparse.Namespace) -> int:
    run_dirs: list[Path] = list(args.runs)
    if len(run_dirs) < 2:
        print("[card-chain-audit] ERROR: --runs needs ≥2 run dirs to be a corpus", file=sys.stderr)
        return 2
    missing = [d for d in run_dirs if _run_artifact(d) is None]
    if missing:
        print(
            f"[card-chain-audit] ERROR: no {' or '.join(RUN_ARTIFACTS)} found in: {', '.join(map(str, missing))}",
            file=sys.stderr,
        )
        return 2
    out_dir: Path = args.out or run_dirs[0]
    out_dir.mkdir(parents=True, exist_ok=True)

    report = audit_corpus(run_dirs, args.skill, args.min_runs)
    (out_dir / "card_chain_audit_corpus.json").write_text(json.dumps(report, indent=2, default=str))
    (out_dir / "card_chain_audit_corpus.html").write_text(render_corpus_html(report))
    print(
        f"[card-chain-audit] corpus: {report['n_runs']} runs ({report['n_traced_runs']} traced), "
        f"{report['n_cards']} cards, {report['n_dead_inputs']} dead input(s), "
        f"{report.get('n_blind_spot_opaque', 0)} blind-spot(s), "
        f"{report.get('n_blind_spot_partial', 0)} partial-blind-spot(s), "
        f"{report.get('n_conditional_unselected', 0)} conditional "
        f"→ {out_dir / 'card_chain_audit_corpus.json'}"
    )
    for f in report["dead_inputs"]:
        print(f"  DEAD  {f['card_id']}: {f['manifest_id']} (read 0/{f['declared_traced_runs']} traced runs)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skill", required=True, help="skill name (labels the report)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--run",
        type=Path,
        help="a single run dir containing decision.json or evidence_package.json (+ read_trace.json)",
    )
    mode.add_argument(
        "--runs",
        type=Path,
        nargs="+",
        help="≥2 run dirs (a matrix of targets/indications) → corpus declared_input_dead detector",
    )
    ap.add_argument("--out", type=Path, default=None, help="output dir (default: the (first) run dir)")
    ap.add_argument("--rederive", action="store_true", help="live-re-read traced objects to recompute scalars")
    ap.add_argument(
        "--min-runs",
        type=int,
        default=2,
        help="corpus mode: min traced runs an input must be declared in before read-by-zero counts as dead",
    )
    args = ap.parse_args(argv)

    if args.runs is not None:
        return _main_corpus(args)

    run_dir: Path = args.run
    if _run_artifact(run_dir) is None:
        print(
            f"[card-chain-audit] ERROR: no {' or '.join(RUN_ARTIFACTS)} in {run_dir}",
            file=sys.stderr,
        )
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
