#!/usr/bin/env python3
"""build_framework_health.py — derive + emit the framework-health dashboard.

A DERIVED artifact (never hand-authored), in the same family as
build_subgroup_coverage_matrix.py. It AST-probes ground truth across the
framework repos (skills + the cards they consume), computes a deterministic
first-match health verdict per component, flags drift vs declared status, and
emits:
  health/framework_health.json   — the structured feed
  health/framework_health.html   — a self-contained dashboard (no server/CDN)

--check recomputes in memory and compares a STABLE PROJECTION (dropping volatile
fields: generated_at + git shas) against the committed JSON — exit 1 on diff. This
is one refinement over the coverage-matrix's raw byte-compare, which would
false-positive on the timestamp.

Usage:
  python validators/framework_health/build_framework_health.py            # generate
  python validators/framework_health/build_framework_health.py --check    # CI staleness guard
  python validators/framework_health/build_framework_health.py --skills-repo /path ...
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Support both `python -m validators.framework_health.build_framework_health`
# and direct-script invocation (the convention the other validators use).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from validators.framework_health import probe, render_html, rollup
else:
    from . import probe, render_html, rollup

SCHEMA_VERSION = "1.0.0"
HEALTH_DIR = probe.CONTRACTS_REPO / "health"
JSON_PATH = HEALTH_DIR / "framework_health.json"
HTML_PATH = HEALTH_DIR / "framework_health.html"


def _git_sha(repo: Path) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def compute_delta(prior: dict | None, fresh_body: dict) -> dict | None:
    """What changed since the last committed artifact — a VOLATILE, relative-to-last-run
    field (dropped from the stable projection, like generated_at). None if no prior exists.

    Kept deliberately small: the headline count moves + the NAMES of skills/cards that
    appeared or disappeared (the "what changed" a maintainer scans for), plus the net
    move in each skill verdict and in error-severity drift. Not part of the derived
    truth — purely a diff of two truths — so it never feeds --check or self_check.
    """
    if not prior:
        return None
    ps, fs = prior.get("summary", {}), fresh_body.get("summary", {})
    prior_skills = {s["name"] for s in prior.get("skills", [])}
    fresh_skills = {s["name"] for s in fresh_body.get("skills", [])}
    prior_cards = {c["card_id"] for c in prior.get("cards", [])}
    fresh_cards = {c["card_id"] for c in fresh_body.get("cards", [])}

    def _tally_delta(key: str) -> dict:
        pt, ft = ps.get(key, {}) or {}, fs.get(key, {}) or {}
        return {k: ft.get(k, 0) - pt.get(k, 0) for k in sorted(set(pt) | set(ft)) if ft.get(k, 0) != pt.get(k, 0)}

    return {
        "has_prior": True,
        "prior_generated_at": prior.get("generated_at"),
        "n_skills": fs.get("n_skills", 0) - ps.get("n_skills", 0),
        "n_cards": fs.get("n_cards", 0) - ps.get("n_cards", 0),
        "n_drift_flags": fs.get("n_drift_flags", 0) - ps.get("n_drift_flags", 0),
        "n_error_drift": fs.get("n_error_drift", 0) - ps.get("n_error_drift", 0),
        "verdict_tally": _tally_delta("verdict_tally"),
        "card_health_tally": _tally_delta("card_health_tally"),
        "skills_added": sorted(fresh_skills - prior_skills),
        "skills_removed": sorted(prior_skills - fresh_skills),
        "cards_added": sorted(fresh_cards - prior_cards),
        "cards_removed": sorted(prior_cards - fresh_cards),
    }


def generate(roots: dict[str, Path], prior: dict | None = None) -> dict:
    """Full report envelope (body + volatile provenance fields).

    `prior` (the currently-committed report, if any) is diffed into a volatile
    `delta` field so the dashboard can show what moved since the last run.
    """
    body = rollup.build_health(roots)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "<stamped-at-write>",  # set at write time; excluded from --check
        "roots": {k: str(v) for k, v in roots.items()},
        "root_shas": {k: _git_sha(v) for k, v in roots.items()},
        "delta": compute_delta(prior, body),  # volatile: relative to the prior artifact
        **body,
    }


def stable_projection(report: dict) -> str:
    """Canonical serialization with volatile fields dropped — the --check basis.

    `delta` joins generated_at/roots/root_shas as volatile: it is a diff against the
    PRIOR artifact, so it legitimately changes run-to-run and must not make --check
    (which asks "is the committed derived-truth stale?") false-positive.

    `derived.test_count` is projected to the boolean the verdict actually consumes.
    The raw count is a `len(glob("test_*.py"))` over `skills/<skill>/tests/` in the
    SKILLS repo, so it increments whenever a skills-repo session adds a test file —
    sibling churn no target-contracts change caused, the same property that made
    `roots`/`md_path` poison the atlas guard. But the count is verdict-inert except
    through `has_tests = test_count > 0` (rollup.build_skill → health_rules.yaml);
    only the 1↔0 transition can move a health verdict. So the projection keeps that
    transition's teeth and drops the rest: 12→13 no longer reports STALE, 1→0 still
    does. The raw count stays in the committed artifact for display (render_html,
    the atlas dashboard) — this narrows the drift BASIS, not the artifact.
    """
    volatile = {"generated_at", "roots", "root_shas", "delta"}
    projected = {k: v for k, v in report.items() if k not in volatile}
    projected["skills"] = [_project_skill(s) for s in projected.get("skills", [])]
    return json.dumps(projected, indent=2, sort_keys=True, default=str)


def _project_skill(skill: dict) -> dict:
    """Reduce a skill entry to its drift-relevant shape: `derived.test_count` → the
    consumed `has_tests` boolean. Copy-on-write so the caller's report is untouched."""
    der = skill.get("derived")
    if not isinstance(der, dict) or "test_count" not in der:
        return skill
    der = {k: v for k, v in der.items() if k != "test_count"}
    der["has_tests"] = (skill["derived"].get("test_count") or 0) > 0
    return {**skill, "derived": der}


