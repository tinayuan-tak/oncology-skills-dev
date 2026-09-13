"""`DEFERRED_ANCHORS` / `UNDECLARED_ANCHORS` — expected-absence declarations that nothing asserted.

TWO mechanisms defer an anchor, and they fail differently. `DEFERRED_ANCHORS` gates a label that HAS an
exemplar set (`fusion_driver`); `UNDECLARED_ANCHORS` records a label deliberately given NO exemplar set
(`synthetic_lethal`), which the first mechanism structurally cannot cover. The second half of this file
(2026-09-13) applies the same four checks to it — see the section comment there.

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


# --- the OTHER deferral mechanism: deferred by having NO exemplar set at all ---------------------------
# `synthetic_lethal` was deferred on the same kind of evidence as `fusion_driver` (2026-09-13 separation
# test: the SL centroid sat inside the p90 NN scale of BOTH dependency_essential and tsg_loss, CHEK1 FLIPPED
# to SL at 54%), but by a strictly WEAKER mechanism — it simply carries no ANCHOR_SETS entry, so the build
# skips it by never iterating it. DEFERRED_ANCHORS cannot protect it: that frozenset only gates labels that
# HAVE an entry, and `test_no_deferred_anchor_dangles` above would in fact go RED if someone tried to add
# `synthetic_lethal` to it as-is. So the absence is invisible, and pasting the curated exemplar list back in
# ACTIVATES a known-bleeding corner with a green suite. `UNDECLARED_ANCHORS` turns the absence into a
# declaration; these are the same four checks applied to it.


def test_the_undeclared_deferral_exists_at_all(build_mod):
    """Positive control for the checks below, which iterate UNDECLARED_ANCHORS."""
    assert build_mod.UNDECLARED_ANCHORS, "UNDECLARED_ANCHORS is empty — the deferral is undeclared again"


def test_synthetic_lethal_specifically_is_still_undeclared(build_mod):
    """Pinned BY NAME: iterating the declaration is GREEN under a SUBSTITUTION (swap this label for any
    other and every other test here still passes), so the load-bearing member needs its own assertion with
    the evidence in the failure message."""
    assert "synthetic_lethal" in build_mod.UNDECLARED_ANCHORS, (
        "synthetic_lethal is no longer declared as deferred. It does NOT separate: 2026-09-13 test put its "
        "centroid inside the p90 NN scale (~6.30) of dependency_essential (5.94) and tsg_loss (5.37), only "
        "3/6 exemplars recovered (WRN->tsg_loss 37%, PARP1->amp_driver 36%), and DDR dependencies bled in "
        "(CHEK1 FLIPPED to synthetic_lethal 54%, WEE1 38%). Root cause is the feature space (SL claim signal "
        "129/213 rows vs dependency::COND 2-3/213), not the exemplar count — re-run the separation test and "
        "make it PASS before removing this."
    )


def test_no_undeclared_anchor_carries_an_exemplar_set(build_mod):
    """The mechanism itself: these labels are deferred BY having no ANCHOR_SETS entry, so an entry appearing
    is the activation this file exists to catch. Mirrors the producer-boundary check in build()."""
    activated = sorted(set(build_mod.UNDECLARED_ANCHORS) & set(build_mod.ANCHOR_SETS))
    assert not activated, (
        f"{activated} are declared deferred in UNDECLARED_ANCHORS but now have an ANCHOR_SETS entry, which "
        f"ACTIVATES them: " + " | ".join(f"{k}: {build_mod.UNDECLARED_ANCHORS[k]['reason']}" for k in activated)
    )


def test_the_undeclared_deferral_is_still_load_bearing(build_mod, doc):
    """STALE-as-ERROR. If the declared exemplars were NOT in the corpus, the label would be skipped anyway
    for having no members present and this whole declaration would document a hypothetical. They ARE in the
    corpus (WRN/COADREAD, PARP1/BRCA, ATR/OV, POLQ/BRCA, MAT2A/PAAD, RAD51/OV all shipped 2026-09-13), so
    restoring an entry activates the anchor on the NEXT build with no further data work — which is exactly
    the accident being guarded. Read from the declaration, not a hardcoded list."""
    pairs = set(zip(doc["targets"], doc["indications"]))
    for label, spec in sorted(build_mod.UNDECLARED_ANCHORS.items()):
        exemplars = [tuple(m) for m in spec["exemplars"]]
        assert exemplars, f"'{label}' declares no exemplars — nothing pins that the deferral still matters"
        present = [m for m in exemplars if m in pairs]
        assert present, (
            f"none of '{label}''s {len(exemplars)} declared exemplars {exemplars} are in the shipped corpus, "
            f"so this deferral is no longer load-bearing (the anchor would be skipped for absence anyway). "
            f"Either the corpus lost them — re-run the separation test against the CURRENT corpus before "
            f"trusting the evidence — or the exemplar list drifted from the panel."
        )


def test_no_undeclared_anchor_reached_the_shipped_artifact(build_mod, doc):
    """Deferral-by-absence leaves NO trace in the artifact — that is its defining weakness, and the
    assertion has to encode it: the label must appear in neither the active anchors nor the skipped list.
    (`anchor_phenotypes_skipped` is populated from the ANCHOR_SETS loop, so a label with no entry cannot get
    in there. If a future re-freeze DOES stamp these labels into meta, this test is where that shows up.)"""
    undeclared = set(build_mod.UNDECLARED_ANCHORS)
    active = set(doc["meta"].get("anchor_phenotypes") or [])
    skipped = set(doc["meta"].get("anchor_phenotypes_skipped") or [])
    assert active, "artifact declares no active anchors — the check below would be vacuous"
    assert not (undeclared & active), (
        f"{sorted(undeclared & active)} are declared deferred but ARE anchors in the shipped atlas — the "
        f"artifact was built from a tree where the exemplar set existed. Re-freeze or re-defer."
    )
    assert not (undeclared & skipped), (
        f"{sorted(undeclared & skipped)} appear in anchor_phenotypes_skipped, which means they had an "
        f"ANCHOR_SETS entry at build time (that list only ever names labels the loop iterated)."
    )


def test_the_undeclared_deferral_carries_its_evidence(build_mod):
    """The reason must be a real evidence statement, not a TODO. Keyed on the declared structure rather
    than a prose window: a substring match on source text is not a population."""
    for label, spec in sorted(build_mod.UNDECLARED_ANCHORS.items()):
        reason = spec.get("reason") or ""
        assert len(reason) > 200, f"'{label}' carries no substantive reason ({len(reason)} chars)"
        assert "separat" in reason.lower(), (
            f"'{label}''s reason does not reference the separation test that justifies the deferral — an "
            f"un-evidenced deferral is indistinguishable from an oversight, and cannot be overturned"
        )


def test_the_build_itself_refuses_an_activated_deferral(build_mod, monkeypatch):
    """★ The guard exercised, not just described. A guard bound to the TEST SUITE cannot protect the caller
    that skips it — `build_atlas.py` is run by hand for a re-freeze — so the refusal lives at the producer
    boundary and this asserts it actually fires, with the evidence in the message."""
    monkeypatch.setitem(build_mod.ANCHOR_SETS, "synthetic_lethal", [("WRN", "COADREAD")])
    with pytest.raises(SystemExit) as e:
        build_mod.build([], Path("/nonexistent/panel.tsv"), "2026-01-01")
    msg = str(e.value)
    assert "synthetic_lethal" in msg and "CHEK1" in msg, msg


def test_the_build_refuses_a_dangling_deferred_anchor(build_mod, monkeypatch):
    """The other half of the producer check: a DEFERRED_ANCHORS label with no ANCHOR_SETS entry is a
    DECORATIVE guard (the skip loop iterates ANCHOR_SETS), which reads as protection while providing none."""
    monkeypatch.setattr(build_mod, "DEFERRED_ANCHORS", frozenset({"fusion_driver", "not_an_anchor"}))
    with pytest.raises(SystemExit) as e:
        build_mod.build([], Path("/nonexistent/panel.tsv"), "2026-01-01")
    assert "not_an_anchor" in str(e.value)


def test_the_build_does_not_refuse_the_shipped_declarations(build_mod):
    """Both poles: the refusals above must not be firing on the tree as it stands, or every build is red."""
    build_mod._assert_deferral_declarations_consistent()
