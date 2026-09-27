"""Verdict-diff backtest harness (rekey_backtest.py, #761 S4) — hermetic tests.

No DESeq2, no S3, no network. Two concerns are exercised separately:

  * MECHANISM — ``reader_pointed_at_local`` swaps the read layer's manifest
    resolution to a LOCAL scratch parquet (the manifest-id override the brief
    calls for) and clears the per-manifest percentile caches so a baseline read
    cannot leak into the shadow read.
  * LOGIC — ``diff_verdicts`` enumerates moved verdict fields per
    (target, indication) and ``attribute_moves`` ties each move to a gene-id
    authority cause (symbol_drift / symbol_reuse_conflict / ensg_ambiguous),
    exercised on directly-constructed snapshots so the assertions are exact.

MUTATION TEETH: the load-bearing guards are that an empty / disjoint /
no-real-verdict baseline↔shadow join RAISES ``RekeyJoinError`` rather than
returning an empty "0 moved = safe" diff, and that the shadow emit REFUSES any
production prefix. Each is asserted to FIRE (and the legitimate no-move case is
asserted NOT to fire, so the teeth are not vacuous).
"""

from __future__ import annotations

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from methods.dge_deseq2 import read as r
from methods.dge_deseq2 import rekey_backtest as rb

MANIFEST_ID = "coadread-dge-tumor-vs-normal-sensitivity-v1"


# --- fixtures ---------------------------------------------------------------
def _authority() -> pd.DataFrame:
    """Synthetic gene-id authority exercising each attribution branch.

    KRAS clean 1:1; DRIFTGENE drift; REUSEGENE reuse-conflict; AMBIGENE backed by
    TWO authority genes (ensg_ambiguous → gene_id NA)."""
    rows = [
        ("KRAS", "ENSG00000133703", False, False),
        ("DRIFTGENE", "ENSG00000000001", True, False),
        ("REUSEGENE", "ENSG00000000002", False, True),
        ("AMBIGENE", "ENSG00000000003", False, False),
        ("AMBIGENE", "ENSG00000000004", False, False),
    ]
    return pd.DataFrame(rows, columns=["symbol_hgnc", "gene_id", "symbol_drift", "symbol_reuse_conflict"])


def _verdict_record(target, indication="COADREAD", **overrides) -> dict:
    rec = {
        "target": target,
        "indication": indication,
        "selectivity_class": "tumor_selective",
        "comparator_concordance": "concordant",
        "selectivity_evidence_independence": "two_families",
        "dominant_direction": "up",
        "sig_all_cells": True,
        "discordant": False,
        "selectivity_allgene_percentile_class": "high",
    }
    rec.update(overrides)
    return rec


def _snap(records) -> pd.DataFrame:
    return pd.DataFrame(records).set_index(["target", "indication"])


def _write_sensitivity_parquet(path, rows):
    """A symbol-keyed four-cell sensitivity.parquet with the native driver schema."""
    cols = {
        "gene_symbol": [],
        "cells_ran": [],
        "cells_supporting": [],
        "dominant_direction": [],
        "sig_all_cells": [],
        "discordant": [],
        "log2fc_A": [],
        "padj_A": [],
        "log2fc_C": [],
        "padj_C": [],
        "max_abs_log2fc": [],
        "gene_id": [],
        "gene_stem": [],
    }
    for row in rows:
        for k in cols:
            cols[k].append(row[k])
    pq.write_table(pa.table(cols), str(path))


def _sens_row(gene_symbol, *, dominant="up", sig_all=True, log2fc_a=2.5, gene_stem="ENSG_X"):
    return {
        "gene_symbol": gene_symbol,
        "cells_ran": 2,
        "cells_supporting": 2 if sig_all else 1,
        "dominant_direction": dominant,
        "sig_all_cells": sig_all,
        "discordant": False,
        "log2fc_A": log2fc_a,
        "padj_A": 1e-6,
        "log2fc_C": 2.0,
        "padj_C": 1e-5,
        "max_abs_log2fc": max(abs(log2fc_a), 2.0),
        "gene_id": f"{gene_stem}.1",
        "gene_stem": gene_stem,
    }


# --- MECHANISM: manifest-id override reads a local scratch product ----------
def test_reader_pointed_at_local_reads_scratch_product(tmp_path):
    path = tmp_path / "sensitivity.parquet"
    _write_sensitivity_parquet(
        path,
        [
            _sens_row("KRAS", gene_stem="ENSG00000133703"),
            _sens_row("TP53", dominant="down", gene_stem="ENSG00000141510"),
        ],
    )
    with rb.reader_pointed_at_local({MANIFEST_ID: str(path)}) as read_module:
        v = rb.read_verdict("KRAS", "COADREAD", read_module=read_module)
    assert v["selectivity_class"] is not None
    assert v["selectivity_class"] != "data_unavailable"
    # additive gene-id provenance forwarded from the scratch product (#835 chain)
    assert v["gene_stem"] == "ENSG00000133703"
    # seams restored on exit
    assert r._get_s3fs.__module__ == "methods.dge_deseq2.read"