# Enums the committed artifact must conform to (kept in sync with health_rules.yaml).
_SKILL_VERDICTS = {"production_ready", "ready_unproven", "partial", "placeholder", "broken_or_drift"}
_CARD_HEALTHS = {"live", "wired", "partial", "blocked", "placeholder", "broken", "self_produced"}
# P4 modality-vector lens (parallel to card_health — see probe.probe_card).
_MODALITY_ROUTINGS = {"declared", "not_required", "missing", "drift", "not_applicable", "unknown"}


def self_check(report_path: Path) -> tuple[bool, list[str]]:
    """Validate the COMMITTED artifact's internal integrity WITHOUT probing siblings.

    This is the CI-safe check: a checkout-only runner cannot reach the four sibling
    repos, so a full recompute would degrade and falsely report STALE. Instead we
    assert the committed JSON is well-formed, self-consistent, and re-rolls-up
    deterministically to the verdicts it records — the invariants that CAN be
    verified from this repo alone. Full cross-repo staleness stays a local/manual
    guard (plain --check with siblings present).
    """
    errs: list[str] = []
    if not report_path.exists():
        return False, [f"{report_path.name} missing — generate it first"]
    try:
        rep = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return False, [f"{report_path.name} unreadable: {e}"]

    # 1. Envelope shape.
    for key in ("schema_version", "summary", "skills", "registry_drift", "drift_index"):
        if key not in rep:
            errs.append(f"envelope missing required key '{key}'")
    if errs:
        return False, errs

    # 2. Per-skill enum conformance + verdict re-derivation from the recorded cards.
    rules = rollup.load_rules()
    tally: dict[str, int] = {}
    for n in rep["skills"]:
        v = n.get("health_verdict")
        tally[v] = tally.get(v, 0) + 1
        if v not in _SKILL_VERDICTS:
            errs.append(f"[{n.get('name')}] invalid health_verdict '{v}'")
        for c in n.get("cards", []):
            if c.get("card_health") not in _CARD_HEALTHS:
                errs.append(f"[{n.get('name')}/{c.get('card_id')}] invalid card_health '{c.get('card_health')}'")
            # Re-roll each card from its own recorded signals — determinism guard.
            got, _ = rollup._resolve(rules["card_health"], c)
            if got != c.get("card_health"):
                errs.append(
                    f"[{n.get('name')}/{c.get('card_id')}] card_health '{c.get('card_health')}' "
                    f"does not re-derive from its signals (got '{got}') — regenerate"
                )

    # 3. Summary tally must match the skills list it summarizes.
    if rep["summary"].get("verdict_tally") != tally:
        errs.append(
            f"summary.verdict_tally {rep['summary'].get('verdict_tally')} "
            f"disagrees with per-skill count {tally} — regenerate"
        )

    # 4. Card-centric section (if present): enum conformance + re-derivation +
    #    orphan-flag consistency + tally agreement.
    cards = rep.get("cards")
    if cards is not None:
        ctally: dict[str, int] = {}
        for c in cards:
            ch = c.get("card_health")
            ctally[ch] = ctally.get(ch, 0) + 1
            if ch not in _CARD_HEALTHS:
                errs.append(f"[card {c.get('card_id')}] invalid card_health '{ch}'")
            got, _ = rollup._resolve(rules["card_health"], c)
            if got != ch:
                errs.append(
                    f"[card {c.get('card_id')}] card_health '{ch}' does not re-derive (got '{got}') — regenerate"
                )
            if c.get("is_orphan") != (c.get("n_consumers", 0) == 0):
                errs.append(f"[card {c.get('card_id')}] is_orphan disagrees with n_consumers")
            if "is_staged_orphan" in c and c.get("is_staged_orphan") != (
                c.get("is_orphan") and bool(c.get("is_placeholder"))
            ):
                errs.append(f"[card {c.get('card_id')}] is_staged_orphan inconsistent")
        if rep["summary"].get("card_health_tally") != ctally:
            errs.append("summary.card_health_tally disagrees with per-card count — regenerate")

    # 4b. Datasets section (if present): orphan/broken-ref flags internally consistent.
    datasets = rep.get("datasets")
    if datasets is not None:
        for d in datasets:
            if d.get("is_orphan") != (d.get("in_catalog") and d.get("n_consumers", 0) == 0):
                errs.append(f"[dataset {d.get('product_id')}] is_orphan inconsistent")
            # broken = referenced, missing from catalog, and NOT a placeholder-only forward-declaration
            # (those are pending, not broken).
            _apc = d.get("all_consumers_placeholder")
            if d.get("is_broken_ref") != ((not d.get("in_catalog")) and d.get("n_consumers", 0) > 0 and not _apc):
                errs.append(f"[dataset {d.get('product_id')}] is_broken_ref inconsistent")
            if "is_pending_ref" in d and d.get("is_pending_ref") != (
                (not d.get("in_catalog")) and d.get("n_consumers", 0) > 0 and bool(_apc)
            ):
                errs.append(f"[dataset {d.get('product_id')}] is_pending_ref inconsistent")
            # Access-cost lens (only for artifacts that carry it): re-derive the band + the
            # missing-sort-key flag from the recorded static inputs — the determinism guard.
            if "access_cost" in d:
                got = rollup._access_cost(d.get("size_bytes"), d.get("file_count"), d.get("n_consumers", 0))
                if got != d.get("access_cost"):
                    errs.append(
                        f"[dataset {d.get('product_id')}] access_cost '{d.get('access_cost')}' "
                        f"does not re-derive (got '{got}') — regenerate"
                    )
            if "missing_sort_key" in d:
                expect = bool(
                    d.get("in_catalog")
                    and d.get("kind") == "derived"
                    and d.get("n_consumers", 0) > 0
                    and d.get("has_sort_key") is False
                    and (d.get("size_bytes") or 0) >= rollup._SORT_KEY_SIZE_FLOOR
                )
                if d.get("missing_sort_key") != expect:
                    errs.append(f"[dataset {d.get('product_id')}] missing_sort_key inconsistent")

    # 4c. Card spec-coverage flag consistency (consumed_but_no_spec) — only for
    # cards that actually carry the field (skip minimal/older artifacts).
    for c in rep.get("cards", []):
        if "consumed_but_no_spec" not in c:
            continue
        expect = c.get("n_consumers", 0) > 0 and not c.get("in_dashboard_spec")
        if c.get("consumed_but_no_spec") != expect:
            errs.append(f"[card {c.get('card_id')}] consumed_but_no_spec inconsistent")

    # 4d. P4 modality-routing lens (if present): enum conformance + tally + count
    #     agreement. Parallel to card_health — never affects it — so checked separately.
    if cards is not None and "modality_routing_tally" in rep.get("summary", {}):
        mtally: dict[str, int] = {}
        for c in cards:
            mr = c.get("modality_routing")
            mtally[mr] = mtally.get(mr, 0) + 1
            if mr not in _MODALITY_ROUTINGS:
                errs.append(f"[card {c.get('card_id')}] invalid modality_routing '{mr}'")
        if rep["summary"].get("modality_routing_tally") != mtally:
            errs.append("summary.modality_routing_tally disagrees with per-card count — regenerate")
        req = sum(mtally.get(k, 0) for k in ("declared", "missing", "drift"))
        dec = sum(mtally.get(k, 0) for k in ("declared", "drift"))
        if rep["summary"].get("n_p4_required_cards") != req:
            errs.append("summary.n_p4_required_cards disagrees with the routing tally — regenerate")
        if rep["summary"].get("n_p4_declared_cards") != dec:
            errs.append("summary.n_p4_declared_cards disagrees with the routing tally — regenerate")
        if rep["summary"].get("n_p4_missing_cards") != mtally.get("missing", 0):
            errs.append("summary.n_p4_missing_cards disagrees with the routing tally — regenerate")
        if rep["summary"].get("n_p4_drift_cards") != mtally.get("drift", 0):
            errs.append("summary.n_p4_drift_cards disagrees with the routing tally — regenerate")

    # 5. Graph section (if present): every edge endpoint must resolve to a node
    #    (a dangling edge is drift), and counts must agree.
    graph = rep.get("graph")
    if graph is not None:
        node_ids = {n["id"] for n in graph.get("nodes", [])}
        for e in graph.get("edges", []):
            if e["src"] not in node_ids:
                errs.append(f"[graph] edge src '{e['src']}' has no node")
            if e["dst"] not in node_ids:
                errs.append(f"[graph] edge dst '{e['dst']}' has no node")
        if graph.get("n_nodes") != len(node_ids):
            errs.append("[graph] n_nodes disagrees with node list — regenerate")
        if graph.get("n_edges") != len(graph.get("edges", [])):
            errs.append("[graph] n_edges disagrees with edge list — regenerate")

    # 6. Descriptor-coverage section (if present): the FIELD-VOCABULARY lens.
    #
    # Every invariant here is re-derived from the section's OWN recorded data — never by
    # re-reading the skills sibling, which this runner cannot see. That is deliberate: a
    # cross-repo check that degrades to "sibling absent, skipping" in the only environment
    # that ever runs it is VACUOUS, and would sit here looking like coverage forever. These
    # checks fire on the committed bytes alone, so they can actually fail in CI.
    dcov = rep.get("descriptor_coverage")
    if dcov is not None:
        summary = rep.get("summary", {})
        if summary.get("descriptor_coverage_available") != bool(dcov.get("available")):
            errs.append("summary.descriptor_coverage_available disagrees with the section — regenerate")

        if not dcov.get("available"):
            # An UNMEASURED dimension must not publish counts: a 0 in the summary would be
            # plotted as "no gaps" when the truth is "nobody looked". Absence is a null.
            for key in (
                "n_descriptor_cells",
                "n_distinct_descriptor_fields",
                "n_gloss_without_descriptor",
                "n_numeric_fields_without_gloss",
            ):
                if summary.get(key) is not None:
                    errs.append(
                        f"summary.{key} is {summary.get(key)!r} but descriptor coverage is "
                        f"UNAVAILABLE — an unmeasured dimension must be null, not a number"
                    )
        else:
            dsum = dcov.get("summary") or {}
            rosters = dcov.get("rosters") or {}
            declared = rosters.get("declared_fields")
            by_type = dcov.get("fields_by_measurement_type")
            if not isinstance(declared, list) or not isinstance(by_type, dict):
                errs.append("[descriptor_coverage] available but missing rosters/fields_by_measurement_type")
            else:
                # Cell count vs DISTINCT field count. These are different numbers (some fields
                # are declared by several measurement_types) and the skills-side census exposes
                # the cell count under the field-shaped name `n_descriptor_fields`, so a
                # consumer that reconciles the wrong one over-counts the roster. Pin both.
                cells = sum(len(v) for v in by_type.values())
                if dsum.get("n_descriptor_cells") != cells:
                    errs.append(
                        f"[descriptor_coverage] n_descriptor_cells {dsum.get('n_descriptor_cells')} "
                        f"disagrees with fields_by_measurement_type ({cells}) — regenerate"
                    )
                if dsum.get("n_distinct_fields") != len(set(declared)):
                    errs.append("[descriptor_coverage] n_distinct_fields disagrees with declared_fields — regenerate")
                if len(declared) != len(set(declared)):
                    errs.append("[descriptor_coverage] declared_fields contains duplicates")
                if dsum.get("n_measurement_types") != len(by_type):
                    errs.append("[descriptor_coverage] n_measurement_types disagrees with the per-type map")

                # multi_type_fields must be exactly the fields the per-type map shows more than
                # once — a real re-derivation, not a restatement of a recorded number.
                seen: dict[str, int] = {}
                for fields in by_type.values():
                    for f in fields:
                        seen[f] = seen.get(f, 0) + 1
                expect_multi = sorted(f for f, n in seen.items() if n > 1)
                if sorted(dcov.get("multi_type_fields") or []) != expect_multi:
                    errs.append(
                        "[descriptor_coverage] multi_type_fields does not re-derive from "
                        "fields_by_measurement_type — regenerate"
                    )
                if sorted(seen) != sorted(set(declared)):
                    errs.append("[descriptor_coverage] declared_fields disagrees with the per-type map — regenerate")

                # The gloss queue: every entry must genuinely lack a descriptor. If one of these
                # ever appears in declared_fields the queue is reporting resolved work as open.
                leaked = [f for f in (dcov.get("gloss_without_descriptor") or []) if f in set(declared)]
                if leaked:
                    errs.append(
                        f"[descriptor_coverage] gloss_without_descriptor lists field(s) that ARE "
                        f"declared: {leaked[:5]} — regenerate"
                    )

                # Roles must come from the published vocabulary, or a consumer's set membership
                # test silently routes a field to `unclassified`.
                roles = set(rosters.get("roles") or [])
                unknown = sorted(set((rosters.get("role_by_field") or {}).values()) - roles)
                if roles and unknown:
                    errs.append(f"[descriptor_coverage] role_by_field uses roles outside the vocabulary: {unknown}")
                if set(rosters.get("numeric_roles") or []) - roles:
                    errs.append("[descriptor_coverage] numeric_roles is not a subset of roles")

                # Summary mirrors must agree with the section they summarize.
                for top, inner in (
                    ("n_descriptor_cells", "n_descriptor_cells"),
                    ("n_distinct_descriptor_fields", "n_distinct_fields"),
                    ("n_gloss_without_descriptor", "n_gloss_without_descriptor"),
                    ("n_numeric_fields_without_gloss", "n_numeric_fields_without_gloss"),
                    ("n_measurement_types_with_descriptors", "n_measurement_types"),
                ):
                    if summary.get(top) != dsum.get(inner):
                        errs.append(f"summary.{top} disagrees with descriptor_coverage.summary.{inner} — regenerate")

                # Counts vs their own lists.
                for count_key, list_key in (
                    ("n_gloss_without_descriptor", "gloss_without_descriptor"),
                    ("n_multi_type_fields", "multi_type_fields"),
                    ("n_numeric_fields_without_gloss", "numeric_fields_without_gloss"),
                ):
                    if dsum.get(count_key) != len(dcov.get(list_key) or []):
                        errs.append(f"[descriptor_coverage] {count_key} disagrees with {list_key} — regenerate")

                # The census warns, in the artifact itself, that an empty `unclassified` set
                # means the classifier is FABRICATING roles rather than that coverage is
                # complete. The consumer of this dimension lives in another repo and will only
                # ever read that note, so its absence is a defect in the feed.
                note = dcov.get("note") or ""
                if "FABRICATING" not in note:
                    errs.append(
                        "[descriptor_coverage] the census note no longer warns that a zero "
                        "unclassified count means fabricated roles — a consumer would read zero "
                        "as success; regenerate from the skills producer"
                    )

    return (not errs), errs


