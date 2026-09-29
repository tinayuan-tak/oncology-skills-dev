"""validate_claim_record.py — factored claim-record schema + cross-field invariant validator
(M0 of the factored-record migration; docs/design/VERDICT_REPRESENTATION_MIGRATION.md).

The factored record replaces the single per-axis verdict TOKEN with a typed record
(schemas/claim_record.schema.json); the legacy token survives as a pure rendering
rho(record). This validator proves the record is COHERENT before any skill emits it —
it has ZERO runtime consumers at M0. It validates each hand-authored example under
docs/design/examples/claim_record.*.yaml against:

  1. the JSON Schema (structure / enums / additionalProperties);
  2. the cross-field INVARIANTS that JSON Schema alone cannot express:
     A. OPEN-WORLD availability {not_wired, data_blocked, read_error} => finding.state
        MUST be the sentinel 'unknown' AND finding.direction MUST be 'neutral'
        (a not_wired record cannot carry a finding or a valence).
     B. magnitude.value non-null  => magnitude.scale non-null  (no bare numbers).
     C. finding.state (when != 'unknown') MUST be a verdict the axis's resolver actually
        emits — reusing emitted_verdicts_by_gate() from validate_verdict_tokens, the same
        source of truth the R1 token guard uses. An axis with no resolver is UNCHECKED
        (warning, never error) — the no-resolver inline-verdict axes get their enum in a
        later migration phase.
     D. certainty.level MUST equal the ordinal min(coverage, corroboration); when
        corroboration is 'unmeasured', level MUST equal coverage (CERTAINTY_MODEL.md).

NOTE the corroborator-disjointness invariant (corroboration card not in the axis's
verdict-precedence set) is NOT re-checked here: the record carries only the categorical
`corroboration` value, and disjointness is validated at the manifest by the existing
validators/validate_certainty_disjointness.py. This validator governs record SHAPE +
the four intra-record invariants above.

CLI:
  python validators/validate_claim_record.py \
      --schema schemas/claim_record.schema.json \
      --examples docs/design/examples/ --resolvers resolvers/
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Reuse the R1 token guard's single source of truth for "what verdicts does this axis emit".
from validate_verdict_tokens import emitted_verdicts_by_gate  # noqa: E402

OPEN_WORLD = frozenset({"not_wired", "data_blocked", "read_error"})
_CERT_ORD = {"low": 0, "medium": 1, "high": 2}
_UNKNOWN_STATE = "unknown"


def _canonical_json(obj) -> str:
    """The single pinned canonical serialization for identity hashing. Any drift here silently
    changes every context_id / record_revision_id, so it is defined ONCE and reused by both the
    example authoring and the recompute checks."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_sha16(obj) -> str:
    return hashlib.sha256(_canonical_json(obj).encode("utf-8")).hexdigest()[:16]


@dataclass
class ClaimRecordReport:
    ok: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    unchecked_axes: set = field(default_factory=set)
    checked_count: int = 0

    def add_error(self, m: str):
        self.ok = False
        self.errors.append(m)

    def add_warning(self, m: str):
        self.warnings.append(m)


