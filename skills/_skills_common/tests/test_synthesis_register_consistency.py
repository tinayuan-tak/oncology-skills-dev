"""Cross-narrator invariant: publication register + deterministic metric legend.

Locks that ALL single-lens narrators (presence, selectivity, genomic, dependency) share the
publication-register discipline in their _SYSTEM prompt AND ship a deterministic METRIC_LEGEND
that attaches on a successful narration but NOT on a degraded {_synthesis_error} block. This keeps
the synthesis family consistent (the port that followed synthesis_dependency). Bedrock mocked.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

COMMON = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON.parent))  # skills/

from _skills_common import synthesis as P            # noqa: E402
from _skills_common import synthesis_selectivity as S  # noqa: E402
from _skills_common import synthesis_genomic as G     # noqa: E402
from _skills_common import synthesis_dependency as D   # noqa: E402
from _skills_common import synthesis_surface_modality as M  # noqa: E402
from _skills_common import synthesis_tractability_sm as T  # noqa: E402

# (module, synthesize_fn, a valid narration key for the mocked success)
NARRATORS = [
    (P, P.synthesize_presence, "expression_relevance_for_target"),
    (S, S.synthesize_selectivity, "selectivity_relevance_for_target"),
    (G, G.synthesize_genomic_alteration, "alteration_relevance_for_target"),
    (D, D.synthesize_dependency, "dependency_relevance_for_target"),
    (M, M.synthesize_surface_modality, "surface_modality_relevance_for_target"),
    (T, T.synthesize_tractability_sm, "tractability_relevance_for_target"),
]

_DECISION = {"target": "KRAS", "indication": "COADREAD", "headline": {}, "cards": []}
_BANNED = ["promising", "exciting", "compelling"]


@pytest.mark.parametrize("mod,fn,key", NARRATORS, ids=lambda x: getattr(x, "__name__", ""))
def test_system_prompt_carries_publication_register(mod, fn, key):
    sysp = mod._SYSTEM.lower()
    assert "publication" in sysp, f"{mod.__name__} missing publication-register instruction"
    # bans promotional language + requires a plain-language gloss
    assert "promotional" in sysp or "editorialis" in sysp
    assert "gloss" in sysp
    for w in _BANNED:
        assert w in sysp, f"{mod.__name__} should name banned word {w!r}"


@pytest.mark.parametrize("mod,fn,key", NARRATORS, ids=lambda x: getattr(x, "__name__", ""))
def test_system_prompt_carries_evidence_only_directive(mod, fn, key):
    """Every narrator must fence the LLM to the presented evidence (blinding-experiment 2026-08-09:
    the model imported prior knowledge of a named target beyond the data). The shared directive lives
    in _skills_common.llm.EVIDENCE_ONLY_DIRECTIVE and is appended to each _SYSTEM."""
    from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE
    assert EVIDENCE_ONLY_DIRECTIVE.strip() in mod._SYSTEM, \
        f"{mod.__name__}._SYSTEM missing the shared EVIDENCE_ONLY_DIRECTIVE"
    assert "evidence-only grounding" in mod._SYSTEM.lower()
    assert "prior knowledge" in mod._SYSTEM.lower()


def test_target_profile_system_prompt_carries_evidence_only_directive():
    import importlib.util
    from _skills_common.llm import EVIDENCE_ONLY_DIRECTIVE
    run_py = COMMON.parent / "target-profile" / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location("tp_run_reg", run_py)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert EVIDENCE_ONLY_DIRECTIVE.strip() in m._SYSTEM_PROMPT


def test_synthesize_temperature_is_optional_none_default():
    """Opus 4.8 DEPRECATES the temperature param (400 on any non-default). synthesize_structured must
    default temperature=None (not sent) so it never breaks the model; a caller may still set it for
    models that honour it. The _prompt_hash must distinguish set-vs-unset."""
    import inspect
    from _skills_common import llm
    assert inspect.signature(llm.synthesize_structured).parameters["temperature"].default is None
    # hash differs between unset and an explicit value (provenance visibility)
    h_default = llm._prompt_hash("s", "u", {"x": 1}, "m", None)
    h_zero = llm._prompt_hash("s", "u", {"x": 1}, "m", 0.0)
    assert h_default != h_zero
    assert h_default == llm._prompt_hash("s", "u", {"x": 1}, "m")  # None is the documented default


@pytest.mark.parametrize("mod,fn,key", NARRATORS, ids=lambda x: getattr(x, "__name__", ""))
def test_metric_legend_is_nontrivial_dict(mod, fn, key):
    assert isinstance(mod.METRIC_LEGEND, dict) and len(mod.METRIC_LEGEND) >= 4
    for k, v in mod.METRIC_LEGEND.items():
        assert isinstance(v, str) and len(v) > 40, f"{mod.__name__}:{k} legend too short"


@pytest.mark.parametrize("mod,fn,key", NARRATORS, ids=lambda x: getattr(x, "__name__", ""))
def test_legend_attaches_on_success(mod, fn, key):
    with patch("_skills_common.llm.synthesize_structured",
               return_value={key: {"value": "x", "_source": "llm_synthesized"}}):
        r = fn(_DECISION)
    assert r["metric_legend"] == mod.METRIC_LEGEND


@pytest.mark.parametrize("mod,fn,key", NARRATORS, ids=lambda x: getattr(x, "__name__", ""))
def test_legend_absent_on_error(mod, fn, key):
    with patch("_skills_common.llm.synthesize_structured",
               return_value={"_synthesis_error": "boom", "_note": "..."}):
        r = fn(_DECISION)
    assert "metric_legend" not in r
