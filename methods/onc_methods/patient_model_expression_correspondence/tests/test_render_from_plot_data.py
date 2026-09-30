"""Figure Stage 6 (recommended-models): the full model rows persist on the verdict read, and
render_from_plot_data draws the patient<->model scatter OFFLINE from them — no S3, no second live read
(read_recommended_models monkeypatched to RAISE)."""

from __future__ import annotations

from pathlib import Path

from onc_methods.patient_model_expression_correspondence import cli as c
from onc_methods.patient_model_expression_correspondence import figures as f

_ROWS = [
    {"target_log2tpm": 3.0, "chronos": -1.2, "screen_role": "positive_model", "lineage_match": True},
    {"target_log2tpm": 2.5, "chronos": -0.1, "screen_role": "resistance_model", "lineage_match": True},
    {"target_log2tpm": 0.2, "chronos": None, "screen_role": "negative_control", "lineage_match": False},
    {"target_log2tpm": 4.1, "chronos": -0.9, "screen_role": "positive_model", "lineage_match": False},
]
_SUMMARY = {"correspondence_class": "strong_correspondence", "patient_iqr": [2.0, 4.0]}


def _write(d: Path) -> Path:
    import pandas as pd

    d.mkdir(parents=True, exist_ok=True)
    out = d / "plot_data_recommended_models.parquet"
    pd.DataFrame(_ROWS).to_parquet(out, index=False)
    return out


def _svg_ok(p: Path) -> bool:
    return p.exists() and p.stat().st_size > 0 and "<svg" in p.read_text()[:2000]


def test_renders_offline_from_persisted_parquet(tmp_path, monkeypatch):
    pd_path = _write(tmp_path / "src")
    monkeypatch.setattr(
        c._read,
        "read_recommended_models",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live read in offline render")),
    )
    out = tmp_path / "out"
    descs = f.render_from_plot_data(pd_path, _SUMMARY, out, "MYGENE", "COADREAD")
    assert _svg_ok(out / "figure_recommended_models.svg")
    assert {d["id"] for d in descs if not d.get("dynamic")} == {"recommended_models_scatter"}
    assert descs[0]["primary"] is True


def test_missing_columns_raises(tmp_path):
    import pandas as pd

    df = pd.DataFrame({"target_log2tpm": [3.0]})  # no chronos
    try:
        f.render_from_plot_data(df, _SUMMARY, tmp_path / "out", "MYGENE", "COADREAD")
    except ValueError as e:
        assert "chronos" in str(e)
    else:
        raise AssertionError("expected ValueError on missing required column")
