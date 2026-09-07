"""PR-1 — tp_figures orchestrator. Pins the ADDITIVE fix: the composed run now emits each sub-skill's
canonical headline HERO to figures/subskills/<short>/hero.svg (previously computed but only re-rendered
inline in HTML, never written as a file). Stubs the shared hero renderer (no matplotlib/S3). Verdict-inert."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(
    Path(__file__).resolve().parents[1], "tp_run_fig"
)  # bootstraps scripts/ + _skills_common onto sys.path
import tp_figures  # noqa: E402
import _skills_common.headline_hero as hh  # noqa: E402


def test_emit_subskill_heros_writes_file_per_headline_block(tmp_path, monkeypatch):
    monkeypatch.setattr(hh, "render_headline_hero_svg", lambda hero, t, i: "<svg id='hero'/>")
    sub_results = {
        "dependency": {"synthesis_facet": {"headline_block": {"hero": {"verdict": "lineage_selective"}}}},
        "mechanism": {"synthesis_facet": {"headline_block": {}}},  # headline_block w/o hero → skipped
        "safety": {"synthesis_facet": None},  # no facet → skipped
        "target_intrinsic": {},  # no synthesis_facet key → skipped
    }
    figdir = tmp_path / "figures"
    figdir.mkdir()
    out = tp_figures.emit_subskill_heros(sub_results, figdir, "KRAS", "COADREAD")
    assert out == {"dependency": "figures/subskills/dependency/hero.svg"}
    assert (figdir / "subskills" / "dependency" / "hero.svg").read_text() == "<svg id='hero'/>"
    assert not (figdir / "subskills" / "mechanism").exists()  # only sub-skills with a hero get a dir


def test_emit_subskill_heros_is_fail_open(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("hero render failed")

    monkeypatch.setattr(hh, "render_headline_hero_svg", boom)
    sub_results = {"dependency": {"synthesis_facet": {"headline_block": {"hero": {"v": 1}}}}}
    figdir = tmp_path / "figures"
    figdir.mkdir()
    out = tp_figures.emit_subskill_heros(sub_results, figdir, "KRAS", "COADREAD")
    assert out == {}  # a render failure contributes nothing and never raises


def test_resolve_figures_root_is_single_source(tmp_path):
    assert tp_figures.resolve_figures_root(tmp_path) == tmp_path / "figures"
