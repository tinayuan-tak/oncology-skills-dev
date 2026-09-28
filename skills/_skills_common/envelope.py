"""Shared evidence-package envelope writer (Phase D, 2026-08-12).

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

A later refinement (2026-08-12): the writer takes `input_context` + `dashboard_spec_ref` as
EXPLICIT params instead of digging into a `run_plan` dict. A focused subskill (dispatcher.py
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

import re
from datetime import datetime, timezone

from _skills_common.paths import analysis_methods_root


def build_governance(data_mode: str, release_pin: str, validation_summary: dict) -> dict:
    """The single source of the evidence-package `governance` block.

    Both composition engines build governance HERE (compose-dashboard via assemble_evidence_package;
    target-profile directly) so the block cannot drift between them — the Phase-D single-engine
    invariant applied to governance. Keys mirror the evidence_package schema's governance object
    (data_mode, release_pin, validation_summary); note we deliberately do NOT emit a lockfile_ref
    (nothing writes a lockfile — see the fix in assemble_evidence_package).
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
    import sys

    mrepo = str(analysis_methods_root())
    if mrepo not in sys.path:
        sys.path.insert(0, mrepo)
    try:
        from methods.catalog_query.read import _family_of, resolve_release

        return resolve_release, _family_of
    except Exception:  # noqa: BLE001 — no catalog helper → skip head/stale enrichment (digest still emits)
        return None, None


