"""CERTAINTY_MODEL validators for the dependency reference axis + the fan-out SIDECAR hook.

  1. verdict → strength is TOTAL over the dependency resolver's verdict enum, and no real (positive
     or negative) call silently reads strength `none` — only the insufficient/underpowered family does.
  2. `_model_ref` names a doc that actually exists (a dangling pointer fails CI).
  3. `_strength_certainty` (the fan-out sidecar hook) reuses `_dependency_strength_certainty` (single
     source) — the hook and the direct computation cannot diverge.

S3-free: pure over the resolver spec + the FR module. Skips gracefully if target-contracts is absent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _test_support import load_run_py

_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
_CONTRACTS = _RUN.resolve().parents[3] / "rnd-computational-biology-oncology-target-contracts"

rc = load_run_py(_RUN.parent.parent, "fr_run_sidecar")


def _dependency_resolver_verdicts():
    """The full verdict enum the dependency resolver can emit, or None if target-contracts absent."""
    from _skills_common.resolver import load_resolver

    spec = load_resolver("dependency")
    if not spec:
        return None
    return {
        r["verdict"] for r in (spec.get("resolve") or []) if isinstance(r, dict) and isinstance(r.get("verdict"), str)
    }


def test_verdict_to_strength_is_total_over_resolver_enum():
    """Every dependency verdict maps to a strength; a real call is never silently
    `none` (which would under-report the axis). Only the insufficient/underpowered family is `none`."""
    verdicts = _dependency_resolver_verdicts()
    if verdicts is None:
        pytest.skip("dependency.resolver.yaml unavailable (target-contracts not checked out)")
    assert verdicts, "dependency resolver emitted no verdicts — spec load broken"
    for v in verdicts:
        s = rc._dependency_strength(v)
        assert isinstance(s, str) and s, f"_dependency_strength({v!r}) is not a strength string"
        if v in rc._DEP_INSUFF:
            assert s == "none", f"insufficient-family verdict {v!r} should map to 'none', got {s!r}"
        else:
            assert s != "none", (
                f"resolver verdict {v!r} maps to strength 'none' — a real dependency call is being "
                f"silently under-reported. Add it to the _DEP_* strength sets."
            )


def test_model_ref_points_at_an_existing_doc():
    """The `_model_ref` a certainty object carries must resolve to a real file."""
    cards = [{"card_id": "pan-cancer-crispr-dependency-distribution", "summary": {}}]
    ref = rc._dependency_strength_certainty(cards, "lineage_selective", "concordant_dependent")["_model_ref"]
    fname = ref.split("#", 1)[0]
    if not _CONTRACTS.is_dir():
        pytest.skip("target-contracts not checked out alongside")
    path = _CONTRACTS / "docs" / "design" / fname
    assert path.is_file(), f"_model_ref names {fname!r} but it is missing at {path}"


def test_sidecar_hook_reuses_single_source():
    """The fan-out hook `_strength_certainty(cards, fired, verdict_pair)` must equal the direct
    `_dependency_strength_certainty` computation — one source, so the sidecar can't drift."""
    cards = [
        {
            "card_id": "pan-cancer-crispr-dependency-distribution",
            "summary": {"n_cell_lines_evaluated": 40, "dependency_class": "strongly_selective"},
        },
        {"card_id": "cross-consortium-dependency", "summary": {"cross_consortium_class": "concordant_dependent"}},
    ]
    hook = rc._strength_certainty(cards, fired=None, verdict_pair=("lineage_selective", "r-x"))
    direct = rc._dependency_strength_certainty(cards, "lineage_selective", "concordant_dependent")
    assert hook == direct
    assert hook["certainty"]["corroboration"] == "high" and hook["strength"] == "moderate_positive"
