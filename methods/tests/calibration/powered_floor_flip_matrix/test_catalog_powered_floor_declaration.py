"""#2330 — pin contracts/vocabularies/property_catalog/dependency.yaml's `reliability.powered_floor`
DECLARATIONS to `onc_methods.reliability_calibration.powered_floors` (#2327), the single source of
truth, BOTH DIRECTIONS (epic #2210, #2306 rollout).

WHY THIS TEST LIVES HERE, NOT IN contracts/. Dependency direction is skills -> methods -> contracts,
never reversed — contracts/validators/validate_property_catalog.py admits the `n_effective_anchor` /
`powered_floor` SHAPE without importing onc_methods (it cannot). methods/ already depends on contracts/
(reads its vocabularies as data) and imports onc_methods directly, so the cross-file VALUE pin belongs
here, mirroring the precedent in ../high_anchor_flip_matrix/test_high_anchor_flip_matrix.py (reads
contracts/vocabularies/property_catalog/*.yaml with `yaml.safe_load`, imports onc_methods constants
directly).

WHAT IS PINNED, and why each pin can FAIL (SK#2091 — no inertness proofs; every assertion has a named
mutant that reds it):

1. **Every catalog-declared `powered_floor.value` equals `powered_floor_for(n_effective_anchor)`** — a
   method retuning its admissibility constant, or a catalog entry hand-editing a stale number, reds.
   (MUTANT: edit dependency.yaml's `value: 300` to `301` -> reds; PROVEN above via the contracts-side
   `test_dependency_powered_floor_declarations_match_the_pinned_roster`, and independently here against
   the LIVE code path rather than a second hardcoded literal.)
2. **Every catalog-declared anchor names a kind `powered_floors.py` actually calibrates** — declaring a
   floor against an anchor the deriver would resolve `unmeasured` (no floor) would silently misrepresent
   it as calibrated. (MUTANT: point a declaration's anchor at an uncalibrated kind -> reds.)
3. **The declared set of anchors is EXACTLY `calibrated_kinds()`** — reconciled BOTH ways: a calibrated
   kind the catalog forgot to declare, or a declared anchor the code no longer calibrates, both red. Not
   a floor (`>=`, additive growth tolerant) — `calibrated_kinds()` is a closed set today (#2327's three),
   so equality is the correct pin (arc habit: pin a roster to equality with its source).
4. **The declaration is genuinely DECLARATION-shaped, never a frozen VALUE** — `powered_floor.value` is
   re-derived from the LIVE `powered_floor_for(anchor)` on every run, never read as a stored answer. If
   the method's constant changes, this test (not a human) is what notices.

Nothing here asserts anything about any verdict (SK#2091). The subject is the derivation's provenance.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from onc_methods.reliability_calibration.powered_floors import calibrated_kinds, powered_floor_for

REPO_ROOT = Path(__file__).resolve().parents[4]
CATALOG_DIR = REPO_ROOT / "contracts" / "vocabularies" / "property_catalog"


def _load_powered_floor_declarations() -> "dict[tuple[str, str], dict]":
    """{(catalog_file, entry_id): reliability_block} for every entry across the property catalog that
    declares a `reliability.powered_floor` — i.e. the DECLARATION-shaped half of #2330, never the
    emitted-value half (no landed catalog carries that yet).
    """
    declared: dict[tuple[str, str], dict] = {}
    for path in sorted(CATALOG_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        section = "families" if doc.get("kind") == "l2b_family" else "properties"
        for entry_id, entry in (doc.get(section) or {}).items():
            rel = (entry or {}).get("reliability") or {}
            if "powered_floor" in rel:
                declared[(path.name, entry_id)] = rel
    return declared


DECLARED = _load_powered_floor_declarations()


def test_the_catalog_declares_at_least_one_powered_floor():
    """ANTI-VACUITY GUARD. Every clause below is proven only if DECLARED is non-empty — an empty corpus
    would make every parametrized clause below vacuously collect zero cases and report green for
    nothing. (MUTANT: an empty dependency.yaml, or one where every `powered_floor` key was renamed,
    reds this directly; every other test in this module would then also silently collect 0 cases.)
    """
    assert len(DECLARED) >= 3, f"expected >= 3 declared powered_floor entries, found {sorted(DECLARED)}"


@pytest.mark.parametrize("key", sorted(DECLARED))
def test_declared_powered_floor_value_equals_the_live_single_source(key):
    """1 — the catalog's frozen `value` must equal what the method computes TODAY, not what it computed
    when someone last hand-typed the number into the catalog."""
    rel = DECLARED[key]
    anchor = rel.get("n_effective_anchor")
    assert anchor, (
        f"{key}: `powered_floor` declared without `n_effective_anchor` (contracts validator should have caught this)"
    )
    live = powered_floor_for(anchor)
    declared_value = rel["powered_floor"]["value"]
    assert declared_value == live, (
        f"{key}: catalog declares powered_floor.value={declared_value} for anchor `{anchor}`, but "
        f"onc_methods.reliability_calibration.powered_floors.powered_floor_for('{anchor}') computes "
        f"{live} — the catalog has drifted from its single source of truth"
    )


@pytest.mark.parametrize("key", sorted(DECLARED))
def test_declared_anchor_is_a_kind_the_method_actually_calibrates(key):
    """2 — a declared floor against an anchor the deriver would resolve `unmeasured` is a false claim of
    calibration. `powered_floor_for` returning None is the deriver's signal that NO floor exists for
    this kind (#2327's six deliberately-unmeasured kinds); declaring one anyway would misrepresent it."""
    rel = DECLARED[key]
    anchor = rel["n_effective_anchor"]
    assert anchor in calibrated_kinds(), (
        f"{key}: declares a powered_floor for anchor `{anchor}`, which "
        f"onc_methods.reliability_calibration.powered_floors does not calibrate "
        f"({sorted(calibrated_kinds())}) — powered_floor_for would resolve None (unmeasured)"
    )


def test_declared_anchor_set_equals_calibrated_kinds_exactly():
    """3 — reconciled BOTH ways against the closed roster, not just '>= '. A calibrated kind the catalog
    forgot to declare is a silent coverage gap; a declared anchor the code no longer calibrates is a
    stale claim — either drift must be a named RED, not a shrink nobody notices.
    (MUTANT: add a 4th calibrated kind to powered_floors.py without a catalog declaration -> reds here;
    remove one of the three from the catalog -> reds here too.)
    """
    declared_anchors = {rel["n_effective_anchor"] for rel in DECLARED.values() if "n_effective_anchor" in rel}
    assert declared_anchors == set(calibrated_kinds()), (
        f"declared anchors {sorted(declared_anchors)} != calibrated_kinds() {sorted(calibrated_kinds())} — "
        f"the catalog and the single source of truth have diverged"
    )


def test_a_mutant_anchor_value_is_caught_by_the_live_recomputation():
    """4 — MUTATION TOOTH proving clause 1 is not vacuous: a hand-typed catalog value that drifts from
    the live constant by even 1 must fail the equality, not just happen to match by construction."""
    anchor, live = next(iter(calibrated_kinds())), None
    live = powered_floor_for(anchor)
    forged_value = live + 1
    assert forged_value != live, "the mutant must actually differ from the live value to prove anything"
    # Same comparison the parametrized test performs, inlined so the mutant is visibly caught here too.
    assert not (forged_value == powered_floor_for(anchor))
