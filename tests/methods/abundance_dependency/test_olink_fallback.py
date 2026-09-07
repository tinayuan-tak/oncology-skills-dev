"""Track C: Olink-NPX fallback when a target is absent from the Gygi MS panel (rescues surface/secreted
antigens). Hermetic — stubs the protein + Chronos loaders (no S3)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.abundance_dependency import read as ad  # noqa: E402


def _stub_chronos(monkeypatch, chronos):
    import methods.depmap_expression_dependency.cli as dep

    monkeypatch.setattr(
        dep, "load_depmap_files_for_card4", lambda release_pin, target_symbol: (chronos, {}, {}, []), raising=False
    )


def test_olink_fallback_used_when_absent_from_gygi(monkeypatch):
    import methods.depmap_protein_abundance.cli as prot

    # Gygi: target not resolvable → empty; Olink: has the column
    monkeypatch.setattr(prot, "resolve_accession", lambda s: None)
    models = [f"ACH-{i:04d}" for i in range(40)]
    olink = {m: (1.0 if i % 2 else 3.0) for i, m in enumerate(models)}
    monkeypatch.setattr(prot, "load_olink_abundance_column", lambda s: (olink, 500, "P12345"))
    # Chronos anti-correlated with abundance (high NPX → dependent) for a real signal
    chronos = {m: (-0.9 if v > 2 else -0.1) for m, v in olink.items()}
    _stub_chronos(monkeypatch, chronos)
    out = ad.read_abundance_dependency("MSLN")
    assert out["abundance_layer"] == "protein_olink_npx"
    assert "Olink NPX" in out["_fallback_note"]
    assert out["abundance_dependency_class"] in (
        "protein_predicts_dependency",
        "weak_protein_dependency_link",
        "no_protein_dependency_link",
    )
    assert out["abundance_dependency_class"] != "data_unavailable"


def test_gygi_primary_still_wins_when_present(monkeypatch):
    import methods.depmap_protein_abundance.cli as prot

    models = [f"ACH-{i:04d}" for i in range(40)]
    gygi = {m: float(i % 5) for i, m in enumerate(models)}
    monkeypatch.setattr(prot, "resolve_accession", lambda s: "P01116")
    monkeypatch.setattr(prot, "load_abundance_column", lambda acc, **kw: (gygi, 375))
    called = {"olink": False}

    def _olink(s):
        called["olink"] = True
        return ({}, 0, None)

    monkeypatch.setattr(prot, "load_olink_abundance_column", _olink)
    _stub_chronos(monkeypatch, {m: -0.3 for m in models})
    out = ad.read_abundance_dependency("KRAS")
    assert out["abundance_layer"] == "protein_gygi_ms"  # primary
    assert called["olink"] is False  # fallback NOT invoked when Gygi has data


def test_data_unavailable_when_both_miss(monkeypatch):
    import methods.depmap_protein_abundance.cli as prot

    monkeypatch.setattr(prot, "resolve_accession", lambda s: None)
    monkeypatch.setattr(prot, "load_olink_abundance_column", lambda s: (None, 500, None))
    out = ad.read_abundance_dependency("NOTAPROTEIN")
    assert out["abundance_dependency_class"] == "data_unavailable"
