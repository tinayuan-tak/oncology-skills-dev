"""DESCRIPTOR-PARITY GUARD (figure Stage 5 acceptance criterion).

For each OFFLINE-MIGRATED distribution card, assert that the descriptors emit_figures_for_card
produces (id + type + primary) match EXACTLY the card contract's declared `figures:` spec in
target-contracts. This is the machine-check that the emitted figure metadata cannot drift from the
card's declared figure spec — closing the gap the existence-only validator left. Static (non-dynamic)
descriptors only; the interactive plotly twins are additive and are not declared in the card
`figures:` list.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/_skills_common
sys.path.insert(0, str(SKILL_DIR))  # _skills_common on path → _figure_emitters
_AM = os.environ.get(
    "ANALYSIS_METHODS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods"
)
sys.path.insert(0, _AM)
_TC = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

import _figure_emitters as fe  # noqa: E402
from methods.depmap_expression_distribution import cli as e3cli  # noqa: E402
from methods.depmap_chronos_distribution import cli as chr_cli  # noqa: E402
from methods.depmap_demeter_distribution import cli as rnai_cli  # noqa: E402
from methods.depmap_cn_distribution import cli as cn_cli  # noqa: E402
from methods.depmap_protein_abundance import cli as prot_cli  # noqa: E402


def _find_figures(node) -> list:
    """Locate the card contract's `figures:` list (a list of dicts carrying id+type), wherever it is
    nested in the card document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "figures" and isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0]:
                return v
            found = _find_figures(v)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_figures(item)
            if found:
                return found
    return []


def _card_declared(card_id: str) -> set:
    doc = yaml.safe_load((_TC / "cards" / f"{card_id}.card.yaml").read_text())
    figs = _find_figures(doc)
    assert figs, f"{card_id}.card.yaml declares no figures: block"
    return {(f["id"], f["type"], bool(f.get("primary"))) for f in figs}


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


# (card_id, fixture_builder) — builder(root_card_dir) persists plot_data there and returns the summary.
def _expr_fixture(card_dir):
    tpm, meta = {}, {}
    for i, (lin, v) in enumerate(
        [("Lung", 6.0), ("Lung", 6.3), ("Breast", 5.2), ("Breast", 5.0), ("Bowel", 0.3), ("Bowel", 0.5)], start=1
    ):
        mid = f"ACH-{i:06d}"
        tpm[mid] = float(v)
        meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
    e3cli.emit_plot_data(tpm, meta, 1.0, card_dir)
    return e3cli.compute_summary_stats(tpm, meta)


def _chronos_fixture(card_dir):
    chronos, meta = _dep_panel(
        {
            "Lung": [-1.2, -1.4, -0.9, -1.1, -1.3],
            "Breast": [-0.3, -0.1, -0.5, 0.0, -0.2],
            "Bowel": [0.1, -0.05, 0.2, 0.0, 0.15],
        }
    )
    chr_cli.emit_plot_data(chronos, meta, -1.0, card_dir)
    return chr_cli.compute_summary_stats(chronos, meta)


def _rnai_fixture(card_dir):
    demeter, meta = _dep_panel(
        {
            "Lung": [-0.7, -0.9, -0.6, -0.8, -0.75],
            "Breast": [-0.2, -0.1, -0.3, 0.0, -0.15],
            "Bowel": [0.05, -0.05, 0.1, 0.0, 0.08],
        }
    )
    rnai_cli.emit_plot_data(demeter, meta, -0.5, card_dir)
    return rnai_cli.compute_summary_stats(demeter, meta)


def _cn_fixture(card_dir):
    cn, meta = _dep_panel(
        {
            "Breast": [3.2, 2.8, 3.5, 2.9, 3.0],
            "Lung": [1.0, 1.1, 0.95, 1.05, 1.0],
            "Bowel": [0.4, 0.35, 0.5, 0.42, 0.38],
        }
    )
    cn_cli.emit_plot_data(cn, meta, card_dir)
    return cn_cli.compute_summary_stats(cn, meta, assay_used="wes")


def _protein_fixture(card_dir):
    ab, lin = {}, {}
    for i, (lg, v) in enumerate(
        [
            ("Lung", 4.0),
            ("Lung", 4.3),
            ("Lung", 3.8),
            ("Lung", 4.1),
            ("Lung", 3.9),
            ("Breast", 2.0),
            ("Breast", 2.2),
            ("Breast", 1.8),
            ("Breast", 2.1),
            ("Breast", 1.9),
        ],
        start=1,
    ):
        mid = f"ACH-{i:06d}"
        ab[mid] = float(v)
        lin[mid] = lg
    prot_cli.emit_plot_data_protein(ab, lin, card_dir)
    return {}


MIGRATED = [
    ("cellline-rna-distribution", _expr_fixture),
    ("pan-cancer-crispr-dependency-distribution", _chronos_fixture),
    ("pan-cancer-rnai-dependency-distribution", _rnai_fixture),
    ("copy-number-distribution", _cn_fixture),
    ("cellline-protein-abundance", _protein_fixture),
]


@pytest.mark.parametrize("card_id,fixture", MIGRATED, ids=[c for c, _ in MIGRATED])
def test_emitter_descriptors_match_card_contract(card_id, fixture, tmp_path):
    """emit_figures_for_card's STATIC (non-dynamic) descriptors == the card contract's figures: spec,
    matched on (id, type, primary). Renders OFFLINE from persisted plot_data."""
    root = tmp_path / "figures"
    card_dir = root / "cards" / card_id
    card_dir.mkdir(parents=True)
    summary = fixture(card_dir)

    descs = fe.emit_figures_for_card(card_id, summary, root, "MYGENE", "COADREAD")
    assert descs, f"{card_id}: offline emitter produced no figures"

    emitted = {(d["id"], d["type"], bool(d.get("primary"))) for d in descs if not d.get("dynamic")}
    declared = _card_declared(card_id)
    assert emitted == declared, (
        f"{card_id}: emitted figure descriptors {sorted(emitted)} != card-declared figures {sorted(declared)}"
    )
