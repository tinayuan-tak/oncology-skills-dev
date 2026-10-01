"""Scorecard shard guard (PR-1c of epic SK#2210 / #1507) — the COMMITTED genomic-alteration-profile
shard stays honest and is a live function of the adapter, not a hand-typed fixture.

The shard (`scorecard/genomic-alteration-profile.json`) is a committed artifact built by
`scripts/scorecard_adapter.py`; the aggregate drift guard (`scripts/regenerate_scorecard.py --check`)
checks schema + render staleness but deliberately never interprets adapter-owned evidence. This module
supplies the adapter-side guards, mirroring functional-requirement's PR-1b precedent exactly:

  1. ROUND-TRIP TEETH — the committed shard equals `build_shard().to_dict()` exactly. A hand-edit that
     drifts from the adapter, or an adapter change not re-materialised into the committed file, reds.
     This is what makes the committed JSON non-fabricated: it is what this code produces.
  2. L2a/L2b are BUILT (PR-1c built the exported source_properties / integrated_properties sections) but
     UNMEASURED — built=True, cell rolls up NULL, every criterion NULL with a null_reason. Never
     promoted on the strength of the layer merely existing.
  3. L1/L3/L4 stay at the all-NULL baseline (built=None): PR-1c is the L2a/L2b substrate item and
     assesses none of them. The pin asserts that, so a future L1/L3/L4 assessment is a deliberate change.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent

from _skills_common import component_scorecard as cs  # noqa: E402

SHARD_PATH = REPO_ROOT / cs.SCORECARD_DIRNAME / "genomic-alteration-profile.json"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "ga_scorecard_adapter_under_test", SKILL_DIR / "scripts" / "scorecard_adapter.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shard_dict() -> dict:
    return json.loads(SHARD_PATH.read_text())


def test_committed_shard_equals_the_adapter_output():
    """ROUND-TRIP TEETH: the committed file IS what build_shard() produces. Reds on any drift between
    the adapter and the committed artifact (in either direction), so neither can silently diverge."""
    ad = _load_adapter()
    assert _shard_dict() == ad.build_shard().to_dict(), (
        "scorecard/genomic-alteration-profile.json has drifted from scorecard_adapter.build_shard() — "
        "re-run `python skills/genomic-alteration-profile/scripts/scorecard_adapter.py` and re-render."
    )


def test_l2_layers_are_built_but_unmeasured():
    """PR-1c BUILT L2a/L2b, so NOT-ASSESSED (built=None) would understate the artifact — but building a
    layer is not measuring it, so every criterion stays NULL with a reason and the cell rolls up NULL,
    never GREEN. The rollup (any NULL blocks GREEN) is what enforces that; this pins the inputs to it."""
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="genomic-alteration-profile")
    for layer in ("L2a", "L2b"):
        cell = shard.cells[layer]
        assert cell.built is True, f"{layer} is exported by run.py::_evidence_sections — built must be True"
        assert cs.cell_rollup(cell) == cs.NULL, f"{layer} rolled up {cs.cell_rollup(cell)}, expected NULL (unmeasured)"
        for name in cs.CRITERIA:
            crit = cell.criteria[name]
            assert crit.status == cs.NULL, f"{layer}/{name} claims {crit.status} with no measurement built"
            assert (crit.evidence or {}).get("null_reason"), f"{layer}/{name} is NULL with no reason recorded"
            assert (crit.evidence or {}).get("structural_pins"), f"{layer}/{name} names no structural pin"


def test_l1_l3_l4_remain_unassessed_baseline():
    """PR-1c is the L2a/L2b substrate item: it assesses no L1 disposition/panel, no L3d story, and no L4
    synthesis. Those stay at the baseline (built=None, criteria NULL/None) — a future assessment must
    move them deliberately and red this pin, not slip in unnoticed."""
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="genomic-alteration-profile")
    for layer in ("L1", "L3", "L4"):
        cell = shard.cells[layer]
        assert cell.built is None, f"{layer} built={cell.built!r} — PR-1c did not assess it; expected the None baseline"
        for name in cs.CRITERIA:
            assert cell.criteria[name].status == cs.NULL, f"{layer}/{name} is not NULL on the baseline"


def test_every_structural_pin_cites_an_existing_file():
    """A structural pin naming a file that does not exist is a fabricated guard reference."""
    data = _shard_dict()
    checked = 0
    for layer in ("L2a", "L2b"):
        for name, crit in data["cells"][layer]["criteria"].items():
            for entry in (crit["evidence"] or {}).get("structural_pins", []):
                rel = entry.split(" ")[0]
                assert (REPO_ROOT / rel).exists(), f"{layer}/{name} structural pin cites missing file {rel}"
                checked += 1
    assert checked >= 8, f"suspiciously few structural pins checked ({checked}) — did the evidence shrink?"
