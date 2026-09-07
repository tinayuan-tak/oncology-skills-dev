"""_llm_synthesis is the fan-out hook a COMPOSED target-profile run calls to narrate the dependency
lens. It previously called `synthesize_dependency` — a bespoke narrator that was migrated to the generic
capsule engine and no longer exists — so a composed run raised NameError (swallowed by the fan-out's
best-effort wrapper → FR narration silently dead in the composed product). This pins that _llm_synthesis
routes through the SAME generic engine the standalone --synthesize path uses, without NameError, without
touching Bedrock (the narrator is stubbed).
"""

from __future__ import annotations

from pathlib import Path

from _skills_common import narrator_engine as NE
from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
fr = load_run_py(SCRIPTS.parent, "fr_run_narr")


def _cards():
    # Every card_id _headline reads must be present (get_card_field raises on an ABSENT card, returns
    # None on an empty summary), so seed the full CARDS set and populate the CRISPR arm.
    populated = {
        "pan-cancer-crispr-dependency-distribution": {
            "dependency_class": "common_essential",
            "median_chronos_panel": -2.7,
            "fraction_strongly_dependent": 0.98,
            "n_cell_lines_evaluated": 1538,
        },
        "pan-cancer-rnai-dependency-distribution": {"rnai_dependency_class": "common_essential"},
    }
    return [{"card_id": cid, "summary": populated.get(cid, {})} for cid in fr.CARDS]


def test_llm_synthesis_routes_through_generic_engine_no_nameerror(monkeypatch):
    captured = {}

    def _stub_narrate(decision, lens, model_id=None):
        captured["lens"] = lens.name
        captured["verdict"] = (decision.get("headline") or {}).get("dependency_verdict")
        return {"_stub": True, "relevance": "argues_against"}

    monkeypatch.setattr(NE, "narrate", _stub_narrate)
    fired = [{"rule_id": "pan-essential-killer", "verdict": "pan_essential_killer"}]
    out = fr._llm_synthesis(_cards(), fired, ("pan_essential_killer", "pan-essential-killer"), "PLK1", "COADREAD")
    assert out == {"_stub": True, "relevance": "argues_against"}  # no NameError; stub reached
    assert captured["lens"] == "functional-requirement"  # narrated through the FR lens
    assert captured["verdict"] == "pan_essential_killer"  # the resolved verdict was threaded


def test_no_dangling_synthesize_dependency_reference():
    # the migrated-away bespoke name must not be referenced as a callable anywhere in run.py source
    src = (SCRIPTS / "run.py").read_text()
    # allowed only in a comment describing the migration; never as a call `synthesize_dependency(`
    assert "synthesize_dependency(" not in src
