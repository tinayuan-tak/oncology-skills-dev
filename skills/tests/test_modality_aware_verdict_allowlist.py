"""Guard: the biology-first invariant — a skill's PRIMARY VERDICT is modality-INDEPENDENT.

`docs/AUTHORING_A_SKILL.md` (§ Biology-first verdicts): the primary output — verdict plus driving
`rule_id` — is modality-independent. Modality (small molecule / ADC / TCE …) is a POST-HOC lens
applied via `--modality`, never an input to the verdict. Mechanically, the dispatcher passes the
`--modality` lens into a skill's verdict callback ONLY when that skill declares
`verdict_modality_aware=True` on its `run_wired_skill(...)` call
(`skills/_skills_common/dispatcher.py`; the kwarg defaults to `False`). So a skill's verdict is
modality-dependent IFF it opts in with that kwarg.

Exactly one skill legitimately opts in — `tumor-selectivity` — for the v1.24.0
modality-conditional normal-breadth veto suppression, a documented biological exception grounded in
target-contracts declaring per-modality signals on the relevant KILL rules
(`skills/tumor-selectivity/scripts/run.py`). Until this guard, nothing PINNED that allowlist: a new
or refactored skill could set `verdict_modality_aware=True` and silently make its verdict depend on
the `--modality` lens — violating the documented invariant — with no test going red.

This guard AST-scans every `skills/*/scripts/run.py` for a `verdict_modality_aware=True` kwarg on
any call and asserts the set of modality-aware skills equals the pinned allowlist below. A new
opt-in fails here until the author either removes it or adds the skill to the allowlist WITH a
documented biological justification (the "waive-with-a-reason" shape the conformance / vocab guards
already use). Teeth = mutation, not inspection: set `verdict_modality_aware=True` in any other
skill's `run.py` dispatcher call and this goes RED; restore it and it GREENs.

AST-only (no imports, no live reads); independent of target-contracts.
"""

from __future__ import annotations

import ast
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent

# Skills whose PRIMARY VERDICT is allowed to depend on the --modality lens, each WITH a documented
# biological justification. Adding an entry is a deliberate, reviewed exception to the biology-first
# invariant — not a default. Keep this in lockstep with AUTHORING_A_SKILL.md § Biology-first verdicts.
_ALLOWLIST: dict[str, str] = {
    "tumor-selectivity": (
        "v1.24.0 modality-conditional normal-breadth veto suppression: the KILL arms carry per-modality "
        "signals in target-contracts (e.g. tvn-no-full-normal-window-veto declares ADC-neutral for the "
        "TROP2/sacituzumab archetype), so the clamp reads the fired rule's own signals[modality]. "
        "Contract-declared biological exception; modality=None stays worst-case (byte-identical without "
        "--modality)."
    ),
}


def _modality_aware_skills() -> set[str]:
    """The set of skills whose run.py sets `verdict_modality_aware=True` as a keyword on any call.

    Discovered by AST scrape of `skills/*/scripts/run.py` — this is the same enumeration the
    dispatcher uses to decide whether to thread the --modality lens into the verdict callback.
    """
    aware = set()
    for run in sorted(SKILLS.glob("*/scripts/run.py")):
        skill = run.relative_to(SKILLS).parts[0]
        tree = ast.parse(run.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "verdict_modality_aware" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    aware.add(skill)
    return aware


def test_modality_aware_discovery_is_not_vacuous():
    """Anti-vacuity floor for the allowlist ratchet below (per the #1648 enforcement-layer ratchet).

    The ratchet iterates `SKILLS.glob("*/scripts/run.py")`. If the glob matches nothing (skills
    relocated) or the AST scraper is refactored to return `set()`, the ratchet would assert an empty
    modality-aware set equals... an allowlist that also (wrongly) reduces to nothing, and pass GREEN
    having proven nothing (`collected` stays constant, so the collapse is invisible). Pin the run.py
    corpus to a member count so an emptied discovery goes RED here. 20 run.py files today; 15 is a
    slack floor. Independent of target-contracts, so this floor always runs."""
    n = len(sorted(SKILLS.glob("*/scripts/run.py")))
    assert n >= 15, (
        f"only {n} skills/*/scripts/run.py discovered — the glob broke; "
        "test_modality_aware_verdict_matches_allowlist would pass vacuously."
    )


def test_modality_aware_verdict_matches_allowlist():
    aware = _modality_aware_skills()
    allowed = set(_ALLOWLIST)
    unexpected = aware - allowed
    missing = allowed - aware
    assert not unexpected, (
        "a skill's PRIMARY VERDICT was made modality-dependent (verdict_modality_aware=True), "
        "violating the biology-first invariant (docs/AUTHORING_A_SKILL.md § Biology-first verdicts). "
        "Remove the opt-in, or add the skill to _ALLOWLIST WITH a documented biological justification "
        "(and the matching per-modality signal declaration in target-contracts): " + ", ".join(sorted(unexpected))
    )
    assert not missing, (
        "an allowlisted modality-aware skill no longer sets verdict_modality_aware=True — the "
        "documented exception was removed but the allowlist entry lingers. Drop it from _ALLOWLIST: "
        + ", ".join(sorted(missing))
    )
