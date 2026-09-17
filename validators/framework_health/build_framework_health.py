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
from collections import Counter
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

    # 7. Field-read-health section (if present): reads MINUS declarations, plus the emission
    #    split this repo adds. Re-derived from the section's OWN bytes for the same reason as
    #    (6): the runner sees neither the skills sibling nor the products root, and a check that
    #    degrades to "skipping" in the only environment that runs it is vacuous.
    frh = rep.get("field_read_health")
    if frh is not None:
        summary = rep.get("summary", {})
        if summary.get("field_read_health_available") != bool(frh.get("available")):
            errs.append("summary.field_read_health_available disagrees with the section — regenerate")

        _FRH_COUNTS = (
            "n_field_read_units",
            "n_field_read_units_clean",
            "n_field_read_units_no_reads_detected",
            "n_undeclared_field_reads",
            "n_field_reads_emitted_but_undeclared",
            "n_field_reads_of_none",
            "n_field_reads_emission_unobserved",
        )
        if not frh.get("available"):
            for key in _FRH_COUNTS:
                if summary.get(key) is not None:
                    errs.append(
                        f"summary.{key} is {summary.get(key)!r} but field-read health is "
                        f"UNAVAILABLE — an unmeasured dimension must be null, not a number"
                    )
        else:
            fsum = frh.get("summary") or {}
            units = frh.get("units")
            queue = frh.get("undeclared_queue")
            if not isinstance(units, dict) or not isinstance(queue, list):
                errs.append("[field_read_health] available but missing units/undeclared_queue")
            else:
                # Dispositions re-derive from the per-unit records, not from the recorded tally.
                disp = Counter(u.get("disposition") for u in units.values())
                for key, want in (
                    ("n_units", len(units)),
                    ("n_clean", disp["clean"]),
                    ("n_units_with_undeclared_reads", disp["undeclared_reads"]),
                    ("n_no_reads_detected", disp["no_reads_detected"]),
                    ("n_undeclared_pairs", len(queue)),
                ):
                    if fsum.get(key) != want:
                        errs.append(
                            f"[field_read_health] summary.{key} disagrees with the units/queue ({want}) — regenerate"
                        )
                unknown_disp = sorted(d for d in disp if d not in ("clean", "undeclared_reads", "no_reads_detected"))
                if unknown_disp:
                    errs.append(
                        f"[field_read_health] unknown disposition(s) {unknown_disp} — the producer's vocabulary changed"
                    )

                # Every queue row must trace back to its own unit's `undeclared` list. This is the
                # check that a flat queue and a per-unit map cannot silently disagree — the exact
                # drift that transcribing the same facts in two shapes invites.
                for row in queue:
                    u = units.get(row.get("unit"))
                    if u is None:
                        errs.append(f"[field_read_health] queue row names unit '{row.get('unit')}' that has no record")
                        continue
                    if not any(
                        d.get("card") == row.get("card") and d.get("field") == row.get("field")
                        for d in u.get("undeclared") or []
                    ):
                        errs.append(
                            f"[field_read_health] queue row {row.get('card')}.{row.get('field')} is not in "
                            f"unit '{row.get('unit')}'.undeclared — regenerate"
                        )
                    if row.get("classification") not in ("meta_key", "emission_undetermined"):
                        errs.append(
                            f"[field_read_health] row {row.get('card')}.{row.get('field')} carries "
                            f"classification {row.get('classification')!r}, outside the producer's vocabulary"
                        )

                # The emission axis: vocabulary, and the aperture/outcome agreement in BOTH
                # directions. Resolving a row with nothing scanned, or leaving one unresolved with
                # packages in hand, are opposite failures and each gets its own message.
                aperture = frh.get("emission_aperture") or {}
                outcomes = [r.get("emission_outcome") for r in queue]
                unknown_out = sorted(
                    str(o) for o in set(outcomes) if o is not None and o not in rollup._EMISSION_OUTCOMES
                )
                if unknown_out:
                    errs.append(f"[field_read_health] emission_outcome(s) outside the vocabulary: {unknown_out}")
                if frh.get("n_emission_unresolved") != sum(1 for o in outcomes if o is None):
                    errs.append("[field_read_health] n_emission_unresolved disagrees with the rows — regenerate")
                if aperture.get("available"):
                    if any(o is None for o in outcomes):
                        errs.append(
                            "[field_read_health] a row is UNRESOLVED while the emission aperture reports "
                            f"{aperture.get('n_packages')} package(s) — every row is decidable when packages were scanned"
                        )
                    tally = frh.get("emission_outcome_tally") or {}
                    for outcome in rollup._EMISSION_OUTCOMES:
                        want = sum(1 for o in outcomes if o == outcome)
                        if tally.get(outcome) != want:
                            errs.append(
                                f"[field_read_health] emission_outcome_tally[{outcome}] disagrees with the rows ({want}) — regenerate"
                            )
                    for key, mirror in (
                        ("n_field_reads_emitted_but_undeclared", "emitted_but_undeclared"),
                        ("n_field_reads_of_none", "read_of_None"),
                        ("n_field_reads_emission_unobserved", "emission_unobserved"),
                    ):
                        if summary.get(key) != tally.get(mirror):
                            errs.append(f"summary.{key} disagrees with emission_outcome_tally[{mirror}] — regenerate")
                    n_obs, n_roster = aperture.get("n_cards_observed"), aperture.get("n_roster_cards")
                    n_roster_obs = aperture.get("n_roster_cards_observed")
                    if isinstance(n_roster_obs, int) and isinstance(n_obs, int) and n_roster_obs > n_obs:
                        errs.append("[field_read_health] n_roster_cards_observed exceeds n_cards_observed — impossible")
                    if isinstance(n_roster_obs, int) and isinstance(n_roster, int) and n_roster_obs > n_roster:
                        errs.append("[field_read_health] n_roster_cards_observed exceeds n_roster_cards — impossible")
                else:
                    # Nothing scanned: every outcome AND every count must be null. A zero here would
                    # be read as "no field ever handed the model None", the worst available lie.
                    if any(o is not None for o in outcomes):
                        errs.append(
                            "[field_read_health] a row carries an emission_outcome while the aperture is "
                            "UNAVAILABLE — an unscanned row cannot be resolved"
                        )
                    for outcome, n in (frh.get("emission_outcome_tally") or {}).items():
                        if n is not None:
                            errs.append(
                                f"[field_read_health] emission_outcome_tally[{outcome}] is {n!r} with an empty aperture — must be null"
                            )

                # The projection: the roster is deliberately NOT copied through, so its two counts
                # are the only trace left and must still match the census summary they came from.
                pin = frh.get("roster_pin") or {}
                if pin.get("n_cards") != fsum.get("n_roster_cards") or pin.get("n_fields") != fsum.get(
                    "n_roster_fields"
                ):
                    errs.append("[field_read_health] roster_pin disagrees with the census summary — regenerate")
                if "declared_fields" in (frh.get("rosters") or {}):
                    errs.append(
                        "[field_read_health] rosters.declared_fields was copied through — the projection is not applied"
                    )

                # Attribution: the census publishes whether per-unit scrapes reproduce the whole-tree
                # scrape. A `reconciled` flag that disagrees with its own numbers is worse than absent.
                att = frh.get("attribution") or {}
                if att:
                    agrees = att.get("whole_tree_pairs") == att.get("per_unit_union_pairs")
                    if bool(att.get("reconciled")) != agrees:
                        errs.append("[field_read_health] attribution.reconciled disagrees with its own pair counts")
                    if not agrees and not att.get("unattributed"):
                        errs.append("[field_read_health] attribution is unreconciled but lists no unattributed reads")

                # The producer's note carries the one warning a consumer in this repo cannot
                # re-derive: that no_reads_detected is instrument silence, not health. Checked for
                # PRESENCE (never absence of a retracted phrase), because losing it would let a
                # dashboard render 7 unmeasured units as 7 healthy ones.
                if "NOT that the unit is clean" not in (frh.get("note") or ""):
                    errs.append(
                        "[field_read_health] the census note no longer warns that no_reads_detected is "
                        "NOT a clean bill of health — regenerate from the skills producer"
                    )

    # 8. Axis-measurability section (if present): the skills static CAPABILITY census plus the
    #    derived-vs-declared reconcile this repo adds. Re-derived from the section's OWN bytes for
    #    the same reason as (6) and (7) — the CI runner sees neither the skills sibling nor the
    #    governed vocab, so a check that needs them would degrade to "skipping" in the only
    #    environment that runs it.
    mapd = rep.get("measured_axes_per_dim")
    if mapd is not None:
        summary = rep.get("summary", {})
        if summary.get("axis_measurability_available") != bool(mapd.get("available")):
            errs.append("summary.axis_measurability_available disagrees with the section — regenerate")

        _MAPD_COUNTS = (
            "n_measurement_types_without_descriptor",
            "n_measurement_types_declared_by_axes",
            "n_axes_descriptor_covered",
            "n_axes_descriptor_blind",
        )
        _RECONCILE_COUNTS = (
            "n_axis_types_declared_not_derived",
            "n_axis_types_derived_nowhere_declared",
            "n_axis_types_derived_declared_elsewhere",
            "n_governed_types_without_card_view",
            "n_governed_types_card_exists_unpulled",
            "n_skill_cards_without_registered_type",
        )
        if not mapd.get("available"):
            for key in _MAPD_COUNTS + _RECONCILE_COUNTS:
                if summary.get(key) is not None:
                    errs.append(
                        f"summary.{key} is {summary.get(key)!r} but axis measurability is "
                        f"UNAVAILABLE — an unmeasured dimension must be null, not a number"
                    )
        else:
            msum = mapd.get("summary") or {}
            axes = mapd.get("axes")
            dims = mapd.get("dims")
            rec = mapd.get("reconcile") or {}
            if not isinstance(axes, dict) or not isinstance(dims, dict):
                errs.append("[measured_axes_per_dim] available but missing axes/dims")
            else:
                # Static states re-derive from the per-axis records, not from the recorded counts.
                states = Counter(a.get("static_state") for a in axes.values())
                declared_states = set(((mapd.get("rosters") or {}).get("static_states")) or ())
                unknown_states = sorted(str(s) for s in states if s not in declared_states)
                if declared_states and unknown_states:
                    errs.append(
                        f"[measured_axes_per_dim] static_state(s) outside the published vocabulary: "
                        f"{unknown_states} — the producer's vocabulary changed"
                    )
                # CAPABILITY vs OUTCOME, enforced on the bytes: the static vocabulary must not
                # acquire a per-run coverage state name. If the two ever converge, a consumer can
                # join a declaration onto a measurement and neither reading survives.
                collided = sorted(declared_states & {"measured", "unmeasured", "undescribed", "absent"})
                if collided:
                    errs.append(
                        f"[measured_axes_per_dim] static state(s) {collided} collide with the per-run "
                        f"coverage vocabulary — capability and outcome must stay nameable apart"
                    )
                for key, want in (
                    ("n_axes", len(axes)),
                    ("n_dims", len(dims)),
                    ("n_axes_descriptor_covered", states["descriptor_covered"]),
                    ("n_axes_descriptor_blind", states["descriptor_blind"]),
                    ("n_axes_not_a_fanout_axis", states["not_a_fanout_axis"]),
                ):
                    if msum.get(key) != want:
                        errs.append(
                            f"[measured_axes_per_dim] summary.{key} disagrees with the axes/dims ({want}) — regenerate"
                        )
                # The per-TYPE queue is the headline number, so it must equal its own list.
                blind_types = mapd.get("types_without_measurement_descriptor")
                if not isinstance(blind_types, list):
                    errs.append("[measured_axes_per_dim] types_without_measurement_descriptor is missing")
                elif msum.get("n_types_without_measurement_descriptor") != len(blind_types):
                    errs.append(
                        "[measured_axes_per_dim] n_types_without_measurement_descriptor disagrees with its list"
                    )
                # Descriptor coverage is a property of the TYPE, not of the axis: a type may not be
                # blind under one axis and covered under another, or every union over axes is
                # ambiguous and the per-dim roll-ups mean nothing.
                per_axis_blind = {
                    t for a in axes.values() for t in (a.get("types_without_measurement_descriptor") or [])
                }
                # EQUALITY, not containment: the producer builds the global list AS the union over
                # declared axes, so a global entry no axis owns is just as much a defect as an axis
                # entry missing from the global list — and it is the direction that would let the
                # headline type-queue grow without any axis becoming actionable. Measured equal
                # (62 == 62) at the time this was written.
                if isinstance(blind_types, list) and per_axis_blind != set(blind_types):
                    errs.append(
                        "[measured_axes_per_dim] the global undescribed-type list is not the union "
                        f"over axes (global-only={sorted(set(blind_types) - per_axis_blind)}, "
                        f"axis-only={sorted(per_axis_blind - set(blind_types))}) — regenerate"
                    )
                # A card-fed pseudo-dim reads 0-of-1 axes covered and is NOT blind. Only
                # `not_a_fanout_axes` distinguishes the two, so a dim with no covered axes and no
                # named non-fan-out axis would be rendered as an instrument gap it is not.
                for dname, d in dims.items():
                    if d.get("n_axes_descriptor_covered") == 0 and not (
                        (d.get("not_a_fanout_axes") or []) or (d.get("descriptor_blind_axes") or [])
                    ):
                        errs.append(
                            f"[measured_axes_per_dim] dim '{dname}' reports no covered axis and names "
                            f"neither a blind nor a non-fan-out axis — 0 would render as blindness"
                        )
                # The projection: the two input rosters are deliberately not copied through, so the
                # pin is the only trace left and must still match the census it came from.
                pin = mapd.get("roster_pin") or {}
                if pin.get("n_cards_distinct") != msum.get("n_declared_cards_distinct") or pin.get(
                    "n_types_distinct"
                ) != msum.get("n_declared_types_distinct"):
                    errs.append("[measured_axes_per_dim] roster_pin disagrees with the census summary — regenerate")
                for dropped in ("cards_by_axis", "declared_types_by_axis"):
                    if dropped in (mapd.get("rosters") or {}):
                        errs.append(
                            f"[measured_axes_per_dim] rosters.{dropped} was copied through — the projection is not applied"
                        )
                # The producer's note carries the one warning this repo cannot re-derive: that the
                # per-axis flag is the saturated half and must not be headlined. Checked for
                # PRESENCE, because losing it would let a dashboard plot 14-of-15 as near-done.
                if "DO NOT HEADLINE" not in (mapd.get("note") or ""):
                    errs.append(
                        "[measured_axes_per_dim] the census note no longer warns against headlining "
                        "the per-axis flag — regenerate from the skills producer"
                    )

                # The reconcile half, which can be unavailable on its own (a readable skills
                # sibling with an unreadable vocab is a real state, not a contradiction).
                if summary.get("axis_type_reconcile_available") != bool(rec.get("available")):
                    errs.append("summary.axis_type_reconcile_available disagrees with the reconcile — regenerate")
                if not rec.get("available"):
                    for key in _RECONCILE_COUNTS:
                        if summary.get(key) is not None:
                            errs.append(
                                f"summary.{key} is {summary.get(key)!r} but the reconcile is "
                                f"UNAVAILABLE — an unmeasured join must be null, not a number"
                            )
                    for outcome, n in (rec.get("outcome_tally") or {}).items():
                        if n is not None:
                            errs.append(
                                f"[measured_axes_per_dim] outcome_tally[{outcome}] is {n!r} with the "
                                f"vocab unreadable — must be null"
                            )
                else:
                    queue = rec.get("queue")
                    by_axis = rec.get("by_axis")
                    tally = rec.get("outcome_tally") or {}
                    if not isinstance(queue, list) or not isinstance(by_axis, dict):
                        errs.append("[measured_axes_per_dim] reconcile available but missing queue/by_axis")
                    else:
                        unknown_out = sorted(
                            str(r.get("outcome")) for r in queue if r.get("outcome") not in rollup._RECONCILE_OUTCOMES
                        )
                        if unknown_out:
                            errs.append(
                                f"[measured_axes_per_dim] reconcile outcome(s) outside the vocabulary: {unknown_out}"
                            )
                        # `agree` is a count only; every OTHER outcome must have one queue row each,
                        # so a tally and a queue cannot silently disagree.
                        for outcome in rollup._RECONCILE_OUTCOMES:
                            if outcome == "agree":
                                continue
                            want = sum(1 for r in queue if r.get("outcome") == outcome)
                            if tally.get(outcome) != want:
                                errs.append(
                                    f"[measured_axes_per_dim] outcome_tally[{outcome}] disagrees with the queue ({want}) — regenerate"
                                )
                        # Each row must trace back to its own axis record.
                        for row in queue:
                            rec_axis = by_axis.get(row.get("axis"))
                            if rec_axis is None:
                                errs.append(
                                    f"[measured_axes_per_dim] queue row names axis '{row.get('axis')}' with no record"
                                )
                                continue
                            bucket = rec_axis.get(row.get("outcome")) or []
                            if row.get("measurement_type") not in bucket:
                                errs.append(
                                    f"[measured_axes_per_dim] queue row {row.get('axis')}/"
                                    f"{row.get('measurement_type')} is not in that axis's "
                                    f"{row.get('outcome')} list — regenerate"
                                )
                        # `derived_declared_elsewhere` asserts a SECOND fact — that another axis
                        # declares the type — so the row has to name that axis or the label is
                        # firing on half its evidence.
                        for row in queue:
                            if row.get("outcome") == "derived_declared_elsewhere" and not row.get("declared_by"):
                                errs.append(
                                    f"[measured_axes_per_dim] {row.get('measurement_type')} is called "
                                    f"declared_elsewhere but names no declaring axis"
                                )
                        # A card with no registered type is undecidable, NOT disagreement: it must
                        # not appear in any outcome bucket.
                        no_type = set(rec.get("cards_without_registered_type") or ())
                        if rec.get("n_cards_without_registered_type") != len(no_type):
                            errs.append(
                                "[measured_axes_per_dim] n_cards_without_registered_type disagrees with its list"
                            )
                        unpulled = rec.get("unpulled_types") or []
                        u_tally = rec.get("unpulled_type_tally") or {}
                        unknown_states = sorted(
                            str(u.get("state")) for u in unpulled if u.get("state") not in rollup._UNPULLED_TYPE_STATES
                        )
                        if unknown_states:
                            errs.append(
                                f"[measured_axes_per_dim] unpulled-type state(s) outside the vocabulary: {unknown_states}"
                            )
                        for state in rollup._UNPULLED_TYPE_STATES:
                            want = sum(1 for u in unpulled if u.get("state") == state)
                            if u_tally.get(state) != want:
                                errs.append(
                                    f"[measured_axes_per_dim] unpulled_type_tally[{state}] disagrees with the rows ({want}) — regenerate"
                                )
                        # `no_card_view` asserts the absence of a card view, so a row in that state
                        # listing cards is self-contradictory.
                        for u in unpulled:
                            if u.get("state") == "no_card_view" and (u.get("cards") or []):
                                errs.append(
                                    f"[measured_axes_per_dim] {u.get('measurement_type')} is no_card_view "
                                    f"but lists cards {u.get('cards')}"
                                )
                        n_gov, n_pulled = rec.get("n_governed_types"), rec.get("n_governed_types_declared_by_an_axis")
                        if isinstance(n_gov, int) and isinstance(n_pulled, int):
                            if n_pulled > n_gov:
                                errs.append(
                                    "[measured_axes_per_dim] more governed types pulled than exist — impossible"
                                )
                            if n_gov - n_pulled != len(unpulled):
                                errs.append(
                                    f"[measured_axes_per_dim] {n_gov} governed types minus {n_pulled} pulled "
                                    f"does not equal the {len(unpulled)} unpulled row(s) — regenerate"
                                )
                        # Summary mirrors must agree with the section they summarize.
                        for top, inner in (
                            ("n_axis_types_declared_not_derived", "declared_not_derived"),
                            ("n_axis_types_derived_nowhere_declared", "derived_nowhere_declared"),
                            ("n_axis_types_derived_declared_elsewhere", "derived_declared_elsewhere"),
                        ):
                            if summary.get(top) != tally.get(inner):
                                errs.append(
                                    f"summary.{top} disagrees with reconcile.outcome_tally[{inner}] — regenerate"
                                )
                        for top, inner in (
                            ("n_governed_types_without_card_view", "no_card_view"),
                            ("n_governed_types_card_exists_unpulled", "card_exists_unpulled"),
                        ):
                            if summary.get(top) != u_tally.get(inner):
                                errs.append(
                                    f"summary.{top} disagrees with reconcile.unpulled_type_tally[{inner}] — regenerate"
                                )
                        if summary.get("n_skill_cards_without_registered_type") != rec.get(
                            "n_cards_without_registered_type"
                        ):
                            errs.append(
                                "summary.n_skill_cards_without_registered_type disagrees with the reconcile — regenerate"
                            )
                        # The reconcile's own note carries the reading order a consumer cannot
                        # re-derive: agreement is saturated, the unpulled split is not.
                        if "READ THE UNPULLED-TYPE SPLIT FIRST" not in (rec.get("note") or ""):
                            errs.append(
                                "[measured_axes_per_dim] the reconcile note no longer states the reading "
                                "order — a dashboard would headline the saturated `agree` count"
                            )
                for top, inner in (
                    ("n_measurement_types_without_descriptor", "n_types_without_measurement_descriptor"),
                    ("n_measurement_types_declared_by_axes", "n_declared_types_distinct"),
                    ("n_axes_descriptor_covered", "n_axes_descriptor_covered"),
                    ("n_axes_descriptor_blind", "n_axes_descriptor_blind"),
                ):
                    if summary.get(top) != msum.get(inner):
                        errs.append(f"summary.{top} disagrees with measured_axes_per_dim.summary.{inner} — regenerate")

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