def _resolve_roots(args) -> dict[str, Path]:
    roots = probe.default_roots()
    for key, val in (
        ("skills", args.skills_repo),
        ("methods", args.methods_repo),
        ("products", args.products_root),
        ("catalog", args.catalog_repo),
        ("contracts", args.contracts_repo),
    ):
        if val:
            roots[key] = Path(val)
    return roots


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build/check the framework-health dashboard.")
    p.add_argument(
        "--check",
        action="store_true",
        help="fail (exit 1) if the committed dashboard is stale vs freshly computed "
        "(needs sibling repos present — local/manual guard)",
    )
    p.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: validate the committed artifact's internal integrity only "
        "(no sibling-repo probes); use in checkout-only CI",
    )
    p.add_argument("--skills-repo", type=Path)
    p.add_argument("--methods-repo", type=Path)
    p.add_argument("--products-root", type=Path)
    p.add_argument("--catalog-repo", type=Path)
    p.add_argument("--contracts-repo", type=Path)
    p.add_argument("--json-only", action="store_true", help="skip HTML emission")
    args = p.parse_args(argv)

    # --self-check does NOT probe siblings — it validates the committed artifact alone.
    if args.self_check:
        ok, errs = self_check(JSON_PATH)
        if ok:
            print(f"  OK {JSON_PATH.name} (self-consistent)")
            return 0
        for e in errs:
            print(f"  FAIL {e}", file=sys.stderr)
        return 1

    roots = _resolve_roots(args)
    missing = [k for k, v in roots.items() if not v.exists()]
    if missing:
        print(f"  WARNING: repo root(s) not found, probes will degrade: {missing}", file=sys.stderr)

    # Load the currently-committed artifact (if any) BEFORE we overwrite it — used both
    # as the --check comparison basis and as the `prior` the delta diffs against.
    prior = None
    if JSON_PATH.exists():
        try:
            prior = json.loads(JSON_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            prior = None

    report = generate(roots, prior=prior)
    fresh_projection = stable_projection(report)

    if args.check:
        if prior is None:
            print(f"  MISSING/UNREADABLE {JSON_PATH.name} — run without --check to generate.", file=sys.stderr)
            return 1
        if stable_projection(prior) != fresh_projection:
            print(f"  STALE {JSON_PATH.name} — committed dashboard differs from computed; regenerate.", file=sys.stderr)
            return 1
        print(f"  OK {JSON_PATH.name} (fresh)")
        return 0

    # Generate mode: stamp the timestamp now, write JSON + HTML.
    import datetime

    report["generated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(report, indent=2, default=str))
    s = report["summary"]
    print(
        f"  wrote {JSON_PATH.relative_to(probe.CONTRACTS_REPO)}: "
        f"{s['n_skills']} skills, tally={s['verdict_tally']}, "
        f"{s['n_drift_flags']} drift flags ({s['n_error_drift']} error), "
        f"{s['n_unregistered_skills']} unregistered"
    )
    if not args.json_only:
        html = render_html.render(report)
        HTML_PATH.write_text(html)
        print(f"  wrote {HTML_PATH.relative_to(probe.CONTRACTS_REPO)} ({len(html) // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
