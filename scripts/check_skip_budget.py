#!/usr/bin/env python3
"""Skip-budget ratchet for the skills CI shard legs (skills#2127).

WHY. ``SKIP != PASS``. ~45 contract-driven guards in this repo carry a
``skipif``/``pytest.skip`` gated on target-contracts being resolvable, and they run on CI
only because the shard job exports ``TARGET_CONTRACTS_ROOT`` at
``.github/workflows/skills-validate.yml``. If that export regresses, or ``contracts/cards``
moves, the whole contract-driven guard family (including the #1644 vocab-exhaustiveness
ratchet and the ``skills/conftest.py`` hierarchy-connectivity ratchet) goes SILENTLY
skipped — green-blind. ``-rs`` (added alongside this script) makes each skip *visible* in
the log; this script makes an *inflation* in their number RED.

HOW. Each skills shard leg redirects its pytest output to a log; the shard then calls this
script once per leg. It parses the leg's own pytest summary line, and asserts:

  1. CARDINALITY FLOOR — the leg reported at least one outcome. A budget guard that
     measures nothing passes green (``no tests ran`` must never read as "0 skips, fine").
  2. CEILING — ``skipped <= budget[label]``, the budget being a COMMITTED baseline
     measured from real CI shard logs (see ``.github/skills-skip-budget.json``).

An unknown label gets a ceiling of 0: a newly added leg/skill suite that skips nothing
stays green, and one that does skip reds with instructions to record the number. There is
no fall-through that grants an unmeasured leg an unbounded budget.

The budget is a CEILING and therefore a RATCHET: when skips go away the number must be
ratcheted DOWN in the same PR, or the slack becomes a permanent ceiling that hides the
next regression beneath it. In particular **skills#2090 (un-skip the contracts
validators) MUST lower the numbers in ``.github/skills-skip-budget.json``.**

Usage:
    python3 scripts/check_skip_budget.py --label <leg> --log <pytest-output-file> \
        [--baseline .github/skills-skip-budget.json]

Exit 0 = within budget; exit 1 = violation (with a ``::error::`` annotation). Always emits
a ``::notice::`` line with the measured numbers, so a single CI run yields the full
per-leg baseline even when every ceiling is still 0.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE = REPO_ROOT / ".github" / "skills-skip-budget.json"

# pytest's terminal summary line, e.g.
#   "12 passed, 3 skipped, 1 xfailed in 4.21s"   /   "no tests ran in 0.01s"
# Under `-q` (and under xdist) the "collected N items" line is suppressed, so the summary
# counts are the only cardinality instrument available — hence the floor below.
_OUTCOME_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|xfailed|xpassed|error|errors|deselected|warnings?)\b")
_SUMMARY_TAIL_RE = re.compile(r"\bin\s+[\d.]+s")

# outcomes that prove tests actually ran (deselected/warnings do NOT)
_CARDINALITY_KEYS = ("passed", "failed", "skipped", "xfailed", "xpassed", "error", "errors")


def parse_outcomes(text: str) -> dict[str, int] | None:
    """Counts from the LAST pytest summary line in ``text``.

    Returns ``None`` when no summary line is present at all (a crashed / truncated log),
    and ``{}`` for an explicit ``no tests ran`` summary — two distinct failures the caller
    must keep distinct, and NEITHER of which may read as "zero skips, fine".
    """
    last: dict[str, int] | None = None
    for line in text.splitlines():
        if not _SUMMARY_TAIL_RE.search(line):
            continue
        counts = {kind: int(n) for n, kind in _OUTCOME_RE.findall(line)}
        if "errors" in counts:
            counts["error"] = counts.pop("errors")
        if counts or "no tests ran" in line:
            last = counts
    return last


def load_baseline(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text())
    budgets = data["budgets"]
    if not isinstance(budgets, dict):
        raise TypeError(f"{path}: 'budgets' must be an object")
    out: dict[str, int] = {}
    for label, value in budgets.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TypeError(f"{path}: budget for {label!r} must be a non-negative int, got {value!r}")
        out[label] = value
    return out


def check(label: str, log_text: str, budgets: dict[str, int]) -> tuple[int, str]:
    """Return ``(exit_code, message)`` for one leg."""
    counts = parse_outcomes(log_text)
    if counts is None:
        return 1, (
            f"skip-budget[{label}]: no pytest summary line found in the leg's output — the leg "
            "crashed or its log was truncated, so its skip count is UNMEASURED. Refusing to "
            "pass a guard that measured nothing."
        )
    ran = sum(counts.get(k, 0) for k in _CARDINALITY_KEYS)
    if ran <= 0:
        return 1, (
            f"skip-budget[{label}]: cardinality floor violated — the leg reported 0 outcomes "
            f"({counts}). 'no tests ran' is not '0 skips'; a leg that collects nothing is a "
            "silent un-cover, not a pass."
        )
    skipped = counts.get("skipped", 0)
    budget = budgets.get(label)
    known = budget is not None
    budget = 0 if budget is None else budget
    if skipped > budget:
        hint = (
            f"this leg has NO entry in the baseline (unknown labels get a ceiling of 0). Add "
            f'"{label}": {skipped} to the "budgets" object'
            if not known
            else f'raise "{label}" only with a written reason, or fix the skip'
        )
        return 1, (
            f"skip-budget[{label}]: {skipped} skipped > budget {budget} "
            f"({ran} outcomes reported). Skips inflated — SKIP != PASS, so a guard family may "
            f"have gone silently dark (e.g. TARGET_CONTRACTS_ROOT no longer resolving). Run the "
            f"leg with -rs to see WHICH tests skipped and why; {hint} in "
            f".github/skills-skip-budget.json."
        )
    return 0, f"skip-budget[{label}]: {skipped} skipped <= budget {budget} ({ran} outcomes reported)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", required=True, help="CI leg label (shard step / skill suite name)")
    ap.add_argument("--log", required=True, type=Path, help="file holding that leg's pytest output")
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    args = ap.parse_args(argv)

    try:
        budgets = load_baseline(args.baseline)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"::error title=skip-budget::baseline unreadable: {exc}")
        return 1
    try:
        log_text = args.log.read_text(errors="replace")
    except OSError as exc:
        print(f"::error title=skip-budget::leg log unreadable: {exc}")
        return 1

    rc, message = check(args.label, log_text, budgets)
    print(f"::{'error' if rc else 'notice'} title=skip-budget::{message}")
    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