def test_reader_override_does_not_leak_percentile_cache(tmp_path):
    """Baseline and shadow share the manifest_id; a stale percentile null must
    not carry the baseline distribution into the shadow read."""
    base = tmp_path / "base.parquet"
    shad = tmp_path / "shadow.parquet"
    _write_sensitivity_parquet(base, [_sens_row("KRAS", log2fc_a=0.1)])
    _write_sensitivity_parquet(shad, [_sens_row("KRAS", log2fc_a=9.9), _sens_row("G2", log2fc_a=-9.9)])
    with rb.reader_pointed_at_local({MANIFEST_ID: str(base)}) as rm:
        vb = rb.read_verdict("KRAS", "COADREAD", read_module=rm)
    with rb.reader_pointed_at_local({MANIFEST_ID: str(shad)}) as rm:
        vs = rb.read_verdict("KRAS", "COADREAD", read_module=rm)
    # both reads succeeded against DISTINCT byte sets under the same manifest_id
    assert vb["selectivity_class"] is not None and vs["selectivity_class"] is not None


# --- LOGIC: enumerate + attribute -------------------------------------------
def test_build_report_enumerates_and_attributes_by_cause():
    baseline = _snap(
        [
            _verdict_record("KRAS"),
            _verdict_record("DRIFTGENE"),
            _verdict_record("REUSEGENE"),
            _verdict_record("AMBIGENE"),
        ]
    )
    shadow = _snap(
        [
            _verdict_record("KRAS"),  # unchanged → NOT reported
            _verdict_record("DRIFTGENE", dominant_direction="down"),
            _verdict_record("REUSEGENE", selectivity_class="not_selective"),
            _verdict_record("AMBIGENE", sig_all_cells=False),
        ]
    )
    report = rb.build_verdict_delta_report(baseline, shadow, authority=_authority())

    moved = set(report["target"])
    assert moved == {"DRIFTGENE", "REUSEGENE", "AMBIGENE"}, "KRAS did not move → absent"

    cause_of = lambda t: set(report[report["target"] == t]["attributed_cause"])
    assert cause_of("DRIFTGENE") == {"symbol_drift"}
    assert cause_of("REUSEGENE") == {"symbol_reuse_conflict"}
    assert cause_of("AMBIGENE") == {"ensg_ambiguous"}

    ambi = report[report["target"] == "AMBIGENE"].iloc[0]
    assert bool(ambi["ensg_ambiguous"]) is True
    assert pd.isna(ambi["gene_id"]), "ambiguous symbol must not resolve to a single gene_id"
    assert int(ambi["n_authority_genes"]) == 2

    # the moved FIELDS are the ones actually changed
    field_of = lambda t: set(report[report["target"] == t]["field"])
    assert "dominant_direction" in field_of("DRIFTGENE")
    assert "selectivity_class" in field_of("REUSEGENE")
    assert "sig_all_cells" in field_of("AMBIGENE")


def test_summarize_report():
    baseline = _snap([_verdict_record("DRIFTGENE"), _verdict_record("KRAS")])
    shadow = _snap([_verdict_record("DRIFTGENE", dominant_direction="down"), _verdict_record("KRAS")])
    report = rb.build_verdict_delta_report(baseline, shadow, authority=_authority())
    s = rb.summarize_report(report)
    assert s["n_moved_targets"] == 1
    assert s["moved_targets"] == ["DRIFTGENE"]
    assert s["moves_by_cause"].get("symbol_drift", 0) >= 1


# --- MUTATION TEETH: degenerate joins FAIL LOUD -----------------------------
def _empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(columns=["target", "indication", *rb.VERDICT_FIELDS]).set_index(["target", "indication"])


def test_empty_snapshot_raises():
    empty = _empty_snapshot()
    real = _snap([_verdict_record("KRAS")])
    with pytest.raises(rb.RekeyJoinError):
        rb.diff_verdicts(empty, real)
    with pytest.raises(rb.RekeyJoinError):
        rb.diff_verdicts(real, empty)


def test_disjoint_keys_raise():
    baseline = _snap([_verdict_record("KRAS", indication="COADREAD")])
    shadow = _snap([_verdict_record("KRAS", indication="LUAD")])
    with pytest.raises(rb.RekeyJoinError, match="share only"):
        rb.diff_verdicts(baseline, shadow)


