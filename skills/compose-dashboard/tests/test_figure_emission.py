"""Phase-2 figure-emission tests.

Verifies that when execute_run_plan / compose is called with an `out_path`,
each card whose card_id is registered in `_figure_emitters.CARD_FIGURE_EMITTERS`:
  - has SVG files written under <out_path>/cards/<card_id>/
  - has a `figures` list attached to its card_output entry
  - those figure paths are referenced verbatim in dashboard.md

This is the rendering counterpart to test_live_reader_chain.py — that test
verifies the dispatcher returns a summary; this test verifies that the
*figures alongside* get emitted when phase-2 is asked to.

Synthetic-data path: we monkeypatch the underlying method CLIs'
DEPMAP_LOCAL_FALLBACK_DIRS so the figure emitter loads a synthetic
CRISPRGeneEffect.csv + Model.csv rather than calling S3. This is the same
pattern Cards 1 and 2's unit tests use.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
SKILL_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(METHODS_REPO))


def _build_synthetic_depmap_dir(target_dir: Path, n_cell_lines: int = 200) -> None:
    """Build CRISPRGeneEffect.csv + Model.csv matching DepMap's OncotreeLineage
    categorical (Bowel, Lung, Pancreas, Stomach, Breast) so Card 2's COADREAD →
    Bowel lookup hits real data."""
    import numpy as np
    rng = np.random.default_rng(seed=42)

    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]
    n_bowel = int(0.25 * n_cell_lines)
    n_lung = int(0.25 * n_cell_lines)
    n_pancreas = int(0.20 * n_cell_lines)
    n_breast = int(0.15 * n_cell_lines)
    n_stomach = n_cell_lines - (n_bowel + n_lung + n_pancreas + n_breast)
    lineage_pool = (
        ["Bowel"] * n_bowel +
        ["Lung"] * n_lung +
        ["Pancreas"] * n_pancreas +
        ["Breast"] * n_breast +
        ["Stomach"] * n_stomach
    )
    rng.shuffle(lineage_pool)

    kras_chronos = []
    for lineage in lineage_pool:
        if lineage == "Bowel":
            kras_chronos.append(float(rng.normal(loc=-1.5, scale=0.2)))
        elif lineage == "Pancreas":
            kras_chronos.append(float(rng.normal(loc=-1.2, scale=0.25)))
        else:
            kras_chronos.append(float(rng.normal(loc=-0.1, scale=0.25)))

    crispr_df = pd.DataFrame({
        "ModelID": cell_line_ids,
        "KRAS (3845)": kras_chronos,
    })
    crispr_df.to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    model_df = pd.DataFrame({
        "ModelID": cell_line_ids,
        "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
        "OncotreeLineage": lineage_pool,
    })
    model_df.to_csv(target_dir / "Model.csv", index=False)


def test_card1_figure_emission(tmp_path, monkeypatch):
    """Directly exercise the figure-emission registry for Card 1."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=150)

    # Point Card 1's CLI loader at the synthetic dir
    import methods.depmap_chronos_distribution.cli as c1cli
    monkeypatch.setattr(c1cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="pan-cancer-crispr-dependency-distribution",
        summary={"some_summary_field": 123},
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert len(figs) >= 1, "Card 1 emitter returned no figures"
    primaries = [f for f in figs if f.get("primary")]
    assert len(primaries) >= 1, "Card 1 emitter returned no primary figure"

    for f in figs:
        full = out_root / f["path"]
        assert full.exists(), f"Figure missing on disk: {full}"
        assert full.stat().st_size > 500, f"Figure too small (likely empty): {full}"
        assert f["path"].startswith("cards/pan-cancer-crispr-dependency-distribution/")


def test_card2_figure_emission(tmp_path, monkeypatch):
    """Directly exercise the figure-emission registry for Card 2."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=200)

    import methods.depmap_chronos.cli as c2cli
    monkeypatch.setattr(c2cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="dependency-lineage-selectivity",
        summary={"lineage_label": "Bowel"},
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert len(figs) >= 1
    for f in figs:
        full = out_root / f["path"]
        assert full.exists()
        assert full.stat().st_size > 500


def _build_synthetic_depmap_dir_with_tpm(target_dir: Path, n_cell_lines: int = 200) -> None:
    """Same lineage layout as the Cards 1+2 helper but ALSO writes the TPM matrix
    that Card 4 needs. Includes the 5-metadata-column TPM schema."""
    import numpy as np
    rng = np.random.default_rng(seed=42)
    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]
    n_bowel = int(0.25 * n_cell_lines)
    n_lung = int(0.25 * n_cell_lines)
    n_pancreas = int(0.20 * n_cell_lines)
    n_breast = int(0.15 * n_cell_lines)
    n_stomach = n_cell_lines - (n_bowel + n_lung + n_pancreas + n_breast)
    lineage_pool = (
        ["Bowel"] * n_bowel + ["Lung"] * n_lung + ["Pancreas"] * n_pancreas
        + ["Breast"] * n_breast + ["Stomach"] * n_stomach
    )
    rng.shuffle(lineage_pool)

    kras_chronos = []
    kras_tpm = []
    for lineage in lineage_pool:
        if lineage == "Bowel":
            kras_chronos.append(float(rng.normal(loc=-1.5, scale=0.2)))
            kras_tpm.append(float(rng.normal(loc=6.5, scale=0.5)))
        elif lineage == "Pancreas":
            kras_chronos.append(float(rng.normal(loc=-1.2, scale=0.25)))
            kras_tpm.append(float(rng.normal(loc=6.0, scale=0.5)))
        else:
            kras_chronos.append(float(rng.normal(loc=-0.1, scale=0.25)))
            kras_tpm.append(float(rng.normal(loc=4.5, scale=0.8)))

    pd.DataFrame({
        "ModelID": cell_line_ids,
        "KRAS (3845)": kras_chronos,
    }).to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    pd.DataFrame({
        "SequencingID": [f"SQ-{i:06d}" for i in range(n_cell_lines)],
        "ModelConditionID": [f"MC-{i:06d}" for i in range(n_cell_lines)],
        "ModelID": cell_line_ids,
        "IsDefaultEntryForMC": ["Yes"] * n_cell_lines,
        "IsDefaultEntryForModel": ["Yes"] * n_cell_lines,
        "KRAS (3845)": kras_tpm,
    }).to_csv(target_dir / "OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv", index=False)

    pd.DataFrame({
        "ModelID": cell_line_ids,
        "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
        "OncotreeLineage": lineage_pool,
    }).to_csv(target_dir / "Model.csv", index=False)


def test_card4_figure_emission(tmp_path, monkeypatch):
    """Directly exercise the figure-emission registry for Card 4."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir_with_tpm(fake_depmap, n_cell_lines=200)

    import methods.depmap_expression_dependency.cli as c4cli
    monkeypatch.setattr(c4cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="expression-dependency-correlation",
        summary={"pearson_r": -0.42},  # non-error summary; emitter ignores content
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert len(figs) >= 1, "Card 4 emitter returned no figures"
    primary = [f for f in figs if f.get("primary")]
    assert primary, "Card 4 emitter returned no primary figure"
    assert any("scatter" in f["id"] for f in figs)

    for f in figs:
        full = out_root / f["path"]
        assert full.exists(), f"Figure missing on disk: {full}"
        assert full.stat().st_size > 500
        assert f["path"].startswith("cards/expression-dependency-correlation/")


def test_subtype_panel_figure_emission(tmp_path, monkeypatch):
    """Subtype-panel emitter: gated on subtype_axis_available, renders one row per stratum
    from the method's shared value reader (monkeypatched offline)."""
    import methods.tcga_gtex_expression_distribution.read as exprread
    monkeypatch.setattr(exprread, "read_tumor_subtype_values", lambda t, i: {
        "available": True, "pooled_median": 2.0, "assignment_manifest": "m",
        "pooled_values": [4.0] * 40 + [1.0] * 40,
        "strata": [
            {"stratum_id": "HI", "values": [4.0] * 40, "subtype_signal": "subtype_enriched",
             "evidence_state": "measured", "subgroup_n_floor_met": True, "n": 40, "median": 4.0},
            {"stratum_id": "LO", "values": [1.0] * 40, "subtype_signal": "subtype_depleted",
             "evidence_state": "measured", "subgroup_n_floor_met": True, "n": 40, "median": 1.0},
        ]})
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="tumor-rna-distribution-by-subtype",
        summary={"subtype_axis_available": True, "n_subtypes_measured": 2},
        out_root=out_root, target="MLH1", indication="COADREAD",
    )
    assert any(f.get("primary") for f in figs), "no primary subtype figure"
    assert any(f["id"] == "expression_distribution_subtype_panel" for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/tumor-rna-distribution-by-subtype/")


def test_q2_percentile_crossing_figure_emission(tmp_path, monkeypatch):
    """Q2 selectivity emitter reuses the tumor-vs-normal box; gated on selectivity_class."""
    import methods.tcga_gtex_expression_distribution.read as exprread
    monkeypatch.setattr(exprread, "read_tumor_samples", lambda t, i: [6.0, 6.5, 7.0] * 10)
    monkeypatch.setattr(exprread, "read_normal_samples", lambda t, i: ([1.0, 1.2] * 10, "COLON"))
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="tumor-vs-normal-percentile-crossing",
        summary={"selectivity_class": "strongly_tumor_enriched",
                 "normal_p95_log2tpm": 1.5, "fraction_tumor_above_normal_p95": 0.9},
        out_root=out_root, target="CEACAM5", indication="COADREAD")
    assert any(f.get("primary") for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/tumor-vs-normal-percentile-crossing/")
    # data_unavailable → no-op
    assert emit_figures_for_card(
        card_id="tumor-vs-normal-percentile-crossing",
        summary={"selectivity_class": "data_unavailable"},
        out_root=tmp_path / "o2", target="X", indication="BRCA") == []


def test_q3_normal_liability_figure_emission(tmp_path, monkeypatch):
    """Q3 liability atlas emitter (target-grain); gated on liability_class."""
    import methods.tcga_gtex_expression_distribution.read as exprread
    monkeypatch.setattr(exprread, "read_all_normal_tissues",
                        lambda t: {"BRAIN": [8.0] * 20, "SKIN": [0.2] * 20, "COLON": [0.1] * 20})
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="normal-tissue-liability-gtex",
        summary={"liability_class": "critical_organ_liability"},
        out_root=out_root, target="GFAP", indication="COADREAD")
    assert any(f["id"] == "normal_tissue_liability_atlas" for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/normal-tissue-liability-gtex/")
    assert emit_figures_for_card(
        card_id="normal-tissue-liability-gtex",
        summary={"liability_class": "data_unavailable"},
        out_root=tmp_path / "o3", target="GHOST", indication="COADREAD") == []


def test_q4_recommended_models_figure_emission(tmp_path, monkeypatch):
    """Q4 correspondence scatter; gated on correspondence_class. Monkeypatch the method readers."""
    import methods.tcga_gtex_expression_distribution.read as pt
    monkeypatch.setattr(pt, "read_tumor_samples", lambda t, i: [3.8, 4.0, 4.2] * 10)
    import methods.depmap_expression_dependency.cli as c4
    monkeypatch.setattr(c4, "load_depmap_files_for_card4", lambda release_pin, target_symbol: (
        {"M1": -2.0, "M2": 0.2}, {"M1": 4.1, "M2": 4.0},
        {"M1": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "B1"},
         "M2": {"OncotreeLineage": "Bowel", "StrippedCellLineName": "B2"}}, []))
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="recommended-models",
        summary={"correspondence_class": "well_modeled_in_lineage"},
        out_root=out_root, target="KRAS", indication="COADREAD")
    assert any(f["id"] == "recommended_models_scatter" for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/recommended-models/")
    assert emit_figures_for_card(
        card_id="recommended-models", summary={"correspondence_class": "data_unavailable"},
        out_root=tmp_path / "o4", target="X", indication="BRCA") == []


def test_q5_rna_protein_concordance_figure_emission(tmp_path, monkeypatch):
    """Q5 concordance scatter; gated on rna_as_biomarker. Monkeypatch the two per-model readers."""
    ids = [f"ACH-{i:04d}" for i in range(40)]
    rna = {m: float(i % 8) for i, m in enumerate(ids)}
    import methods.depmap_expression_dependency.cli as rna_cli
    monkeypatch.setattr(rna_cli, "load_depmap_files_for_card4",
                        lambda release_pin, target_symbol: ({}, rna, {}, []))
    import methods.depmap_protein_abundance.cli as prot_cli
    monkeypatch.setattr(prot_cli, "resolve_accession", lambda t, sidecar_path=None: "P00000")
    monkeypatch.setattr(prot_cli, "load_abundance_column",
                        lambda acc, matrix_path=None: ({m: rna[m] + 0.1 for m in ids}, len(ids)))
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="cellline-rna-protein-concordance",
        summary={"rna_as_biomarker": "adequate_proxy", "rna_protein_r": 0.99, "n_paired_models": 40},
        out_root=out_root, target="EGFR", indication="COADREAD")
    assert any(f["id"] == "rna_protein_concordance_scatter" for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/cellline-rna-protein-concordance/")
    assert emit_figures_for_card(
        card_id="cellline-rna-protein-concordance", summary={"rna_as_biomarker": "data_unavailable"},
        out_root=tmp_path / "o5", target="X", indication="COADREAD") == []


def test_q5_tumor_concordance_figure_emission(tmp_path, monkeypatch):
    """Q5 TUMOR concordance scatter; gated on rna_as_biomarker. Monkeypatch the matched-cohort reader."""
    import pandas as pd
    import methods.depmap_rna_protein_concordance.read as rpr
    rows = [{"patient_id": f"01CO{i:03d}", "gene": "CDX2",
             "rna_log2tpm": 3.0 + (i % 8) * 0.3, "protein_log2abundance": 3.0 + (i % 8) * 0.3 + 0.1}
            for i in range(40)]
    monkeypatch.setattr(rpr, "_read_matched_cohort", lambda cohort: pd.DataFrame(rows))
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="rna-protein-concordance-tumor",
        summary={"rna_as_biomarker": "adequate_proxy", "rna_protein_r": 0.99, "n_paired_tumors": 40},
        out_root=out_root, target="CDX2", indication="COADREAD")
    assert any(f["id"] == "rna_protein_concordance_tumor_scatter" for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/rna-protein-concordance-tumor/")
    assert emit_figures_for_card(
        card_id="rna-protein-concordance-tumor", summary={"rna_as_biomarker": "data_unavailable"},
        out_root=tmp_path / "o5t", target="X", indication="SKCM") == []


def test_alteration_role_figure_emission(tmp_path, monkeypatch):
    """alteration-role evidence card; gated on alteration_role. Monkeypatch the overlay loaders."""
    import methods.driver_role_overlay.read as dro
    dro._load_oncokb_roles.cache_clear() if hasattr(dro._load_oncokb_roles, "cache_clear") else None
    monkeypatch.setattr(dro, "_load_oncokb_roles", lambda: {"KRAS": "ONCOGENE"})
    import pandas as pd
    monkeypatch.setattr(dro, "_load_intogen_compendium", lambda: pd.DataFrame(
        [{"SYMBOL": "KRAS", "CANCER_TYPE": "COAD", "ROLE": "Act",
          "QVALUE_COMBINATION": 1e-30, "%_SAMPLES_COHORT": 0.4, "IS_DRIVER": True}],
        columns=["SYMBOL", "CANCER_TYPE", "ROLE", "QVALUE_COMBINATION", "%_SAMPLES_COHORT", "IS_DRIVER"]))
    from _figure_emitters import emit_figures_for_card
    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="alteration-role",
        summary={"alteration_role": "direct_driver_gof", "functional_direction": "activating",
                 "oncokb_gene_type": "ONCOGENE", "intogen_role": "Act", "intogen_scope": "indication",
                 "sources": ["oncokb", "intogen"]},
        out_root=out_root, target="KRAS", indication="COADREAD")
    assert any(f["id"] == "alteration_role_evidence_card" for f in figs)
    for f in figs:
        assert (out_root / f["path"]).exists()
        assert f["path"].startswith("cards/alteration-role/")
    assert emit_figures_for_card(
        card_id="alteration-role", summary={"alteration_role": "data_unavailable"},
        out_root=tmp_path / "oar", target="GHOST", indication="COADREAD") == []


