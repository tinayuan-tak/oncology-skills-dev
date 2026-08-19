"""Phase-3 tests for the actionability_mode render emphasis routing (tp_render_md).
Reorder-only: leads with mode-relevant axes, NEVER drops/hides one (so gating axes always render)."""
import sys
from pathlib import Path

_SK = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_SK), str(_SK / "target-profile" / "scripts")]
import tp_render_md as R  # noqa: E402

_SHORTS = ["expression", "selectivity", "dependency", "mechanism", "genomic_alteration",
           "tractability_sm", "surface_modality", "safety"]


def test_cis_leads_with_genomic_dependency_tractability():
    out = R._mode_ordered_shorts(_SHORTS, {"dominant": "cis_feature"})
    assert out[:3] == ["genomic_alteration", "dependency", "tractability_sm"]
    assert set(out) == set(_SHORTS)                       # NOTHING dropped


def test_abundance_leads_with_surface_presence_selectivity_safety():
    out = R._mode_ordered_shorts(_SHORTS, {"dominant": "abundance"})
    assert out[0] == "surface_modality" and "safety" in out[:4]
    assert set(out) == set(_SHORTS)


def test_no_mode_or_insufficient_keeps_canonical_order():
    assert R._mode_ordered_shorts(_SHORTS, None) == _SHORTS
    assert R._mode_ordered_shorts(_SHORTS, {"dominant": "insufficient"}) == _SHORTS


def test_gating_axes_never_dropped_any_mode():
    """dependency + safety (gating axes) must survive every reorder — the never-collapse guarantee."""
    for mode in ("cis_feature", "abundance", "mixed", "dependency_relational"):
        out = R._mode_ordered_shorts(_SHORTS, {"dominant": mode})
        assert "dependency" in out and "safety" in out
        assert set(out) == set(_SHORTS)


def test_lead_axes_absent_from_run_are_skipped_cleanly():
    """A mode whose lead axis isn't in this run's shorts must not inject a phantom section."""
    partial = ["expression", "selectivity", "safety"]     # no genomic/dependency/tractability
    out = R._mode_ordered_shorts(partial, {"dominant": "cis_feature"})
    assert set(out) == set(partial) and len(out) == len(partial)