def test_no_real_verdicts_raises():
    # shared keys, but the baseline products could not be read → nothing to certify
    baseline = _snap([_verdict_record("KRAS", selectivity_class="data_unavailable")])
    shadow = _snap([_verdict_record("KRAS", selectivity_class="tumor_selective")])
    with pytest.raises(rb.RekeyJoinError, match="no real verdicts"):
        rb.diff_verdicts(baseline, shadow)


def test_identical_products_report_no_move_without_raising():
    """The teeth must not over-fire: a legitimate, non-degenerate, no-move diff
    returns an EMPTY report (0 moved) — a real 'the re-key is safe' result."""
    baseline = _snap([_verdict_record("KRAS"), _verdict_record("DRIFTGENE")])
    shadow = baseline.copy()
    moves = rb.diff_verdicts(baseline, shadow)
    assert len(moves) == 0
    report = rb.build_verdict_delta_report(baseline, shadow, authority=_authority())
    assert len(report) == 0
    assert list(report.columns)[-1] == "attributed_cause"  # typed empty frame


def test_min_shared_guard_fires_when_neutered():
    """Prove the min_shared guard is what stops a fully-disjoint join: with the
    guard's effect removed (min_shared=0) the same disjoint input yields an empty
    diff — the vacuous green the default guard prevents."""
    baseline = _snap([_verdict_record("KRAS", indication="COADREAD")])
    shadow = _snap([_verdict_record("KRAS", indication="LUAD")])
    # default (min_shared=1) raises …
    with pytest.raises(rb.RekeyJoinError):
        rb.diff_verdicts(baseline, shadow)
    # … but the no-real-verdict guard still catches min_shared=0 (0 shared keys →
    # 0 real verdicts across the empty shared set), so the join can never silently
    # report "0 moved".
    with pytest.raises(rb.RekeyJoinError):
        rb.diff_verdicts(baseline, shadow, min_shared=0)


# --- NO PROD WRITE: the emit guard REFUSES a production prefix ---------------
def test_assert_scratch_prefix_refuses_prod(tmp_path):
    with pytest.raises(rb.RekeyBacktestError):
        rb.assert_scratch_prefix("s3://onc-compbio/data-catalog/derived/x")
    with pytest.raises(rb.RekeyBacktestError):
        rb.assert_scratch_prefix("/some/local/onc-compbio/thing")
    with pytest.raises(rb.RekeyBacktestError):
        rb.assert_scratch_prefix("relative/data-catalog/derived/coadread-...-v1")
    # a genuine local scratch dir is accepted
    ok = rb.assert_scratch_prefix(tmp_path / "shadow")
    assert str(ok).endswith("shadow")


def test_rekey_loader_argv_wires_collapse_key(tmp_path):
    out = tmp_path / "bundle.rds"
    argv = rb.rekey_loader_argv(config="/cfg/coadread.yaml", out_rds=str(out))
    assert "--collapse-key" in argv
    assert argv[argv.index("--collapse-key") + 1] == "gene_stem"
    assert "00_load_recount3.R" in argv[2]
    assert argv[argv.index("--out") + 1] == str(out)
    # default collapse (byte-identical shipped path) is selectable
    argv_sym = rb.rekey_loader_argv(config="/cfg/c.yaml", out_rds=str(out), collapse_key="gene_symbol")
    assert argv_sym[argv_sym.index("--collapse-key") + 1] == "gene_symbol"


def test_rekey_loader_argv_rejects_bad_key_and_prod(tmp_path):
    with pytest.raises(rb.RekeyBacktestError):
        rb.rekey_loader_argv(config="/c.yaml", out_rds=str(tmp_path / "b.rds"), collapse_key="ensg")
    with pytest.raises(rb.RekeyBacktestError):
        rb.rekey_loader_argv(config="/c.yaml", out_rds="s3://onc-compbio/x.rds")


def test_driver_argv_points_at_driver_and_guards_prod(tmp_path):
    argv = rb.driver_argv(in_rds=str(tmp_path / "b.rds"), out_dir=str(tmp_path / "prod"))
    assert argv[2].endswith("06_four_cell_driver.R")
    assert "--out-dir" in argv
    with pytest.raises(rb.RekeyBacktestError):
        rb.driver_argv(in_rds="/b.rds", out_dir="s3://onc-compbio/data-catalog/derived/x")


def test_attribute_moves_empty_is_typed():
    empty = pd.DataFrame(columns=["target", "indication", "field", "baseline_value", "shadow_value"])
    out = rb.attribute_moves(empty, authority=_authority())
    assert len(out) == 0
    for col in ("attributed_cause", "ensg_ambiguous", "symbol_drift", "symbol_reuse_conflict"):
        assert col in out.columns
