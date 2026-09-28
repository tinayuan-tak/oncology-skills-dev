"""Scorecard shard guard (#1992) — the COMMITTED target-intrinsic shard stays honest.

The shard (`scorecard/target-intrinsic.json`) is a committed artifact built by
`scripts/scorecard_adapter.py`; A0a's drift guard checks schema + render staleness but deliberately
never interprets adapter-owned evidence. This module supplies the adapter-side guards the exemplar
(#1988) promises siblings:

  1. every criterion the shard marks GREEN cites at least one test file that EXISTS in the tree —
     evidence naming a phantom test is a fabricated measurement;
  2. L2a/L2b/L3/L4 are all NOT_BUILT (this skill exports no source_properties/integrated_properties/
     l3d envelope) and carry no measured (non-NULL) criterion;
  3. accuracy is NULL everywhere (re-derivation is issue #2003, out of scope here) — never fabricated;
  4. the panel checks have TEETH: fed a doctored panel (every target emitting one constant class),
     `collect_panel_rows` reds its own checks — the GREEN is a live function of the package bytes.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import component_scorecard as cs  # noqa: E402

SHARD_PATH = REPO_ROOT / cs.SCORECARD_DIRNAME / "target-intrinsic.json"


def _load_adapter():
    spec = importlib.util.spec_from_file_location(
        "t1992_scorecard_adapter_under_test", SKILL_DIR / "scripts" / "scorecard_adapter.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shard_dict() -> dict:
    return json.loads(SHARD_PATH.read_text())


def test_shard_validates_and_l2_l3_l4_are_not_built():
    shard = cs.shard_from_dict(_shard_dict(), expected_skill="target-intrinsic")
    for layer in ("L2a", "L2b", "L3", "L4"):
        assert cs.cell_rollup(shard.cells[layer]) == cs.NOT_BUILT, f"{layer} must roll up NOT_BUILT"
        assert shard.cells[layer].built is False

    l1 = shard.cells["L1"]
    assert l1.built is True
    # accuracy is NULL per the brief (re-derivation is a separate issue, #2003) — never fabricated.
    assert l1.criteria["accuracy"].status == cs.NULL
    for c in ("utilization", "fail_open"):
        assert l1.criteria[c].status != cs.NULL, f"L1/{c} must be measured, not NULL"
    pc = l1.criteria["panel_consistency"]
    if pc.status == cs.NULL:
        assert (pc.evidence or {}).get("null_reason"), "a NULL panel criterion must carry a disposition note"


def test_every_green_criterion_cites_an_existing_test_file():
    """Evidence naming a phantom test is a fabricated measurement — resolve every cited path."""
    data = _shard_dict()
    checked = 0
    for layer, cell in data["cells"].items():
        for name, crit in cell["criteria"].items():
            if crit["status"] != cs.GREEN:
                continue
            ev = crit["evidence"] or {}
            cited = [ev["test"]] if "test" in ev else list(ev.get("tests", []))
            if name == "panel_consistency":
                continue  # panel evidence is package rows + computed checks, not test citations
            assert cited, f"GREEN {layer}/{name} cites no test at all"
            for entry in cited:
                rel = entry.split("::")[0].split(" ")[0]
                assert (REPO_ROOT / rel).exists(), f"GREEN {layer}/{name} cites missing file {rel}"
                checked += 1
    assert checked >= 4, f"suspiciously few citations checked ({checked}) — did the evidence shrink?"


def test_panel_checks_have_teeth_doctored_constant_panel_reds():
    """A degenerate panel (every target emitting the SAME class, no gap-shaped safety reads on
    HTR1D) must fail every non-vacuity check — proving `collect_panel_rows`'s checks are a live
    function of the package bytes, not a rubber stamp."""
    mod = _load_adapter()
    constant_row = {
        "status": "OK",
        "tdl_class": "Tclin",
        "modality_implication_class": "inhibitor_sufficient",
        "n_safety_legs_gap_shaped": 0,
        "n_safety_legs_measured": 6,
    }
    doctored = {
        target: {**constant_row, "target": target, "source": f"doctored/{target}/decision.json"}
        for target in mod.ROSTER
    }

    def fake_load_package(target, *, timeout=300):
        row = doctored[target]
        pkg = {
            "headline": {
                "tdl_class": row["tdl_class"],
                "modality_implication_class": row["modality_implication_class"],
                "gnomad_constraint_class": "moderately_constrained",
                "gene_burden_safety_class": "measured",
                "clinvar_pathogenic_class": "benign",
                "clingen_dosage_class": "no_evidence",
                "impc_ko_phenotype_class": "no_phenotype_reported",
                "mouse_ko_phenotype_class": "viable",
            }
        }
        return pkg, row["source"]

    mod._load_package = fake_load_package
    rows, checks = mod.collect_panel_rows()

    assert checks["all_roster_rows_present"] is True
    assert checks["tdl_class_not_constant"] is False
    assert checks["modality_implication_class_not_constant"] is False
    assert checks["thin_coverage_control_degrades"] is False
    assert checks["all_pass"] is False, "a constant, non-degrading doctored panel must NOT pass"
