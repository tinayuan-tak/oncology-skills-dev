"""Framework-wide measurement_types PULL-consistency (DATA_TO_SKILL_CONTRACT step 5 / Rule 3).

Every gate-view's composition.measurement_types_pulled must resolve to a REGISTERED measurement_type,
and every card it USES whose type is registered must be one the gate declares it pulls — the two halves
of the "a gate can't pull a claim no provider could satisfy, and can't silently pull a claim it never
declared" guard. This is the framework-wide net that also covers gate-views WITHOUT their own per-skill
parity test (tumor-presence / tumor-selectivity / functional-requirement / tractability-small-molecule).

The read-side PULL resolver these checks once wrapped (resolve_pull / PullResolution / STATUS_* — the
DATA_TO_SKILL_CONTRACT "resolver matches on type" affordance) was aspirational scaffolding never wired
into any production path; it was retired 2026-09-06 and these guards now read the registry directly.

Cross-repo: reads target-contracts. Graceful-skips the registry-dependent assertions when
target-contracts isn't checked out alongside (isolated CI), mirroring the other cross-repo checks.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# conftest puts skills/ on sys.path, so the worktree's copy of _skills_common resolves. We reuse the
# retained registry loader (_load_registry) rather than reimplementing path resolution.
from _skills_common import measurement_types as mt

yaml = pytest.importorskip("yaml")

COMMON = Path(__file__).resolve().parent.parent
SKILLS_DIR = COMMON.parent


def _registered_types() -> "set[str] | None":
    """The set of registered measurement_type keys, or None if the registry is unreachable."""
    doc = mt._load_registry()
    return set(doc["measurement_types"]) if doc else None


_REGISTRY_REACHABLE = _registered_types() is not None


# ---------- framework-wide pull consistency ----------


def _gate_pulls() -> dict:
    """Map skill_dir -> measurement_types_pulled, for every SKILL.md that declares one."""
    out = {}
    for md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = md.read_text()
        for chunk in text.split("---")[1:]:
            try:
                doc = yaml.safe_load(chunk)
            except yaml.YAMLError:
                continue
            if isinstance(doc, dict) and isinstance(doc.get("composition"), dict):
                pulled = doc["composition"].get("measurement_types_pulled")
                if pulled:
                    out[md.parent.name] = pulled
                break
    return out


def test_at_least_the_wired_gates_declare_pulls():
    pulls = _gate_pulls()
    # the wired biology gate-views that should each declare a pull now
    expected = {
        "functional-requirement",
        "genomic-alteration-profile",
        "mechanism-and-pharmacology",
        "on-target-safety-liability",
        "tractability-small-molecule",
        "tumor-presence",
        "tumor-selectivity",
        "differentiation-landscape",
        "surface-modality-fit",
    }
    missing = expected - set(pulls)
    assert not missing, f"these gate-views do not declare measurement_types_pulled: {sorted(missing)}"


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_every_pulled_type_is_registered():
    """The framework-wide invariant: no gate pulls a claim that isn't a registered measurement_type."""
    registered = _registered_types()
    offenders = {}
    for skill, pulled in _gate_pulls().items():
        bad = [t for t in pulled if t not in registered]
        if bad:
            offenders[skill] = bad
    assert not offenders, f"gate-views pulling unregistered types: {offenders}"


# ---------- framework-wide ANTI-DRIFT parity (cards_used → measurement_types_pulled) ----------
#
# The 2026-08-14 production-grade sweep found the SAME drift class in 4 skills (genomic-alteration,
# on-target-safety-liability, mechanism-and-pharmacology, differentiation-landscape): a card was added
# to cards_used but its measurement_type was never added to measurement_types_pulled — so the gate
# silently pulled a claim it never declared. Each got a per-skill parity test; THIS is the framework-wide
# net that also covers the gate-views WITHOUT their own parity test, so the drift can't reappear anywhere.

# Documented, intentional (skill_dir, type) exceptions where a used card's type is deliberately NOT
# declared. Add an entry ONLY with a rationale. Mirrors the composer waivers.
_WAIVED_UNDECLARED_CARD_TYPES: set[tuple[str, str]] = {
    # surface-modality-fit uses structure-features-static, but structure_druggability is an INPUT to the
    # DERIVED type adc_tce_modality_fit (which surface-modality-fit DOES declare), not pulled directly —
    # the gate declares the derived pull, not its inputs. Matches surface-modality-fit's own per-skill
    # test (test_measurement_types_pulled.py allowed_indirect={"structure-features-static"}).
    ("surface-modality-fit", "structure_druggability"),
}


def _gate_cards_used() -> dict:
    """Map skill_dir -> cards_used, for every SKILL.md that declares composition.cards_used."""
    out = {}
    for md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        for chunk in md.read_text().split("---")[1:]:
            try:
                doc = yaml.safe_load(chunk)
            except yaml.YAMLError:
                continue
            if isinstance(doc, dict) and isinstance(doc.get("composition"), dict):
                cu = doc["composition"].get("cards_used")
                if cu:
                    out[md.parent.name] = cu
                break
    return out


def _card_to_registered_type() -> dict:
    """Reverse index card_id -> measurement_type from the registry's per-type `cards:` lists."""
    vocab = (mt._load_registry() or {}).get("measurement_types") or {}
    c2t = {}
    for mtype, spec in vocab.items():
        for cid in (spec or {}).get("cards") or []:
            c2t[cid] = mtype
    return c2t


@pytest.mark.skipif(not _REGISTRY_REACHABLE, reason="measurement_types.yaml not reachable")
def test_every_used_card_type_is_declared_framework_wide():
    """FRAMEWORK-WIDE ANTI-DRIFT GUARD (consolidates the per-skill parity tests): for EVERY gate-view
    that declares measurement_types_pulled, every card in its cards_used whose registered measurement_type
    resolves must map to a type the gate DECLARES it pulls. Catches the exact drift the sweep kept finding
    — a card added without declaring its type — across ALL skills, including ones with no per-skill test.
    Gate-views that declare NO pulls (utility/placeholder skills) are out of scope for Rule 3 and skipped."""
    c2t = _card_to_registered_type()
    pulls = _gate_pulls()
    cards_used = _gate_cards_used()
    offenders: dict[str, list] = {}
    for skill, used in cards_used.items():
        if skill not in pulls:
            continue  # skill makes no Rule-3 pull declaration → out of scope
        declared = set(pulls[skill])
        undeclared = [
            (cid, c2t[cid])
            for cid in used
            if c2t.get(cid) is not None
            and c2t[cid] not in declared
            and (skill, c2t[cid]) not in _WAIVED_UNDECLARED_CARD_TYPES
        ]
        if undeclared:
            offenders[skill] = undeclared
    assert not offenders, (
        "cards used but whose registered measurement_type is NOT in the skill's measurement_types_pulled "
        f"(the sweep's drift class — declare the type or add a documented waiver): {offenders}"
    )
