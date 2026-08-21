"""Per-axis (strength, certainty) SIDECAR plumbing in the composed target-profile (CERTAINTY_MODEL):
  1. _load_sub_skill_certainty_fn returns functional-requirement's `_strength_certainty` hook, and
     None for a sub-skill that does not expose it (generic + opt-in, like the facet loader);
  2. _certainty_by_axis assembles only the present sidecars, keyed by sub-skill short, and is
     None-safe / empty until an axis opts in;
  3. the sidecar is VERDICT-INERT: it lives under a dedicated `certainty_by_axis` block, never inside
     the nomination `sub_verdicts`.
S3-free: pure over the loader + assembler + synthetic sub_results.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tp_fanout import _load_sub_skill_certainty_fn, _load_sub_skill_verdict_fn  # noqa: E402
from tp_facets import _certainty_by_axis  # noqa: E402


def test_certainty_loader_is_opt_in():
    # functional-requirement (the reference axis) supplies the hook
    _load_sub_skill_verdict_fn("functional-requirement")   # warm the module cache
    fn = _load_sub_skill_certainty_fn("functional-requirement")
    assert callable(fn)
    # a sub-skill without the hook returns None (loader never fabricates one)
    _load_sub_skill_verdict_fn("mechanism-and-pharmacology")
    assert _load_sub_skill_certainty_fn("mechanism-and-pharmacology") is None


def _cert(level="high"):
    return {"strength": "moderate_positive",
            "certainty": {"level": level, "coverage": "high", "corroboration": "high",
                          "unknown_mass": 0.0},
            "provenance": {}, "_model_ref": "CERTAINTY_MODEL.md#dependency"}


def test_certainty_by_axis_assembles_only_present_sidecars():
    sub_results = {
        "dependency": {"verdict": ("lineage_selective", "r"), "strength_certainty": _cert()},
        "expression": {"verdict": ("tumor_broadly_expressed", "r"), "strength_certainty": None},
        "selectivity": {"verdict": ("strong_tumor_selective", "r")},  # no key at all
    }
    out = _certainty_by_axis(sub_results)
    assert set(out) == {"dependency"}
    assert out["dependency"]["certainty"]["level"] == "high"


def test_certainty_by_axis_is_empty_and_none_safe_until_opt_in():
    assert _certainty_by_axis({}) == {}
    assert _certainty_by_axis({"dependency": {"strength_certainty": {}}}) == {}   # empty dict → skipped
    assert _certainty_by_axis({"x": {}}) == {}
    assert _certainty_by_axis(None) == {}


def test_sidecar_is_disjoint_from_sub_verdicts():
    """The sidecar must be its OWN block — never merged into `sub_verdicts` (CERTAINTY_MODEL:
    NOT in nomination sub_verdicts / GateVerdict / a shared carrier)."""
    sub_results = {"dependency": {"verdict": ("lineage_selective", "r"), "strength_certainty": _cert()}}
    out = _certainty_by_axis(sub_results)
    # the assembler returns a standalone {short: certainty} map; it does not touch the verdict tuple
    assert "verdict" not in out["dependency"]
    assert out["dependency"].keys() >= {"strength", "certainty"}
