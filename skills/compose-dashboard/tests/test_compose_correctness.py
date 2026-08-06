"""Regression tests for compose-dashboard batch-3 correctness fixes.

C3 — _live_readers ADC/TCE both_viable branch permanently unreachable:
     adc_favorable requires endo_high_conf >= 3; tce_favorable requires
     endo_high_conf <= 2 — mutually exclusive, so both_viable never fires.

C4 — _synthesis fit_level="strong" assigned before primary_total_in_scope==0
     check — dominant-signal path can produce "strong" with zero cards in scope.

C5 — _parse_existing_index path cell format is [`path`](path/) — the parser
     strips backticks incorrectly, returning the literal string '[' on 2nd run.
"""
from __future__ import annotations

import sys
from pathlib import Path
import textwrap

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from _live_readers import _dispatch_adc_tce_modality_fit  # noqa: E402
from compose_dashboard import _parse_existing_index  # noqa: E402
from _synthesis import synthesize  # noqa: E402


# ---------------------------------------------------------------------------
# C3 — both_viable reachability
# ---------------------------------------------------------------------------

def _topo(tm=1, ec=200, endo_hc=None, n_ubiq=None) -> dict:
    """Topology fixture. endo_hc / n_ubiq default to None to mirror the LIVE product, which carries
    topology only (endocytosis + ubiquitination fields are hardcoded None, _ptm_coverage=
    data_unavailable). Pass explicit ints to exercise the MEASURED-endocytosis upgrade path."""
    return {
        "tm_pass_count": tm,
        "extracellular_residue_count": ec,
        "endocytosis_motif_count_high_confidence": endo_hc,
        "n_ubiquitination_sites": n_ubiq,
    }


def _fit(topology: dict, family: dict | None = None, target: str = "GENE") -> dict:
    """Full dispatcher return (not just fit_class) — for asserting endocytosis_confidence etc.
    `target` lets a test pass a curated internalizing-antigen symbol (B1 Rank-2)."""
    import unittest.mock as mock
    with mock.patch("_live_readers._dispatch_surface_topology_and_ptm", return_value=topology), \
         mock.patch("_live_readers._dispatch_surfaceome_family_classification",
                    return_value=(family or _family())), \
         mock.patch("_live_readers._dispatch_structure_features_static", return_value={}):
        return _dispatch_adc_tce_modality_fit(target, "NSCLC")

def _family(is_surface=True) -> dict:
    return {"is_surface_protein": is_surface, "family_class": "RTK"}


def _fit_class(topology: dict, family: dict | None = None) -> str:
    """Extract fit_class by patching _dispatch_surface_topology_and_ptm etc."""
    import unittest.mock as mock
    with mock.patch("_live_readers._dispatch_surface_topology_and_ptm",
                    return_value=topology), \
         mock.patch("_live_readers._dispatch_surfaceome_family_classification",
                    return_value=(family or _family())), \
         mock.patch("_live_readers._dispatch_structure_features_static",
                    return_value={}):
        return _dispatch_adc_tce_modality_fit("GENE", "NSCLC")["fit_class"]


def test_both_viable_is_reachable():
    """A target with ADC topology AND low n_ubiq should be both_viable (C3 regression).

    ADC (fixed): tm=1, ec>=200, endo_hc>=3  (n_ubiq >= 5 requirement removed)
    TCE (fixed): tm>=1, ec>=100, n_ubiq<=3  (endo_hc <= 2 requirement removed)
    Overlap is now possible: high endo + low n_ubiq satisfies both.
    """
    result = _fit_class(_topo(tm=1, ec=250, endo_hc=3, n_ubiq=3))
    assert result == "both_viable", (
        f"Expected both_viable for high-endo + low-ubiq topology, got {result!r}"
    )


def test_adc_preferred_when_high_n_ubiq():
    """High n_ubiq blocks TCE → ADC_preferred when endo high."""
    result = _fit_class(_topo(tm=1, ec=250, endo_hc=4, n_ubiq=6))
    assert result == "ADC_preferred", (
        f"High n_ubiq: expected ADC_preferred, got {result!r}"
    )


def test_tce_preferred_low_endo():
    """Low endo_hc, low n_ubiq → TCE_preferred."""
    result = _fit_class(_topo(tm=1, ec=150, endo_hc=1, n_ubiq=2))
    assert result == "TCE_preferred", f"Got {result!r}"


def test_neither_viable_when_not_surface():
    """Non-surface protein → neither_viable regardless of endo."""
    result = _fit_class(_topo(), _family(is_surface=False))
    assert result == "neither_viable"


# ---------------------------------------------------------------------------
# C4 — fit_level "strong" with zero cards in scope
# ---------------------------------------------------------------------------

