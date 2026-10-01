#!/usr/bin/env python3
"""eval/loop/convergence.py — the subskill-iteration loop's STOPPING RULE (SK#2303 Phase-0 WI-H, #2359).

The loop needs a defensible place to stop. This module defines ONE: **finding-set emptiness on the
hash-fixed held-out roster** — NEVER a score, NEVER a verdict-stability claim (SK#2091). Convergence is
declared iff, across ``hysteresis_n`` CONSECUTIVE held-out runs, every held-out package is fully ALIVE
and the judge (``critic/judge.py``, #2355) + the regression probes (``critic/probes.py``, #2357) emit
ZERO surviving findings on the PINNED/hash-fixed held-out roster (the split from
``batch_constructor.py``, #2348).

Three load-bearing properties, each with teeth in ``tests/test_convergence.py``:

1. **NULL-blocking (the fail-open trap).** A NULL / degraded held-out package — a dead run
   (``substrate.null_everything`` ⇒ ``judge(...)["skipped"]`` is set), a judge that was never run, or a
   probe that reported ``not_evaluable`` (a framework-coverage gap) — can NEVER be scored as "clean."
   This is subtle precisely because a dead package emits ZERO judge findings and ZERO probe *fails*
   (its probes return ``not_evaluable``, never ``fail``) — so a naive "no findings ⇒ converged" reads a
   dead batch as a perfect pass. Convergence BLOCKS on any non-alive package. SKIP ≠ PASS; absence of
   findings because nothing was evaluated is NOT convergence (the WI-G NULL-not-pass semantics extend
   here, epic #2303).

2. **Hysteresis.** Emptiness must hold across ``hysteresis_n`` CONSECUTIVE held-out runs, not one lucky
   pass — a single empty run with ``hysteresis_n > 1`` does NOT declare convergence. Any run that is not
   fully-converged (a NULL package, a surviving finding, or a moved roster) RESETS the streak.

3. **Roster pinning.** The held-out roster is fixed by hash (``batch_constructor._split_hash_pct`` pins
   the split; this module pins the resulting *membership* via :func:`roster_pin`). A run whose observed
   held-out membership does not match the pinned hash is NOT counted as converged — a silently re-sampled
   roster invalidates the emptiness claim (a different, easier set could be empty for the wrong reason).

An EMPTY held-out roster never converges (vacuous emptiness = nothing evaluated = the fail-open trap in
another dress): :attr:`HeldOutRunResult.all_alive` requires at least one assessed package.

Index on the PROPERTY LAYERS, never the verdict (SK#2091): a "surviving finding" is a judge structural
proposal or a probe ``fail`` over L2a/L2b; nothing here reads ``synthesis.verdict`` / ``driving_rule_id``.
The convergence report is keyed on the property-layer coverage of the held-out set (passed through from
``batch_constructor.RosterResult.coverage_report``), never on a verdict distribution.

No ``__init__.py`` here (the ``eval/`` convention — a bare sys.path import, see ``critic/judge.py`` and
``findings.py``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional, Sequence

SCHEMA_VERSION = "1.0"

DEFAULT_HYSTERESIS_N = 2

# Probe verdict tokens (critic/probes.py returns 4-tuples (probe_id, severity, verdict, message)).
PROBE_FAIL = "fail"
PROBE_NOT_EVALUABLE = "not_evaluable"


# ── roster pinning ─────────────────────────────────────────────────────────────────────────────────
def roster_pin(keys: "Sequence[str]") -> str:
    """A pin over a held-out roster's MEMBERSHIP: ``sha256`` of the SORTED, de-duplicated candidate keys.

    Order-independent and set-identity-only — two runs over the SAME members pin identically regardless
    of input order; a run that drops, adds, or swaps a member pins DIFFERENTLY (that is what lets
    :func:`assess_run` catch a silently re-sampled roster). Keys are the ``batch_constructor.Candidate.key``
    strings whose split is ``held_out``."""
    uniq = sorted({str(k) for k in keys})
    payload = json.dumps(uniq, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def held_out_keys(split: dict) -> list[str]:
    """The held-out member keys of a ``batch_constructor.SplitResult.split`` mapping — the roster this
    module pins and evaluates. Sorted for determinism."""
    return sorted(k for k, label in split.items() if label == "held_out")


# ── per-package assessment ───────────────────────────────────────────────────────────────────────────
def _probe_verdict(finding: object) -> "Optional[str]":
    """The verdict slot (index 2) of a probe 4-tuple ``(probe_id, severity, verdict, message)``; ``None``
    for a malformed entry (which is itself treated as not-alive, never silently ignored)."""
    if isinstance(finding, (tuple, list)) and len(finding) >= 3:
        return finding[2]
    return "__malformed__"


@dataclass(frozen=True)
class HeldOutAssessment:
    """One held-out package's convergence-relevant status.

    ``alive`` is False whenever the package is NULL/degraded/not-evaluable — the NULL-block. A package is
    convergence-clean iff it is ``alive`` AND carries zero ``surviving_findings`` (judge findings + probe
    fails). ``surviving_findings`` is reported even for a non-alive package (for the report), but a
    non-alive package can never be clean regardless of its finding count."""

    key: str
    alive: bool
    surviving_findings: int
    null_reasons: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return self.alive and self.surviving_findings == 0

    def to_jsonable(self) -> dict:
        return {
            "key": self.key,
            "alive": self.alive,
            "surviving_findings": self.surviving_findings,
            "clean": self.clean,
            "null_reasons": list(self.null_reasons),
        }


def assess_package(key: str, judge_result: object, probe_findings: "Optional[Sequence]" = None) -> HeldOutAssessment:
    """Assess ONE held-out package from its judge result (``critic/judge.judge`` output) and the list of
    probe tuples (``critic/probes.probe_c1`` + ``probe_calib`` concatenated).

    NULL-BLOCK (any ⇒ ``alive=False``):
      - ``judge_result`` is not a dict (the judge was never run / crashed),
      - ``judge_result["skipped"]`` is set (``substrate.null_everything`` — a dead/degraded package),
      - any probe reported ``not_evaluable`` (a section was absent — a framework-coverage gap),
      - a malformed probe tuple.

    SURVIVING FINDINGS (count, independent of alive): the judge's ``n_findings`` + the number of probe
    ``fail`` verdicts. A dead package contributes 0 here (its probes are ``not_evaluable``, not ``fail``,
    and ``skipped`` carries ``findings=[]``) — which is EXACTLY why the NULL-block, not the finding count,
    is what stops a dead batch from reading as clean."""
    probe_findings = list(probe_findings or [])
    reasons: list[str] = []

    jr = judge_result if isinstance(judge_result, dict) else None
    if jr is None:
        reasons.append("judge result is not a dict (judge never ran / crashed)")
    elif jr.get("skipped"):
        reasons.append(f"judge skipped (null/dead substrate): {jr.get('skipped')}")

    n_not_evaluable = 0
    n_malformed = 0
    for pf in probe_findings:
        verdict = _probe_verdict(pf)
        if verdict == PROBE_NOT_EVALUABLE:
            n_not_evaluable += 1
        elif verdict == "__malformed__":
            n_malformed += 1
    if n_not_evaluable:
        reasons.append(f"{n_not_evaluable} probe(s) not_evaluable (framework-coverage gap, SKIP != PASS)")
    if n_malformed:
        reasons.append(f"{n_malformed} malformed probe finding(s)")

    n_judge = int((jr or {}).get("n_findings") or 0)
    n_probe_fail = sum(1 for pf in probe_findings if _probe_verdict(pf) == PROBE_FAIL)
    surviving = n_judge + n_probe_fail

    return HeldOutAssessment(
        key=key,
        alive=not reasons,
        surviving_findings=surviving,
        null_reasons=tuple(reasons),
    )


# ── per-run assessment ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class HeldOutRunResult:
    """One held-out RUN (one loop iteration's pass over the full pinned held-out roster)."""

    run_id: str
    assessments: tuple[HeldOutAssessment, ...]
    observed_pin: str
    expected_pin: "Optional[str]" = None

    @property
    def roster_matches(self) -> bool:
        """True iff this run's observed held-out membership matches the pinned roster. ``expected_pin``
        of ``None`` means 'no pin supplied' — treated as a match (pinning is enforced only when a pin is
        given), but :func:`declare_convergence` requires a pin for a real stopping decision."""
        return self.expected_pin is None or self.observed_pin == self.expected_pin

    @property
    def all_alive(self) -> bool:
        """Every assessed package is alive — AND there is at least one (an empty roster is vacuous, never
        'all alive': nothing was evaluated, so nothing converged)."""
        return bool(self.assessments) and all(a.alive for a in self.assessments)

    @property
    def finding_empty(self) -> bool:
        """Zero surviving findings across every assessed package (meaningful only alongside ``all_alive``)."""
        return all(a.surviving_findings == 0 for a in self.assessments)

    @property
    def converged(self) -> bool:
        """This run is a convergence candidate iff the roster is the pinned one, every package is alive,
        and not one surviving finding remains."""
        return self.roster_matches and self.all_alive and self.finding_empty

    @property
    def block_reasons(self) -> list[str]:
        """Why this run did NOT converge (empty ⇒ it did). Ordered: roster, emptiness-of-roster, NULL, findings."""
        reasons: list[str] = []
        if not self.roster_matches:
            reasons.append(
                f"roster pin mismatch (observed {self.observed_pin[:12]}... != pinned {str(self.expected_pin)[:12]}...)"
            )
        if not self.assessments:
            reasons.append("held-out roster is EMPTY (vacuous — nothing evaluated)")
        for a in self.assessments:
            if not a.alive:
                reasons.append(f"{a.key}: NULL/degraded — {'; '.join(a.null_reasons)}")
        n_findings = sum(a.surviving_findings for a in self.assessments if a.alive)
        if n_findings:
            offenders = [
                f"{a.key}({a.surviving_findings})" for a in self.assessments if a.alive and a.surviving_findings
            ]
            reasons.append(f"{n_findings} surviving finding(s): {', '.join(offenders)}")
        return reasons

    def to_jsonable(self) -> dict:
        return {
            "run_id": self.run_id,
            "observed_pin": self.observed_pin,
            "expected_pin": self.expected_pin,
            "roster_matches": self.roster_matches,
            "all_alive": self.all_alive,
            "finding_empty": self.finding_empty,
            "converged": self.converged,
            "block_reasons": self.block_reasons,
            "n_packages": len(self.assessments),
            "assessments": [a.to_jsonable() for a in self.assessments],
        }


def assess_run(
    run_id: str,
    packages: "Sequence[tuple]",
    *,
    expected_pin: "Optional[str]" = None,
) -> HeldOutRunResult:
    """Assess one held-out run from ``packages`` — a sequence of ``(key, judge_result, probe_findings)``
    triples (``probe_findings`` optional, defaulting to no probes). The run's ``observed_pin`` is computed
    from the keys actually present, so a re-sampled roster (a dropped/added/swapped member) pins
    differently from ``expected_pin`` and :attr:`HeldOutRunResult.roster_matches` goes False."""
    assessments: list[HeldOutAssessment] = []
    keys: list[str] = []
    for pkg in packages:
        key = pkg[0]
        judge_result = pkg[1] if len(pkg) > 1 else None
        probe_findings = pkg[2] if len(pkg) > 2 else None
        keys.append(key)
        assessments.append(assess_package(key, judge_result, probe_findings))
    return HeldOutRunResult(
        run_id=run_id,
        assessments=tuple(assessments),
        observed_pin=roster_pin(keys),
        expected_pin=expected_pin,
    )


# ── hysteresis + convergence declaration ──────────────────────────────────────────────────────────
@dataclass
class ConvergenceReport:
    """The convergence decision over a chronological sequence of held-out runs.

    ``converged`` is True iff the ``hysteresis_n`` MOST RECENT runs ALL converged (the tail streak reaches
    the threshold). ``property_coverage`` is passed straight through from
    ``batch_constructor.RosterResult.coverage_report`` so the report is keyed on the held-out set's
    property-layer coverage (never a verdict distribution)."""

    converged: bool
    hysteresis_n: int
    consecutive_clean: int
    expected_pin: "Optional[str]"
    runs: list = field(default_factory=list)  # list[HeldOutRunResult]
    property_coverage: "Optional[dict]" = None

    @property
    def latest_block_reasons(self) -> list[str]:
        """Why we are NOT (yet) converged, from the most recent run — empty iff that run converged."""
        return self.runs[-1].block_reasons if self.runs else ["no held-out runs recorded"]

    def to_jsonable(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "stopping_rule": "judge+probe finding-emptiness on the hash-fixed held-out roster (SK#2303 WI-H)",
            "converged": self.converged,
            "hysteresis_n": self.hysteresis_n,
            "consecutive_clean": self.consecutive_clean,
            "expected_pin": self.expected_pin,
            "n_runs": len(self.runs),
            "latest_block_reasons": self.latest_block_reasons,
            "property_coverage": self.property_coverage,
            "runs": [r.to_jsonable() for r in self.runs],
        }


def _tail_streak(runs: "Sequence[HeldOutRunResult]") -> int:
    """Length of the trailing run of ``converged`` runs (0 if the most recent did not converge)."""
    streak = 0
    for r in reversed(runs):
        if r.converged:
            streak += 1
        else:
            break
    return streak


def declare_convergence(
    runs: "Sequence[HeldOutRunResult]",
    *,
    hysteresis_n: int = DEFAULT_HYSTERESIS_N,
    expected_pin: "Optional[str]" = None,
    property_coverage: "Optional[dict]" = None,
) -> ConvergenceReport:
    """Decide convergence over ``runs`` (chronological order, oldest first).

    Convergence iff ``hysteresis_n >= 1`` and the ``hysteresis_n`` MOST-RECENT runs ALL converged — i.e.
    the tail streak of fully-alive, finding-empty, correctly-pinned runs reaches ``hysteresis_n``. A single
    empty pass with ``hysteresis_n > 1`` does NOT converge; a NULL/degraded package, a surviving finding,
    or a moved roster in ANY of the trailing runs breaks the streak.

    ``expected_pin``, when given, is applied to EVERY run that did not already carry one, so the whole
    sequence is judged against the SAME pinned roster (a mid-sequence re-sample is caught)."""
    runs = list(runs)
    if expected_pin is not None:
        runs = [r if r.expected_pin is not None else _with_expected_pin(r, expected_pin) for r in runs]
    streak = _tail_streak(runs)
    converged = hysteresis_n >= 1 and streak >= hysteresis_n
    return ConvergenceReport(
        converged=converged,
        hysteresis_n=hysteresis_n,
        consecutive_clean=streak,
        expected_pin=expected_pin,
        runs=runs,
        property_coverage=property_coverage,
    )


def _with_expected_pin(run: HeldOutRunResult, expected_pin: str) -> HeldOutRunResult:
    """Return a copy of ``run`` with ``expected_pin`` set (``HeldOutRunResult`` is frozen)."""
    return HeldOutRunResult(
        run_id=run.run_id,
        assessments=run.assessments,
        observed_pin=run.observed_pin,
        expected_pin=expected_pin,
    )
