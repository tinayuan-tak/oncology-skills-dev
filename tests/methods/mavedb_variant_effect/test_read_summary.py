"""Credential-less tests for the MAVEdb measured-variant-effect reader.

No S3: a synthetic local per-gene parquet (the derived product's schema — gene_symbol,
has_hgnc_mapping, n_score_sets, n_variants_assayed, n_variants_scored, score_min/median/max,
target_categories, urns) is read via the `product_path` offline seam. Pins:
  * the emitted summary carries EVERY field the variant-effect-mave-mavedb card declares
    (the reader-real-field-names drift class the genomic-alteration replay exists to catch);
  * mave_evidence_class is computed on the HGNC-mapped score-set count (well_characterized /
    assayed reachable);
  * a NON-HGNC-mapped row (raw target name carrying assay data) → mave_unmapped_target (surfaced
    with counts, out of the clean HGNC universe — never a silent not_assayed on an assayed gene);
  * a gene with NO row → not_assayed (MEASURED absence of MAVE evidence — NOT data_unavailable);
  * a genuine 404-class fault → data_unavailable + _live_read_error (never crashes the compose path);
  * a transient/creds error is RE-RAISED (never masked as an empty footprint).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

read = importlib.import_module("methods.mavedb_variant_effect.read")

# The fields the variant-effect-mave-mavedb card declares in outputs.summary_fields — the reader
# MUST emit all of them (the drift guard). Kept explicit so a card/reader divergence fails HERE.
_CARD_SUMMARY_FIELDS = {
    "mave_evidence_class",
    "has_hgnc_mapping",
    "n_score_sets",
    "n_variants_assayed",
    "n_variants_scored",
    "score_min",
    "score_median",
    "score_max",
    "target_categories",
    "urns",
    "mave_context",
    "method_version",
}
_CLASS_VOCAB = {"mave_well_characterized", "mave_assayed", "mave_unmapped_target", "not_assayed", "data_unavailable"}

_COLS = [
    "gene_symbol",
    "has_hgnc_mapping",
    "n_score_sets",
    "n_variants_assayed",
    "n_variants_scored",
    "score_min",
    "score_median",
    "score_max",
    "target_categories",
    "urns",
]


def _write_product(tmp_path, rows) -> Path:
    """rows: list of dicts (product schema). Writes a synthetic per-gene parquet."""
    df = pd.DataFrame(rows, columns=_COLS)
    p = tmp_path / "mavedb_variant_effect.parquet"
    df.to_parquet(p, index=False)
    return p


def _row(
    gene,
    mapped=True,
    n_score_sets=2,
    n_assayed=1000,
    n_scored=950,
    smin=-4.0,
    smed=-0.5,
    smax=1.2,
    cats="protein_coding",
    urns="urn:mavedb:00000001-a-1",
):
    return {
        "gene_symbol": gene,
        "has_hgnc_mapping": mapped,
        "n_score_sets": n_score_sets,
        "n_variants_assayed": n_assayed,
        "n_variants_scored": n_scored,
        "score_min": smin,
        "score_median": smed,
        "score_max": smax,
        "target_categories": cats,
        "urns": urns,
    }


def test_summary_shape_matches_card_and_class(tmp_path):
    # TP53 assayed by 3 MAVE score sets (>=2 → well_characterized); a background gene forces the
    # pushdown to actually filter on gene_symbol.
    rows = [
        _row("TP53", n_score_sets=3, n_assayed=8000, n_scored=7900, smin=-6.1, smed=-0.2, smax=2.3),
        _row("BRCA1", n_score_sets=1),
    ]
    prod = _write_product(tmp_path, rows)

    out = read.read_target_summary("TP53", indication="COADREAD", product_path=prod)

    missing = _CARD_SUMMARY_FIELDS - set(out)
    assert not missing, f"reader is missing card-declared summary_fields: {sorted(missing)}"
    assert out["mave_evidence_class"] in _CLASS_VOCAB
    assert out["mave_evidence_class"] == "mave_well_characterized"
    assert out["has_hgnc_mapping"] is True
    assert out["n_score_sets"] == 3
    assert out["n_variants_assayed"] == 8000
    assert out["n_variants_scored"] == 7900
    assert out["score_min"] == -6.1
    assert out["score_median"] == -0.2
    assert out["score_max"] == 2.3
    assert out["target_categories"] == "protein_coding"
    assert out["urns"]
    assert out["method_version"] == read.METHOD_VERSION


def test_single_score_set_is_assayed(tmp_path):
    prod = _write_product(tmp_path, [_row("PTEN", n_score_sets=1)])
    out = read.read_target_summary("PTEN", product_path=prod)
    assert out["mave_evidence_class"] == "mave_assayed"
    assert out["n_score_sets"] == 1


def test_non_hgnc_mapped_row_is_unmapped_target(tmp_path):
    """A raw non-HGNC MAVEdb target-name row that carries assay data is out-of-universe →
    mave_unmapped_target: NOT counted as clean human-gene MAVE evidence, but its assay counts are
    still SURFACED (never a silent not_assayed on a gene that plainly was assayed — the real KRAS case,
    30 score sets under an unmapped raw target name)."""
    prod = _write_product(tmp_path, [_row("KRAS", mapped=False, n_score_sets=30, n_assayed=200000, n_scored=198000)])
    out = read.read_target_summary("KRAS", product_path=prod)
    assert out["mave_evidence_class"] == "mave_unmapped_target"
    assert out["has_hgnc_mapping"] is False
    assert out["n_score_sets"] == 30  # counts surfaced for transparency
    assert out["n_variants_scored"] == 198000


def test_gene_absent_is_not_assayed_not_unavailable(tmp_path):
    """MEASURED absence of MAVE evidence for the gene is the weak-negative not_assayed — NOT
    data_unavailable (which is reserved for a read/coverage fault)."""
    prod = _write_product(tmp_path, [_row("TP53")])
    out = read.read_target_summary("GHOSTGENE", product_path=prod)
    assert out["mave_evidence_class"] == "not_assayed"
    assert out["n_score_sets"] == 0
    assert out["score_min"] is None
    # the gap path still emits every card-declared field (headline/display read via get → None safely)
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_definitive_absence_degrades_not_crashes(monkeypatch):
    """A genuine 404-class fault → data_unavailable + _live_read_error (honest degrade)."""

    def _boom(*a, **k):
        raise FileNotFoundError("no such key")

    monkeypatch.setattr(read, "load_and_classify", _boom)
    out = read.read_target_summary("TP53", indication="COADREAD")
    assert out["_live_read_error"] == "mavedb_variant_effect_read_failed"
    assert out["mave_evidence_class"] == "data_unavailable"
    assert out["method_version"] == read.METHOD_VERSION


def test_transient_fault_is_reraised(monkeypatch):
    """A transient / non-definitive error must NOT be masked as an empty footprint — re-raise so the
    live-read seam surfaces the infra failure (absence discipline)."""

    def _boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(read, "load_and_classify", _boom)
    with pytest.raises(RuntimeError):
        read.read_target_summary("TP53")