def test_subtype_panel_no_op_when_axis_unavailable(tmp_path):
    """No landed shard for the indication → subtype_axis_available:false → emitter no-ops []."""
    from _figure_emitters import emit_figures_for_card
    figs = emit_figures_for_card(
        card_id="tumor-rna-distribution-by-subtype",
        summary={"subtype_axis_available": False},
        out_root=tmp_path / "compose_out", target="MLH1", indication="BRCA",
    )
    assert figs == []


def test_emitter_no_op_on_live_read_error(tmp_path):
    """If summary contains _live_read_error, emitter must return [] (no crash, no figures)."""
    from _figure_emitters import emit_figures_for_card

    out_root = tmp_path / "compose_out"
    figs = emit_figures_for_card(
        card_id="pan-cancer-crispr-dependency-distribution",
        summary={"_live_read_error": "s3_read_failed"},
        out_root=out_root,
        target="KRAS",
        indication="COADREAD",
    )

    assert figs == [], "Emitter should no-op on _live_read_error"
    assert not (out_root / "cards").exists(), \
        "No directory should be created when emitter no-ops"


def test_emitter_no_op_for_unregistered_card(tmp_path):
    """Cards without an emitter return [] without raising."""
    from _figure_emitters import emit_figures_for_card

    figs = emit_figures_for_card(
        card_id="some-card-with-no-emitter",
        summary={"x": 1},
        out_root=tmp_path,
        target="KRAS", indication="COADREAD",
    )
    assert figs == []


