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

import contextlib
import sys
import unittest.mock as mock
from pathlib import Path
import textwrap

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import _live_readers  # noqa: E402
from _live_readers import _dispatch_adc_tce_modality_fit, _import_method  # noqa: E402
from compose_dashboard import _parse_existing_index  # noqa: E402
from _synthesis import synthesize, _build_headline  # noqa: E402


# ---------------------------------------------------------------------------
# HERMETICITY (2026-08-15): _dispatch_adc_tce_modality_fit performs FOUR live reads —
# _dispatch_surface_topology_and_ptm, _dispatch_surfaceome_family_classification,
# _dispatch_structure_features_static, AND methods.uniprot_gpi_anchor.read_gpi_anchor.
# The fit_class tests below only ever cared about topology+family; the gpi read had been
# left UNMOCKED and "passed" solely because the methods reader used to swallow a no-creds
# error to an empty dict (`... or {}`). Reader hardening now RE-RAISES creds/transient
# errors, so the unmocked read raises NoCredentialsError in a creds-less CI and the tests
# failed. This context manager mocks EVERY live read so no S3/creds access happens; gpi
# defaults to {} (no anchor) — exactly the empty result the swallowed-error path used to
# yield, so the fit_class assertions are unchanged.
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _mock_modality_upstream(topology: dict, family: dict | None = None, *, gpi: dict | None = None):
    gpi_mod = _import_method("uniprot_gpi_anchor")  # also guarantees methods repo is on sys.path
    with mock.patch.object(_live_readers, "_dispatch_surface_topology_and_ptm",
                           return_value=topology), \
         mock.patch.object(_live_readers, "_dispatch_surfaceome_family_classification",
                           return_value=(family if family is not None else _family())), \
         mock.patch.object(_live_readers, "_dispatch_structure_features_static",
                           return_value={}), \
         mock.patch.object(gpi_mod, "read_gpi_anchor",
                           return_value=({} if gpi is None else gpi)):
        yield


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
    with _mock_modality_upstream(topology, family):
        return _dispatch_adc_tce_modality_fit(target, "NSCLC")

def _family(is_surface=True) -> dict:
    return {"is_surface_protein": is_surface, "family_class": "RTK"}


def _fit_class(topology: dict, family: dict | None = None) -> str:
    """Extract fit_class by patching _dispatch_surface_topology_and_ptm etc."""
    with _mock_modality_upstream(topology, family):
        return _dispatch_adc_tce_modality_fit("GENE", "NSCLC")["fit_class"]


def test_both_viable_is_reachable():
    """A target with ADC topology AND low n_ubiq should be both_viable.

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
# E2b hardening (2026-08-12, adc-tce-modality-fit audit) — a COVERAGE GAP in EITHER required input
# (surfaceome-family OR topology) must resolve to data_unavailable, NOT neither_viable. Regression:
# tm_count/ec_length coalesce None→0, and the guard was `family_unavailable AND topology_unavailable`,
# so a target with an available family but data_unavailable topology fell through tm_count==0 →
# neither_viable — a coverage gap masquerading as a measured biologics no-go.
# ---------------------------------------------------------------------------

def test_topology_unavailable_is_data_unavailable_not_neither():
    """Topology product data_unavailable (tm/ec None) + family AVAILABLE → data_unavailable, NOT
    neither_viable. This is the demonstrated bug: without the `or` guard, tm_count coalesces to 0
    and the target reads as a hard biologics no-go rather than 'we couldn't look'."""
    topo = {"topology_class": "data_unavailable", "tm_pass_count": None,
            "extracellular_residue_count": None}
    result = _fit_class(topo, _family(is_surface=True))
    assert result == "data_unavailable", (
        f"topology data_unavailable + family available must be a coverage gap, got {result!r}")


def test_family_unavailable_is_data_unavailable_not_neither():
    """Symmetric case: family classification data_unavailable + topology available → data_unavailable.
    Without the family call we don't know surface-ness, so is_surface defaults False and WOULD hit
    neither_viable — a coverage gap, not a measured no."""
    result = _fit_class(_topo(tm=1, ec=250),
                        {"is_surface_protein": False, "family_class": "data_unavailable"})
    assert result == "data_unavailable", f"family data_unavailable must be a coverage gap, got {result!r}"


