"""Synthetic-data test of depmap-mutation-stratified (Card 3).

Builds synthetic CRISPRGeneEffect.csv + OmicsSomaticMutationsMatrixHotspot.csv +
OmicsSomaticMutationsMatrixDamaging.csv + Model.csv with a designed-in BRAF-
V600E-like signal: cells flagged as hotspot-mutant have strongly-dependent
Chronos (loc=-1.4); WT cells have non-essential Chronos (loc=-0.05). Expected
outcome: mutation_stratification_class == "mutant_strongly_dependent".

Mirrors Card 1+2+4 synthetic-test pattern. No S3 required.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
CONTRACTS_ROOT = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def _build_synthetic_depmap_dir(target_dir: Path, n_cell_lines: int = 250, mutant_fraction: float = 0.18) -> None:
    """Build synthetic DepMap files: CRISPRGeneEffect + hotspot matrix +
    damaging matrix + Model.csv. Designed-in BRAF-V600E-like signal.

    mutant_fraction = 0.18 matches the rough rate of activating-hotspot mutations
    across a pan-cancer cell-line panel for canonical oncogenes."""
    import numpy as np

    rng = np.random.default_rng(seed=42)

    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]
    n_mutant = int(mutant_fraction * n_cell_lines)
    is_mutant_pool = [True] * n_mutant + [False] * (n_cell_lines - n_mutant)
    rng.shuffle(is_mutant_pool)

    # Distribute lineages
    lineages = (
        ["Skin"] * int(0.20 * n_cell_lines)
        + ["Bowel"] * int(0.20 * n_cell_lines)
        + ["Lung"] * int(0.25 * n_cell_lines)
        + ["Pancreas"] * int(0.15 * n_cell_lines)
    )
    lineages += ["Breast"] * (n_cell_lines - len(lineages))
    rng.shuffle(lineages)

    # BRAF-V600E-like Chronos: mutant strongly dependent (-1.4 ± 0.25),
    # WT non-essential (-0.05 ± 0.20)
    braf_chronos = []
    for is_mut in is_mutant_pool:
        if is_mut:
            braf_chronos.append(float(rng.normal(loc=-1.4, scale=0.25)))
        else:
            braf_chronos.append(float(rng.normal(loc=-0.05, scale=0.20)))

    # CRISPRGeneEffect
    pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "BRAF (673)": braf_chronos,
            "EGFR (1956)": rng.normal(loc=-0.3, scale=0.4, size=n_cell_lines).tolist(),
        }
    ).to_csv(target_dir / "CRISPRGeneEffect.csv", index=False)

    # Hotspot matrix — boolean per (model, gene). Real DepMap uses string "True"/"False"
    # OR int 0/1 OR Python bool. We emit Python bool here; method's parser handles all 3.
    pd.DataFrame(
        {
            "SequencingID": [f"SQ-{i:06d}" for i in range(n_cell_lines)],
            "ModelConditionID": [f"MC-{i:06d}" for i in range(n_cell_lines)],
            "ModelID": cell_line_ids,
            "IsDefaultEntryForMC": ["Yes"] * n_cell_lines,
            "IsDefaultEntryForModel": ["Yes"] * n_cell_lines,
            "BRAF (673)": is_mutant_pool,
            "EGFR (1956)": [False] * n_cell_lines,
        }
    ).to_csv(target_dir / "OmicsSomaticMutationsMatrixHotspot.csv", index=False)

    # Damaging matrix — for synthetic test, make damaging strictly nested in hotspot
    # (every hotspot mutant also damaging, plus a few additional non-hotspot damaging).
    # This mirrors real biology imperfectly but stresses the dual-tier code path.
    extra_damaging = rng.choice(
        [i for i, m in enumerate(is_mutant_pool) if not m],
        size=min(5, n_cell_lines - n_mutant),
        replace=False,
    )
    is_damaging = list(is_mutant_pool)
    for idx in extra_damaging:
        is_damaging[idx] = True

    pd.DataFrame(
        {
            "SequencingID": [f"SQ-{i:06d}" for i in range(n_cell_lines)],
            "ModelConditionID": [f"MC-{i:06d}" for i in range(n_cell_lines)],
            "ModelID": cell_line_ids,
            "IsDefaultEntryForMC": ["Yes"] * n_cell_lines,
            "IsDefaultEntryForModel": ["Yes"] * n_cell_lines,
            "BRAF (673)": is_damaging,
            "EGFR (1956)": [False] * n_cell_lines,
        }
    ).to_csv(target_dir / "OmicsSomaticMutationsMatrixDamaging.csv", index=False)

    # Model.csv (basic)
    pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "CellLineName": [f"CL{i}" for i in range(n_cell_lines)],
            "OncotreeLineage": lineages,
        }
    ).to_csv(target_dir / "Model.csv", index=False)


def test_synthetic_braf_v600e_strong_stratification(tmp_path, monkeypatch):
    """End-to-end synthetic test: build BRAF-V600E-like data → method should classify
    as mutant_strongly_dependent."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()
    _build_synthetic_depmap_dir(fake_depmap, n_cell_lines=250, mutant_fraction=0.18)

    import sys

    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos_distribution.cli as c1cli
    import methods.depmap_mutation_dependency.cli as c3cli

    # Point BOTH loaders at the synthetic dir
    monkeypatch.setattr(c1cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])
    monkeypatch.setattr(c3cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    # Load chronos via Card 1's loader (reused)
    chronos, model_meta, errs = c1cli.load_depmap_files("26q1", "BRAF")
    assert errs == []
    assert len(chronos) == 250

    # Load mutation data
    hot, dam, mut_errs = c3cli.load_mutation_data("26q1", "BRAF")
    assert mut_errs == [], f"unexpected mutation load errors: {mut_errs}"
    assert len(hot) == 250, "hotspot matrix should cover all 250 model IDs"

    summary = c3cli.compute_mutation_stratification(chronos, hot, dam)

    # Card 3 spec assertions
    assert "mutation_stratification_class" in summary
    assert summary["mutation_stratification_class"] in (
        "mutant_strongly_dependent",
        "mutant_moderately_dependent",
        "wt_strongly_dependent",
        "not_mutation_stratified",
        "insufficient_mutation_rate",
        "data_unavailable",
    ), f"class outside vocabulary: {summary['mutation_stratification_class']!r}"

    # BRAF-V600E-like designed signal: expect strong mutant dependency
    assert summary["mutation_stratification_class"] == "mutant_strongly_dependent", (
        f"BRAF-V600E synthetic should classify as mutant_strongly_dependent; got {summary['mutation_stratification_class']!r}"
    )
    assert summary["delta_chronos_hotspot_mut_vs_wt"] < -0.5, (
        f"designed delta should be < -0.5; got {summary['delta_chronos_hotspot_mut_vs_wt']}"
    )
    assert summary["hotspot_mannwhitney_q"] < 0.01, (
        f"designed signal should be highly significant; got q={summary['hotspot_mannwhitney_q']}"
    )
    assert summary["n_hotspot_mutant"] == int(0.18 * 250)
    assert summary["n_hotspot_wildtype"] == 250 - int(0.18 * 250)

    # Figure emission
    out = tmp_path / "card_output"
    out.mkdir()
    c3cli.emit_plot_data(chronos, hot, dam, model_meta, out)
    c3cli.emit_mut_vs_wt_strip_plot(chronos, hot, dam, "BRAF", summary, out, CONTRACTS_ROOT)
    c3cli.emit_per_hotspot_chronos_plot(chronos, summary["per_hotspot_stats"], "BRAF", out, CONTRACTS_ROOT)
    c3cli.emit_manifest("BRAF", "MELANOMA", "26q1", summary, out, [])

    assert (out / "figure_mut_vs_wt_strip.svg").stat().st_size > 1000
    assert (out / "figure_per_hotspot_chronos.svg").stat().st_size > 500  # placeholder figure smaller
    assert (out / "plot_data.parquet").exists()

    pdf = pd.read_parquet(out / "plot_data.parquet")
    assert len(pdf) == 250
    assert {"cell_line_id", "chronos_score", "is_hotspot_mutant", "is_damaging_mutant", "is_any_mutant"}.issubset(
        pdf.columns
    )
    assert pdf["is_hotspot_mutant"].sum() == int(0.18 * 250)

    with (out / "manifest.yaml").open() as f:
        mani = yaml.safe_load(f)
    assert mani["method"] == "depmap-mutation-stratified"
    assert mani["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_synthetic_non_stratified_target(tmp_path, monkeypatch):
    """Negative-control: random mutation status with no mut-vs-WT Chronos difference
    should classify as not_mutation_stratified (or insufficient_mutation_rate if rate too low)."""
    fake_depmap = tmp_path / "depmap-26q1"
    fake_depmap.mkdir()

    import numpy as np

    rng = np.random.default_rng(seed=11)
    n_cell_lines = 250

    cell_line_ids = [f"ACH-{i:06d}" for i in range(n_cell_lines)]
    # Mutation status independent of Chronos
    is_mutant_pool = list(rng.random(n_cell_lines) < 0.15)
    # Chronos independent of mutation: pure noise around -0.3
    braf_chronos = rng.normal(loc=-0.3, scale=0.3, size=n_cell_lines).tolist()

    pd.DataFrame({"ModelID": cell_line_ids, "BRAF (673)": braf_chronos}).to_csv(
        fake_depmap / "CRISPRGeneEffect.csv", index=False
    )
    for mname in ("OmicsSomaticMutationsMatrixHotspot.csv", "OmicsSomaticMutationsMatrixDamaging.csv"):
        pd.DataFrame(
            {
                "SequencingID": [f"SQ-{i:06d}" for i in range(n_cell_lines)],
                "ModelConditionID": [f"MC-{i:06d}" for i in range(n_cell_lines)],
                "ModelID": cell_line_ids,
                "IsDefaultEntryForMC": ["Yes"] * n_cell_lines,
                "IsDefaultEntryForModel": ["Yes"] * n_cell_lines,
                "BRAF (673)": is_mutant_pool,
            }
        ).to_csv(fake_depmap / mname, index=False)
    pd.DataFrame(
        {
            "ModelID": cell_line_ids,
            "OncotreeLineage": ["Skin"] * n_cell_lines,
        }
    ).to_csv(fake_depmap / "Model.csv", index=False)

    import sys

    sys.path.insert(0, str(METHODS_REPO))
    import methods.depmap_chronos_distribution.cli as c1cli
    import methods.depmap_mutation_dependency.cli as c3cli

    monkeypatch.setattr(c1cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])
    monkeypatch.setattr(c3cli, "DEPMAP_LOCAL_FALLBACK_DIRS", [fake_depmap])

    chronos, _, _ = c1cli.load_depmap_files("26q1", "BRAF")
    hot, dam, _ = c3cli.load_mutation_data("26q1", "BRAF")
    summary = c3cli.compute_mutation_stratification(chronos, hot, dam)

    assert summary["mutation_stratification_class"] in ("not_mutation_stratified", "insufficient_mutation_rate"), (
        f"random data should NOT classify as mutant_strongly_dependent; got {summary['mutation_stratification_class']!r}"
    )
