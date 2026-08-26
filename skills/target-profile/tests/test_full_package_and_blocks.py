"""PR-4b — fold in --full-package + surface the coherence / data-package body blocks. Pins: the
coherence through-line block renders from target_coherence.v1; the data-package explorer renders under
--full-package; write_full_package emits per-sub-skill packages + a MANIFEST. Bedrock-free, no S3."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_fpb", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()
import tp_render_html as tph  # noqa: E402
import tp_manifest as tm      # noqa: E402

_LLM = {"executive_summary": {"value": "e"}, "overall_recommendation": {"value": "hold"},
        "confidence": {"value": "high"}, "tension_analysis": {"value": "t"}}


def _sr():
    return {"expression": {"skill_dir": "tumor-presence", "cards": [{"card_id": "rna", "summary": {"x": 1}}],
                           "verdict": ("tumor_broadly_expressed", "r"), "fired": []}}


def test_coherence_block_renders_from_target_coherence():
    tc = {"thesis": {"primary": "surface_antigen_no_dependency", "co_theses": [],
                     "reclassified_note": "genomic driver label is an artifact"},
          "coherence": {"class": "coherent_with_caveats",
                        "confirms": ["cis-uncoupled — coherent with antigen thesis"],
                        "caveats": ["non_dependent is expected for a surface antigen"],
                        "artifact_flags": ["genomic driver via mut-spectrum → data_artifact"]}}
    h = tph._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {}, target_coherence=tc)
    assert "id=s-coherence" in h
    assert "Surface antigen no dependency" in h or "surface_antigen_no_dependency" in h
    assert "Reclassified" in h and "data_artifact" in h


def test_no_coherence_block_without_target_coherence():
    h = tph._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {})
    assert "id=s-coherence" not in h


def test_data_package_block_only_under_full_package():
    h = tph._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {}, full_package=True)
    assert "id=s-data-package" in h and "evidence_package.json" in h
    assert "subskills/expression/package.json" in h
    h2 = tph._render_target_profile_html("KRAS", "COADREAD", _sr(), _LLM, {})   # default
    assert "id=s-data-package" not in h2


def test_hypothesis_edges_and_evidence_paths_render():
    doc = {"hypothesis": {"causal_rationale": {"statement": "s", "citations": []}, "go_forth": {}},
           "verdict": {"computed": "proposed"}, "uncertainty": {}, "defensibility": {},
           "edges": [{"type": "contradicts", "from_dimension": "combinatorial_dependency",
                      "to_dimension": "dependency", "rationale": "combo signal vs mono non-dependence"}],
           "evidence_paths": [{"claim": "KRAS dependency is mutant-confined", "citations": ["123"],
                               "path": ["genomic_alteration", "dependency"]}],
           "provenance": {"model_id": "m"}}
    hh = "".join(tph._render_hypothesis_html(doc))
    assert "Cross-dimension edges" in hh and "combinatorial_dependency" in hh and "contradicts" in hh
    assert "Evidence paths" in hh and "KRAS dependency is mutant-confined" in hh and "123" in hh


def test_write_full_package_emits_subskills_and_manifest(tmp_path):
    sr = {"expression": {"skill_dir": "tumor-presence",
                         "cards": [{"card_id": "rna", "card_version": "1", "summary": {"_data_source": "x"}}],
                         "verdict": ("tumor_broadly_expressed", "r"), "fired": [], "synthesis_facet": {}}}
    (tmp_path / "figures").mkdir()
    mpath = tm.write_full_package(tmp_path, target="KRAS", indication="COADREAD", sub_results=sr,
                                  skill_name="target-profile", skill_version="1.0", generated_at="t",
                                  subtypes=None, modality=None, has_figures=True,
                                  has_evidence_package=True, has_narrative=True)
    assert mpath.name == "MANIFEST.json" and mpath.exists()
    pkg = tmp_path / "subskills" / "expression" / "package.json"
    assert pkg.exists()
    d = json.loads(pkg.read_text())
    assert d["sub_skill"] == "expression" and d["verdict"] == "tumor_broadly_expressed"
    man = json.loads(mpath.read_text())
    assert man["bundle_type"] == "target-profile-full-package" and (tmp_path / "MANIFEST.md").exists()