def _run_plan_for(modality: str, primary_cards: list[str],
                  dominant_calls_by_card: dict | None = None) -> dict:
    """Minimal run_plan with one modality module."""
    return {
        "axis_resolution": {"status": "resolved", "resolved_axis": "target-profile"},
        "input_context": {"target_symbol": "GENE", "indication": "NSCLC"},
        "loaded_modality_modules": [{
            "modality": modality,
            "synthesis_emphasis": {
                "primary_cards": primary_cards,
                "secondary_cards": [],
                "modality_killer_conditions": [],
            },
        }],
    }


def _card_out(card_id: str, call: str, excluded: bool = False) -> dict:
    return {
        "card_id": card_id,
        "interpretation_call": call,
        "excluded_by_applies_when": excluded,
        "summary": {},
    }


def test_zero_in_scope_dominant_does_not_produce_strong():
    """When the sole primary card is excluded, fit_level must not be 'strong' (C4)."""
    run_plan = _run_plan_for("small_molecule", ["card-a"])
    cards = [_card_out("card-a", "dominant_call", excluded=True)]
    # Patch _build_dominant_calls_map to surface the dominant call
    import unittest.mock as mock
    with mock.patch("_synthesis._build_dominant_calls_map",
                    return_value={"card-a": {"dominant_call"}}):
        result = synthesize(run_plan, cards, contracts_root=None)
    fit = result["modality_fit_assessment"][0]
    assert fit["fit_level"] != "strong", (
        f"Expected fit_level != strong when all primaries excluded, got {fit['fit_level']!r}"
    )
    assert fit["fit_level"] == "insufficient_evidence", (
        f"Expected insufficient_evidence, got {fit['fit_level']!r}"
    )


def test_dominant_with_cards_in_scope_still_strong():
    """Dominant signal + 2 cards in scope should still produce strong (sanity)."""
    run_plan = _run_plan_for("small_molecule", ["card-a", "card-b"])
    cards = [
        _card_out("card-a", "dominant_call"),
        _card_out("card-b", "positive_call"),
    ]
    import unittest.mock as mock
    with mock.patch("_synthesis._build_dominant_calls_map",
                    return_value={"card-a": {"dominant_call"}}):
        result = synthesize(run_plan, cards, contracts_root=None)
    fit = result["modality_fit_assessment"][0]
    assert fit["fit_level"] == "strong", f"Got {fit['fit_level']!r}"


# ---------------------------------------------------------------------------
# C5 — _parse_existing_index path round-trip
# ---------------------------------------------------------------------------

def _make_index_md(paths: list[str]) -> str:
    """Minimal INDEX.md with the format compose_dashboard writes."""
    lines = [
        "# GENE — evidence-package index",
        "",
        "| Generated | Indication | Package | Path | Class calls | Headline |",
        "|---|---|---|---|---|---|",
    ]
    for i, p in enumerate(paths):
        lines.append(
            f"| 2026-08-01T00:00:00 | NSCLC | `pkg-{i}` | "
            f"[`{p}`]({p}/) | dep: high | A headline |"
        )
    lines.append("")
    return "\n".join(lines)


def test_path_round_trips_correctly(tmp_path):
    """Path cell [`rel/path`](rel/path/) must parse back to 'rel/path', not '[' (C5)."""
    idx = tmp_path / "INDEX.md"
    idx.write_text(_make_index_md(["GENE/NSCLC/pkg-0/20260801"]))
    rows = _parse_existing_index(idx)
    assert len(rows) == 1
    assert rows[0]["path"] == "GENE/NSCLC/pkg-0/20260801", (
        f"Path round-trip failed: got {rows[0]['path']!r}"
    )


def test_path_not_literal_bracket(tmp_path):
    """Specifically verify the '[' bug is gone."""
    idx = tmp_path / "INDEX.md"
    idx.write_text(_make_index_md(["some/deep/rel/path"]))
    rows = _parse_existing_index(idx)
    assert rows[0]["path"] != "[", "C5 regression: path still parsing to '['"


def test_multiple_rows_parse_correctly(tmp_path):
    """Multiple rows with different paths all round-trip."""
    paths = ["A/NSCLC/pkg1/2026", "B/CRC/pkg2/2026", "C/HNSC/pkg3/2026"]
    idx = tmp_path / "INDEX.md"
    idx.write_text(_make_index_md(paths))
    rows = _parse_existing_index(idx)
    assert len(rows) == 3
    parsed = {r["path"] for r in rows}
    assert parsed == set(paths), f"Path mismatch: {parsed} vs {set(paths)}"