def _load_manifest_loader():
    """Lazily import catalog_query.load_manifest (analysis-methods) for md5 content-fingerprinting.
    (None) when unavailable — the content digest is best-effort and never blocks emission."""
    import sys

    mrepo = str(analysis_methods_root())
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
    whether staleness is knowable. Best-effort.

    PERF (2026-08-18): call load_catalog with the SAME kwargs form catalog_query.resolve_release uses
    (`load_catalog(root=..., contracts_root=...)` — read.py:233). functools.lru_cache keys on the args
    AS PASSED and does NOT normalize defaults, so a bare `load_catalog()` here is a DIFFERENT cache key
    than resolve_release's kwargs call — which made build_subskill_provenance parse the entire ~450-file
    catalog TWICE (~15s each: once in resolved_release_governance, once here). Passing the canonical
    roots explicitly makes this a cache HIT on the entry resolved_release_governance already populated.
    Result is byte-identical (same catalog); it just stops re-parsing it."""
    import sys

    mrepo = str(analysis_methods_root())
    if mrepo not in sys.path:
        sys.path.insert(0, mrepo)
    try:
        # Import the module's canonical DATA_CATALOG / TARGET_CONTRACTS Paths so the lru_cache key
        # matches resolve_release's `load_catalog(root=root, contracts_root=contracts_root)` exactly.
        from methods.catalog_query.read import DATA_CATALOG, TARGET_CONTRACTS, load_catalog

        return set(load_catalog(root=DATA_CATALOG, contracts_root=TARGET_CONTRACTS).manifests)
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

        per_file = sorted(f.get("md5") for f in files if isinstance(f, dict) and f.get("md5"))
        if per_file:
            return hashlib.sha256("\n".join(per_file).encode()).hexdigest()[:16]
    return None


def _refine_product_id_staleness(resolved: dict) -> None:
    """Rewrite in-place the `is_stale` flag for product-id-declared families to be HONEST.

    Cards declare their inputs as products.yaml product_ids (card_spec.required_inputs[].product_id),
    so a family whose `used` ids are ALL product_ids (not concrete manifest ids) has
    is_stale = (head not in used) = trivially True even when the run read the current head — a false
    'stale' signal. We cannot know the concrete release read from a product_id alone (that needs a
    reader-side stamp of the resolved manifest id), so staleness is INDETERMINATE, not True.

    SCHEMA-SAFE REPRESENTATION (2026-08-15): this runs on the evidence_package ENVELOPE path
    (assemble_evidence_package), whose governance.resolved_releases[*].is_stale is schema-typed
    `boolean` — so we OMIT is_stale (dropping the false True) and add a `stale_indeterminate` marker
    (an allowed additional property) rather than setting is_stale=None (which would fail schema
    validation and trip target-profile's --emit SystemExit). This differs, by necessity, from the
    subskill decision.json path (build_subskill_provenance), which is NOT schema-bound and keeps
    is_stale=None; both encode the same intent (no false stale). Requires the catalog to distinguish a
    product_id from a concrete manifest id; a no-op when the catalog is unavailable."""
    known = _known_manifest_ids()
    if known is None:
        return
    for entry in resolved.values():
        used = entry.get("used") or []
        # every declared id for this family is a product_id, not a concrete manifest id
        if used and not any(u in known for u in used) and entry.get("head") is not None:
            entry.pop("is_stale", None)
            entry["stale_indeterminate"] = "product_id_declared_not_concrete_manifest"


def resolved_release_governance(
    card_outputs,
    data_mode,
    release_pin,
    resolve_release=None,
    family_of=None,
    refine_product_id_staleness: bool = False,
) -> dict:
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
    hermetic testing; otherwise lazily imported.

    `refine_product_id_staleness` (2026-08-15): when True, families whose `used` ids are all
    products.yaml product_ids get an HONEST-staleness rewrite (see _refine_product_id_staleness) —
    the false-True is_stale is dropped and a stale_indeterminate marker is added. DEFAULT FALSE so the
    compose-dashboard byte-golden envelope is unchanged (only target-profile's --emit envelope opts in,
    via assemble_evidence_package)."""
    used = sorted(
        {
            m
            for c in card_outputs
            if not c.get("excluded_by_applies_when")
            for m in ((c.get("provenance") or {}).get("input_manifest_ids") or [])
        }
    )
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
    if refine_product_id_staleness:
        _refine_product_id_staleness(resolved)
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
    used = sorted(
        {
            m
            for c in card_outputs
            if not c.get("excluded_by_applies_when")
            for m in ((c.get("provenance") or {}).get("input_manifest_ids") or [])
        }
    )
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


def build_subskill_provenance(
    card_outputs: list,
    data_mode: str,
    release_pin: "str | None",
    skills_repo_sha: str,
    resolver_release_pin: "str | None" = None,
) -> dict:
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
    # (2026-08-14) HONEST STALENESS for product-id-declared families — SUBSKILL-ONLY. Cards declare
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


def _stamp_evidence_substrate(entry: dict) -> None:
    """Stamp (measurement_type, evidence_substrate, provenance.required_product_ids) onto a
    card_present entry IN PLACE (cross-evidence independence invariant). Best-effort + fail-open: any
    unresolved key is omitted and a skills-only / registry-unreachable checkout is a silent no-op —
    provenance enrichment must never block or crash evidence-package emission."""
    card_id = entry.get("card_id")
    if not card_id:
        return
    try:
        from .measurement_types import substrate_for_card

        mt, substrate = substrate_for_card(card_id)
        if mt:
            entry["measurement_type"] = mt
        if substrate:
            entry["evidence_substrate"] = substrate
    except Exception:  # noqa: BLE001 — registry read is best-effort
        pass
    try:
        from . import card_input_manifest_ids

        req = list(card_input_manifest_ids(card_id))
        if req:
            prov = entry.setdefault("provenance", {"method_calls": [], "input_manifest_ids": []})
            prov["required_product_ids"] = req
    except Exception:  # noqa: BLE001 — card-spec read is best-effort
        pass


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
    refine_product_id_staleness: bool = False,
    stamp_evidence_substrate: bool = False,
    evidence_sections: "dict | None" = None,
) -> dict:
    """Build the evidence_package envelope from phase outputs.

    `input_context` — the invocation binding: reads `target_symbol`, `indication`,
        `data_mode`, and (optional) `release_pin` + `subgroup_spec`. compose-dashboard
        passes run_plan["input_context"]; a subskill builds an equivalent dict.
    `dashboard_spec_ref` — the dashboard/skill spec this package was composed against.
        compose-dashboard passes its resolved base dashboard (or "unresolved"); a subskill
        passes "skill:<skill_name>". Explicit param so the writer no longer digs into
        a run_plan["axis_resolution"] structure that only compose-dashboard has.
    `framework_version` — semver stamped into the envelope (e.g. "2.0.0").
    `generated_by` — producer identity + git sha (e.g. "skills/compose-dashboard@a1b2c3d").
        The caller owns this so the writer is reusable across skills.
    `unavailable_cards` (2026-07-20): reasoned absences (unwired / data-blocked / etc.)
    collected by phase-2 separately from the synthesis-input card_outputs; emitted as
    card_unavailable envelope entries so a consumer can see WHY a card is absent instead of
    an opaque n_cards_failed integer.

    `refine_product_id_staleness` (2026-08-15): forwarded to resolved_release_governance so a
    caller reading product-id-declared cards (target-profile's --emit) emits HONEST staleness
    (indeterminate, not false-True) for those families. DEFAULT FALSE — compose-dashboard leaves it
    off so its byte-golden envelope is unchanged.

    `stamp_evidence_substrate` (2026-08-16, cross-evidence independence invariant — "independence
    before certainty"): when True, each present card_present entry is stamped with its `measurement_type` +
    `evidence_substrate` (resolved from the measurement_types registry's `cards:` back-refs +
    `evidence_substrates` vocab) and its provenance carries the DECLARED `required_product_ids`
    (card_spec.required_inputs[].product_id). This lets a cross-evidence integrator detect which cards
    share an underlying data product and NOT count correlated evidence twice toward certainty (the
    HTR1D expression<->selectivity double-count). DEFAULT FALSE so every existing caller
    (compose-dashboard byte-golden, target-profile --emit, subskill --emit-envelope) is byte-identical
    AND keeps validating against the un-updated evidence_package.schema until the target-contracts
    substrate schema (the sibling PR) lands. Best-effort: unresolved type/substrate keys are simply
    omitted; a skills-only checkout stamps nothing and never raises.

    `evidence_sections` (2026-09-27, SK#1941 — the tumor-presence reference-vertical export boundary):
    a pre-built {section_name: section_object} map of the NAMED, bounded top-level evidence sections
    (source_properties L2a, integrated_properties L2b, local_composites, l3d — see
    docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md :259-275). When supplied, each entry is spliced in as a
    TOP-LEVEL package key right after `cards`, so a consumer reads L2a/L2b/local/L3d as STRUCTURE, not by
    convention over synthesis.headline.claim_vector. The section objects carry the SAME content already
    computed in the decision headline, each entry reconstructable downward to its claim IDs / L1 card_ids
    (source_properties[*].card_id, the islands' provenance.sources[*].provenance.card_id, the claim axes'
    evidence_atom.cite.card_id, l3d.provenance.claim_ids). DEFAULT None so every existing caller
    (compose-dashboard byte-golden, functional-requirement/other --emit, subskill envelope) is
    byte-identical; the emitting skill (tumor-presence) owns the section shapes and the schema declares
    them (evidence_package.schema top-level unevaluatedProperties:false). Verdict-INERT: additive
    structure over the same content — presence_verdict / presence_verdict_by_modality / resolver goldens
    are untouched."""
    ctx = input_context
    target = ctx["target_symbol"]
    indication = ctx["indication"]
    data_mode = ctx["data_mode"]
    release_pin = ctx.get("release_pin") or "unpinned"

    # Slugify: the evidence_package.schema constrains package_id to `^ep-[a-z0-9_-]+$`, so a
    # multi-word indication ("Non-Small Cell Lung Cancer") or any target/indication carrying spaces,
    # slashes, parens, etc. would fail validation with a bare .lower(). Replace every run of
    # disallowed chars with a single '-' (underscores + dashes are allowed, so existing single-token
    # ids like `ep-kras-coadread-...` are byte-unchanged), then collapse repeats and trim.
    package_id = re.sub(
        r"-+", "-", re.sub(r"[^a-z0-9_-]+", "-", f"ep-{target}-{indication}-{release_pin}-{data_mode}-001".lower())
    ).strip("-")

    # Determine concurrence absence — ships without concurrence by default.
    # 2026-08-10 fix: do NOT advertise governance.lockfile_ref="lockfile.yaml" —
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
    governance.update(
        resolved_release_governance(
            card_outputs, data_mode, release_pin, refine_product_id_staleness=refine_product_id_staleness
        )
    )

    # Build context block — extract target identity from the target-identity-summary card if present
    target_identity_card = next(
        (
            c
            for c in card_outputs
            if c.get("card_id") == "target-identity-summary" and not c.get("excluded_by_applies_when")
        ),
        None,
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
        # Fix (post-adversarial-review): no more hgnc_id=1 placeholder. When
        # target-identity-summary is missing/failed/excluded, the framework MUST NOT
        # fabricate an identity. We emit a clearly-marked placeholder hgnc_id that
        # downstream consumers can detect (-1 means "not resolved"; downstream renderer
        # and any consumer reading the package can branch on the negative value).
        # The evidence_package schema requires hgnc_id >= 1, so a value of -1 will
        # FAIL evidence_package validation — which is the right behavior: a package
        # missing target identity is not a valid governance-grade artifact.
        target_block = {"symbol": target, "hgnc_id": -1}

    # scope must reflect the actual request, not a constant. It was hardcoded "cancer_type" even for
    # subtype-scoped runs (which set subgroup_spec to a strata list), so context.scope never told a
    # consumer whether the package was indication-level or subtype-level. Derive it from subgroup_spec,
    # the single input that carries that distinction (truthy = a strata list or "all" => subtype-scoped;
    # null/empty => indication-level). Mirrors the truthy reads downstream already use (render_markdown,
    # cross-evidence-hypothesis). pancancer is a target-intrinsic scope not emitted on this
    # (target, indication) path, so it is not derivable here and is intentionally not produced.
    _subgroup_spec = ctx.get("subgroup_spec")
    context_block = {
        "target": target_block,
        "indication": {"oncotree_code": indication},
        "subgroup_spec": _subgroup_spec,
        "scope": "cancer_subtype" if _subgroup_spec else "cancer_type",
    }

    # Build cards array — normalize each card_output into the evidence_package schema shape
    cards = []
    for c in card_outputs:
        if c.get("excluded_by_applies_when"):
            cards.append(
                {
                    "card_id": c["card_id"],
                    "card_version": c.get("card_version", "n/a"),
                    "excluded_by_applies_when": True,
                    "exclusion_reason": c["exclusion_reason"],
                }
            )
        else:
            entry = {
                "card_id": c["card_id"],
                "card_version": c.get("card_version", "1.0.0"),
                "validation_state": c["validation_state"],
                "summary": c.get("summary", {}),
                "interpretation_call": c.get("interpretation_call", "uninterpreted"),
                "caveats": c.get("caveats", []),
                "provenance": {**{"method_calls": [], "input_manifest_ids": []}, **(c.get("provenance") or {})},
            }
            if c.get("warning_ids"):
                entry["warning_ids"] = c["warning_ids"]
            if c.get("figures"):
                entry["figures"] = c["figures"]
            if stamp_evidence_substrate:
                _stamp_evidence_substrate(entry)
            cards.append(entry)

    # Append reasoned-absence entries (2026-07-20): the card_unavailable envelope variant.
    # A card whose live reader returned None (unwired) is no longer silently dropped to the
    # n_cards_failed integer — it appears here with a typed availability_state so a consumer
    # (and the deciding-axis router) can distinguish "not built yet" from a measured absence.
    for u in unavailable_cards or []:
        cards.append(
            {
                "card_id": u["card_id"],
                "card_version": u.get("card_version", "n/a"),
                "availability_state": u["availability_state"],
                "availability_reason": u.get("availability_reason", "unavailable"),
            }
        )

    # Build the top-level evidence_package
    timestamp = (
        "2026-06-26T00:00:00Z"
        if deterministic_timestamps
        else (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    )
    package = {
        "package_id": package_id,
        "framework_version": framework_version,
        "generated_at": timestamp,
        "generated_by": generated_by,
        "context": context_block,
        "governance": governance,
        "dashboard_spec_ref": dashboard_spec_ref,
        "cards": cards,
    }
    # SK#1941: splice the NAMED bounded evidence sections in as top-level keys right after `cards`
    # (source_properties L2a / integrated_properties L2b / local_composites / l3d) so the layered
    # export shape is STRUCTURE, not a convention over synthesis.headline.claim_vector. The emitting
    # skill owns the shapes; DEFAULT None => every existing caller stays byte-identical.
    if evidence_sections:
        for _section_name, _section_obj in evidence_sections.items():
            package[_section_name] = _section_obj
    package["synthesis"] = synthesis_block
    # 2026-08-10 fix: the pointer said "renderings/dashboard.md" but main() writes
    # the rendering to the package ROOT (out / "dashboard.md") — no renderings/ subdir is ever
    # created, so the self-describing pointer was wrong on every emitted package. Point at the
    # actual file. (Keeping the file at root; only the pointer was inconsistent.)
    package["renderings"] = {"markdown": "dashboard.md"}
    package["schema_version"] = 1
    return package