def test_both_products_available_measured_non_surface_still_neither():
    """Guard against over-firing the `or`: when BOTH products are available and the family call is a
    MEASURED non-surface (family_class present, is_surface False), the honest verdict is still
    neither_viable — a measured no, distinct from data_unavailable."""
    result = _fit_class(_topo(tm=0, ec=0), _family(is_surface=False))
    assert result == "neither_viable", (
        f"measured non-surface (both products present) must stay neither_viable, got {result!r}")


# ---------------------------------------------------------------------------
# GPI-anchor rescue (2026-08-09, modality-fit review M1) — TMbed 1D cannot see a GPI anchor, so a
# GPI-anchored antigen reads tm_count==0 and WAS false-negatived to neither_viable despite being a
# surface-displayed biologics target (FOLR1/Elahere approved ADC, MSLN, CD59). The curated UniProt
# LIPID GPI fact rescues it. These patch read_gpi_anchor to exercise the branch hermetically.
# ---------------------------------------------------------------------------

def _fit_gpi(topology, *, is_gpi, is_surface=True, target="GENE"):
    """fit_class with read_gpi_anchor patched to a chosen is_gpi_anchored."""
    with _mock_modality_upstream(topology, _family(is_surface=is_surface),
                                 gpi={"is_gpi_anchored": is_gpi}):
        return _dispatch_adc_tce_modality_fit(target, "NSCLC")


def test_gpi_anchored_rescued_from_neither_viable():
    """A GPI-anchored surface antigen at tm=0 with a real ECD is RESCUED (not neither_viable).
    MSLN-class: large ECD, no internalizing precedent → TCE_preferred (no cytoplasmic tail)."""
    out = _fit_gpi(_topo(tm=0, ec=587), is_gpi=True)
    assert out["fit_class"] != "neither_viable"
    assert out["fit_class"] == "TCE_preferred"
    assert out["is_gpi_anchored"] is True and out["gpi_surface_rescued"] is True


def test_gpi_anchored_adc_when_internalizing_precedent():
    """FOLR1-class: GPI + large ECD + curated internalizing-ADC precedent → both_viable (ADC survives)."""
    out = _fit_gpi(_topo(tm=0, ec=234), is_gpi=True, target="FOLR1")
    assert out["fit_class"] == "both_viable"
    assert out["gpi_surface_rescued"] is True


def test_gpi_small_ecd_not_adc():
    """CD59-class: GPI but small ECD (<200) + no precedent → TCE_preferred, NOT ADC (no default internalization)."""
    out = _fit_gpi(_topo(tm=0, ec=104), is_gpi=True)
    assert out["fit_class"] == "TCE_preferred"


def test_gpi_tiny_ecd_not_rescued():
    """A GPI flag with a sub-100 ECD is NOT rescued (no bindable epitope) → stays neither_viable."""
    out = _fit_gpi(_topo(tm=0, ec=40), is_gpi=True)
    assert out["fit_class"] == "neither_viable"
    assert out["gpi_surface_rescued"] is False


def test_non_gpi_tm0_still_neither_viable():
    """The rescue is GPI-GATED: a non-GPI tm=0 protein (intracellular) stays neither_viable."""
    out = _fit_gpi(_topo(tm=0, ec=300), is_gpi=False)
    assert out["fit_class"] == "neither_viable"
    assert out["gpi_surface_rescued"] is False


def test_gpi_does_not_disturb_normal_single_pass():
    """A normal single-pass target (tm=1) is unaffected by the GPI branch even if flagged GPI
    (CEACAM5-class: TMbed already gave it a TM → normal path, not the rescue)."""
    out = _fit_gpi(_topo(tm=1, ec=250, endo_hc=3, n_ubiq=3), is_gpi=True)
    assert out["gpi_surface_rescued"] is False        # tm=1 → normal path
    assert out["fit_class"] == "both_viable"


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
# ADC-reachability on the LIVE path (2026-08-06)
# The live topology product carries NO endocytosis/ubiquitination data (both None,
# _ptm_coverage=data_unavailable). Before B1, `endo_hc or 0` collapsed None→0, so an
# UNMEASURED field vetoed the ADC branch → ADC_preferred/both_viable were unreachable on
# every real target. These tests exercise the live (unmeasured) path the old mocks hid.
# ---------------------------------------------------------------------------

