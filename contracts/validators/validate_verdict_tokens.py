"""validate_verdict_tokens.py — nomination-gate ↔ resolver verdict-token consistency
validator (R1-class drift guard, 2026-08-15).

STRUCTURALLY prevents the R1-class bug: a verdict token referenced by the nomination
gate policy that does not match — CASE-EXACT — any verdict its sub-skill's resolver can
actually emit, so the gate entry SILENTLY NEVER FIRES. The canonical instance was
`positive_signals_modality_scoped` carrying TitleCase `ADC_preferred` / `TCE_preferred`
while surface_modality.resolver.yaml emits lowercase `adc_preferred` / `tce_preferred`
(surface_modality.resolver.yaml:61-63); the two positives were DEAD until #366 fixed the
casing. This validator catches that class statically (casing typos, plain typos, and
stale verdicts a resolver no longer emits) — the same silent-drift discipline
validate_resolvers.py enforces for dangling RUNGS, extended to the gate policy's
verdict TOKENS.

THE INVARIANT — every verdict token referenced by vocabularies/nomination_verdict_gate.yaml
in the three ACTIONABLE blocks:
    - `gates`                          (each gate's `verdict` — the veto/hold kills)
    - `positive_signals`               (the confidence-floor positives)
    - `positive_signals_modality_scoped` (the modality-scoped positives — the R1 site)
keyed by (sub_skill, verdict), must exist CASE-EXACT among the set of verdicts the
corresponding sub_skill's resolver can emit (resolvers/<gate>.resolver.yaml — the union
of every `resolve[].verdict` plus the explicit `default`).

SCOPE — the three ACTIONABLE blocks above PLUS the two `excluded_*` documentation blocks
(`excluded_modality_scoped`, `excluded_positive_modality_scoped`) are enforced. The
actionable trio's tuples the target-profile gate loader matches against LIVE sub-verdicts
to force an action / raise a confidence tier; a mis-token there silently under-fires
(misses a veto or a positive). The `excluded_*` blocks DOCUMENT which modality-scoped
verdicts must NOT be treated as kills/positives in default mode — a stale token there is an
INERT guard that silently documents nothing real (the 2026-08-15 bug: the block carried
`adc_favorable`/`tce_favorable`, which surface_modality.resolver.yaml never emits — it emits
`adc_preferred`/`tce_preferred`; extending the check to these blocks catches exactly that).
The remaining blocks (veto_suppressors, positive_contradictions, contested_threshold) stay
out of scope.

SUB_SKILL → RESOLVER MAPPING — discovered from each resolver's own `gate:` field (the
resolver names itself). Most sub_skill shorts equal their resolver gate; the ONE documented
alias is `tractability_sm` → `tractability_small_molecule` (see the target-profile
_SHORT_TO_GATE map in claude-oncology-skills/skills/target-profile/scripts/run.py). A
sub_skill with NO resolver (advisory-only presence axes: `expression`, `subtype_fit`) is
SKIPPED — reported as UNCHECKED (a warning, never an error), so the validator does not
false-positive on axes that have no emitting resolver to compare against.

CLI:
  python validators/validate_verdict_tokens.py \
      --gate vocabularies/nomination_verdict_gate.yaml --resolvers resolvers/
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The three ACTIONABLE gate blocks whose (sub_skill, verdict) tuples the target-profile
# gate loader matches against live sub-verdicts. A mis-cased/typo'd/stale verdict in any
# of these silently under-fires (misses a veto or a positive) — the R1-class bug.
ACTIONABLE_BLOCKS = ("gates", "positive_signals", "positive_signals_modality_scoped")

# The two DOCUMENTATION blocks: modality-scoped verdicts that must NOT be treated as
# kills/positives in default mode. A stale token here is an INERT guard (2026-08-15 bug #2:
# adc_favorable/tce_favorable were never emitted). Enforced identically — case-exact against
# the resolver's emitted set — so the exclusion always references a real verdict.
EXCLUSION_BLOCKS = ("excluded_modality_scoped", "excluded_positive_modality_scoped")

ENFORCED_BLOCKS = ACTIONABLE_BLOCKS + EXCLUSION_BLOCKS

# sub_skill short → resolver gate name, for the shorts that do NOT equal their gate.
# The one documented exception (mirrors _SHORT_TO_GATE in the target-profile run.py):
#   tractability_sm's resolver is tractability_small_molecule.resolver.yaml.
SUBSKILL_RESOLVER_ALIASES = {
    "tractability_sm": "tractability_small_molecule",
}


@dataclass
class VerdictTokenReport:
    ok: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    unchecked_subskills: set = field(default_factory=set)
    checked_count: int = 0

    def add_error(self, m: str):
        self.ok = False
        self.errors.append(m)

    def add_warning(self, m: str):
        self.warnings.append(m)


def emitted_verdicts_by_gate(resolvers_dir: Path) -> dict[str, set[str]]:
    """gate name (resolver's own `gate:` field) → set of every verdict it can emit.

    A resolver emits: every `resolve[].verdict` (the ordered precedence ladder) PLUS its
    explicit `default` (the no-rung-matched verdict). Both are real, reachable verdicts.
    """
    out: dict[str, set[str]] = {}
    for rp in sorted(resolvers_dir.glob("*.resolver.yaml")):
        spec = yaml.safe_load(rp.read_text()) or {}
        gate = spec.get("gate")
        if not gate:
            continue
        verdicts: set[str] = set()
        for rung in spec.get("resolve", []) or []:
            v = rung.get("verdict")
            if v is not None:
                verdicts.add(v)
        default = spec.get("default")
        if default is not None:
            verdicts.add(default)
        # POST-RESOLVER python-clamp verdicts (optional `clamp_verdicts:` block) — verdicts a sub-skill's
        # Python post-pass mints AFTER the resolver (e.g. selectivity's normal-breadth / stromal-confound
        # veto in _skills_common/selectivity_veto.py). They are real emitted verdicts of this gate but can
        # never appear in `resolve[].verdict`; folding them in lets a nomination-gate entry for a clamp KILL
        # be validated CASE-EXACT instead of wrongly rejected as "never emitted".
        for v in spec.get("clamp_verdicts", []) or []:
            if v is not None:
                verdicts.add(v)
        out[gate] = verdicts
    return out


def resolver_gate_for_subskill(sub_skill: str, emitted: dict[str, set[str]]) -> str | None:
    """Resolve a gate-file `sub_skill` short to the resolver gate that emits its verdicts,
    or None if the sub_skill is advisory-only (no emitting resolver → UNCHECKED)."""
    if sub_skill in emitted:
        return sub_skill
    alias = SUBSKILL_RESOLVER_ALIASES.get(sub_skill)
    if alias is not None and alias in emitted:
        return alias
    return None


def _iter_gate_tokens(gate_spec: dict):
    """Yield (block, sub_skill, verdict) for every enforced entry in the gate policy."""
    for block in ENFORCED_BLOCKS:
        for entry in gate_spec.get(block, []) or []:
            if not isinstance(entry, dict):
                continue
            sub = entry.get("sub_skill")
            verd = entry.get("verdict")
            if sub is None or verd is None:
                continue
            yield block, sub, verd


def validate_verdict_tokens(gate_spec: dict, emitted: dict[str, set[str]]) -> VerdictTokenReport:
    """Pure check: every enforced (sub_skill, verdict) must be CASE-EXACT in its
    resolver's emitted verdict set. Unmapped sub_skills → UNCHECKED (warning)."""
    report = VerdictTokenReport()
    for block, sub, verd in _iter_gate_tokens(gate_spec):
        gate = resolver_gate_for_subskill(sub, emitted)
        if gate is None:
            report.unchecked_subskills.add(sub)
            continue
        report.checked_count += 1
        verdict_set = emitted[gate]
        if verd not in verdict_set:
            # Case-insensitive near-match makes the R1 casing bug unmistakable in the message.
            casing_hit = next((e for e in verdict_set if e.lower() == str(verd).lower()), None)
            hint = (
                f" (case mismatch — resolver emits `{casing_hit}`)"
                if casing_hit
                else f" (resolver emits: {sorted(verdict_set)})"
            )
            consequence = (
                "documents a verdict the resolver never emits — INERT guard"
                if block in EXCLUSION_BLOCKS
                else "the gate entry can NEVER fire"
            )
            report.add_error(
                f"UNMATCHED_VERDICT [{block}]: (sub_skill={sub!r}, verdict={verd!r}) is not "
                f"emitted CASE-EXACT by resolver `{gate}` — {consequence}{hint}."
            )
    for sub in sorted(report.unchecked_subskills):
        report.add_warning(
            f"UNCHECKED sub_skill `{sub}`: no resolver emits its verdicts (advisory-only axis) — "
            f"its gate-verdict tokens are NOT consistency-checked."
        )
    return report


def validate(gate_path: Path, resolvers_dir: Path) -> VerdictTokenReport:
    """File-driven wrapper: load the gate policy + resolver emitted-sets, then check."""
    emitted = emitted_verdicts_by_gate(resolvers_dir)
    if not emitted:
        r = VerdictTokenReport()
        r.add_error(f"NO_RESOLVERS: no *.resolver.yaml with a `gate:` field under {resolvers_dir}")
        return r
    try:
        gate_spec = yaml.safe_load(gate_path.read_text())
    except (OSError, yaml.YAMLError) as e:
        r = VerdictTokenReport()
        r.add_error(f"GATE_LOAD: could not read/parse {gate_path}: {e}")
        return r
    if not isinstance(gate_spec, dict):
        r = VerdictTokenReport()
        r.add_error(f"GATE_SHAPE: expected a mapping at top level of {gate_path}")
        return r
    return validate_verdict_tokens(gate_spec, emitted)


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--gate",
        type=Path,
        default=Path("vocabularies/nomination_verdict_gate.yaml"),
        help="Path to nomination_verdict_gate.yaml",
    )
    ap.add_argument("--resolvers", type=Path, default=Path("resolvers/"), help="Directory of *.resolver.yaml")
    args = ap.parse_args(argv)

    report = validate(args.gate, args.resolvers)
    print("validate_verdict_tokens.py results:")
    print(f"  gate={args.gate}  resolvers={args.resolvers}")
    print(f"  checked {report.checked_count} (sub_skill, verdict) token(s) against resolver emitted-sets.")
    for w in report.warnings:
        print(f"    [WARNING] {w}")
    for e in report.errors:
        print(f"    [ERROR]   {e}")
    status = "OK" if report.ok else "FAIL"
    print(
        f"\nSummary: [{status}] {len(report.errors)} error(s), {len(report.warnings)} warning(s); "
        f"unchecked sub_skills: {sorted(report.unchecked_subskills) or 'none'}."
    )
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(_main())
