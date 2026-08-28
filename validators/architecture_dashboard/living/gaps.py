"""gaps.py — the unified GAPS layer (the primary tab).

Aggregates every "missing / broken piece" the framework already detects into ONE ranked list,
replacing scattered CI logs:
  1. the gap-detection validators (validators/validate_*.py), called IN-PROCESS
  2. framework_health signals already on the merged graph (drift_index, orphan/broken/
     placeholder cards, broken-or-drift skills)
  3. Explorer + coverage signals already on the graph (uncataloged dataset GAP_NOTES,
     promotion backlog)

Every finding is normalized to:
  {severity, gap_type, component_type, component_id, code, message, source}
Deduped on (component_id, code) keeping the highest severity; ranked severity -> type -> id.

Validators run only during `generate`/`--check` (local, siblings present). Each adapter is
individually guarded: a validator that cannot run in this environment degrades to a single
info-level `validator_unavailable` finding rather than breaking the build. `build_gaps`
returns `{items, summary, validators_run}` so the coverage test can assert wiring.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SEV_RANK = {"error": 3, "warn": 2, "info": 1}


def _rec(severity, gap_type, component_type, component_id, message, source, code=None):
    return {"severity": severity, "gap_type": gap_type, "component_type": component_type,
            "component_id": component_id or "", "code": code or gap_type,
            "message": " ".join(str(message or "").split())[:400], "source": source}


# --------------------------------------------------------------------------- #
# 1. In-process validator adapters. Each yields normalized records. Guarded by _run().
# --------------------------------------------------------------------------- #
def _import_validators(tc: Path):
    """Add the repo root to sys.path so `validators` is importable, then import the modules
    we wire. Returns a module namespace dict (best-effort; missing ones are skipped)."""
    # repo root enables `import validators.X`; the validators/ dir enables the intra-package
    # bare sibling imports some validators use (e.g. validate_claim_record -> validate_verdict_tokens).
    for p in (str(tc), str(tc / "validators")):
        if p not in sys.path:
            sys.path.insert(0, p)
    mods = {}
    names = ["validate_cards", "validate_interpretation_rules", "validate_resolvers",
             "validate_verdict_tokens", "validate_measurement_types",
             "validate_certainty_disjointness", "validate_fold_migration",
             "validate_claim_record", "validate_card_resolver_consumption"]
    for n in names:
        try:
            mods[n] = __import__(f"validators.{n}", fromlist=[n])
        except Exception:
            mods[n] = None
    return mods


def _report_lines(rep):
    """Normalize any validator report to [(severity, msg)]. Handles the .errors/.warnings
    dataclasses, list[str] (all errors), and (ok, errs) tuples."""
    out = []
    if rep is None:
        return out
    if isinstance(rep, tuple) and len(rep) == 2 and isinstance(rep[1], (list, tuple)):
        return [("error", m) for m in rep[1]]
    if isinstance(rep, (list, tuple)):
        # a bare list — could be reports or strings
        for x in rep:
            if isinstance(x, str):
                out.append(("error", x))
            else:
                out.extend(_report_lines(x))
        return out
    errs = getattr(rep, "errors", None)
    warns = getattr(rep, "warnings", None)
    if errs is not None or warns is not None:
        out += [("error", m) for m in (errs or [])]
        out += [("warn", m) for m in (warns or [])]
    return out


def _validator_gaps(tc: Path, dc: Path | None) -> tuple[list, list]:
    """Run the wired validators in-process. Returns (records, validators_run)."""
    mods = _import_validators(tc)
    records: list = []
    run: list = []

    def emit(name, gap_type, comp_type, lines, id_fn=lambda m: None):
        run.append(name)
        for sev, msg in lines:
            records.append(_rec(sev, gap_type, comp_type, id_fn(msg), msg, name))

    def unavailable(name, e):
        records.append(_rec("info", "validator_unavailable", "framework", name,
                            f"{name} could not run here: {e}", name))

    # -- cards (per-file)
    m = mods.get("validate_cards")
    if m:
        try:
            schema = m._load_schema()
            lines = []
            for p in sorted((tc / "cards").glob("*.card.yaml")):
                rep = m.validate_card_file(p, schema)
                for sev, msg in _report_lines(rep):
                    lines.append((sev, f"{p.stem.replace('.card','')}: {msg}"))
            emit("validate_cards", "card_structural", "card", lines,
                 id_fn=lambda msg: msg.split(":", 1)[0])
        except Exception as e:
            unavailable("validate_cards", e)

    # -- interpretation rules (per-file)
    m = mods.get("validate_interpretation_rules")
    if m:
        try:
            lines = []
            for p in sorted((tc / "interpretation-rules").glob("*.rules.yaml")):
                rep = m.validate_rules_file(p, tc / "cards")
                for sev, msg in _report_lines(rep):
                    lines.append((sev, f"{p.stem.replace('.rules','')}: {msg}"))
            emit("validate_interpretation_rules", "dead_rule", "interpretation_rule", lines,
                 id_fn=lambda msg: msg.split(":", 1)[0])
        except Exception as e:
            unavailable("validate_interpretation_rules", e)

    # -- resolvers (dir)
    m = mods.get("validate_resolvers")
    if m:
        try:
            reps = m.validate_dir(tc / "resolvers", tc / "interpretation-rules")
            lines = []
            for r in reps:
                gate = Path(getattr(r, "path", "")).stem.replace(".resolver", "")
                for sev, msg in _report_lines(r):
                    lines.append((sev, f"{gate}: {msg}"))
            emit("validate_resolvers", "dangling_rung", "resolver", lines,
                 id_fn=lambda msg: msg.split(":", 1)[0])
        except Exception as e:
            unavailable("validate_resolvers", e)

    # -- verdict tokens
    m = mods.get("validate_verdict_tokens")
    if m:
        try:
            rep = m.validate(tc / "vocabularies" / "nomination_verdict_gate.yaml", tc / "resolvers")
            emit("validate_verdict_tokens", "verdict_token", "resolver", _report_lines(rep))
        except Exception as e:
            unavailable("validate_verdict_tokens", e)

    # -- measurement types
    m = mods.get("validate_measurement_types")
    if m:
        try:
            rep = m.validate(tc / "vocabularies" / "measurement_types.yaml", tc / "cards")
            emit("validate_measurement_types", "measurement_type", "card", _report_lines(rep))
        except Exception as e:
            unavailable("validate_measurement_types", e)

    # -- certainty disjointness
    m = mods.get("validate_certainty_disjointness")
    if m:
        try:
            emit("validate_certainty_disjointness", "certainty_double_count", "card",
                 _report_lines(m.validate(tc)))
        except Exception as e:
            unavailable("validate_certainty_disjointness", e)

    # -- fold migration
    m = mods.get("validate_fold_migration")
    if m:
        try:
            emit("validate_fold_migration", "fold_migration", "resolver",
                 _report_lines(m.validate(tc / "resolvers")))
        except Exception as e:
            unavailable("validate_fold_migration", e)

    # -- claim record
    m = mods.get("validate_claim_record")
    if m:
        try:
            rep = m.validate(tc / "schemas" / "claim_record.schema.json",
                             tc / "docs" / "design" / "examples", tc / "resolvers")
            emit("validate_claim_record", "claim_record", "evidence_package", _report_lines(rep))
        except Exception as e:
            unavailable("validate_claim_record", e)

    # -- card/resolver consumption (exposes report(); else compute())
    m = mods.get("validate_card_resolver_consumption")
    if m:
        try:
            fn = getattr(m, "report", None)
            if callable(fn):
                emit("validate_card_resolver_consumption", "card_structural", "card", _report_lines(fn()))
            else:
                run.append("validate_card_resolver_consumption")  # present but no report surface
        except Exception as e:
            unavailable("validate_card_resolver_consumption", e)

    return records, sorted(set(run))


# --------------------------------------------------------------------------- #
# 2 + 3. Signals already on the merged graph (no imports).
# --------------------------------------------------------------------------- #
def _graph_gaps(graph: dict) -> list:
    records: list = []
    H = graph.get("health") or {}

    # framework_health drift_index
    for d in H.get("drift_index") or []:
        sev = d.get("severity") or "info"
        comp_id = d.get("skill") or d.get("card") or ""
        comp_type = "skill" if d.get("skill") else ("card" if d.get("card") else "framework")
        records.append(_rec(sev, "skill_drift" if comp_type == "skill" else "card_structural",
                            comp_type, comp_id, d.get("detail") or d.get("code"),
                            "framework_health", code=d.get("code")))

    # health card flags: orphan / placeholder / broken
    for cid, c in (H.get("cards") or {}).items():
        ch = c.get("card_health")
        if c.get("is_orphan"):
            records.append(_rec("warn", "orphan_card", "card", cid,
                                "card on disk but no skill consumes it", "framework_health"))
        if ch in ("placeholder", "blocked"):
            records.append(_rec("info", "placeholder_card", "card", cid,
                                c.get("reason_text") or f"card health = {ch}", "framework_health",
                                code=f"card_{ch}"))
        elif ch == "broken":
            records.append(_rec("error", "card_structural", "card", cid,
                                c.get("reason_text") or "card health = broken", "framework_health",
                                code="card_broken"))

    # Explorer: uncataloged dataset refs (broken vs planned) with GAP_NOTES category
    for pid, d in (graph.get("datasets") or {}).items():
        if not d.get("in_catalog"):
            cat = d.get("gap_category")
            # a bare uncataloged ref with no note is a broken ref; a categorized one is a known gap
            if cat:
                records.append(_rec("info", "uncataloged_dataset", "source_manifest", pid,
                                    f"[{cat}] {d.get('gap_note') or ''}", "explorer",
                                    code=f"uncataloged_{cat}"))
            else:
                records.append(_rec("warn", "broken_dataset_ref", "source_manifest", pid,
                                    f"card names product_id with no catalog record "
                                    f"(→ {len(d.get('consumed_by_cards') or [])} card(s))", "explorer"))

    # coverage: promotion backlog
    cov = graph.get("coverage") or {}
    n_exp = (cov.get("summary") or {}).get("n_cells_exploratory_only")
    if n_exp:
        records.append(_rec("info", "coverage_backlog", "evidence_package", "",
                            f"{n_exp} target×indication cell(s) exist only as exploratory runs — "
                            "candidates to promote to governed packages", "coverage",
                            code="promotion_backlog"))
    return records


# --------------------------------------------------------------------------- #
# Assemble.
# --------------------------------------------------------------------------- #
def build_gaps(graph: dict, roots: dict) -> dict:
    tc = Path(roots.get("target_contracts") or graph.get("roots", {}).get("target_contracts") or ".")
    dc = Path(roots["data_catalog"]) if roots.get("data_catalog") else None

    vrecs, vrun = _validator_gaps(tc, dc)
    grecs = _graph_gaps(graph)
    allrecs = vrecs + grecs

    # dedup on (component_id, code) keeping highest severity
    best: dict = {}
    for r in allrecs:
        # include the message in the key so DISTINCT findings that share (component_id, code)
        # — e.g. several verdict-token / measurement-type issues (empty component_id) or two
        # structural violations on one card — are not collapsed to a single row. True cross-source
        # dupes (health + a validator flagging the same thing) still merge on identical message.
        key = (r["component_id"], r["code"], (r.get("message") or "")[:120])
        if key not in best or _SEV_RANK.get(r["severity"], 0) > _SEV_RANK.get(best[key]["severity"], 0):
            best[key] = r
    items = list(best.values())

    # rank severity desc -> gap_type -> component_id
    items.sort(key=lambda r: (-_SEV_RANK.get(r["severity"], 0), r["gap_type"], r["component_id"]))

    by_sev: dict = {}
    by_type: dict = {}
    for r in items:
        by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1
        by_type[r["gap_type"]] = by_type.get(r["gap_type"], 0) + 1

    return {
        "items": items,
        "summary": {"n_gaps": len(items),
                    "n_error": by_sev.get("error", 0),
                    "n_warn": by_sev.get("warn", 0),
                    "n_info": by_sev.get("info", 0),
                    "by_severity": by_sev, "by_type": by_type},
        "validators_run": vrun,
    }
