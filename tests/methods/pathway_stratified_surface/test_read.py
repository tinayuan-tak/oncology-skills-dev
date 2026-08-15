"""pathway_stratified_surface.read — hermetic tests (injected rows, no S3)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pathway_stratified_surface.read import read_pathway_stratified_surface  # noqa: E402


def _row(**kw):
    base = {"pathway_stratified_surface_class": "not_stratified", "signature": "HALLMARK_HYPOXIA",
            "indication": "NSCLC", "delta_log2": 0.1, "q_value": 0.4, "n_high": 348, "n_low": 348}
    base.update(kw)
    return base


def test_pathway_high_up_surface():
    s = read_pathway_stratified_surface("CA9", row=_row(
        pathway_stratified_surface_class="pathway_high_up_surface", delta_log2=2.51, q_value=1e-20))
    assert s["pathway_stratified_surface_class"] == "pathway_high_up_surface"
    assert "biologics handle" in s["pathway_stratified_context"]
    assert s["signature"] == "HALLMARK_HYPOXIA"


def test_pathway_high_down():
    s = read_pathway_stratified_surface("X", row=_row(
        pathway_stratified_surface_class="pathway_high_down_surface", delta_log2=-0.8, q_value=1e-4))
    assert s["pathway_stratified_surface_class"] == "pathway_high_down_surface"


def test_not_in_product_is_coverage_gap(monkeypatch):
    # GENUINE absence: the reader returns None on NoSuchKey/404 -> not_in_product (coverage gap,
    # unchanged). A transient/creds read failure now RE-RAISES instead of masking — see
    # test_read_row_absence.py. row=None means "read live", so monkeypatch the reader to stay hermetic.
    import methods.pathway_stratified_surface.read as _m
    monkeypatch.setattr(_m, "_read_row", lambda *a, **k: None)
    s = read_pathway_stratified_surface("CD19", signature="HALLMARK_INFLAMMATORY_RESPONSE",
                                        indication="DLBCL", row=None)
    assert s["pathway_stratified_surface_class"] == "not_in_product"
    assert "coverage gap" in s["pathway_stratified_context"].lower()
    assert s["delta_log2"] is None


def test_underpowered():
    s = read_pathway_stratified_surface("Y", row=_row(
        pathway_stratified_surface_class="underpowered", delta_log2=None, q_value=None, n_high=5))
    assert s["pathway_stratified_surface_class"] == "underpowered"
