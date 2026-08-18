"""Offline guards for the one-shot loop driver (tools/run_full_loop.py). No subprocess, no Bedrock:
asserts the pure command builders + the stage-1→stage-2 substrate bridge + --dry-run wiring."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_full_loop as L  # noqa: E402

PY = "python3"


def test_ground_cmd_skips_synthesis_and_threads_ground_indication():
    c = L.ground_cmd(PY, "KRAS", "COADREAD", Path("/o"), "engine", "colorectal cancer")
    assert "--ground" in c and c[c.index("--ground") + 1] == "engine"
    # grounding must NOT pay for Tier-3 synthesis or figures (cheap stage)
    assert "--no-synthesis" in c and "--no-figures" in c
    assert c[c.index("--ground-indication") + 1] == "colorectal cancer"
    assert c[c.index("--out") + 1] == str(Path("/o") / L.GROUND_DIR)
    # no ground-indication → flag omitted
    c2 = L.ground_cmd(PY, "KRAS", "COADREAD", Path("/o"), "all", None)
    assert "--ground-indication" not in c2 and c2[c2.index("--ground") + 1] == "all"


def test_collect_substrate_reads_grounded_files_axis_sorted(tmp_path):
    (tmp_path / "grounded_safety.json").write_text("{}")
    (tmp_path / "grounded_dependency.json").write_text("{}")
    (tmp_path / "other.json").write_text("{}")  # ignored — not a grounded_ record
    specs = L.collect_substrate(tmp_path)
    assert specs == [f"dependency={tmp_path/'grounded_dependency.json'}",
                     f"safety={tmp_path/'grounded_safety.json'}"]
    assert L.collect_substrate(tmp_path / "does-not-exist") == []


def test_hypothesis_cmd_wires_substrate_and_optionals():
    ep = Path("/o") / L.GROUND_DIR / "evidence_package.json"
    c = L.hypothesis_cmd(PY, ep, ["safety=/o/01-ground/grounded_safety.json"], Path("/o"),
                         "adc", Path("/d/dossier.json"), "ADC drug target")
    assert c[c.index("--evidence-package") + 1] == str(ep)
    assert "--substrate" in c and "safety=/o/01-ground/grounded_safety.json" in c
    assert c[c.index("--modality") + 1] == "adc"
    assert c[c.index("--target-dossier") + 1] == "/d/dossier.json"
    assert c[c.index("--objective") + 1] == "ADC drug target"
    assert c[c.index("--out") + 1] == str(Path("/o") / L.HYP_DIR)
    # no substrate/optionals → those flags absent (empty substrate must not emit a bare --substrate)
    c2 = L.hypothesis_cmd(PY, ep, [], Path("/o"), None, None, None)
    assert "--substrate" not in c2 and "--modality" not in c2 and "--target-dossier" not in c2


def test_render_cmd_reuses_grounded_dir_and_hypothesis():
    c = L.render_cmd(PY, "KRAS", "COADREAD", Path("/o"), "adc")
    # stage 3 must NOT re-ground — it reuses stage-1 records via --grounded-dir
    assert "--ground" not in c
    assert c[c.index("--grounded-dir") + 1] == str(Path("/o") / L.GROUND_DIR)
    assert c[c.index("--hypothesis") + 1] == str(Path("/o") / L.HYP_DIR / "hypothesis.json")
    assert c[c.index("--out") + 1] == str(Path("/o") / L.DASH_DIR)


def test_dry_run_prints_three_stages_and_runs_nothing(capsys, tmp_path):
    rc = L.main(["--target", "KRAS", "--indication", "COADREAD", "--out", str(tmp_path),
                 "--ground", "engine", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[1 GROUND]" in out and "[2 HYPOTHESIZE]" in out and "[3 RENDER]" in out
    # dry-run must not create the output root
    assert not (tmp_path / L.GROUND_DIR).exists()
