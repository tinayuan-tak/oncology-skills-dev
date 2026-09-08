"""Conformance test for the framework figure contract (FIGURE_STYLE_GUIDE.md).

Guards the shared figure machinery so the small adjustments we tuned on the pilots can't silently
regress and so new figures that use figure_frame inherit — and keep — the contract. Renders a
synthetic figure through the real helpers (no analysis-methods dependency) and asserts the four
annotation slots + the verdict-status binding behave. Skips cleanly where matplotlib is absent
(bare-python contracts CI)."""

import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")  # rendering test — only where matplotlib is installed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # plot_styles/ on path
import takeda_palette as pal  # noqa: E402

# ---- verdict-status binding (status_for_card): the figure↔verdict source of truth ----------------


def test_status_palette_covers_the_signal_vocabulary():
    for sig in ("supportive", "neutral", "opposing", "killer", "insufficient", "not_applicable"):
        assert sig in pal.VERDICT_STATUS
        st = pal.resolve_status(sig)
        assert st["signal"] == sig and st["label"] and st["icon"]  # never color-alone


def test_resolve_status_unknown_is_context_not_a_fabricated_negative():
    assert pal.resolve_status("bogus")["signal"] == "context"
    assert pal.resolve_status(None)["signal"] == "context"


def test_status_for_card_reads_the_fired_rule_signal():
    fired = [
        {"rule_id": "tumor-expression-broadly-high-supportive", "card_id": "tumor-rna-distribution", "dominant": True}
    ]
    st = pal.status_for_card("tumor-rna-distribution", fired)
    assert st["signal"] == "supportive" and st["rule_id"].endswith("-supportive")


def test_status_for_card_killer_dominates_cofired_supportive():
    fired = [
        {"rule_id": "x-supportive", "card_id": "c"},
        {"rule_id": "y-veto", "card_id": "c"},
    ]  # a co-fired veto wins (severity)
    assert pal.status_for_card("c", fired)["signal"] == "killer"


def test_status_for_card_no_rule_is_context():
    assert pal.status_for_card("c", [])["signal"] == "context"


def test_explicit_signal_map_overrides_rule_suffix():
    fired = [{"rule_id": "weird-name", "card_id": "c"}]
    st = pal.status_for_card("c", fired, signal_by_rule_id={"weird-name": "opposing"})
    assert st["signal"] == "opposing"


# ---- the four annotation slots via figure_frame --------------------------------------------------


def _texts(fig):
    return [t.get_text() for t in fig.texts]


def test_figure_frame_draws_the_four_slots_and_saves(tmp_path):
    out = tmp_path / "fig.svg"
    with pal.figure_frame(
        "EPCAM",
        "COADREAD",
        "tumor vs. normal expression",
        out_path=out,
        kind="single",
        provenance="TCGA COADREAD · recount3 / GENCODE v26",
        takeaway="74% of COADREAD tumors express EPCAM above the normal 95th percentile.",
    ) as F:
        assert F.ax is not None
        F.ax.boxplot([[1, 2, 3, 4], [5, 6, 7, 8]], orientation="horizontal")
        F.axis_label("x", "Expression", "log2(TPM + 1)")
        F.n_on_boxes([4, 4])
        fig = F.fig
    assert out.exists() and out.stat().st_size > 1000  # saved on clean exit
    texts = _texts(fig)
    # TITLE: descriptive, carries no class token / verdict word
    assert any(t == "EPCAM in COADREAD — tumor vs. normal expression" for t in texts)
    assert not any(w in " ".join(texts) for w in ("broadly_high", "SUPPORTS", "KILLER"))
    # PROVENANCE + TAKEAWAY present; takeaway carries NO "Takeaway:" label
    assert any("recount3" in t for t in texts)
    assert any(t.startswith("74% of COADREAD tumors") for t in texts)
    assert not any(t.lower().startswith("takeaway") for t in texts)
    # n annotated on the boxes (axes-level), NOT in the axis label
    ax_texts = [t.get_text() for t in fig.axes[0].texts]
    assert any(t.startswith("n = ") for t in ax_texts)
    assert "n=" not in (fig.axes[0].get_xlabel() or "").replace(" ", "")


def test_axis_label_is_concept_first():
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    pal.axis_label(ax, "x", "Expression", "log2(TPM + 1)")
    assert ax.get_xlabel() == "Expression"  # concept is the label
    assert any("log2(TPM + 1)" in t.get_text() for t in ax.texts)  # scale is a secondary annotation
    plt.close(fig)


def test_figure_frame_target_grain_title_has_no_indication():
    with pal.figure_frame(
        "EPCAM",
        None,
        "normal-tissue protein footprint",
        out_path=Path("/tmp/_frame_tg.svg"),
        kind="tall",
        make_ax=False,
    ) as F:
        fig = F.fig
    assert any(t == "EPCAM — normal-tissue protein footprint" for t in _texts(fig))


def test_frame_does_not_draw_a_verdict_badge(tmp_path):
    """The verdict is a report-layer concern — the frame must never stamp SUPPORTS/KILLER/etc."""
    out = tmp_path / "f.svg"
    with pal.figure_frame(
        "EPCAM", "COADREAD", "expression vs. tumor purity", out_path=out, kind="scatter", takeaway="…"
    ) as F:
        F.ax.scatter([1, 2], [3, 4])
        fig = F.fig
    joined = " ".join(_texts(fig))
    assert not any(lbl in joined for lbl in ("SUPPORTS", "NEUTRAL", "AGAINST", "KILLER"))
