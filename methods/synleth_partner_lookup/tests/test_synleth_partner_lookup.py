"""Synthetic-data tests for synleth_partner_lookup (no S3).

Validates: (1) evidence-tier bucketing (experimental/computational/other); (2) the
symmetric pair inversion (edge x-y → y in x's partners AND x in y's); (3) strongest-
tier-wins per partner; (4) has_experimental_partner gate; (5) reader classes
(has_experimental / has_computational / no_curated_sl_partner) + the absent-gene ≠
data_unavailable distinction; (6) graceful degradation. derive + read are pure over a
tiny synthetic TSV / parquet.
"""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(METHODS_REPO))
from methods.synleth_partner_lookup import derive as d  # noqa: E402
from methods.synleth_partner_lookup import read as r  # noqa: E402


# --- evidence tier (pure) --------------------------------------------------


def test_evidence_tier_buckets():
    assert d.evidence_tier("CRISPR/CRISPRi") == "experimental"
    assert d.evidence_tier("GenomeRNAi") == "experimental"
    assert d.evidence_tier("High Throughput") == "experimental"
    assert d.evidence_tier("Computational Prediction") == "computational"
    assert d.evidence_tier("Text Mining") == "computational"
    assert d.evidence_tier(None) == "other"
    assert d.evidence_tier("") == "other"


# --- symmetric inversion (synthetic TSV) -----------------------------------


def _write_sl_tsv(tmp_path, rows):
    """rows: [(x_ent, x_name, y_ent, y_name, rel_source, cell_line, pubmed, cancer)]."""
    p = tmp_path / "sl.tsv"
    cols = [
        "x:START_ID",
        "x_type",
        "x_name",
        "x_source",
        "y:END_ID",
        "y_type",
        "y_name",
        "y_source",
        "relation",
        ":TYPE",
        "rel_source",
        "edge_index",
        "cell_line",
        "pubmed_id",
        "cancer",
    ]
    with open(p, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for xe, xn, ye, yn, rs, cl, pm, ca in rows:
            fh.write(
                "\t".join([xe, "Gene", xn, "NCBI", ye, "Gene", yn, "NCBI", "SL", "Gene_SL_Gene", rs, "1", cl, pm, ca])
                + "\n"
            )
    return str(p)


def test_symmetric_inversion(tmp_path):
    tsv = _write_sl_tsv(
        tmp_path,
        [
            ("1", "SMARCA2", "2", "SMARCA4", "CRISPR/CRISPRi", "HELA", "123", ""),
        ],
    )
    df = d.build_and_write(tsv_path=tsv)
    a2 = df[df.gene_symbol == "SMARCA2"].iloc[0]
    a4 = df[df.gene_symbol == "SMARCA4"].iloc[0]
    assert "SMARCA4" in list(a2.sl_partner_symbols)  # y in x's partners
    assert "SMARCA2" in list(a4.sl_partner_symbols)  # x in y's partners (symmetric)
    assert a2.has_experimental_partner and a4.has_experimental_partner


def test_strongest_tier_wins_per_partner(tmp_path):
    # same pair from a computational AND an experimental source → experimental wins
    tsv = _write_sl_tsv(
        tmp_path,
        [
            ("1", "GENEA", "2", "GENEB", "Computational Prediction", "", "1", ""),
            ("1", "GENEA", "2", "GENEB", "CRISPR/CRISPRi", "K562", "2", ""),
        ],
    )
    df = d.build_and_write(tsv_path=tsv)
    a = df[df.gene_symbol == "GENEA"].iloc[0]
    assert a.sl_partner_count == 1  # deduped
    assert a.has_experimental_partner  # strongest tier retained
    assert a.top_partners[0]["evidence_tier"] == "experimental"


def test_computational_only_partner_not_experimental(tmp_path):
    tsv = _write_sl_tsv(
        tmp_path,
        [
            ("1", "MARK3", "2", "MTA1", "Computational Prediction", "", "9", ""),
        ],
    )
    df = d.build_and_write(tsv_path=tsv)
    m = df[df.gene_symbol == "MARK3"].iloc[0]
    assert m.sl_partner_count == 1
    assert not m.has_experimental_partner
    assert m.best_evidence_tier == "computational"


# --- reader classes (synthetic parquet) ------------------------------------


def _build_parquet(tmp_path, rows):
    tsv = _write_sl_tsv(tmp_path, rows)
    out = tmp_path / "sl.parquet"
    d.build_and_write(tsv_path=tsv, out_path=str(out))
    return str(out)


def test_reader_experimental_class(tmp_path):
    pq = _build_parquet(tmp_path, [("1", "SMARCA2", "2", "SMARCA4", "CRISPR/CRISPRi", "HELA", "1", "")])
    s = r.read_target_summary("SMARCA2", parquet_path=pq)
    assert s["sl_partner_class"] == "has_experimental_sl_partner"
    assert s["has_experimental_partner"] and s["sl_partner_count"] == 1


def test_reader_computational_class(tmp_path):
    pq = _build_parquet(tmp_path, [("1", "MARK3", "2", "MTA1", "Computational Prediction", "", "1", "")])
    s = r.read_target_summary("MARK3", parquet_path=pq)
    assert s["sl_partner_class"] == "has_computational_sl_partner"
    assert not s["has_experimental_partner"]


def test_reader_absent_gene_is_no_partner_not_data_unavailable(tmp_path):
    pq = _build_parquet(tmp_path, [("1", "SMARCA2", "2", "SMARCA4", "CRISPR/CRISPRi", "HELA", "1", "")])
    s = r.read_target_summary("NOPE", parquet_path=pq)
    assert s["sl_partner_class"] == "no_curated_sl_partner", (
        "a gene absent from the SL table is a real 'no partner' read, NOT data_unavailable"
    )


def test_reader_case_insensitive(tmp_path):
    pq = _build_parquet(tmp_path, [("1", "SMARCA2", "2", "SMARCA4", "CRISPR/CRISPRi", "HELA", "1", "")])
    assert r.read_target_summary("smarca2", parquet_path=pq)["sl_partner_count"] == 1


def test_reader_graceful_on_read_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(r, "_read_gene_rows", _boom)
    s = r.read_target_summary("SMARCA2")
    assert s["sl_partner_class"] == "data_unavailable"
    assert s["_live_read_error"] == "synlethdb_partners_read_failed"


# ── evidence-tier drift-guard + ordering (deferred-debt hardening) ───────────────────────────────
def test_known_v3_rel_sources_never_fall_to_other():
    """Every rel_source value observed in the SynLethDB v3 table (+ common combinations) must map to
    experimental or computational — a drift into the least-trusted 'other' bucket on the next source
    refresh would silently mis-tier partners. If v3 adds a NEW rel_source, extend the markers."""
    known = [
        "CRISPR/CRISPRi",
        "GenomeRNAi",
        "High Throughput",
        "Low Throughput",
        "Computational Prediction",
        "Text Mining",
        "CRISPR/CRISPRi;High Throughput",
        "GenomeRNAi;Low Throughput",
    ]
    for src in known:
        assert d.evidence_tier(src) in ("experimental", "computational"), (
            f"{src!r} fell to 'other' — extend _EXPERIMENTAL_MARKERS/_COMPUTATIONAL_MARKERS"
        )


def test_tier_rank_orders_experimental_over_computational_over_other():
    """An UNRECOGNIZED source ('other') must rank BELOW a known computational prediction (it is the
    least-trustworthy tier, not a middle one)."""
    assert d._TIER_RANK["experimental"] > d._TIER_RANK["computational"] > d._TIER_RANK["other"]
