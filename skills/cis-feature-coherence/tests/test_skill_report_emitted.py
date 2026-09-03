"""cis-feature-coherence emits the unified skill_report (Wave-3, INERT role → verdict-shaped but not a
call; polarity=not_scored)."""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR.parent))
def _load():
    spec = importlib.util.spec_from_file_location("cis_run_sr", SKILL_DIR / "scripts" / "run.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
cis = _load()
def _cards():
    return [{"card_id": c, "summary": {}} for c in cis.CARDS]
def test_cis_emits_inert_skill_report():
    hl = cis._headline(_cards(), [], ("expressed_cis_coupled_inert", "r"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict)
    assert sr["role"] == "inert" and sr["polarity"] == "not_scored"   # inert is never scored
    assert sr["call"] == hl.get("cis_coherence_verdict")              # verdict-shaped string, not a call
    assert "skill_report" in cis._SYNTHESIS_FACET_KEYS
