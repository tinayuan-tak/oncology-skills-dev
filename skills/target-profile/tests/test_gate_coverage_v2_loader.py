"""Backward-compatible gate_coverage loader (v1 flat `gates:` OR v2 three-list) — 2026-07-21.

PR-A of the gate-model 2.0.0 migration. The target-profile loader reads the target-contracts
`gate_coverage.yaml`. 2.0.0 restructures that file from a flat `gates:` list into three lists
(biology_gates / modality_fit / biomarker_facets), moves letters, and makes modality-fit gates
letterless. These tests pin that `_flatten_gate_coverage` + `_load_gate_coverage` handle BOTH
shapes and, critically, that the v2 flatten:
  - includes biology + modality_fit + sub_skill-grain facets as scorecard-row entries (as v1 did),
  - EXCLUDES card-grain biomarker_facets (they render in-section, never as their own greyed row),
  - tolerates letterless modality-fit rows (gate: None) without crashing the scorecard sort,
  - defaults a facet with no `grain:` to sub_skill (fail-open — a mis-tag becomes a visible row).

Bedrock-free: synthetic dicts + a written temp YAML; no S3, no live contract dependency.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_v2loader", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


# A synthetic 2.0.0 three-list contract (the shape PR-B will write). Deliberately minimal but
# structurally faithful: letters move (genomic_alteration→E "Altered"), modality-fit letterless,
# facets carry a grain.
_V2 = {
    "enum_id": "gate_coverage",
    "version": "2.0.0",
    "biology_gates": [
        {"short": "expression", "gate": "A", "gate_name": "Present", "band": "necessity", "axis": "biology"},
        {"short": "dependency", "gate": "C", "gate_name": "Required", "band": "necessity", "axis": "biology"},
        {"short": "genomic_alteration", "gate": "E", "gate_name": "Altered", "band": "necessity",
         "axis": "biology", "reports_into": ["dependency"]},
    ],
    "modality_fit": [
        {"short": "tractability_sm", "gate_name": "Small-molecule druggability", "band": "sufficiency",
         "axis": "modality_fit", "modality_relevance": ["small_molecule", "degrader"]},
        {"short": "safety", "gate_name": "Safety", "band": "sufficiency", "axis": "modality_fit"},
    ],
    "biomarker_facets": [
        # sub_skill grain → IS a scorecard row (as in v1)
        {"short": "synthetic_lethal_partners", "grain": "sub_skill", "role": "stratification",
         "reports_into": ["dependency"], "band": "necessity", "axis": "biology"},
        {"short": "subtype_fit", "grain": "sub_skill", "role": "stratification",
         "reports_into": ["dependency"], "band": "necessity", "axis": "biology"},
        # card grain → NOT a row (renders inside Required's section); carries card_id for the breadcrumb
        {"short": "mutation_stratified", "grain": "card", "card_id": "mutation-stratified-dependency",
         "role": "stratification", "reports_into": ["dependency"]},
        {"short": "crispr_rnai_concordance", "grain": "card", "card_id": "crispr-rnai-dependency-concordance",
         "role": "corroboration", "reports_into": ["dependency"]},
        # missing grain → fail-open to sub_skill (becomes a row, not silently dropped)
        {"short": "mystery_facet", "role": "corroboration", "reports_into": ["dependency"]},
    ],
}


# --- v2 flatten shape --------------------------------------------------------

def test_v2_flatten_includes_gates_and_sub_skill_facets():
    m = tp._flatten_gate_coverage(_V2)
    # biology + modality_fit gates present
    for s in ("expression", "dependency", "genomic_alteration", "tractability_sm", "safety"):
        assert s in m, s
    # sub_skill-grain facets present (they were v1 scorecard rows)
    assert "synthetic_lethal_partners" in m and "subtype_fit" in m


def test_v2_flatten_excludes_card_grain_facets():
    """card-grain facets surface INSIDE a gate section, never as their own scorecard row."""
    m = tp._flatten_gate_coverage(_V2)
    assert "mutation_stratified" not in m
    assert "crispr_rnai_concordance" not in m


def test_v2_flatten_missing_grain_defaults_to_row_fail_open():
    """A facet with no grain: must NOT silently vanish — it becomes a visible row (fail-open)."""
    m = tp._flatten_gate_coverage(_V2)
    assert "mystery_facet" in m


def test_v2_flatten_preserves_letter_moves_and_letterless():
    m = tp._flatten_gate_coverage(_V2)
    assert m["genomic_alteration"]["gate"] == "E"          # moved A→E "Altered"
    assert m["genomic_alteration"]["gate_name"] == "Altered"
    assert m["tractability_sm"].get("gate") is None         # modality-fit is letterless in v2
    assert m["safety"].get("gate") is None


# --- v1 flatten still works (the live shape today) ---------------------------

def test_v1_flat_shape_unchanged():
    v1 = {"version": "1.1.0", "gates": [
        {"short": "expression", "gate": "A", "band": "necessity", "axis": "biology"},
        {"short": "safety", "gate": "F", "band": "sufficiency", "axis": "modality_fit"}]}
    m = tp._flatten_gate_coverage(v1)
    assert set(m) == {"expression", "safety"}
    assert m["safety"]["gate"] == "F"


# --- loader end-to-end over a written 2.0.0 file -----------------------------

def test_loader_reads_v2_file_from_disk(tmp_path):
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "gate_coverage.yaml").write_text(yaml.safe_dump(_V2))
    baseline, source = tp._load_gate_coverage(tmp_path)
    assert source == "vocab"
    assert "dependency" in baseline and "mutation_stratified" not in baseline


def test_scorecard_sort_tolerates_letterless_v2_rows(tmp_path):
    """The whole point: a scorecard built from a v2 baseline must group biology-before-modality_fit
    and not crash on the letterless (gate=None) modality-fit rows."""
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "gate_coverage.yaml").write_text(yaml.safe_dump(_V2))
    sub_results = {"dependency": {"verdict": ("concordant_dependent", "r"), "cards": [{"card_id": "c"}],
                                  "fired": []},
                   "safety": {"verdict": ("highly_constrained_safety_concern", "r"),
                              "cards": [{"card_id": "c"}], "fired": []}}
    sc = tp._gate_scorecard(sub_results, None, contracts_repo=tmp_path)
    axes = [r["axis"] for r in sc]
    # biology rows all precede modality_fit rows (axis-primary sort)
    first_mf = axes.index("modality_fit") if "modality_fit" in axes else len(axes)
    assert all(a == "biology" for a in axes[:first_mf])
    # every row carries an axis; letterless rows are fine
    assert all(r.get("axis") in ("biology", "modality_fit") for r in sc)
    assert any(r.get("gate") is None for r in sc)   # the letterless modality-fit rows


# (The reports_into breadcrumb resolver tests were removed with the retirement of tp_render_html
# 2026-09-03: `_card_reports_into` + `_CARD_REPORTS_INTO_FALLBACK` lived in that renderer and had no
# other live consumer — report_render doesn't render reports-into breadcrumbs. Reintroducing that
# cross-gate breadcrumb is a report_render feature-parity item, tracked with the render owner.)
