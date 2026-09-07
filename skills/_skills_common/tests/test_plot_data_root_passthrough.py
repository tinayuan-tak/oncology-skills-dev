"""Figure Stage 1 (skills pass-through): plot_data_root threads to the data-access layer.

read_live_summary forwards a per-card plot_data dir (plot_data_root/cards/<card_id>) to a dispatcher
ONLY when its signature declares plot_data_out (signature introspection, the same discipline as the
T4 data_context forwarding — see test_data_context_threading.py), so:
  - a plot_data-aware dispatcher receives the per-card dir;
  - a legacy (target, indication) dispatcher is untouched (no TypeError masked into _live_read_error);
  - with plot_data_root=None, nothing is forwarded (byte-identical to the former call).
resolve_cards threads plot_data_root down to _resolve_one_card -> read_live.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/compose-dashboard
sys.path.insert(0, str(SKILL_DIR / "scripts"))  # for _live_readers
sys.path.insert(0, str(SKILL_DIR.parent))  # skills/ — for _skills_common

from _skills_common import _live_readers as lr  # noqa: E402
import _skills_common as skc  # noqa: E402


def test_plot_data_aware_dispatcher_receives_per_card_dir(monkeypatch, tmp_path):
    def d(target, indication, plot_data_out=None):
        return {"expression_class": "broadly_high", "_saw": plot_data_out}

    monkeypatch.setitem(lr.CARD_DISPATCHERS, "_test-card", d)
    out = lr.read_live_summary("_test-card", "KRAS", "COADREAD", plot_data_root=tmp_path)
    assert out["_saw"] == tmp_path / "cards" / "_test-card"


def test_var_kwargs_dispatcher_receives_it(monkeypatch, tmp_path):
    def d(target, indication, **kw):
        return {"ok": True, "_kw": dict(kw)}

    monkeypatch.setitem(lr.CARD_DISPATCHERS, "_test-card", d)
    out = lr.read_live_summary("_test-card", "KRAS", "COADREAD", plot_data_root=tmp_path)
    assert out["_kw"].get("plot_data_out") == tmp_path / "cards" / "_test-card"


def test_legacy_dispatcher_untouched(monkeypatch, tmp_path):
    def d(target, indication):
        return {"ok": True}

    monkeypatch.setitem(lr.CARD_DISPATCHERS, "_test-card", d)
    out = lr.read_live_summary("_test-card", "KRAS", "COADREAD", plot_data_root=tmp_path)
    assert out == {"ok": True}  # NOT masked into a _live_read_error


def test_no_plot_data_root_forwards_nothing(monkeypatch):
    def d(target, indication, plot_data_out=None):
        return {"ok": True, "_saw": plot_data_out}

    monkeypatch.setitem(lr.CARD_DISPATCHERS, "_test-card", d)
    out = lr.read_live_summary("_test-card", "KRAS", "COADREAD", plot_data_root=None)
    assert out["_saw"] is None


def test_resolve_cards_threads_plot_data_root(monkeypatch, tmp_path):
    captured = {}

    def fake_read_live(card_id, target, indication, **kw):
        captured["plot_data_root"] = kw.get("plot_data_root")
        return {"expression_class": "broadly_high"}

    monkeypatch.setattr(skc, "_import_dispatcher", lambda: fake_read_live)
    out = skc.resolve_cards(["cellline-rna-distribution"], "KRAS", "COADREAD", plot_data_root=tmp_path)
    assert captured["plot_data_root"] == tmp_path
    assert out[0]["card_id"] == "cellline-rna-distribution"


import pytest


@pytest.mark.parametrize(
    "card_id",
    [
        "copy-number-distribution",  # read_cn_distribution
        "recommended-models",  # patient_model_expression_correspondence.cli.build_summary
        "cellline-rna-protein-concordance",  # depmap_rna_protein_concordance.cli.build_summary
        "rna-protein-concordance-tumor",  # depmap_rna_protein_concordance.cli.build_tumor_summary
        "tumor-rna-distribution",  # tcga_gtex_expression_distribution.cli.build_summary
        "tumor-vs-normal-percentile-crossing",  # .cli.build_selectivity_crossing_summary
        "normal-tissue-liability-gtex",  # .cli.build_normal_liability_summary
        "tumor-rna-distribution-by-subtype",  # .cli.build_subtype_panorama -> read_tumor_expression_subtype_landscape
    ],
)
def test_bespoke_dispatchers_forward_plot_data_out(card_id):
    """Offline-seam activation guard (2026-08-21 follow-on): each bespoke dispatcher whose method read
    layer persists plot_data must DECLARE plot_data_out, so read_live_summary's signature-introspection
    forwards the per-card dir → the figure emitter renders OFFLINE instead of re-executing the live read.
    (The method cli.build_* entrypoints + read fns already thread/persist it; this pins the dispatcher
    forward — the link read_live_summary gates on.)"""
    import inspect

    d = lr.CARD_DISPATCHERS[card_id]
    params = inspect.signature(d).parameters
    assert "plot_data_out" in params or any(p.kind == p.VAR_KEYWORD for p in params.values()), (
        f"{card_id} dispatcher must forward plot_data_out for the offline figure seam"
    )


def test_cn_distribution_dispatcher_declares_plot_data_out():
    """Regression (2026-08-21 offline-seam follow-on): the bespoke copy-number-distribution dispatcher
    must DECLARE plot_data_out so read_live_summary's signature-introspection forwards the per-card dir
    → the CN figure emitter renders OFFLINE from the persisted plot_data_cn.parquet instead of
    re-executing the live CN read. read_cn_distribution already accepts plot_data_out; this dispatcher
    was the missing forward (it routed read_cn_distribution(target, indication) only)."""
    import inspect

    d = lr.CARD_DISPATCHERS["copy-number-distribution"]
    params = inspect.signature(d).parameters
    assert "plot_data_out" in params or any(p.kind == p.VAR_KEYWORD for p in params.values()), (
        "copy-number-distribution dispatcher must forward plot_data_out for the offline figure seam"
    )
