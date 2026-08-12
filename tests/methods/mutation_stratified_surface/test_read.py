"""mutation_stratified_surface.read — hermetic tests (injected rows, no S3)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.mutation_stratified_surface.read import read_mutation_stratified_surface  # noqa: E402


def _row(**kw):
    base = {"mutant_stratified_surface_class": "not_stratified", "driver_gene": "KRAS",
            "indication": "NSCLC", "delta_log2": 0.1, "q_value": 0.4, "n_mutant": 166, "n_wt": 878}
    base.update(kw)
    return base


def test_mutant_up_surface():
    s = read_mutation_stratified_surface("MSLN", row=_row(
        mutant_stratified_surface_class="mutant_up_surface", delta_log2=3.58, q_value=1e-12))
    assert s["mutant_stratified_surface_class"] == "mutant_up_surface"
    assert "biologics handle" in s["mutation_stratified_context"]
    assert s["driver_gene"] == "KRAS"


def test_mutant_down_is_directional_negative():
    s = read_mutation_stratified_surface("EGFR", row=_row(
        mutant_stratified_surface_class="mutant_down_surface", delta_log2=-0.64, q_value=1e-5))
    assert s["mutant_stratified_surface_class"] == "mutant_down_surface"


def test_not_in_product_is_coverage_gap(monkeypatch):
    # `row=None` means "no injection" to the reader (it then does a LIVE read), NOT "injected
    # absence" — so offline this hit the S3 read, which raised and (correctly) returned
    # data_unavailable. Mock _read_row -> None to exercise the ABSENCE path (not_in_product)
    # deterministically without S3.
    import methods.mutation_stratified_surface.read as _msr
    monkeypatch.setattr(_msr, "_read_row", lambda *a, **k: None)
    s = read_mutation_stratified_surface("CD19", driver="MYC", indication="DLBCL")
    assert s["mutant_stratified_surface_class"] == "not_in_product"
    assert "coverage gap" in s["mutation_stratified_context"].lower()
    assert s["delta_log2"] is None


def test_underpowered():
    s = read_mutation_stratified_surface("X", row=_row(
        mutant_stratified_surface_class="underpowered", delta_log2=None, q_value=None, n_mutant=4))
    assert s["mutant_stratified_surface_class"] == "underpowered"
