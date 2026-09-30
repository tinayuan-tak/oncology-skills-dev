"""Per-sub-group signals-first figure emitter. Renders subgroup_signals (+ first-class subtype
by_stratum) as SVG small multiples; best-effort ([] when absent). Display-only / offline."""

from __future__ import annotations

from _skills_common.subgroup_figure import emit_subgroup_figure, render_subgroup_svg  # noqa: E402

_SG = {
    "abundance": {
        "signal": "strong",
        "confidence": "moderate",
        "n_sources": 4,
        "n_agree": 3,
        "power": "high",
        "conflict": True,
        "sources": [
            {"card": "tumor RNA", "tier": "strong", "n": 669, "conflict": False},
            {"card": "protein", "tier": "moderate", "n": 375, "conflict": True},
        ],
        "by_stratum": {"MSI_H": {"signal": "strong", "powered": True}, "MSS": {"signal": "weak", "powered": True}},
        "subtype_axis": {"epsilon_squared": 0.21},
    },
    "malignant_intrinsic": {
        "signal": "strong",
        "confidence": "high",
        "n_sources": 1,
        "n_agree": 1,
        "power": "very high",
        "conflict": False,
        "sources": [{"card": "single-cell", "tier": "strong", "n": 500000, "conflict": False}],
    },
}


def test_renders_wellformed_with_subtype():
    svg = render_subgroup_svg(_SG, "EPCAM", "COADREAD")
    assert svg.strip().endswith("</svg>")
    assert "by sub-group" in svg and "abundance" in svg
    assert "MSI_H" in svg  # first-class subtype row rendered
    # abundance (strong) ranked before... both strong here; malignant present
    assert "malignant_intrinsic" in svg


def test_emit_writes_files(tmp_path):
    out = emit_subgroup_figure(
        {"target": "EPCAM", "indication": "COADREAD", "headline": {"subgroup_signals": _SG}}, tmp_path
    )
    assert any(p.name == "figure_subgroup_signals.svg" for p in out)
    assert (tmp_path / "figure_subgroup_signals.svg").exists()


def test_noop_when_absent(tmp_path):
    assert emit_subgroup_figure({"headline": {}}, tmp_path) == []