def _invariants(rec: dict, where: str, emitted: dict[str, set[str]], report: ClaimRecordReport) -> None:
    """Apply the four cross-field invariants to one already-schema-valid record."""
    axis = rec.get("axis")
    finding = rec.get("finding", {})
    state = finding.get("state")
    direction = finding.get("direction")
    availability = finding.get("availability")
    mag = finding.get("magnitude", {})

    # A. open-world ignorance => non-committal finding.
    if availability in OPEN_WORLD:
        if state != _UNKNOWN_STATE:
            report.add_error(
                f"{where}: OPEN_WORLD_STATE — availability={availability!r} is open-world so "
                f"finding.state must be {_UNKNOWN_STATE!r}, got {state!r} (ignorance != negation)."
            )
        if direction != "neutral":
            report.add_error(
                f"{where}: OPEN_WORLD_DIRECTION — availability={availability!r} is open-world so "
                f"finding.direction must be 'neutral', got {direction!r} (a not_wired record "
                f"cannot carry a valence)."
            )

    # B. no bare numbers.
    if mag.get("value") is not None and mag.get("scale") is None:
        report.add_error(
            f"{where}: BARE_NUMBER — magnitude.value={mag.get('value')!r} is set but "
            f"magnitude.scale is null (a measured value must name its unit/scale)."
        )

    # E. M2 render-equivalence anchor: a MEASURED finding renders to its own state (the token survives
    #    as a field), so provenance.legacy_verdict — when present — must equal a non-'unknown' state.
    #    For an open-world 'unknown' state, legacy_verdict legitimately DIFFERS (it preserves the
    #    discarded no-data token so rho(record) still reproduces the byte-exact legacy verdict).
    legacy = (rec.get("provenance") or {}).get("legacy_verdict")
    if legacy is not None and state != _UNKNOWN_STATE and legacy != state:
        report.add_error(
            f"{where}: LEGACY_VERDICT — finding.state={state!r} is measured (not 'unknown') so "
            f"provenance.legacy_verdict must equal it, got {legacy!r} (render-equivalence would break)."
        )

    # C. finding.state membership in the axis resolver's emitted verdict set.
    if state != _UNKNOWN_STATE:
        verdicts = emitted.get(axis)
        if verdicts is None:
            report.unchecked_axes.add(axis)
        elif state not in verdicts:
            report.add_error(
                f"{where}: UNKNOWN_STATE — finding.state={state!r} is not a verdict resolver "
                f"`{axis}` emits (emits: {sorted(verdicts)})."
            )

    # D. certainty.level must not EXCEED the ordinal min(coverage, corroboration) — DOWNGRADE-ONLY.
    # corroboration is the ordinal {low,medium,high,unmeasured} the shipped CERTAINTY_MODEL hooks emit;
    # 'unmeasured' drops out (level bounded by coverage alone). A skill may legitimately downgrade level
    # BELOW the min (e.g. forcing 'low' on a none/absent verdict), so the invariant is `<=`, not `==`:
    # it catches the real error (claiming MORE certainty than the weakest measured component warrants)
    # without false-failing a valid downgrade.
    cert = rec.get("certainty", {})
    level, coverage, corrob = cert.get("level"), cert.get("coverage"), cert.get("corroboration")
    measured = [x for x in (coverage, corrob) if x in _CERT_ORD]  # 'unmeasured' excluded
    if level in _CERT_ORD and measured:
        ceiling = min(measured, key=lambda x: _CERT_ORD[x])
        if _CERT_ORD[level] > _CERT_ORD[ceiling]:
            report.add_error(
                f"{where}: CERTAINTY_LEVEL — level={level!r} EXCEEDS min(coverage={coverage!r}, "
                f"corroboration={corrob!r})={ceiling!r} (certainty is downgrade-only; a strong level "
                f"cannot outrank its weakest measured component)."
            )

    # F/G/H. Optional record-grain context + identity (recompute, never trust).
    _context_identity_invariants(rec, where, report)


def _context_identity_invariants(rec: dict, where: str, report: ClaimRecordReport) -> None:
    """H/F/G: the optional record-grain context + identity model (2026-09-18).

    H — the scope<->specifier-field coupling that keeps a pan-X claim from silently joining to a
        specific-X one (SPECIFIC requires the id field; ALL / NOT_STRATIFIED forbid it).
    F — context_id RECOMPUTES from canonical(context); logical_key RECOMPUTES from context_id+axis.
    G — record_revision_id RECOMPUTES from logical_key + l0_digest + ruleset_version + versions.

    Everything is recomputed, never trusted. All checks are no-ops on a record that omits both
    blocks, so the model is additive/forward-compatible.
    """
    context = rec.get("context")
    identity = rec.get("identity")

    if context is not None:
        ind = context.get("indication") or {}
        if ind.get("scope") == "SPECIFIC" and "oncotree_code" not in ind:
            report.add_error(f"{where}: INDICATION_SCOPE_FIELD — indication.scope=SPECIFIC requires oncotree_code.")
        if ind.get("scope") == "ALL" and "oncotree_code" in ind:
            report.add_error(
                f"{where}: INDICATION_SCOPE_FIELD — indication.scope=ALL (pan-cancer) must NOT carry "
                f"oncotree_code (got {ind.get('oncotree_code')!r}); a specifier on an ALL scope is the "
                f"silent-empty-join hazard."
            )
        sub = context.get("subtype") or {}
        if sub.get("scope") == "SPECIFIC" and not sub.get("subgroup_ids"):
            report.add_error(
                f"{where}: SUBTYPE_SCOPE_FIELD — subtype.scope=SPECIFIC requires a non-empty subgroup_ids."
            )
        if sub.get("scope") in {"ALL", "NOT_STRATIFIED"} and "subgroup_ids" in sub:
            report.add_error(
                f"{where}: SUBTYPE_SCOPE_FIELD — subtype.scope={sub.get('scope')} must NOT carry "
                f"subgroup_ids ('pan-subtype' and 'not stratified' are not a specific subgroup)."
            )
        mod = context.get("modality") or {}
        if mod.get("scope") == "SPECIFIC" and "channel" not in mod:
            report.add_error(f"{where}: MODALITY_SCOPE_FIELD — modality.scope=SPECIFIC requires a channel.")
        if mod.get("scope") == "ALL" and "channel" in mod:
            report.add_error(
                f"{where}: MODALITY_SCOPE_FIELD — modality.scope=ALL must NOT carry a channel "
                f"(got {mod.get('channel')!r})."
            )

    if identity is not None:
        if context is None:
            report.add_error(
                f"{where}: IDENTITY_WITHOUT_CONTEXT — identity is derived from context, so it may not "
                f"appear without a context block."
            )
            return
        axis = rec.get("axis")
        expected_cid = _canonical_sha16(context)
        if identity.get("context_id") != expected_cid:
            report.add_error(
                f"{where}: CONTEXT_ID_MISMATCH — context_id={identity.get('context_id')!r} but "
                f"sha256(canonical(context))[:16]={expected_cid!r} (identity is derived, never authored)."
            )
        expected_lk = f"{expected_cid}::{axis}"
        if identity.get("logical_key") != expected_lk:
            report.add_error(
                f"{where}: LOGICAL_KEY_MISMATCH — logical_key={identity.get('logical_key')!r} but "
                f"'<context_id>::<axis>'={expected_lk!r}."
            )
        versions = (rec.get("provenance") or {}).get("versions") or {}
        payload = "|".join(
            [
                expected_lk,
                identity.get("l0_digest", ""),
                identity.get("ruleset_version", ""),
                _canonical_json(versions),
            ]
        )
        expected_rrid = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        if identity.get("record_revision_id") != expected_rrid:
            report.add_error(
                f"{where}: RECORD_REVISION_ID_MISMATCH — record_revision_id="
                f"{identity.get('record_revision_id')!r} but recompute from "
                f"logical_key|l0_digest|ruleset_version|canonical(versions)={expected_rrid!r}."
            )


