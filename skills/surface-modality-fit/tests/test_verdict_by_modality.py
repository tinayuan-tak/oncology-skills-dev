"""Tests for the per-modality-ARM decomposition (surface_modality_verdict_by_modality, 2026-09-01).

The one-word surface_modality_verdict packs the ADC-vs-TCE call into a compound token
(adc_preferred_tce_unsafe = ADC viable, TCE unsafe). _surface_verdict_by_modality projects the RESOLVED
token onto explicit {adc, bite_tce, antibody[, pmhc_tce]} arms so consumers need not string-parse it.

Pins the load-bearing properties:
  (1) EVERY resolver-emittable token is mapped (no token falls through to the all-insufficient default);
  (2) it is a pure PROJECTION of the resolved token → it CANNOT disagree with surface_modality_verdict
      (the byte-stable compressed label) and is verdict-inert;
  (3) the arm semantics match the resolver's design (bite_tce-only killer preserves ADC; pMHC promotion
      adds a supported pmhc_tce arm while the surface arms stay not_viable);
  (4) the arms ride in the headline_block hero payload (rendered surface), the 5 evidence axes untouched.
All pure (no S3).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))


def _load_run():
    run_path = SKILL_SCRIPTS / "run.py"
    spec = importlib.util.spec_from_file_location("smf_run_bymod", run_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_M = _load_run()


# ── (1) every resolver token maps (no silent default) ────────────────────────────────────────────
def test_every_resolver_token_is_mapped():
    """The set of mapped tokens must cover every verdict the surface_modality resolver can emit — the
    union of run.py's own strength buckets (which enumerate the vocab). A token missing from the map
    would silently project to all-insufficient (an honest but lossy fallback we must not hit blindly)."""
    resolver_tokens = (_M._SM_STRONG_POS | _M._SM_MOD_POS | _M._SM_WEAK_POS | _M._SM_NEG
                       | {t for t in _M._SM_NONE if t is not None})
    mapped = set(_M._VERDICT_ARMS)
    missing = resolver_tokens - mapped
    assert not missing, f"resolver tokens missing a per-modality-arm mapping: {sorted(missing)}"


def test_none_and_unknown_fall_back_to_insufficient_never_viable():
    for tok in (None, "some_future_token"):
        arms = _M._surface_verdict_by_modality(tok)
        assert arms == {"adc": "insufficient", "bite_tce": "insufficient", "antibody": "insufficient"}
        # the fallback NEVER fabricates a viable/preferred arm
        assert "viable" not in arms.values() and "preferred" not in arms.values()


# ── (2)+(3) arm semantics match the resolver design ──────────────────────────────────────────────
def test_bite_tce_only_killer_preserves_adc():
    # adc_preferred_tce_unsafe (CEACAM5-class): drops TCE on safety, PRESERVES ADC
    arms = _M._surface_verdict_by_modality("adc_preferred_tce_unsafe")
    assert arms["adc"] == "viable" and arms["bite_tce"] == "unsafe" and arms["antibody"] == "viable"


def test_both_viable_and_neither_viable_are_uniform():
    assert set(_M._surface_verdict_by_modality("both_viable").values()) == {"viable"}
    assert set(_M._surface_verdict_by_modality("neither_viable").values()) == {"not_viable"}


def test_pmhc_promotion_adds_supported_arm_but_surface_stays_not_viable():
    arms = _M._surface_verdict_by_modality("pmhc_tce_supported")
    assert arms["pmhc_tce"] == "supported"
    assert arms["adc"] == "not_viable" and arms["bite_tce"] == "not_viable" and arms["antibody"] == "not_viable"


def test_density_and_shed_hit_every_binder_arm():
    assert set(_M._surface_verdict_by_modality("surface_viable_density_caveated").values()) == {"caveated"}
    assert set(_M._surface_verdict_by_modality("shed_dominant_opposed").values()) == {"opposed"}


# ── (2) verdict-inert: projection is a pure function of the token, decoupled from fit_class ───────
def test_projection_is_pure_function_of_token():
    a = _M._surface_verdict_by_modality("adc_preferred_tce_unsafe")
    b = _M._surface_verdict_by_modality("adc_preferred_tce_unsafe")
    assert a == b and a is not b   # fresh dict per call, deterministic


# ── (4) the arms ride in the headline_block hero, evidence axes untouched ────────────────────────
def test_arms_surface_in_headline_block_hero():
    headline = {
        "surface_modality_verdict": "adc_preferred_tce_unsafe",
        "surface_modality_verdict_by_modality": _M._surface_verdict_by_modality("adc_preferred_tce_unsafe"),
        "fit_class": "both_viable",
        "driving_rule_id": "sc-normal-high-liability-bite-killer",
        "claim_vector": {k: {"signal": "strong", "corroboration": "high"} for k in
                         ("FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED")},
        "key_signals": {},
    }
    blk = _M._build_headline_block(headline)
    hero = blk["hero"]
    # evidence axes unchanged (the frozen 5)
    assert [a["key"] for a in hero["axes"]] == ["FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"]
    # arms present + legible in the hero payload
    assert hero["modality_arms"]["adc"] == "viable" and hero["modality_arms"]["bite_tce"] == "unsafe"
    # verdict.call stays the fit_class substrate call (byte-stable spine)
    assert blk["verdict"]["call"] == "both_viable"