# ---------------------------------------------------------------------------
# C3b — ADC-reachability on the LIVE path (B1 fix, 2026-08-06)
# The live topology product carries NO endocytosis/ubiquitination data (both None,
# _ptm_coverage=data_unavailable). Before B1, `endo_hc or 0` collapsed None→0, so an
# UNMEASURED field vetoed the ADC branch → ADC_preferred/both_viable were unreachable on
# every real target. These tests exercise the live (unmeasured) path the old mocks hid.
# ---------------------------------------------------------------------------

def test_adc_preferred_reachable_when_endocytosis_UNMEASURED():
    """The core B1 fix: TROP2-like single-pass, long-ECD, endocytosis UNMEASURED (None, the live
    product state) must reach ADC_preferred on topology — an unmeasured field cannot veto."""
    r = _fit(_topo(tm=1, ec=248, endo_hc=None, n_ubiq=None))  # TROP2-like ECD ~248
    assert r["fit_class"] in ("ADC_preferred", "both_viable"), (
        f"ADC arm must be reachable with unmeasured endocytosis, got {r['fit_class']!r}")
    # the gap is surfaced explicitly, not silently treated as a positive
    assert r["endocytosis_confidence"] == "unmeasured"


def test_measured_low_endocytosis_STILL_gates_adc():
    """Discipline check: when endocytosis IS measured and low (0), it legitimately gates the ADC
    arm (a measured negative, unlike an unmeasured gap) → not ADC_preferred."""
    r = _fit(_topo(tm=1, ec=250, endo_hc=0, n_ubiq=1))
    assert r["endocytosis_confidence"] == "low"
    assert r["fit_class"] != "ADC_preferred"   # measured-low endo correctly withholds the ADC upgrade
    # TCE arm still reachable (ec>=100, ubiq measured-low)
    assert r["fit_class"] == "TCE_preferred"


def test_measured_high_endocytosis_confirms_adc():
    """When endocytosis IS measured high (>=3), ADC is confirmed with high confidence (the upgrade)."""
    r = _fit(_topo(tm=1, ec=250, endo_hc=3, n_ubiq=6))  # high ubiq blocks TCE
    assert r["fit_class"] == "ADC_preferred"
    assert r["endocytosis_confidence"] == "high"


def test_endocytosis_confidence_field_always_emitted():
    """The card declares endocytosis_confidence; the dispatcher must always emit it (contract gap fix)."""
    for endo in (None, 0, 2, 5):
        r = _fit(_topo(tm=1, ec=250, endo_hc=endo, n_ubiq=None))
        assert "endocytosis_confidence" in r
    assert _fit(_topo(endo_hc=None))["endocytosis_confidence"] == "unmeasured"
    assert _fit(_topo(endo_hc=2))["endocytosis_confidence"] == "moderate"


# ---------------------------------------------------------------------------
# C3c — B1 Rank-2: curated clinical-ADC internalization signal
# ---------------------------------------------------------------------------

def test_curated_antigen_gets_clinically_internalizing_confidence():
    """A gene in internalizing_antigen_targets.yaml (e.g. TROP2/TACSTD2) with unmeasured topology
    endocytosis gets endocytosis_confidence='clinically_internalizing' (a measured-positive from
    clinical-ADC precedent), NOT 'unmeasured'."""
    r = _fit(_topo(tm=1, ec=248, endo_hc=None, n_ubiq=None), target="TACSTD2")
    assert r["endocytosis_confidence"] == "clinically_internalizing"
    assert r["fit_class"] in ("ADC_preferred", "both_viable")


def test_noncurated_target_stays_unmeasured():
    """A gene NOT in the vocab is unchanged — endocytosis_confidence stays 'unmeasured' (positive-only
    vocab; absence of ADC precedent is never marked non-internalizing)."""
    r = _fit(_topo(tm=1, ec=248, endo_hc=None, n_ubiq=None), target="NOVELGENE123")
    assert r["endocytosis_confidence"] == "unmeasured"


def test_curated_overrides_measured_low_endo_for_adc():
    """Edge where Rank-2 changes the CALL: a curated antigen with a MEASURED-low motif count would
    fail the >=3 motif gate, but clinical-ADC precedent satisfies the internalization requirement →
    ADC arm reachable. (Measured motif still sets confidence when present.)"""
    r = _fit(_topo(tm=1, ec=248, endo_hc=0, n_ubiq=6), target="TACSTD2")  # measured-low + high ubiq (blocks TCE)
    # measured motif present → confidence reflects the measurement ('low'), but the curated precedent
    # satisfies endo_ok so the ADC arm is reachable despite the low motif count.
    assert r["fit_class"] == "ADC_preferred"
