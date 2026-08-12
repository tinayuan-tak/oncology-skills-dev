"""Shared evidence-package envelope writer (Phase D, D1a — 2026-08-12).

ONE reusable builder for the top-level evidence_package.json envelope. Extracted
byte-preserving from compose-dashboard's `_assemble_evidence_package`, so that other
subskills can emit the same governance-grade envelope shape without copying the
assembly logic (the "copied not shared" drift that this Phase-D sweep is retiring).

This function is DELIBERATELY pure: it takes phase outputs (input_context, card_outputs,
validation_summary, synthesis_block) plus the caller's identity (framework_version,
generated_by, dashboard_spec_ref) and returns the envelope dict. It performs NO I/O, NO
schema validation, NO git/SHA resolution, and reads NO repo roots — the caller owns
provenance identity (`generated_by`) and version stamping (`framework_version`). This keeps
the writer reusable across skills: each caller stamps its OWN `generated_by` (e.g.
`skills/<skill>@<sha>`) rather than inheriting compose-dashboard's.

D1b (2026-08-12): the writer takes `input_context` + `dashboard_spec_ref` as EXPLICIT
params instead of digging into a `run_plan` dict. A focused subskill (dispatcher.py
run_wired_skill --emit-envelope) has no run_plan, so decoupling the writer from that
compose-dashboard-only structure lets a subskill emit the same envelope around its own
resolver verdict. compose-dashboard passes input_context=run_plan["input_context"] and
dashboard_spec_ref=(run_plan["axis_resolution"].get("selected_base_dashboard") or
"unresolved") — byte-identical to the previous run_plan-digging implementation.

Byte-identity contract: for identical inputs this produces a byte-identical envelope
to the previous in-line compose-dashboard implementation (proven by
compose-dashboard/tests/test_end_to_end.py::test_e2e_invariance_byte_identical_reruns
and test_envelope_integrity.py).
"""

from __future__ import annotations

from datetime import datetime, timezone


def assemble_evidence_package(
    input_context: dict,
    card_outputs: list[dict],
    validation_summary: dict,
    synthesis_block: dict,
    deterministic_timestamps: bool,
    framework_version: str,
    generated_by: str,
    dashboard_spec_ref: str,
    unavailable_cards: "list[dict] | None" = None,
) -> dict:
    """Build the evidence_package envelope from phase outputs.

    `input_context` — the invocation binding: reads `target_symbol`, `indication`,
        `data_mode`, and (optional) `release_pin` + `subgroup_spec`. compose-dashboard
        passes run_plan["input_context"]; a subskill builds an equivalent dict.
    `dashboard_spec_ref` — the dashboard/skill spec this package was composed against.
        compose-dashboard passes its resolved base dashboard (or "unresolved"); a subskill
        passes "skill:<skill_name>". Explicit param (D1b) so the writer no longer digs into
        a run_plan["axis_resolution"] structure that only compose-dashboard has.
    `framework_version` — semver stamped into the envelope (e.g. "2.0.0").
    `generated_by` — producer identity + git sha (e.g. "skills/compose-dashboard@a1b2c3d").
        The caller owns this so the writer is reusable across skills.
    `unavailable_cards` (F, 2026-07-20): reasoned absences (unwired / data-blocked / etc.)
    collected by phase-2 separately from the synthesis-input card_outputs; emitted as
    card_unavailable envelope entries so a consumer can see WHY a card is absent instead of
    an opaque n_cards_failed integer.
    """
    ctx = input_context
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
        "framework_version": framework_version,
        "generated_at": timestamp,
        "generated_by": generated_by,
        "context": context_block,
        "governance": governance,
        "dashboard_spec_ref": dashboard_spec_ref,
        "cards": cards,
        "synthesis": synthesis_block,
        # 2026-08-10 REVIEW FIX (L4): the pointer said "renderings/dashboard.md" but main() writes
        # the rendering to the package ROOT (out / "dashboard.md") — no renderings/ subdir is ever
        # created, so the self-describing pointer was wrong on every emitted package. Point at the
        # actual file. (Keeping the file at root; only the pointer was inconsistent.)
        "renderings": {"markdown": "dashboard.md"},
        "schema_version": 1,
    }
