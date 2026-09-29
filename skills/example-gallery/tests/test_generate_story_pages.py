"""generate_story_pages — pure integration test of `build_story_page` (decision.json already on
disk -> assemble_target_synthesis -> render_story_page), no subprocess / live tumor-presence run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
for p in (str(SKILLS), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import generate_story_pages as G  # noqa: E402

GOLDEN = SKILLS / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"


def test_build_story_page_from_an_existing_decision_json(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    decision = json.loads(GOLDEN.read_text())
    (run_dir / "decision.json").write_text(json.dumps(decision))

    page = G.build_story_page("EPCAM", "COADREAD", run_dir, decision)

    assert "EPCAM" in page
    assert "COADREAD" in page
    assert "L4 target story" in page


def test_flagship_roster_is_the_two_named_targets():
    pairs = {(f["target"], f["indication"]) for f in G.FLAGSHIPS}
    assert pairs == {("EPCAM", "COADREAD"), ("KRAS", "COADREAD")}


def test_run_tumor_presence_live_returns_none_on_missing_run_py(tmp_path, monkeypatch):
    """Never raises on a broken subprocess path — a failed live run is reported, not fatal."""
    monkeypatch.setattr(G, "SKILLS_DIR", tmp_path)  # no tumor-presence/scripts/run.py under here
    # run.py won't exist, so the subprocess call itself will fail fast (non-zero exit / FileNotFoundError
    # surfaced as a CalledProcessError-shaped failure is fine too) -- we only assert it degrades to None.
    out_dir = tmp_path / "out"
    result = None
    try:
        result = G.run_tumor_presence_live("EPCAM", "COADREAD", out_dir)
    except Exception as e:  # noqa: BLE001
        raise AssertionError(f"run_tumor_presence_live must not raise; got {type(e).__name__}: {e}")
    assert result is None
