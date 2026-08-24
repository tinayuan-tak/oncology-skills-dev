"""Factored claim-record SHADOW plumbing in the composed target-profile (M1;
VERDICT_REPRESENTATION_MIGRATION.md):
  1. _load_sub_skill_claim_record_fn returns a sub-skill's `_claim_record` hook (genomic +
     selectivity opt in today), and None for a sub-skill without it — generic + opt-in, exactly like
     the certainty loader;
  2. _claim_record_shadow_by_axis assembles only the present shadow records, keyed by sub-skill short,
     None-safe / empty until an axis opts in;
  3. the shadow is VERDICT-INERT: it lives under a dedicated `claim_record_shadow` block, never inside
     the nomination `sub_verdicts`.
S3-free: pure over the loader + assembler + synthetic sub_results.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent                       # skills/ — tp_fanout imports _skills_common
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_fanout import _load_sub_skill_claim_record_fn, _load_sub_skill_verdict_fn  # noqa: E402
from tp_facets import _claim_record_shadow_by_axis  # noqa: E402


def test_claim_record_loader_is_opt_in():
    for axis in ("genomic-alteration-profile", "tumor-selectivity"):
        _load_sub_skill_verdict_fn(axis)                 # warm the module cache
        assert callable(_load_sub_skill_claim_record_fn(axis)), f"{axis} should expose _claim_record"
    # a sub-skill without the hook returns None (loader never fabricates one)
    _load_sub_skill_verdict_fn("mechanism-and-pharmacology")
    assert _load_sub_skill_claim_record_fn("mechanism-and-pharmacology") is None


def test_loaded_hook_produces_a_schema_shaped_record():
    _load_sub_skill_verdict_fn("tumor-selectivity")
    fn = _load_sub_skill_claim_record_fn("tumor-selectivity")
    rec = fn([], fired=[], verdict_pair=("data_unavailable", None))
    assert rec["axis"] == "selectivity"
    assert set(rec["finding"]) == {"state", "direction", "magnitude", "availability"}
    assert rec["finding"]["state"] == "unknown"          # open-world invariant honored end-to-end


def test_assembler_collects_present_and_skips_absent():
    sub_results = {
        "genomic_alteration": {"claim_record_shadow": {"axis": "genomic_alteration", "finding": {}}},
        "selectivity": {"claim_record_shadow": {"axis": "selectivity", "finding": {}}},
        "mechanism": {"claim_record_shadow": None},       # opted out
        "safety": {},                                     # key entirely absent
    }
    out = _claim_record_shadow_by_axis(sub_results)
    assert set(out) == {"genomic_alteration", "selectivity"}


def test_assembler_none_safe():
    assert _claim_record_shadow_by_axis({}) == {}
    assert _claim_record_shadow_by_axis(None) == {}