def test_adc_preferred_reachable_when_endocytosis_UNMEASURED():
    """TROP2-like single-pass, long-ECD, endocytosis UNMEASURED (None, the live
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


# ---------------------------------------------------------------------------
# C1 (2026-08-10 review fix) — applies_when-excluded cards must NOT count toward
# the "Insufficient evidence" headline override. An applies_when exclusion is
# routine subgroup gating (evidence-neutral), not evidence that the target is
# un-evaluable. Counting them flipped a strong verdict to "Insufficient evidence"
# on the default no-subgroup run (4 subgroup-gated optional cards all excluded).
# ---------------------------------------------------------------------------

def test_excluded_cards_do_not_trigger_insufficient_headline():
    """The default no-subgroup run excludes the 4 subgroup-gated optional cards via applies_when.
    With one strong informative card and NO non-informative CALLS, the headline must NOT be
    'Insufficient evidence' — the exclusions are routine gating, not missing evidence."""
    fit_assessment = [{"modality": "small molecule", "fit_level": "strong",
                       "decision_question": "Q", "primary_cards": []}]
    card_outputs = [
        {"card_id": "informative-1", "interpretation_call": "resolved cleanly with curated biology axis"},
        {"card_id": "sub-1", "excluded_by_applies_when": True},
        {"card_id": "sub-2", "excluded_by_applies_when": True},
        {"card_id": "sub-3", "excluded_by_applies_when": True},
        {"card_id": "sub-4", "excluded_by_applies_when": True},
    ]
    headline = _build_headline("KRAS", "COADREAD", fit_assessment, card_outputs)
    assert "Insufficient evidence" not in headline
    assert "KRAS" in headline


def test_three_noninformative_calls_still_trigger_insufficient():
    """The override still fires on GENUINELY non-informative calls (>=3), independent of exclusions —
    the fix narrows the count to real non-informative calls, it does not disable the guard."""
    fit_assessment = [{"modality": "small molecule", "fit_level": "strong",
                       "decision_question": "Q", "primary_cards": []}]
    card_outputs = [
        {"card_id": "n1", "interpretation_call": "not informative"},
        {"card_id": "n2", "interpretation_call": "not informative"},
        {"card_id": "n3", "interpretation_call": "not informative"},
        {"card_id": "sub-1", "excluded_by_applies_when": True},
    ]
    headline = _build_headline("KRAS", "COADREAD", fit_assessment, card_outputs)
    assert "Insufficient evidence" in headline
    assert "3 cards returned non-informative calls" in headline


# ---------------------------------------------------------------------------
# O1 (2026-08-15 safety fail-open) — a modality killer-veto card that CRASHED
# (availability_state read_error) or is UNWIRED (not_wired) is ABSENT from
# card_outputs, so its killer predicate would silently evaluate `card is None ->
# fired=False` and positive primary cards would score the modality VIABLE. An
# unavailable safety veto must instead mark the modality NON-CONCLUDABLE — a
# read_error / not_wired safety veto is never a pass.
# ---------------------------------------------------------------------------

def _run_plan_with_killer(modality: str, primary_cards: list[str], veto_card_id: str,
                          veto_message: str = "ESSENTIAL TISSUE LIABILITY") -> dict:
    """Minimal run_plan with one modality module carrying a killer condition on veto_card_id.
    resolved_axis='target-profile' is NOT in AXIS_GATE_MAP, so synthesis uses the fit_level lens
    path (not the resolver headline) — the exact path this fix hardens."""
    return {
        "axis_resolution": {"status": "resolved", "resolved_axis": "target-profile"},
        "input_context": {"target_symbol": "GENE", "indication": "NSCLC"},
        "loaded_modality_modules": [{
            "modality": modality,
            "synthesis_emphasis": {
                "primary_cards": primary_cards,
                "secondary_cards": [],
                "modality_killer_conditions": [{
                    "card_id": veto_card_id,
                    "predicate_type": "warning_id_fires",
                    "predicate_value": "essential_normal_tissue",
                    "message": veto_message,
                }],
            },
        }],
    }


def _positive_card(card_id: str) -> dict:
    # "strong protein surface evidence" is in _synthesis.POSITIVE_CALLS
    return _card_out(card_id, "strong protein surface evidence")


def test_killer_veto_card_read_error_marks_modality_non_concludable():
    """Two positive primary cards would score the modality 'strong', but the
    killer-veto (safety) card CRASHED (read_error) and is absent from card_outputs. The modality
    must be NON-CONCLUDABLE, never viable."""
    run_plan = _run_plan_with_killer(
        "bite_tce", ["surface-density-a", "surface-density-b"],
        veto_card_id="tvn-sc-normal-critical-organ")
    cards = [_positive_card("surface-density-a"), _positive_card("surface-density-b")]
    unavailable = [{"card_id": "tvn-sc-normal-critical-organ",
                    "availability_state": "read_error",
                    "availability_reason": "boom: reader crash"}]
    result = synthesize(run_plan, cards, contracts_root=None, unavailable_cards=unavailable)
    fit = result["modality_fit_assessment"][0]
    assert fit["fit_level"] == "non_concludable", (
        f"read_error safety veto must block the modality, got {fit['fit_level']!r}")
    assert fit["fit_level"] not in ("strong", "moderate", "weak"), "must not read as viable"
    assert fit["non_concludable_reasons"], "must record the blocked reason"
    assert "tvn-sc-normal-critical-organ" in result["caveats_summary"]
    assert "read_error" in result["caveats_summary"]


def test_killer_veto_card_read_error_without_fix_would_have_been_viable():
    """Explicit negative control: the SAME positive primaries WITHOUT any unavailable veto card
    score 'strong'. Proves the block above is caused by the unavailable safety card, not the
    fixture being weak."""
    run_plan = _run_plan_with_killer(
        "bite_tce", ["surface-density-a", "surface-density-b"],
        veto_card_id="tvn-sc-normal-critical-organ")
    cards = [_positive_card("surface-density-a"), _positive_card("surface-density-b")]
    # No unavailable cards at all → killer condition sees an absent card (card is None -> not fired),
    # so positives score it viable. This is the PRE-FIX behavior (still correct here: nothing signals
    # the card was un-readable). The fix only bites when the card is a known reasoned-absence.
    result = synthesize(run_plan, cards, contracts_root=None, unavailable_cards=[])
    fit = result["modality_fit_assessment"][0]
    assert fit["fit_level"] == "strong"


def test_killer_veto_card_not_wired_marks_modality_non_concludable():
    """The not_wired variant (dispatcher returned None): same block — an unwired safety veto is
    never a pass."""
    run_plan = _run_plan_with_killer(
        "bite_tce", ["surface-density-a", "surface-density-b"], veto_card_id="safety-veto")
    cards = [_positive_card("surface-density-a"), _positive_card("surface-density-b")]
    unavailable = [{"card_id": "safety-veto", "availability_state": "not_wired",
                    "availability_reason": "dispatcher_returned_none"}]
    result = synthesize(run_plan, cards, contracts_root=None, unavailable_cards=unavailable)
    fit = result["modality_fit_assessment"][0]
    assert fit["fit_level"] == "non_concludable"
    assert "not_wired" in result["caveats_summary"]


def test_present_clear_killer_card_does_not_block_modality():
    """Byte-stability guard: when the killer-veto card IS present and its predicate does NOT fire,
    positive primary cards still score the modality viable. The fix bites ONLY on unavailable
    veto cards, never on cleanly-read ones."""
    run_plan = _run_plan_with_killer(
        "bite_tce", ["surface-density-a", "surface-density-b"], veto_card_id="safety-veto")
    cards = [
        _positive_card("surface-density-a"),
        _positive_card("surface-density-b"),
        {"card_id": "safety-veto", "interpretation_call": "low normal-tissue liability",
         "excluded_by_applies_when": False, "summary": {}, "warning_ids": []},
    ]
    result = synthesize(run_plan, cards, contracts_root=None, unavailable_cards=[])
    fit = next(f for f in result["modality_fit_assessment"] if f["modality"] == "bite_tce")
    assert fit["fit_level"] == "strong", (
        f"clear veto + positives should be viable, got {fit['fit_level']!r}")
    assert not fit["non_concludable_reasons"]
