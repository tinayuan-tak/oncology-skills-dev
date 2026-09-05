"""DETERMINISTIC panel-intersect-provenance caveat (verdict-INERT).

The read-time classifier assigns `cooccurrence_class` from q + log2-OR ALONE and never consults
`pooled_eligible`, so a panel-ABSENT target (0 panel-intersect-eligible pairs) can still surface a
`strong_cooccurring` pattern built entirely from per-source pairs — a TMB / gene-length artifact for a
large/passenger gene, live-observed for PCLO/COADREAD (strong_cooccurring, n_pairs_panel_intersect_eligible=0).
This skill now surfaces that provenance DETERMINISTICALLY (key_signals.caveat + headline top_tension)
instead of leaving it to LLM discretion. The differentiation VERDICT token is untouched (verdict-INERT),
and the caveat fires ONLY for panel-absent targets, so every panel-present target (incl. the KRAS/FBXW7
replay fixtures and CD19) is byte-identical.
"""
from __future__ import annotations

import copy
import json
import runpy
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


# ── the helper contract (panel-absent detection) ────────────────────────────────────────────────
def test_panel_absent_signal_fires_only_for_scanned_panel_absent_target():
    m = load_run_py(SKILL_DIR, "_diff_run_helpers")
    # panel-ABSENT but scanned (PCLO/COADREAD regime): eligible=0, per-source>0 → caveat fires
    cav = m._panel_absent_signal({"n_pairs_panel_intersect_eligible": 0, "n_pairs_per_source_only": 3961})
    assert cav and "panel-intersect" in cav and "3961" in cav
    ten = m._panel_absent_tension({"n_pairs_panel_intersect_eligible": 0, "n_pairs_per_source_only": 3961})
    assert ten and ten["source"] == "panel_intersect.absent" and ten["severity"] == 3 and ten["text"] == cav

    # panel-PRESENT target (KRAS-like): eligible>0 → NO caveat / NO tension
    assert m._panel_absent_signal({"n_pairs_panel_intersect_eligible": 1084, "n_pairs_per_source_only": 2278}) is None
    assert m._panel_absent_tension({"n_pairs_panel_intersect_eligible": 1084, "n_pairs_per_source_only": 2278}) is None

    # NOT-in-scan (data_unavailable regime): both 0 → NOT a panel-absent caveat (distinct failure mode)
    assert m._panel_absent_signal({"n_pairs_panel_intersect_eligible": 0, "n_pairs_per_source_only": 0}) is None

    # field-absent-safe: None counts must not raise and must not fire
    assert m._panel_absent_signal({}) is None
    assert m._panel_absent_signal({"n_pairs_panel_intersect_eligible": None,
                                   "n_pairs_per_source_only": None}) is None


# ── panel-present replay is byte-stable (the fixture the spine is frozen against) ─────────────────
def _replay(pair_id: str, target: str, indication: str) -> dict:
    fx = FIXTURES / f"{pair_id}.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx}")
    frozen = yaml.safe_load(fx.read_text()) or {}
    import _skills_common as skc

    def _factory():
        def _read_live(card_id, *a, **k):
            s = frozen.get(card_id)
            if not (isinstance(s, dict) and s and not s.get("_freeze_error")
                    and not s.get("_dispatcher_returned_none")):
                return None
            return copy.deepcopy(s)
        return _read_live

    out_dir = Path(tempfile.mkdtemp(prefix=f"diff-pa-{pair_id}-"))
    mp = pytest.MonkeyPatch()
    mp.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    mp.setattr(skc, "_import_dispatcher", _factory)
    mp.setattr(sys, "argv", ["run.py", "--target", target, "--indication", indication, "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None)
    finally:
        mp.undo()
    return json.loads((out_dir / "decision.json").read_text())


@pytest.mark.parametrize("pair_id,target", [("kras_coadread", "KRAS"), ("fbxw7_coadread", "FBXW7")])
def test_panel_present_fixture_carries_no_panel_absent_signal(pair_id, target):
    """KRAS/FBXW7 COADREAD are panel-present (n_pairs_panel_intersect_eligible > 0), so the panel-absent
    caveat must NOT fire: key_signals.caveat stays None and the top_tension (if any) is not the
    panel-absent flag — proving the fix is inert on the frozen spine."""
    h = (_replay(pair_id, target, "COADREAD").get("headline") or {})
    assert (h.get("n_pairs_panel_intersect_eligible") or 0) > 0, "fixture no longer panel-present — refreeze"
    assert (h.get("key_signals") or {}).get("caveat") is None, "panel-absent caveat leaked onto a panel-present target"
    tension = (h.get("headline_block") or {}).get("top_tension") or {}
    assert tension.get("source") != "panel_intersect.absent"
