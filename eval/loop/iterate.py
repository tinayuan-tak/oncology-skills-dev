#!/usr/bin/env python3
"""eval/loop/iterate.py — the subskill-iteration loop's END-TO-END ORCHESTRATOR (SK#2303 WI-I, #2360).

This is the CAPSTONE that wires the Phase-0 core into ONE iteration over ONE skill's emitted batch:

    run_batch (#2345) → substrate (#2347) → judge (#2355) → containment (#2356)
                     → findings ledger + tiers (#2358)  [DEV split]
                     → probes (#2357) + convergence (#2359)  [HELD-OUT split]

``run_batch.py`` is run FIRST (separately — it re-execs under pixi and shells out to each skill's
``scripts/run.py --emit-envelope``; see ``eval/loop/LOOP.md``). This module then consumes that run
directory: for every roster entry it locates the emitted package (``run_batch`` lays each triple's
``evidence_package.json`` + ``decision.json`` under ``<run_dir>/_emit__<target>_<indication>/``),
assembles the judge substrate, runs the propose-only triangulation judge, containment-guards every
finding, appends the CONTAINED findings of the DEV split to the hash-chained ledger, routes them into
tiers (report-only — ``teeth_green`` defaults ``False``, STOP-A), and assesses the HELD-OUT split for
convergence (judge-finding + probe emptiness on the hash-fixed roster).

Load-bearing invariants (carried verbatim from the parts, each with teeth in its own module's tests):

- **Propose-only / STOP-A.** The orchestrator never edits code, never moves a threshold, never lands a
  verdict change. ``teeth_green`` is a CALLER assertion (CI-confirmed), defaulting ``False`` so every
  otherwise-T1-eligible finding is reported at T2 until the teeth + containment guard are green.
- **Index on the property layers, never the verdict** (SK#2091). Nothing here reads
  ``synthesis.verdict`` / ``driving_rule_id``; the ledger dedup, tier routing and convergence all key on
  the L2a/L2b/L3 structure.
- **NULL-blocking convergence.** A dead/degraded held-out package (``substrate.null_everything`` ⇒ the
  judge is ``skipped``) or a probe ``not_evaluable`` can NEVER read as "clean" — convergence blocks on it
  (SKIP ≠ PASS).
- **Frozen-symbol denylist forces T3** (``tiers.touches_frozen_symbol`` / ``frozen_symbols.yaml``).
- **Verdict-blind findings** (SK#2091): a finding is a structural L1-L3 proposal, re-verified against the
  RAW island by the containment guard before it reaches the ledger.

Per-skill probe applicability (``applicable_probes``): C1 (L2b pair-identity) is generic — it runs on any
skill with an ``integrated_properties`` section. CALIB is tumor-presence-SPECIFIC (it reads the
``patient_tumor_abundance`` L2a property against the curated ``tumor_presence_controls.yaml`` roster), so
it runs ONLY for ``tumor-presence``; running it on another skill would report ``not_evaluable`` on every
control gene (that property is absent) and spuriously NULL-block convergence. This is why the FIRST real
iteration (dependency / safety, post-L2a) uses C1 as its only regression probe.

The LLM judge is INJECTABLE (``run_iteration(..., llm=...)``) so the whole orchestration is covered by a
hermetic test with NO live Bedrock (``tests/test_iterate.py``). The CLI uses the live judge; its run
recipe (SSO for cmp-dev expires mid-session — re-``aws sso login`` if it 400s)::

    env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev \\
        PYTHONPATH=$REPO/skills pixi run python eval/loop/iterate.py \\
            --skill functional-requirement --batch-spec eval/loop/batches/dependency/batch-001.v1.json \\
            --run-dir eval/loop/runs/iter-001-<sha> --out-dir eval/loop/iterations/dependency/iter-001

No ``__init__.py`` under ``critic/`` (the ``eval/`` convention — a bare ``sys.path`` import, see
``critic/judge.py``). This module adds the loop dir + the critic dir to ``sys.path`` and imports the
siblings by module name, exactly as judge.py / probes.py / containment.py do.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, Sequence

_LOOP_DIR = Path(__file__).resolve().parent
_CRITIC_DIR = _LOOP_DIR / "critic"
for _p in (_LOOP_DIR, _CRITIC_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import containment as _containment  # noqa: E402  (critic/containment.py — _CRITIC_DIR is on sys.path)
import convergence as _convergence  # noqa: E402
import findings as _findings  # noqa: E402
import judge as _judge  # noqa: E402  (critic/judge.py)
import probes as _probes  # noqa: E402  (critic/probes.py)
import run_batch as _run_batch  # noqa: E402
import substrate as _substrate  # noqa: E402
import tiers as _tiers  # noqa: E402

SCHEMA_VERSION = "1.0"

# CALIB is tumor-presence-specific (reads patient_tumor_abundance + the curated control roster); C1 is
# generic over integrated_properties. See the module docstring.
_TUMOR_PRESENCE = "tumor-presence"


def applicable_probes(skill: str) -> tuple[str, ...]:
    """The regression probes (``critic/probes.py``) applicable to ``skill``.

    C1 (L2b pair-identity) runs for every skill that emits ``integrated_properties``; CALIB (L2a
    tumor-abundance direction) runs ONLY for tumor-presence (the only skill with the
    ``patient_tumor_abundance`` property + a curated control roster)."""
    return ("c1", "calib") if skill == _TUMOR_PRESENCE else ("c1",)


# ── roster entry ───────────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Entry:
    """One roster triple + its dev/held-out split label, carrying BOTH key conventions in play:

    - :attr:`candidate_key` — ``batch_constructor.Candidate.key`` (``target|indication|subtype``); the
      key the batch spec, the split, and ``convergence.roster_pin`` all speak.
    - :attr:`emit_key` — ``run_batch.Triple.key`` (``slug(target)_slug(indication)``); the key
      ``run_batch`` names each emitted package directory with.
    """

    target: str
    indication: str
    subtype: str = ""
    stratum: str = "unlabeled"
    split: str = "dev"

    @property
    def candidate_key(self) -> str:
        return f"{self.target}|{self.indication}|{self.subtype}"

    @property
    def emit_key(self) -> str:
        return _run_batch.Triple(self.target, self.indication).key

    def package_dir(self, run_dir: Path) -> Path:
        """Where ``run_batch`` left this triple's emitted package (``evidence_package.json`` +
        ``decision.json`` — the ``run_health`` the substrate assembler reads lives in ``decision.json``)."""
        return run_dir / f"_emit__{self.emit_key}"


def load_entries_from_batch_spec(spec: dict) -> list[Entry]:
    """Build the roster from a ``batch_constructor.build_batch_spec`` manifest's ``roster`` list."""
    out: list[Entry] = []
    for row in spec.get("roster") or []:
        out.append(
            Entry(
                target=row["target"],
                indication=row["indication"],
                subtype=row.get("subtype", "") or "",
                stratum=row.get("stratum", "unlabeled") or "unlabeled",
                split=row.get("split", "dev") or "dev",
            )
        )
    return out


