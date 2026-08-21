"""GALLERY-CONVERGENCE GUARD (figure Stage 3 acceptance criterion).

The example-gallery is the single human-facing review surface and calls emit_figures_for_card — it has
no plotting of its own. This guard asserts that, for a migrated card, emit_figures_for_card returns the
SAME figures as the method's render_from_plot_data, so the gallery / dashboard / subskill can never
fork. It also proves the OFFLINE path is taken (the live loader is monkeypatched to RAISE).

Add one case per card as it is repointed (Stage 3).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent            # skills/_skills_common
sys.path.insert(0, str(SKILL_DIR))                            # _skills_common on path → _figure_emitters
_AM = os.environ.get("ANALYSIS_METHODS_ROOT",
                     "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, _AM)

import _figure_emitters as fe  # noqa: E402
from methods.depmap_expression_distribution import cli as e3cli  # noqa: E402
from methods.depmap_expression_distribution.figures import render_from_plot_data  # noqa: E402
from methods.depmap_chronos_distribution import cli as chr_cli  # noqa: E402
from methods.depmap_chronos_distribution import figures as chr_fig  # noqa: E402
from methods.depmap_demeter_distribution import cli as rnai_cli  # noqa: E402
from methods.depmap_demeter_distribution import figures as rnai_fig  # noqa: E402
from methods.depmap_cn_distribution import cli as cn_cli  # noqa: E402
from methods.depmap_cn_distribution import figures as cn_fig  # noqa: E402
from methods.depmap_protein_abundance import cli as prot_cli  # noqa: E402
from methods.depmap_protein_abundance import figures as prot_fig  # noqa: E402
from methods.depmap_chronos import cli as chr2_cli  # noqa: E402  (card2 dependency-lineage-selectivity)
from methods.depmap_chronos import figures as chr2_fig  # noqa: E402
from methods.depmap_expression_dependency import cli as c4_cli  # noqa: E402  (card4)
from methods.depmap_expression_dependency import figures as c4_fig  # noqa: E402
from methods.depmap_crispr_rnai_concordance import cli as c1c_cli  # noqa: E402  (card1c)
from methods.depmap_crispr_rnai_concordance import figures as c1c_fig  # noqa: E402
from methods.depmap_mutation_dependency import cli as c3_cli  # noqa: E402  (card3)
from methods.depmap_mutation_dependency import figures as c3_fig  # noqa: E402
from methods.depmap_cis_dosage import cli as cis_cli  # noqa: E402  (cis-feature-expression-coherence)
from methods.depmap_cis_dosage import figures as cis_fig  # noqa: E402
from methods.tcga_gtex_expression_distribution import figures as tcga_fig  # noqa: E402
from methods.tcga_gtex_expression_distribution import read as tcga_read  # noqa: E402


def _write_tcga_per_sample(d):
    """Persist the tcga per-sample plot_data (group/source/log2_tpm) the offline render replays."""
    import pandas as pd
    d.mkdir(parents=True, exist_ok=True)
    rows = ([{"group": "tumor", "source": "TCGA", "log2_tpm": v}
             for v in (6.0, 6.3, 5.8, 6.5, 5.6, 6.1)]
            + [{"group": "normal", "source": "GTEx:Colon", "log2_tpm": v}
               for v in (1.2, 1.5, 0.9, 1.1, 1.3)])
    pd.DataFrame(rows, columns=["group", "source", "log2_tpm"]).to_parquet(
        d / "plot_data_expression_distribution.parquet", index=False)

_TCGA_SUMMARY = {"tumor_expression_class": "broadly_high", "selectivity_class": "strongly_tumor_enriched",
                 "normal_p95_log2tpm": 1.5, "fraction_tumor_above_normal_p95": 0.9,
                 "distribution_pattern": "unimodal_high"}


def _panel():
    tpm, meta = {}, {}
    for i, (lin, v) in enumerate([("Lung", 6.0), ("Lung", 6.3), ("Breast", 5.2),
                                  ("Breast", 5.0), ("Bowel", 0.3), ("Bowel", 0.5)], start=1):
        mid = f"ACH-{i:06d}"
        tpm[mid] = float(v)
        meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
    return tpm, meta


def _key(d):
    return (d["id"], d["type"], bool(d.get("primary")), bool(d.get("dynamic")))


def test_cellline_rna_distribution_gallery_convergence(tmp_path, monkeypatch):
    card_id = "cellline-rna-distribution"
    tpm, meta = _panel()
    summary = e3cli.compute_summary_stats(tpm, meta)

    # 1) persist plot_data exactly where the emitter reads it (figures/cards/<id>/)
    root = tmp_path / "figures"
    card_dir = root / "cards" / card_id
    card_dir.mkdir(parents=True)
    e3cli.emit_plot_data(tpm, meta, 1.0, card_dir)

    # 2) prove OFFLINE: the legacy live read must NOT be exercised
    monkeypatch.setattr(e3cli, "load_expression_files",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read — offline path not taken")))

    # 3) what the GALLERY sees (emit_figures_for_card) ...
    descs_emit = fe.emit_figures_for_card(card_id, summary, root, "MYGENE", "COADREAD")
    assert descs_emit, "offline emitter produced no figures"

    # ... must equal what render_from_plot_data produces directly (the single rendering path)
    direct = tmp_path / "direct"; direct.mkdir()
    e3cli.emit_plot_data(tpm, meta, 1.0, direct)
    descs_render = render_from_plot_data(direct / "plot_data_expression.parquet", summary, direct,
                                         "MYGENE", "COADREAD")

    assert [_key(d) for d in descs_emit] == [_key(d) for d in descs_render]
    prefix = f"cards/{card_id}/"
    assert all(d["path"].startswith(prefix) for d in descs_emit)          # emit prepends the card dir
    assert [d["path"][len(prefix):] for d in descs_emit] == [d["path"] for d in descs_render]


# --- Stage-3 repoint guards (chronos / rnai / cn / protein): one case per newly-migrated card. ------

def _assert_convergence(card_id, cli_mod, render_from_plot_data_fn, loader_name, parquet_name,
                        persist, summary, tmp_path, monkeypatch, target="MYGENE", indication="COADREAD"):
    """Shared body: emit_figures_for_card(card_id) must equal the method render_from_plot_data, and
    the OFFLINE path must be taken (the method's live loader is monkeypatched to RAISE). `persist`
    writes the plot_data parquet into the given dir."""
    root = tmp_path / "figures"
    card_dir = root / "cards" / card_id
    card_dir.mkdir(parents=True)
    persist(card_dir)

    monkeypatch.setattr(cli_mod, loader_name,
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read — offline path not taken")))

    descs_emit = fe.emit_figures_for_card(card_id, summary, root, target, indication)
    assert descs_emit, "offline emitter produced no figures"

    direct = tmp_path / f"direct_{card_id}"; direct.mkdir()
    persist(direct)
    descs_render = render_from_plot_data_fn(direct / parquet_name, summary, direct, target, indication)

    assert [_key(d) for d in descs_emit] == [_key(d) for d in descs_render]
    prefix = f"cards/{card_id}/"
    assert all(d["path"].startswith(prefix) for d in descs_emit)
    assert [d["path"][len(prefix):] for d in descs_emit] == [d["path"] for d in descs_render]


def _dep_panel(scores_by_lineage):
    by_model, meta = {}, {}
    i = 1
    for lin, vals in scores_by_lineage.items():
        for v in vals:
            mid = f"ACH-{i:06d}"
            by_model[mid] = float(v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
            i += 1
    return by_model, meta


def test_chronos_distribution_gallery_convergence(tmp_path, monkeypatch):
    chronos, meta = _dep_panel({"Lung": [-1.2, -1.4, -0.9, -1.1, -1.3],
                                "Breast": [-0.3, -0.1, -0.5, 0.0, -0.2],
                                "Bowel": [0.1, -0.05, 0.2, 0.0, 0.15]})
    summary = chr_cli.compute_summary_stats(chronos, meta)
    _assert_convergence(
        "pan-cancer-crispr-dependency-distribution", chr_cli, chr_fig.render_from_plot_data,
        "load_depmap_files", "plot_data.parquet",
        lambda d: chr_cli.emit_plot_data(chronos, meta, -1.0, d), summary, tmp_path, monkeypatch)


def test_rnai_distribution_gallery_convergence(tmp_path, monkeypatch):
    demeter, meta = _dep_panel({"Lung": [-0.7, -0.9, -0.6, -0.8, -0.75],
                                "Breast": [-0.2, -0.1, -0.3, 0.0, -0.15],
                                "Bowel": [0.05, -0.05, 0.1, 0.0, 0.08]})
    summary = rnai_cli.compute_summary_stats(demeter, meta)
    _assert_convergence(
        "pan-cancer-rnai-dependency-distribution", rnai_cli, rnai_fig.render_from_plot_data,
        "load_rnai_files", "plot_data_rnai.parquet",
        lambda d: rnai_cli.emit_plot_data(demeter, meta, -0.5, d), summary, tmp_path, monkeypatch)


def test_cn_distribution_gallery_convergence(tmp_path, monkeypatch):
    cn, meta = _dep_panel({"Breast": [3.2, 2.8, 3.5, 2.9, 3.0],
                           "Lung": [1.0, 1.1, 0.95, 1.05, 1.0],
                           "Bowel": [0.4, 0.35, 0.5, 0.42, 0.38]})
    summary = cn_cli.compute_summary_stats(cn, meta, assay_used="wes")
    _assert_convergence(
        "copy-number-distribution", cn_cli, cn_fig.render_from_plot_data,
        "load_cn_files", "plot_data_cn.parquet",
        lambda d: cn_cli.emit_plot_data(cn, meta, d), summary, tmp_path, monkeypatch)


def test_card2_lineage_selectivity_gallery_convergence(tmp_path, monkeypatch):
    # Stage-6 dependency family, card2. Bowel = the COADREAD lineage (the figure highlights it).
    chronos, meta = _dep_panel({"Bowel": [-1.2, -1.4, -0.9, -1.1, -1.3],
                                "Lung": [-0.6, -0.5, -0.7, -0.4, -0.55],
                                "Breast": [0.05, -0.1, 0.1, -0.05, 0.0]})
    _assert_convergence(
        "dependency-lineage-selectivity", chr2_cli, chr2_fig.render_from_plot_data,
        "load_depmap_files", "plot_data.parquet",
        lambda d: chr2_cli.emit_plot_data(chronos, meta, "", -1.0, d), {}, tmp_path, monkeypatch)


def test_card4_expression_dependency_gallery_convergence(tmp_path, monkeypatch):
    chronos, tpm, meta = {}, {}, {}
    i = 1
    for lin, rows in {"Bowel": [(-1.3, 6.0), (-1.1, 5.6), (-0.9, 5.0), (-1.2, 6.2), (-0.8, 4.8)],
                      "Lung": [(-0.4, 2.1), (-0.2, 1.8), (-0.5, 2.4), (-0.1, 1.2), (-0.3, 2.0)]}.items():
        for cv, tv in rows:
            mid = f"ACH-{i:06d}"; chronos[mid] = cv; tpm[mid] = tv
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}; i += 1
    summary = c4_cli.compute_correlation_summary(chronos, tpm, meta, indication="COADREAD")
    _assert_convergence(
        "expression-dependency-correlation", c4_cli, c4_fig.render_from_plot_data,
        "load_depmap_files_for_card4", "plot_data.parquet",
        lambda d: c4_cli.emit_plot_data(c4_cli.build_merged_data(chronos, tpm, meta, "Bowel"), d),
        summary, tmp_path, monkeypatch)


def test_card1c_concordance_gallery_convergence(tmp_path, monkeypatch):
    chronos = {"ACH-1": -1.2, "ACH-2": -0.9, "ACH-3": -0.3, "ACH-4": 0.1, "ACH-5": -1.0, "ACH-6": -0.6}
    demeter = {"ACH-1": -0.7, "ACH-2": -0.5, "ACH-3": -0.1, "ACH-4": 0.0, "ACH-5": -0.55, "ACH-7": -0.3}
    meta = {f"ACH-{i}": {"CCLEName": f"CL{i}", "OncotreeLineage": "Bowel"} for i in range(1, 8)}
    summary = c1c_cli.compute_concordance(chronos, demeter, meta)
    _assert_convergence(
        "crispr-rnai-dependency-concordance", c1c_cli, c1c_fig.render_from_plot_data,
        "load_concordance_inputs", "plot_data_concordance.parquet",
        lambda d: c1c_cli.emit_plot_data(summary["per_line_concordance"], d),
        summary, tmp_path, monkeypatch)


def test_card3_mutation_stratified_gallery_convergence(tmp_path, monkeypatch):
    chronos, hot, dam, meta = {}, {}, {}, {}
    i = 1
    for lin, (muts, wts) in {"Bowel": ([-1.4, -1.2, -1.3], [-0.2, -0.1]),
                             "Lung": ([-1.1, -1.3], [-0.3, 0.0, -0.1])}.items():
        for v in muts:
            mid = f"ACH-{i:06d}"; chronos[mid] = v; hot[mid] = True; dam[mid] = False
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}; i += 1
        for v in wts:
            mid = f"ACH-{i:06d}"; chronos[mid] = v; hot[mid] = False; dam[mid] = False
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}; i += 1
    _assert_convergence(
        "mutation-stratified-dependency", c3_cli, c3_fig.render_from_plot_data,
        "load_mutation_data", "plot_data.parquet",
        lambda d: c3_cli.emit_plot_data(chronos, hot, dam, meta, d), {}, tmp_path, monkeypatch)


def test_cis_dosage_gallery_convergence(tmp_path, monkeypatch):
    cn, tpm, meta = {}, {}, {}
    i = 1
    for lin, rows in {"Bowel": [(2.8, 5.6), (3.2, 6.0), (1.0, 3.1), (0.5, 2.0), (1.5, 4.2)],
                      "Lung": [(1.0, 3.0), (1.1, 3.2), (0.9, 2.8), (2.0, 4.8), (1.2, 3.4)]}.items():
        for cv, tv in rows:
            mid = f"ACH-{i:06d}"; cn[mid] = cv; tpm[mid] = tv
            meta[mid] = {"OncotreeLineage": lin, "CellLineName": f"CL{i}"}; i += 1
    summary = cis_cli.compute_cis_dosage(cn, tpm)
    _assert_convergence(
        "cis-feature-expression-coherence", cis_fig, cis_fig.render_from_plot_data,
        "load_cn_tpm_model", "plot_data.parquet",
        lambda d: cis_fig.emit_plot_data(cis_fig.build_merged_data(cn, tpm, meta), d),
        summary, tmp_path, monkeypatch)


def test_tumor_rna_distribution_gallery_convergence(tmp_path, monkeypatch):
    _assert_convergence(
        "tumor-rna-distribution", tcga_read, tcga_fig.render_from_plot_data,
        "read_tumor_samples", "plot_data_expression_distribution.parquet",
        _write_tcga_per_sample, dict(_TCGA_SUMMARY), tmp_path, monkeypatch)


def test_percentile_crossing_gallery_convergence(tmp_path, monkeypatch):
    _assert_convergence(
        "tumor-vs-normal-percentile-crossing", tcga_read, tcga_fig.render_from_plot_data,
        "read_tumor_samples", "plot_data_expression_distribution.parquet",
        _write_tcga_per_sample, dict(_TCGA_SUMMARY), tmp_path, monkeypatch)


def _write_tcga_atlas(d):
    import pandas as pd
    d.mkdir(parents=True, exist_ok=True)
    atlas = {"Liver": [5.5, 6.0, 5.8], "Brain": [0.5, 0.7], "Colon": [3.0, 3.2], "Lung": [1.2, 1.5]}
    rows = [{"tissue": t, "log2_tpm": float(v)} for t, vals in atlas.items() for v in vals]
    pd.DataFrame(rows, columns=["tissue", "log2_tpm"]).to_parquet(
        d / "plot_data_normal_tissue_atlas.parquet", index=False)


def test_normal_tissue_liability_gallery_convergence(tmp_path, monkeypatch):
    _assert_convergence(
        "normal-tissue-liability-gtex", tcga_read, tcga_fig.render_liability_from_plot_data,
        "read_all_normal_tissues", "plot_data_normal_tissue_atlas.parquet",
        _write_tcga_atlas, {"liability_class": "critical_organ_liability"}, tmp_path, monkeypatch)


def test_protein_abundance_gallery_convergence(tmp_path, monkeypatch):
    ab, lin = {}, {}
    for i, (lg, v) in enumerate([("Lung", 4.0), ("Lung", 4.3), ("Lung", 3.8), ("Lung", 4.1), ("Lung", 3.9),
                                 ("Breast", 2.0), ("Breast", 2.2), ("Breast", 1.8), ("Breast", 2.1),
                                 ("Breast", 1.9)], start=1):
        mid = f"ACH-{i:06d}"
        ab[mid] = float(v)
        lin[mid] = lg
    _assert_convergence(
        "cellline-protein-abundance", prot_cli, prot_fig.render_from_plot_data,
        "load_abundance_column", "plot_data_protein_abundance.parquet",
        lambda d: prot_cli.emit_plot_data_protein(ab, lin, d), {}, tmp_path, monkeypatch)
