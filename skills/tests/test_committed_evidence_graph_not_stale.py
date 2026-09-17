"""A committed ``headline.evidence_graph`` must equal what the builder produces TODAY.

A decision fixture may carry a pre-built ``headline.evidence_graph``. Nothing regenerates those
blocks when the builder changes, so each is a SNAPSHOT that silently ages. Measured when this guard
landed: 5 of the 6 carriers had drifted from a rebuild by 16-72 leaves, and the dominant shape was
not a changed value but ``<absent> -> a real value`` — whole ``interpretation`` / ``categorical``
substructures the builder has since learned to emit. Those 5 were DELETED rather than refreshed,
because nothing read them: ``skills/conftest.py``'s ``eg_graph`` fixture REBUILDS from (decision +
questions registry) and never looks at the committed block, and no test in the repo reads
``key_evidence.n``. Only ``translational_full_emit.json`` was already byte-equal to a rebuild, so it
stays as this guard's live subject.

Staleness here is not automatically harmless, and that is the point of this guard. A stale block is a
plausible-looking artifact that a later reader can prefer over a rebuild and then be confidently
wrong about what the code emits today — ``report_render`` merges a carried block straight onto the
skill_report, and ``tumor-presence/tests/reconstruct_from_evidence_graph.py`` used to do exactly this
via ``decision[...].get("evidence_graph") or build_evidence_graph(...)``, correct only by the
accident that its own fixture carried no block. Deleting the stale data fixed the instances; this
fixes the CLASS, by turning any carried block into a checked claim about the current builder.

Deliberately a scan of EVERY fixture rather than a per-skill parametrization: the sibling
``test_evidence_graph_invariants.py`` discovers skills via ``*/tests/fixtures/*decision*.json`` and
takes ``sorted(...)[0]``, which resolves to ``kras_target_intrinsic_decision.json`` and was therefore
blind to the stale ``target_intrinsic_egfr_full_decision.json`` sitting in the same directory. A
narrower glob is how this class hid in the first place.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from _skills_common.evidence_graph import build_evidence_graph, load_questions

SKILLS_DIR = Path(__file__).resolve().parents[1]


def _carriers() -> list[Path]:
    """Every committed fixture that ships a ``headline.evidence_graph``, whatever it is named."""
    out = []
    for p in sorted(SKILLS_DIR.glob("*/tests/fixtures/*.json")):
        try:
            d = json.loads(p.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue  # non-decision fixtures (raw payloads, malformed-input cases) are not our subject
        if isinstance(d, dict) and isinstance(d.get("headline"), dict) and "evidence_graph" in d["headline"]:
            out.append(p)
    return out


_CARRIERS = _carriers()


def _norm(obj):
    """JSON round-trip so a rebuilt graph is compared on the SAME types the committed file can hold
    (a tuple the builder returns is a list once written, and would otherwise read as drift)."""
    return json.loads(json.dumps(obj))


def _leaves(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{prefix}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{prefix}[{i}]")
    else:
        yield prefix, obj


def _drift(committed, rebuilt) -> list[str]:
    """Differing leaf paths, rendered. Leaf-level rather than ``==`` so a failure names WHERE it
    drifted: an added substructure reports as ``<absent> -> value``, which is the shape that actually
    occurred, and a whole-object inequality message would be thousands of lines of unreadable dict."""
    a, b = dict(_leaves(committed)), dict(_leaves(rebuilt))
    return sorted(
        f"{k}: committed={a.get(k, '<absent>')!r} rebuilt={b.get(k, '<absent>')!r}"
        for k in set(a) | set(b)
        if a.get(k, "<absent>") != b.get(k, "<absent>")
    )


def _rebuild(path: Path):
    """(committed, rebuilt) for a carrier. The block is stripped before rebuilding so the builder
    sees what production hands it — a decision that does not yet have a graph."""
    decision = json.loads(path.read_text())
    committed = _norm(decision["headline"]["evidence_graph"])
    stripped = copy.deepcopy(decision)
    stripped["headline"].pop("evidence_graph")
    skill_dir = path.parents[2]  # …/skills/<skill>/tests/fixtures/x.json
    return committed, _norm(build_evidence_graph(stripped, questions=load_questions(skill_dir)))


def _control_graph():
    """A real graph for the detector controls below, built from a fixture that carries NO committed
    block. Anchoring the controls here rather than at ``_CARRIERS[0]`` keeps them meaningful whatever
    happens to the carriers — including if every one is eventually deleted, which is precisely when a
    silently-broken detector would matter most."""
    skill_dir = SKILLS_DIR / "tumor-presence"
    decision = json.loads((skill_dir / "tests" / "fixtures" / "epcam_coadread_decision.json").read_text())
    return _norm(build_evidence_graph(decision, questions=load_questions(skill_dir)))


def test_at_least_one_carrier_is_checked():
    """Anti-vacuity. Every stale block was deleted, so "no carrier drifts" would pass trivially if a
    rename or a deletion emptied the scan. One equal carrier is deliberately kept; if this goes RED,
    the guard below is asserting nothing and the scan — not the fixtures — is what to look at."""
    assert _CARRIERS, "no fixture carries headline.evidence_graph — this guard has become vacuous"


@pytest.mark.parametrize("path", _CARRIERS, ids=lambda p: p.stem)
def test_committed_graph_equals_a_rebuild(path):
    """A carried block must be what the builder emits today. To fix a RED: regenerate the block, or
    delete it (nothing is required to carry one — ``evidence_graph`` is neither declared nor required
    in any target-contracts decision schema, and ``headline.additionalProperties`` is unset)."""
    committed, rebuilt = _rebuild(path)
    drift = _drift(committed, rebuilt)
    assert not drift, f"{path.relative_to(SKILLS_DIR.parent)} is a STALE snapshot ({len(drift)} leaves):\n" + "\n".join(
        drift[:10]
    )


def test_the_comparison_detects_a_changed_value():
    """Positive control on the DETECTOR. Without it, the guard's green would only prove that the
    fixtures are equal — not that unequal ones would be caught."""
    rebuilt = _control_graph()
    assert not _drift(copy.deepcopy(rebuilt), rebuilt)  # a graph does not drift from itself
    mutated = copy.deepcopy(rebuilt)
    mutated["cards"][0]["id"] = "definitely-not-the-real-card-id"
    drift = _drift(mutated, rebuilt)
    assert len(drift) == 1 and ".cards[0].id" in drift[0], drift


def test_the_comparison_detects_a_missing_substructure():
    """The second control covers the shape the real drift actually took: the committed block was not
    WRONG about a value, it was MISSING substructure the builder later learned to emit. An equality
    check that only compared shared keys would have called all 5 stale fixtures clean."""
    rebuilt = _control_graph()
    trimmed = copy.deepcopy(rebuilt)
    trimmed["cards"][0].pop("confidence")
    trimmed["cards"].pop()  # a dropped list element shifts indices — drift, not a silent pass
    drift = _drift(trimmed, rebuilt)
    assert drift, "a committed block missing whole subtrees must not read as equal"
    assert any("<absent>" in d for d in drift), drift
