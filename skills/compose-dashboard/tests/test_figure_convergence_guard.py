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

SKILL_DIR = Path(__file__).resolve().parent.parent            # skills/compose-dashboard
sys.path.insert(0, str(SKILL_DIR / "scripts"))                # _figure_emitters
_AM = os.environ.get("ANALYSIS_METHODS_ROOT",
                     "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, _AM)

import _figure_emitters as fe  # noqa: E402
from methods.depmap_expression_distribution import cli as e3cli  # noqa: E402
from methods.depmap_expression_distribution.figures import render_from_plot_data  # noqa: E402


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
