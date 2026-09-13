"""`DEFERRED_ANCHORS` — an expected-absence declaration that, until now, nothing asserted.

`fusion_driver` is deferred by an EVIDENCED separation failure, not by absence: a 2026-09-02 re-freeze that
activated it regressed the panel (MET flipped fusion-dominant, CLDN18 31%) because FUS is one sparse
feature and the anchor bled RTK-ness. The deferral lives in one `frozenset` in `build_atlas.py`, and
skills #1243 is the only other record of it.

★ Why this file exists. Two of `fusion_driver`'s five exemplars — `RET/THCA` and `NTRK1/THCA` — RE-ENTERED
the corpus with the 2026-09-13 expansion. Before that, the anchor would have been skipped anyway for
having no members present, so `DEFERRED_ANCHORS` was belt-and-braces. It is now the ONLY thing keeping a
known-bleeding anchor out of the shipped artifact, and no test read it: deleting the frozenset, or dropping
the `if label in DEFERRED_ANCHORS` branch, would have produced a fully GREEN re-freeze that silently
re-introduced the 2026-09-02 regression.

Structured as the four checks this repo uses for any expected-absence declaration (see TC #752's
`expected_inert_arms`): **dangling** (it names a real anchor), **misdeclared** (the anchor did not in fact
activate), **stale** (the declaration is still load-bearing — an ERROR, not a warning, because a deferral
that no longer does anything documents the opposite of the behaviour), and the **reason** being present in
prose rather than implied.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build_atlas.py"


@pytest.fixture(scope="module")
def build_mod():
    spec = importlib.util.spec_from_file_location("build_atlas", BUILD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_atlas"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(ATLAS.read_text())


def test_the_deferral_exists_at_all(build_mod):
    """Positive control: every check below iterates DEFERRED_ANCHORS, so all of them pass vacuously against
    an empty frozenset."""
    assert build_mod.DEFERRED_ANCHORS, "DEFERRED_ANCHORS is empty — the deferral mechanism is gone"


def test_fusion_driver_specifically_is_still_deferred(build_mod):
    """The named pin, and NOT redundant with the positive control above. Every other test here iterates
    whatever DEFERRED_ANCHORS happens to contain, so dropping `fusion_driver` while adding some other label
    keeps the set non-empty and the whole file green — while the one anchor with a MEASURED regression
    behind it activates. The evidence is specific to this anchor, so the guard is too."""
    assert "fusion_driver" in build_mod.DEFERRED_ANCHORS, (
        "fusion_driver is no longer deferred. It bled RTK-ness when activated on 2026-09-02 (MET flipped "
        "fusion-dominant, CLDN18 31%) and 2 of its 5 exemplars are back in the corpus, so a re-freeze will "
        "now ACTIVATE it. Only remove this with a passing separation test in the same PR (skills #1243)."
    )


def test_no_deferred_anchor_dangles(build_mod):
    """DANGLING: a deferred label that names nothing in ANCHOR_SETS protects nothing, and reads as if it
    did."""
    unknown = set(build_mod.DEFERRED_ANCHORS) - set(build_mod.ANCHOR_SETS)
    assert not unknown, f"DEFERRED_ANCHORS names anchors that do not exist: {sorted(unknown)}"


def test_no_deferred_anchor_reached_the_shipped_artifact(build_mod, doc):
    """MISDECLARED: the declaration and the artifact must agree. A deferred anchor appears in
    `anchor_phenotypes_skipped` and must NOT appear in `anchor_phenotypes`."""
    deferred = set(build_mod.DEFERRED_ANCHORS)
    active = set(doc["meta"].get("anchor_phenotypes") or [])
    skipped = set(doc["meta"].get("anchor_phenotypes_skipped") or [])
    leaked = deferred & active
    assert not leaked, (
        f"DEFERRED anchor(s) {sorted(leaked)} ACTIVATED in the shipped atlas. This is the 2026-09-02 "
        "regression: fusion_driver bleeds RTK-ness into its neighbours (MET flipped fusion-dominant, "
        "CLDN18 31%). Do not relax this guard — re-freeze without the anchor, or land a passing "
        "separation test first (skills #1243)."
    )
    assert deferred <= skipped, (
        f"deferred anchors missing from meta.anchor_phenotypes_skipped: {sorted(deferred - skipped)} — the "
        "artifact does not record its own deferral, so a consumer cannot tell a deferred anchor from one "
        "that never existed"
    )


def test_the_deferral_is_still_load_bearing(build_mod, doc):
    """★ STALE — an ERROR, not a warning, and the check that makes this whole file worth having.

    A `DEFERRED_ANCHORS` entry only does work when its exemplars are PRESENT in the corpus; with none
    present, the build skips the anchor for absence and the deferral is decoration. This asserts the
    condition that makes the guard live, so the guard cannot quietly become a no-op — and so the day the
    corpus regains the exemplars is a day this test already covered rather than a silent change of state.

    Measured on the 2026-09-13 freeze: 2 of the 5 fusion_driver exemplars (RET/THCA, NTRK1/THCA) are in
    the corpus, having re-entered with the diverse expansion.
    """
    pairs = set(zip(doc["targets"], doc["indications"]))
    for label in sorted(build_mod.DEFERRED_ANCHORS):
        members = build_mod.ANCHOR_SETS.get(label, [])
        present = [tuple(m) for m in members if tuple(m) in pairs]
        assert present, (
            f"DEFERRED anchor '{label}' has no exemplars in the corpus, so the deferral currently changes "
            "NOTHING — the build would skip it for absence anyway. Either the corpus lost them (then this "
            "guard is decoration and the deferral's evidenced reason is misleading) or the exemplar set "
            "was edited. Re-read the deferral rather than deleting this test."
        )


def test_the_deferral_carries_a_prose_reason(build_mod):
    """A bare frozenset is an unexplained absence. The WHY has to survive next to the mechanism, because
    the whole failure mode here is a future session reading `{"fusion_driver"}` and seeing no cost to
    removing it."""
    src = BUILD.read_text()
    for label in build_mod.DEFERRED_ANCHORS:
        i = src.index(f'"{label}":')
        window = src[max(0, i - 2500) : i + 2500]
        assert "DEFERRED" in window and "separat" in window.lower(), (
            f"no prose reason near the '{label}' anchor definition explaining the deferral"
        )