# ── probes ─────────────────────────────────────────────────────────────────────────────────────────
def run_probes(
    evidence_package: dict,
    entry: Entry,
    skill: str,
    *,
    contracts_root: "Path | str | None" = None,
) -> list[tuple]:
    """Run the skill-applicable regression probes over one emitted package, returning the concatenated
    4-tuples ``(probe_id, severity, verdict, message)`` the convergence gate consumes."""
    which = applicable_probes(skill)
    out: list[tuple] = []
    if "c1" in which:
        out.extend(_probes.probe_c1(evidence_package, contracts_root=contracts_root))
    if "calib" in which:
        out.extend(_probes.probe_calib(evidence_package, entry.target, entry.indication, contracts_root=contracts_root))
    return out


# ── per-package pipeline ─────────────────────────────────────────────────────────────────────────────
def _load_json(path: Path) -> "dict | None":
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


@dataclass
class PackageResult:
    entry: Entry
    assembled: bool
    null_reason: "str | None"
    judge_skipped: "str | None"
    n_findings: int
    containment: dict  # the contain() report (counts + contained/dropped/demoted)
    probes: list  # 4-tuples
    judge_result: dict = field(default_factory=dict)

    def to_jsonable(self) -> dict:
        c = self.containment
        return {
            "candidate_key": self.entry.candidate_key,
            "target": self.entry.target,
            "indication": self.entry.indication,
            "stratum": self.entry.stratum,
            "split": self.entry.split,
            "assembled": self.assembled,
            "null_reason": self.null_reason,
            "judge_skipped": self.judge_skipped,
            "n_judge_findings": self.n_findings,
            "containment": {k: c.get(k) for k in ("n_in", "n_contained", "n_dropped", "n_demoted", "skipped")},
            "probes": [list(p) for p in self.probes],
        }