def validate_record(
    rec: dict, where: str, schema: dict, validator_cls, emitted: dict[str, set[str]], report: ClaimRecordReport
) -> None:
    """Schema-validate one record, then (only if schema-clean) apply the invariants."""
    schema_errors = sorted(validator_cls(schema).iter_errors(rec), key=lambda e: e.path)
    if schema_errors:
        for e in schema_errors:
            loc = "/".join(str(p) for p in e.path) or "<root>"
            report.add_error(f"{where}: SCHEMA [{loc}] {e.message}")
        return  # invariants assume a schema-valid shape
    report.checked_count += 1
    _invariants(rec, where, emitted, report)


def _iter_example_files(examples_dir: Path):
    yield from sorted(examples_dir.glob("claim_record.*.yaml"))
    yield from sorted(examples_dir.glob("claim_record.*.yml"))
    yield from sorted(examples_dir.glob("claim_record.*.json"))


def validate(schema_path: Path, examples_dir: Path, resolvers_dir: Path) -> ClaimRecordReport:
    report = ClaimRecordReport()
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        report.add_error(f"SCHEMA_LOAD: could not read/parse {schema_path}: {e}")
        return report
    try:
        from jsonschema import Draft202012Validator as validator_cls

        validator_cls.check_schema(schema)
    except Exception as e:  # noqa: BLE001 — surface any schema-meta or import problem as one error
        report.add_error(f"SCHEMA_META: {schema_path} is not a valid Draft 2020-12 schema: {e}")
        return report

    emitted = emitted_verdicts_by_gate(resolvers_dir)
    if not emitted:
        report.add_warning(f"NO_RESOLVERS under {resolvers_dir} — state-enum invariant (C) UNCHECKED.")

    files = list(_iter_example_files(examples_dir))
    if not files:
        report.add_error(
            f"NO_EXAMPLES: no claim_record.*.yaml under {examples_dir}. M0 requires at least one "
            f"hand-authored example so the schema is exercised."
        )
        return report

    for fp in files:
        try:
            doc = yaml.safe_load(fp.read_text())
        except (OSError, yaml.YAMLError) as e:
            report.add_error(f"{fp.name}: LOAD {e}")
            continue
        records = doc if isinstance(doc, list) else [doc]
        for i, rec in enumerate(records):
            if not isinstance(rec, dict):
                report.add_error(f"{fp.name}[{i}]: not a mapping")
                continue
            validate_record(rec, f"{fp.name}[{i}]", schema, validator_cls, emitted, report)

    for axis in sorted(report.unchecked_axes):
        report.add_warning(
            f"UNCHECKED axis `{axis}`: no resolver emits verdicts for it (no-resolver inline axis) — "
            f"finding.state enum NOT checked (invariant C skipped for this axis)."
        )
    return report


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--schema", type=Path, default=Path("schemas/claim_record.schema.json"))
    ap.add_argument("--examples", type=Path, default=Path("docs/design/examples/"))
    ap.add_argument("--resolvers", type=Path, default=Path("resolvers/"))
    args = ap.parse_args(argv)

    report = validate(args.schema, args.examples, args.resolvers)
    print("validate_claim_record.py results:")
    print(f"  schema={args.schema}  examples={args.examples}  resolvers={args.resolvers}")
    print(f"  validated {report.checked_count} record(s).")
    for w in report.warnings:
        print(f"    [WARNING] {w}")
    for e in report.errors:
        print(f"    [ERROR]   {e}")
    status = "OK" if report.ok else "FAIL"
    print(f"\nSummary: [{status}] {len(report.errors)} error(s), {len(report.warnings)} warning(s).")
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(_main())
