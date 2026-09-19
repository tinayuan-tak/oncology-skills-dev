"""Step-2 (signals-first): presence emits hierarchy-DERIVED sub-group signals — sources bound by
measurement_type from question_hierarchy.yaml (no hand-wired card-ids), confidence = agreement ×
sample-size. Verdict-INERT: presence_verdict byte-stable. skipif target-contracts absent (needs
measurement_type lookup)."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import runpy
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread.yaml"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _contracts_absent():
    root = Path(
        os.environ.get(
            "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
        )
    )
    return not (root / "cards").is_dir()


@pytest.fixture(scope="module")
def _headline(tmp_path_factory):
    if not FIXTURE.exists():
        pytest.skip("no fixture")
    frozen = yaml.safe_load(FIXTURE.read_text()) or {}
    import _skills_common as skc

    def _factory():
        def _read(cid, t, i, *a, **k):
            s = frozen.get(cid)
            return copy.deepcopy(s) if isinstance(s, dict) and s and not s.get("_freeze_error") else None

        return _read

    out = tmp_path_factory.mktemp("subgroup")
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(sys, "argv", ["run.py", "--target", "EPCAM", "--indication", "COADREAD", "--out", str(out)])
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit:
        pass
    finally:
        mp.undo()
    return json.loads((out / "decision.json").read_text()).get("headline", {})


def test_verdict_byte_stable(_headline):
    assert _headline.get("presence_verdict") == "tumor_broadly_expressed"


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent (measurement_type lookup)")
def test_subgroups_derived_from_hierarchy(_headline):
    sg = _headline.get("subgroup_signals") or {}
    assert set(sg) >= {"abundance", "malignant_intrinsic", "generality"}, f"got {set(sg)}"
    ab = sg["abundance"]
    assert ab["signal"] == "strong"
    assert ab["confidence"] in ("moderate", "high")
    assert ab["conflict"] is True  # cell-line protein bottom-decile level
    # ProCan (the ledger-audit orphan) is now a DERIVED abundance source — no hand-wiring
    assert any(s["card"] == "cellline-protein-abundance-procan" for s in ab["sources"])
    assert sg["malignant_intrinsic"]["signal"] == "strong"
    assert sg["malignant_intrinsic"]["confidence"] == "high"


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent (measurement_type lookup)")
def test_signal_unified_from_claim_vector(_headline):
    """UNIFICATION: the sub-group SIGNAL is overlaid from the tuned claim (A→abundance, C→malignant,
    D→generality) carrying its evidence-atom trace; cards still supply the corroborating sources."""
    sg = _headline.get("subgroup_signals") or {}
    cv = _headline.get("claim_vector") or {}
    ab = sg["abundance"]
    assert ab["signal_source"] == "claim_vector"
    assert ab["signal"] == cv["A"]["signal"]  # not the coarse heuristic re-read
    claims = {c["axis"]: c for c in ab.get("claims", [])}
    assert "A" in claims and "evidence_atom" in claims["A"]  # rules→data trace carried through
    assert len(ab["sources"]) >= 2  # cards still corroborate the signal
    assert sg["malignant_intrinsic"]["claims"][0]["axis"] == "C"
    assert sg["generality"]["claims"][0]["axis"] == "D"


@pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")
def test_subtype_grain_cards_excluded(_headline):
    """entity_grain=subtype cards are conditioners, not whole-cohort sources."""
    ab = (_headline.get("subgroup_signals") or {}).get("abundance") or {}
    src_cards = {s["card"] for s in ab.get("sources", [])}
    assert "tumor-rna-distribution-by-subtype" not in src_cards
    assert "cellline-rna-distribution-by-subtype" not in src_cards


def test_protein_subtype_arm_projected_onto_headline(_headline):
    """Stage 5: the protein-subtype arm is lifted onto the headline (mirroring the cell-line arm), ending
    "resolved every run, read zero times". WIRING guard: the keys must EXIST — values may be None on a
    fixture frozen before the protein by-subtype card existed (the nightly re-freeze populates real
    values), so this pins wiring, not a magnitude."""
    for k in (
        "protein_subtype_scope_available",
        "protein_subtype_axis_quality",
        "protein_n_subtypes_measured",
        "protein_subtype_stratification_class",
    ):
        assert k in _headline, f"{k} not surfaced into the presence headline (protein-subtype wiring drift)"


def test_subtype_layer_concordance_wired_and_verdict_inert(_headline):
    """The cross-layer concordance facet is surfaced on the headline; when present it carries the
    never-lift stamp. Verdict-INERT: presence_verdict is byte-stable regardless of the facet."""
    assert "subtype_layer_concordance" in _headline
    assert _headline.get("presence_verdict") == "tumor_broadly_expressed"  # spine unmoved by the facet
    c = _headline.get("subtype_layer_concordance")
    if c is not None:
        assert "verdict-INERT" in c["_never_lift"]
        assert c["concordance_class"] in ("discordant", "concordant", "insufficient")