def process_package(
    entry: Entry,
    run_dir: Path,
    skill: str,
    *,
    llm: "Optional[Callable[..., dict]]" = None,
    contracts_root: "Path | str | None" = None,
    max_tokens: int = 3000,
) -> PackageResult:
    """Assemble → judge → contain → probe ONE emitted package. A missing/unparseable package is a
    NULL-everything result (never silently clean): the substrate assembler returns ``null_everything``,
    the judge is ``skipped``, and the probes report ``not_evaluable`` — exactly the signals the
    convergence NULL-block keys on."""
    pkg_dir = entry.package_dir(run_dir)
    ep_path = pkg_dir / "evidence_package.json"
    evidence_package = _load_json(ep_path) if ep_path.exists() else None

    if evidence_package is None:
        # No emitted package → a NULL bundle so the judge is skipped and the probes are not_evaluable.
        bundle = {
            "null_everything": True,
            "null_reason": f"no emitted package at {ep_path}",
            "l2a": {},
            "l2b": {},
            "l3": None,
        }
        decision = None
        evidence_package = {}
    else:
        decision = _load_json(pkg_dir / "decision.json")
        bundle = _substrate.assemble_from_objects(evidence_package, decision, contracts_root=contracts_root)

    judge_result = _judge.judge(bundle, decision, llm=llm, max_tokens=max_tokens)
    containment = _containment.contain(judge_result, bundle)
    probes = run_probes(evidence_package, entry, skill, contracts_root=contracts_root)

    return PackageResult(
        entry=entry,
        assembled=not bundle.get("null_everything"),
        null_reason=bundle.get("null_reason"),
        judge_skipped=judge_result.get("skipped"),
        n_findings=int(judge_result.get("n_findings") or 0),
        containment=containment,
        probes=probes,
        judge_result=judge_result,
    )


# ── one whole iteration ───────────────────────────────────────────────────────────────────────────────
def run_iteration(
    skill: str,
    entries: Sequence[Entry],
    run_dir: "Path | str",
    *,
    llm: "Optional[Callable[..., dict]]" = None,
    teeth_green: bool = False,
    contracts_root: "Path | str | None" = None,
    ledger: "Optional[_findings.Ledger]" = None,
    hysteresis_n: int = _convergence.DEFAULT_HYSTERESIS_N,
    property_coverage: "Optional[dict]" = None,
    iteration_id: str = "iter-001",
    max_tokens: int = 3000,
) -> dict:
    """Run ONE loop iteration end-to-end over an emitted ``run_dir``; returns the iteration report dict.

    DEV-split packages feed the findings ledger (``ledger`` is resumed if passed, so a repeat finding
    collapses across iterations) and tier routing. HELD-OUT-split packages feed the convergence
    assessment (judge-finding + probe emptiness on the hash-fixed roster). ``teeth_green`` is forwarded to
    tier routing verbatim (STOP-A: default ``False`` ⇒ report-only, nothing lands at T1)."""
    run_dir = Path(run_dir)
    ledger = ledger if ledger is not None else _findings.Ledger()

    dev_results: list[PackageResult] = []
    held_results: list[PackageResult] = []
    for entry in entries:
        pr = process_package(entry, run_dir, skill, llm=llm, contracts_root=contracts_root, max_tokens=max_tokens)
        (held_results if entry.split == "held_out" else dev_results).append(pr)

    # DEV: ledger + tiers over the CONTAINED findings only (dropped/demoted never route — acceptance).
    dev_contained: list[dict] = []
    for pr in dev_results:
        dev_contained.extend(pr.containment.get("contained") or [])
    ledger.extend(dev_contained)
    tier_report = _tiers.route_many(dev_contained, teeth_green=teeth_green)

    # HELD-OUT: convergence over (candidate_key, judge_result, probe_findings) triples.
    held_keys = [pr.entry.candidate_key for pr in held_results]
    expected_pin = _convergence.roster_pin(held_keys) if held_keys else None
    held_packages = [(pr.entry.candidate_key, pr.judge_result, pr.probes) for pr in held_results]
    run_result = _convergence.assess_run(iteration_id, held_packages, expected_pin=expected_pin)
    convergence_report = _convergence.declare_convergence(
        [run_result], hysteresis_n=hysteresis_n, expected_pin=expected_pin, property_coverage=property_coverage
    )

    chain = ledger.verify()
    return {
        "schema_version": SCHEMA_VERSION,
        "iteration_id": iteration_id,
        "skill": skill,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_dir": str(run_dir),
        "teeth_green": teeth_green,
        "report_only": not teeth_green,
        "applicable_probes": list(applicable_probes(skill)),
        "roster": {
            "n_total": len(entries),
            "n_dev": len(dev_results),
            "n_held_out": len(held_results),
        },
        "dev": {
            "packages": [pr.to_jsonable() for pr in dev_results],
            "n_contained_findings": len(dev_contained),
            "tiers": {
                "T1_land": len(tier_report[_tiers.T1]),
                "T2_propose": len(tier_report[_tiers.T2]),
                "T3_adjudicate": len(tier_report[_tiers.T3]),
            },
            "tier_report": tier_report,
        },
        "held_out": {
            "packages": [pr.to_jsonable() for pr in held_results],
            "convergence": convergence_report.to_jsonable(),
        },
        "ledger": {
            "n_entries": len(ledger),
            "chain_ok": chain["ok"],
            "head_hash": ledger.head_hash,
        },
    }, ledger