def test_dashboard_md_embeds_figure_references(tmp_path):
    """Renderer test: an evidence_package with figures on a card produces ![alt](path) in markdown."""
    sys.path.insert(0, str(SKILL_DIR.parent / "render-evidence-package" / "scripts"))
    from render_markdown import render_evidence_package

    ep = {
        "package_id": "ep-test",
        "framework_version": "2.0.0",
        "generated_at": "2026-06-29T00:00:00Z",
        "generated_by": "test",
        "context": {
            "target": {"symbol": "KRAS", "hgnc_id": 6407},
            "indication": {"oncotree_code": "COADREAD"},
            "scope": "cancer_type",
        },
        "governance": {
            "data_mode": "latest_approved",
            "release_pin": "26q1",
            "lockfile_ref": "lockfile.yaml",
            "validation_summary": {
                "n_cards_attempted": 1, "n_cards_passed": 1,
                "n_cards_passed_with_warnings": 0, "n_cards_failed": 0,
                "n_cards_excluded_by_applies_when": 0,
            },
        },
        "dashboard_spec_ref": "test",
        "cards": [{
            "card_id": "pan-cancer-crispr-dependency-distribution",
            "card_version": "1.0.0",
            "validation_state": "pass",
            "summary": {"distribution_shape": "bimodal_selective"},
            "interpretation_call": "selective dependency",
            "caveats": [],
            "provenance": {"method_calls": [], "input_manifest_ids": []},
            "figures": [
                {"id": "waterfall", "path": "cards/pan-cancer-crispr-dependency-distribution/figure_waterfall.svg",
                 "type": "waterfall_plot", "primary": True},
                {"id": "histogram_kde", "path": "cards/pan-cancer-crispr-dependency-distribution/figure_histogram_kde.svg",
                 "type": "histogram_kde", "primary": False},
            ],
        }],
        "synthesis": {"headline": "test", "caveats_summary": [], "modality_fit_assessment": []},
        "renderings": {"markdown": "renderings/dashboard.md"},
        "schema_version": 1,
    }

    md = render_evidence_package(ep)

    assert "![waterfall_plot](cards/pan-cancer-crispr-dependency-distribution/figure_waterfall.svg)" in md, \
        "Primary figure not embedded in markdown"
    assert "![histogram_kde](cards/pan-cancer-crispr-dependency-distribution/figure_histogram_kde.svg)" in md, \
        "Alternate figure not embedded in markdown"
    assert "<details><summary>Alternate views</summary>" in md, \
        "Alternate-views collapsible block missing"
