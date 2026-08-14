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


def build_governance(data_mode: str, release_pin: str, validation_summary: dict) -> dict:
    """The single source of the evidence-package `governance` block.

    Both composition engines build governance HERE (compose-dashboard via assemble_evidence_package;
    target-profile directly) so the block cannot drift between them — the Phase-D single-engine
    invariant applied to governance. Keys mirror the evidence_package schema's governance object
    (data_mode, release_pin, validation_summary); note we deliberately do NOT emit a lockfile_ref
    (nothing writes a lockfile — see the L3 fix in assemble_evidence_package).
    """
    return {
        "data_mode": data_mode,
        "release_pin": release_pin,
        "validation_summary": validation_summary,
    }


def _load_catalog_resolver():
    """Lazily import catalog_query.resolve_release + _family_of from the analysis-methods repo.
    Returns (resolve_release, _family_of) or (None, None) if unavailable — governance enrichment is
    best-effort and must NEVER block evidence-package emission."""
    import os
    import sys
    mrepo = os.environ.get("ANALYSIS_METHODS_ROOT",
                           "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
    if mrepo not in sys.path:
        sys.path.insert(0, mrepo)
    try:
        from methods.catalog_query.read import resolve_release, _family_of
        return resolve_release, _family_of
    except Exception:  # noqa: BLE001 — no catalog helper → skip head/stale enrichment (digest still emits)
        return None, None


def _load_manifest_loader():
    """Lazily import catalog_query.load_manifest (analysis-methods) for md5 content-fingerprinting.
    (None) when unavailable — the content digest is best-effort and never blocks emission."""
    import os
    import sys
    mrepo = os.environ.get("ANALYSIS_METHODS_ROOT",
                           "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
    if mrepo not in sys.path:
        sys.path.insert(0, mrepo)
    try:
        from methods.catalog_query.read import load_manifest
        return load_manifest
    except Exception:  # noqa: BLE001 — no loader → content digest omitted (id digest still emits)
        return None


def _known_manifest_ids() -> "set | None":
    """The set of concrete manifest ids in the catalog, or None if the catalog is unavailable.
    Used ONLY to tell a concrete-manifest `used` id from a product_id (declared input) when deciding
    whether staleness is knowable. Best-effort; load_catalog is lru_cached in catalog_query."""
    import os
    import sys
    mrepo = os.environ.get("ANALYSIS_METHODS_ROOT",
                           "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
    if mrepo not in sys.path:
        sys.path.insert(0, mrepo)
    try:
        from methods.catalog_query.read import load_catalog
        return set(load_catalog().manifests)
    except Exception:  # noqa: BLE001 — no catalog → skip the indeterminate-staleness refinement
        return None


def _manifest_content_md5(manifest: dict) -> "str | None":
    """A content fingerprint for one manifest: the top-level `md5` for a single-file derived product,
    else a stable hash over the sorted per-file md5s of a multi-file `files:` source manifest, else
    None (no fingerprint available). This is what lets the content digest detect a same-id republish
    (CLAUDE.md forbids silently changing a merged manifest's md5 — this makes such a change visible)."""
    md5 = manifest.get("md5")
    if isinstance(md5, str) and md5:
        return md5
    files = manifest.get("files")
    if isinstance(files, list) and files:
        import hashlib
        per_file = sorted(
            f.get("md5") for f in files if isinstance(f, dict) and f.get("md5")
        )
        if per_file:
            return hashlib.sha256("\n".join(per_file).encode()).hexdigest()[:16]
    return None


def resolved_release_governance(card_outputs, data_mode, release_pin,
                                resolve_release=None, family_of=None) -> dict:
    """Governance ENRICHMENT (2026-08-12): derive a release fingerprint from the manifests the run
    ACTUALLY read (cards' provenance.input_manifest_ids), and resolve each data family's current
    catalog HEAD via catalog_query.resolve_release.

    Returns a dict merged into `governance`:
      resolved_release_digest — sha256(sorted used manifest_ids)[:16]. The run's DATA FINGERPRINT: it
        changes whenever the underlying releases change, so the eval-ledger cross-release TREND is
        meaningful even when release_pin is 'unpinned' (target-profile/compose read live today).
      resolved_releases — {family: {used:[...], head:<catalog head id>, is_stale:bool}}. is_stale=True
        flags a run that read a SUPERSEDED release (drift from the catalog head).

    Best-effort + fail-open: returns {} when the run read no manifests; the digest still emits if the
    catalog helper is unavailable; a per-family resolution error degrades to head=None + an error note.
    Never raises (governance must not block emission). `resolve_release`/`family_of` are injectable for
    hermetic testing; otherwise lazily imported."""
    used = sorted({m for c in card_outputs
                   if not c.get("excluded_by_applies_when")
                   for m in ((c.get("provenance") or {}).get("input_manifest_ids") or [])})
    if not used:
        return {}
    import hashlib
    out = {"resolved_release_digest": hashlib.sha256("\n".join(used).encode()).hexdigest()[:16]}
    if resolve_release is None or family_of is None:
        resolve_release, family_of = _load_catalog_resolver()
    if resolve_release is None or family_of is None:
        return out
    mode = data_mode if data_mode in ("latest_approved", "pinned", "exploratory") else "latest_approved"
    by_family: dict = {}
    for m in used:
        try:
            by_family.setdefault(family_of(m), []).append(m)
        except Exception:  # noqa: BLE001 — a malformed id must not sink the whole enrichment
            continue
    resolved: dict = {}
    for fam, mids in sorted(by_family.items()):
        entry = {"used": sorted(mids)}
        try:
            head = resolve_release(fam, mode, release_pin)
            entry["head"] = head
            entry["is_stale"] = head not in mids
        except Exception as e:  # noqa: BLE001 — fail-loud resolver → record, don't crash the package
            entry["head"] = None
            entry["resolution_error"] = f"{type(e).__name__}: {e}"
        resolved[fam] = entry
    out["resolved_releases"] = resolved
    return out


def resolved_content_digest(card_outputs: list) -> "str | None":
    """A CONTENT fingerprint over the manifests a run declared: sha256 of sorted
    `manifest_id=<md5>` pairs. The id-based resolved_release_digest keys on manifest_id (version
    rides the -vN suffix); this keys on each manifest's md5 content-fingerprint, so a same-id
    republish (new bytes, unchanged id — which CLAUDE.md forbids doing silently) is detectable. The
    strongest reproducibility anchor available, since there is no catalog-wide release to pin.

    Best-effort: returns None if no manifests were declared or the catalog loader is unavailable.
    Computed OUTSIDE resolved_release_governance ON PURPOSE — that function feeds the compose /
    target-profile evidence envelope (byte-golden + engine-equivalence pinned), so it must stay
    unchanged; the content digest is a subskill-decision.json enrichment only."""
    used = sorted({m for c in card_outputs
                   if not c.get("excluded_by_applies_when")
                   for m in ((c.get("provenance") or {}).get("input_manifest_ids") or [])})
    if not used:
        return None
    load_manifest = _load_manifest_loader()
    if load_manifest is None:
        return None
    import hashlib
    pairs = []
    for m in used:
        try:
            cmd5 = _manifest_content_md5(load_manifest(m) or {})
        except Exception:  # noqa: BLE001 — a missing/malformed manifest must not sink the digest
            cmd5 = None
        pairs.append(f"{m}={cmd5 or 'no-md5'}")
    return hashlib.sha256("\n".join(pairs).encode()).hexdigest()[:16]


def build_subskill_provenance(card_outputs: list, data_mode: str, release_pin: "str | None",
                              skills_repo_sha: str,
                              resolver_release_pin: "str | None" = None) -> dict:
    """The run-level reproducibility block for a subskill's default decision.json / provenance.yaml.

    Single-sourced HERE so the subskill default path records the same fingerprint the opt-in
    evidence envelope does (both go through resolved_release_governance). Captures WHICH CODE
    (skills_repo_sha), WHICH POSTURE (data_mode, release_pin, resolver_release_pin), and WHICH DATA
    (resolved_release_digest + resolved_content_digest + per-family head/staleness from the manifests
    the run declared). Best-effort — resolved_release_governance never raises."""
    prov = {
        "skills_repo_sha": skills_repo_sha,
        "data_mode": data_mode,
        "release_pin": release_pin or "unpinned",
    }
    if resolver_release_pin:
        prov["resolver_release_pin"] = resolver_release_pin
    prov.update(resolved_release_governance(card_outputs, data_mode, release_pin or "unpinned"))
    # (B, 2026-08-14) HONEST STALENESS for product-id-declared families — SUBSKILL-ONLY. Cards declare
    # their inputs as products.yaml product_ids (card_spec.required_inputs[].product_id), so a family
    # whose `used` ids are all product_ids (not concrete manifest ids) has is_stale = (head not in used)
    # = trivially True even when the run read the current head — a false 'stale' signal. We cannot know
    # the concrete release read from a product_id alone (that needs a reader-side stamp of the resolved
    # manifest id), so mark staleness INDETERMINATE rather than falsely True. Done HERE, not in the
    # shared resolved_release_governance, because that function feeds compose-dashboard's byte-golden
    # evidence envelope; build_subskill_provenance is on the subskill decision.json path ONLY.
    rr = prov.get("resolved_releases")
    if isinstance(rr, dict) and rr:
        known = _known_manifest_ids()
        if known is not None:
            for entry in rr.values():
                used = entry.get("used") or []
                # every declared id for this family is a product_id, not a concrete manifest id
                if used and not any(u in known for u in used) and entry.get("head") is not None:
                    entry["is_stale"] = None
                    entry["stale_indeterminate"] = "product_id_declared_not_concrete_manifest"
    _content = resolved_content_digest(card_outputs)
    if _content:
        prov["resolved_content_digest"] = _content
    return prov


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
    governance = build_governance(data_mode, release_pin, validation_summary)
    # Governance ENRICHMENT (2026-08-12): stamp a release fingerprint (resolved_release_digest) + the
    # per-family catalog head + drift, derived from the manifests the run actually read. Best-effort —
    # never blocks emission. Makes release_pin='unpinned' runs distinguishable across catalog releases
    # (the eval-ledger cross-release trend keys on resolved_release_digest).
    governance.update(resolved_release_governance(card_outputs, data_mode, release_pin))

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