# ── CLI (live run — never reached by the test suite) ────────────────────────────────────────────────
def _cli(argv: "Optional[list[str]]" = None) -> int:
    parser = argparse.ArgumentParser(description="Run ONE subskill-loop iteration end-to-end (propose-only).")
    parser.add_argument(
        "--skill", required=True, help="skill directory name under skills/ (e.g. functional-requirement)"
    )
    parser.add_argument("--batch-spec", required=True, type=Path, help="a batch_constructor batch-<id>.v1.json")
    parser.add_argument("--run-dir", required=True, type=Path, help="the run_batch iter-NNN-<sha> directory")
    parser.add_argument("--out-dir", required=True, type=Path, help="where to persist the ledger + iteration report")
    parser.add_argument("--iteration-id", default="iter-001")
    parser.add_argument(
        "--teeth-green",
        action="store_true",
        help="assert the judge+containment teeth are CI-confirmed green (else report-only — STOP-A)",
    )
    parser.add_argument("--max-tokens", type=int, default=3000)
    args = parser.parse_args(argv)

    spec = json.loads(args.batch_spec.read_text())
    entries = load_entries_from_batch_spec(spec)
    property_coverage = spec.get("coverage") if isinstance(spec, dict) else None

    args.out_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = args.out_dir / "findings_ledger.json"
    ledger = _findings.load_ledger(ledger_path)  # resume if a prior iteration persisted one

    report, ledger = run_iteration(
        args.skill,
        entries,
        args.run_dir,
        teeth_green=args.teeth_green,
        ledger=ledger,
        property_coverage=property_coverage,
        iteration_id=args.iteration_id,
        max_tokens=args.max_tokens,
    )

    _findings.save_ledger(ledger, ledger_path)
    report_path = args.out_dir / "iteration_report.json"
    report_path.write_text(json.dumps(report, indent=1, default=str))

    conv = report["held_out"]["convergence"]
    print(f"=== loop iteration {args.iteration_id}: skill={args.skill} ===")
    print(f"  roster: {report['roster']}")
    print(
        f"  dev: {report['dev']['n_contained_findings']} contained finding(s) → "
        f"tiers {report['dev']['tiers']} (teeth_green={report['teeth_green']})"
    )
    print(f"  held-out convergence: converged={conv['converged']} (consecutive_clean={conv['consecutive_clean']})")
    if not conv["converged"]:
        for r in conv["latest_block_reasons"]:
            print(f"      • {r}")
    print(f"  ledger: {report['ledger']['n_entries']} entr(ies), chain_ok={report['ledger']['chain_ok']}")
    print(f"  → {report_path}")
    print(f"  → {ledger_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
