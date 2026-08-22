"""Hermetic tests for _actionability_mode_facet — the verdict-inert cis_feature vs abundance vs
dependency_relational selection-basis profile (routes narrative emphasis; never changes the verdict).

Panel-based (avoids single-example overfit): clean-cis, clean-abundance, mixed (HER2-like), and the
relational cases the binary breaks on (TP53 LoF must NOT read cis). Also pins the honesty invariants:
unknown != none (a blind arm never cedes), and mixed forces when >=2 arms are dominant.
"""
import sys
from pathlib import Path

_SK = Path(__file__).resolve().parents[2]          # .../skills
sys.path[:0] = [str(_SK), str(_SK / "target-profile" / "scripts")]
import tp_facets as F  # noqa: E402


def _R(verdict=None, cardvals=()):
    return {"verdict": (verdict, "r") if verdict else None,
            "cards": [{"card_id": c, "summary": {f: v}} for (c, f, v) in cardvals]}


def _mode(sub_results):
    return F._actionability_mode_facet(sub_results)


def test_clean_cis_kras():
    s = {"genomic_alteration": _R("biomarker_stratified_dependency",
            [("alteration-role", "alteration_role", "direct_driver_gof"),
             ("mutation-hotspot-frequency", "pooled_driver_recurrence_class", "top_1pct")]),
         "surface_modality": _R("neither_viable", [("adc-tce-modality-fit", "fit_class", "neither_viable")])}
    m = _mode(s)
    assert m["dominant"] == "cis_feature"
    # abundance was MEASURED (neither_viable) → 'none' (measured-absent), NOT 'unknown' — the
    # unknown != none distinction: a present-but-negative card reads none, a missing card reads unknown.
    assert m["arms"]["cis_feature"] == "dominant" and m["arms"]["abundance"] == "none"


def test_clean_abundance_trop2():
    s = {"genomic_alteration": _R("passenger", [("alteration-role", "alteration_role", "passenger")]),
         "surface_modality": _R("adc_preferred", [("surface-abundance-density", "absolute_density_class", "high"),
                                                  ("adc-tce-modality-fit", "fit_class", "ADC_preferred")]),
         "selectivity": _R("strong_tumor_selective"), "dependency": _R("non_dependent")}
    m = _mode(s)
    assert m["dominant"] == "abundance"
    assert m["arms"]["abundance"] == "dominant"


def test_mixed_her2():
    s = {"genomic_alteration": _R("recurrent_amplification_driver",
            [("alteration-role", "alteration_role", "direct_driver_gof")]),
         "surface_modality": _R("both_viable", [("surface-abundance-density", "absolute_density_class", "high"),
                                               ("adc-tce-modality-fit", "fit_class", "both_viable")])}
    m = _mode(s)
    assert m["dominant"] == "mixed"                    # both cis + abundance dominant → mixed (HER2 guarantee)
    assert m["arms"]["cis_feature"] == "dominant" and m["arms"]["abundance"] == "dominant"


def test_lof_driver_routes_relational_not_cis_or_mixed():
    """TP53-like: a direct_driver_lof is NOT a positive cis handle — must be dependency_relational, NOT
    cis and NOT mixed (the binary-breaks-here case that motivated the third mode)."""
    s = {"genomic_alteration": _R("confirmed_driver", [("alteration-role", "alteration_role", "direct_driver_lof")]),
         "dependency": _R("non_dependent")}
    m = _mode(s)
    assert m["dominant"] == "dependency_relational"
    assert m["arms"]["cis_feature"] == "none"          # LoF suppressed from cis (can't target an absence)


def test_partner_conditional_is_relational():
    s = {"dependency": _R("partner_conditional_dependent"),
         "synthetic_lethal_partners": _R("has_experimental_sl_partner")}
    m = _mode(s)
    assert m["dominant"] == "dependency_relational"


def test_thin_signal_is_insufficient_low_confidence():
    m = _mode({})
    assert m["dominant"] == "insufficient" and m["confidence"] == "low"
    assert all(t == "unknown" for t in m["arms"].values())


def test_unknown_is_not_none_lowers_confidence():
    """A dominant cis call with a BLIND abundance arm stays confident-but-not-max and never reads the
    blind arm as 'none' (unknown != none)."""
    s = {"genomic_alteration": _R("biomarker_stratified_dependency",
            [("alteration-role", "alteration_role", "direct_driver_gof")])}  # no surface/selectivity read at all
    m = _mode(s)
    assert m["dominant"] == "cis_feature"
    assert m["arms"]["abundance"] == "unknown"         # NOT 'none'
    assert m["confidence"] == "moderate"               # downgraded from high by the unknown arm


def test_shape_is_wellformed():
    m = _mode({})
    for k in ("dominant", "secondary", "arms", "confidence", "derivation", "note"):
        assert k in m
    assert set(m["arms"]) == {"cis_feature", "abundance", "dependency_relational"}


# ── curated OVERRIDE ──────────────────────────────────────────────────────────────────────
def _cis_signals():
    return {"genomic_alteration": _R("biomarker_stratified_dependency",
            [("alteration-role", "alteration_role", "direct_driver_gof")])}


def test_curated_override_pins_mode_and_keeps_derived(monkeypatch):
    """A listed high-value dual (ERBB2) is pinned `mixed` even when the run derived only `cis_feature` —
    the collapse-guard. The derived call is retained for audit; source flags the override."""
    import tp_facets as F
    monkeypatch.setattr(F, "_actionability_mode_overrides",
                        lambda: {"ERBB2": {"mode": "mixed", "rationale": "amp is both cis + abundance"},
                                 "HER2": {"mode": "mixed", "rationale": "alias"}})
    m = F._actionability_mode_facet(_cis_signals(), target="ERBB2")
    assert m["dominant"] == "mixed" and m["derived_dominant"] == "cis_feature"
    assert m["source"] == "curated_override" and m["confidence"] == "high"
    # alias resolves too
    assert F._actionability_mode_facet(_cis_signals(), target="HER2")["dominant"] == "mixed"


def test_no_override_for_unlisted_target_is_pure_derived(monkeypatch):
    import tp_facets as F
    monkeypatch.setattr(F, "_actionability_mode_overrides", lambda: {"ERBB2": {"mode": "mixed"}})
    m = F._actionability_mode_facet(_cis_signals(), target="KRAS")
    assert m["dominant"] == "cis_feature" and m["source"] == "derived"
    assert m["derived_dominant"] == "cis_feature"


def test_override_graceful_skip_when_lookup_absent(monkeypatch):
    import tp_facets as F
    monkeypatch.setattr(F, "_actionability_mode_overrides", lambda: {})
    m = F._actionability_mode_facet(_cis_signals(), target="ERBB2")
    assert m["dominant"] == "cis_feature" and m["source"] == "derived"   # no lookup → pure derived
