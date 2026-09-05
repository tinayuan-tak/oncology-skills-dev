"""--full-package packaging: write_full_package emits per-sub-skill packages + a MANIFEST. Bedrock-free,
no S3.

(The coherence / data-package / hypothesis HTML body-block assertions that used to live here were removed
with the retirement of tp_render_html 2026-09-03 — the default html render path is report_render, covered
by its own suite. The renderer-agnostic packaging invariant below is retained.)"""
from __future__ import annotations

import json
from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_fpb")
import tp_manifest as tm      # noqa: E402


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
