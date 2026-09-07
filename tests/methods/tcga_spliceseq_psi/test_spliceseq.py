"""tcga_spliceseq_psi — per-(gene, indication) patient splicing summary.

build_spliceseq_psi_table is exercised on synthetic per-tissue PSI files (the SpliceSeq layout:
10 annotation columns + per-sample PSI columns, `_Norm` suffix = matched normal, a clinical row
with empty splice_type), pinning: the variability (std) computation, the tumour-vs-normal shift,
the class precedence (tumor_shifted > highly_variable > stable), matched-normal absence handling,
the composite-indication rollup (COAD+READ -> COADREAD), and gene-sorted output.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.tcga_spliceseq_psi import read as r  # noqa: E402


def _write_tissue(dirpath: Path, tissue: str, sample_names, events):
    """events: list of (symbol, splice_type, {sample_name: psi}). Writes PSI_download_<T>.txt."""
    p = dirpath / f"PSI_download_{tissue}.txt"
    ann = ["symbol", "as_id", "splice_type", "exons", "from_exon", "to_exon",
           "novel_splice", "pct_with_values", "psi_range", "std_psi"]
    header = ann + list(sample_names)
    lines = ["\t".join(header)]
    # a clinical-annotation row (empty splice_type) — must be skipped
    lines.append("\t".join(["Gender"] + [""] * 9 + ["MALE"] * len(sample_names)))
    for i, (sym, st, psis) in enumerate(events):
        row = [sym, f"as{i}", st, "1:2", "1", "2", "no", "90", "0.5", "0.1"]
        row += [str(psis.get(s, "")) for s in sample_names]
        lines.append("\t".join(row))
    p.write_text("\n".join(lines))
    return p


def test_highly_variable_and_stable(tmp_path):
    # GENEA: one event swings 0..1 across tumours (std high) -> variable; GENEB flat -> stable.
    samples = [f"T{i}" for i in range(6)]
    events = [
        ("GENEA", "ES", {"T0": 0.0, "T1": 1.0, "T2": 0.0, "T3": 1.0, "T4": 0.0, "T5": 1.0}),
        ("GENEB", "AA", {s: 0.5 for s in samples}),   # zero variance
    ]
    _write_tissue(tmp_path, "PAAD", samples, events)
    tbl = r.build_spliceseq_psi_table(local_dir=str(tmp_path), tissues=["PAAD"])
    # assert against the Arrow table directly: a null int64 round-trips through pandas as NaN,
    # so nullness must be checked on the Arrow value, not the pandas frame.
    recs = {(x["gene_symbol"], x["indication"]): x for x in tbl.to_pylist()}
    a = recs[("GENEA", "PAAD")]
    b = recs[("GENEB", "PAAD")]
    assert a["splicing_dysregulation_class"] == "highly_variable"
    assert a["max_event_psi_std"] >= 0.49
    assert a["n_variable_events"] == 1
    assert a["dominant_event_splice_type"] == "ES"
    assert b["splicing_dysregulation_class"] == "stable"
    assert b["n_variable_events"] == 0
    # no matched normals in this tissue -> shift is data_unavailable (None)
    assert a["n_tumor_shifted_events"] is None
    assert a["n_normal_samples"] == 0


def test_tumor_shifted_precedence(tmp_path):
    # matched normals present; event PSI shifts tumour(0.9) vs normal(0.1) -> tumor_shifted wins.
    samples = ["T0", "T1", "T2", "N0_Norm", "N1_Norm"]
    events = [("GENEC", "RI", {"T0": 0.9, "T1": 0.9, "T2": 0.9, "N0_Norm": 0.1, "N1_Norm": 0.1})]
    _write_tissue(tmp_path, "STAD", samples, events)
    tbl = r.build_spliceseq_psi_table(local_dir=str(tmp_path), tissues=["STAD"])
    c = tbl.to_pandas().iloc[0]
    assert c["splicing_dysregulation_class"] == "tumor_shifted"
    assert c["n_tumor_shifted_events"] == 1
    assert c["n_normal_samples"] == 2
    assert c["n_tumor_samples"] == 3


def test_composite_indication_rollup(tmp_path):
    # COAD + READ member tissues roll up into a COADREAD row merging their events.
    _write_tissue(tmp_path, "COAD", ["T0", "T1"],
                  [("KRAS", "ES", {"T0": 0.0, "T1": 1.0})])
    _write_tissue(tmp_path, "READ", ["T0", "T1"],
                  [("KRAS", "ES", {"T0": 0.2, "T1": 0.8})])
    tbl = r.build_spliceseq_psi_table(local_dir=str(tmp_path), tissues=["COAD", "READ"])
    df = tbl.to_pandas()
    assert set(df.indication) == {"COAD", "READ", "COADREAD"}
    comp = df[(df.gene_symbol == "KRAS") & (df.indication == "COADREAD")].iloc[0]
    assert comp["n_splice_events"] == 2       # one event from each member tissue
    assert comp["n_tumor_samples"] == 4       # 2 + 2


def test_gene_sorted_output(tmp_path):
    _write_tissue(tmp_path, "BRCA", ["T0", "T1", "T2"], [
        ("ZZZ3", "ES", {"T0": 0.1, "T1": 0.9, "T2": 0.5}),
        ("AAAS", "AA", {"T0": 0.5, "T1": 0.5, "T2": 0.5}),
    ])
    df = r.build_spliceseq_psi_table(local_dir=str(tmp_path), tissues=["BRCA"]).to_pandas()
    syms = list(df.gene_symbol)
    assert syms == sorted(syms)


def test_summary_for_gene_data_unavailable(monkeypatch):
    monkeypatch.setattr(r, "_read_from_product", lambda t, i: None)
    out = r.spliceseq_summary_for_gene("NOPE", "PAAD")
    assert out["splicing_dysregulation_class"] == "data_unavailable"
    assert out["n_tumor_samples"] == 0


def test_clinical_rows_skipped(tmp_path):
    # the Gender annotation row (empty splice_type) must not become a phantom gene.
    _write_tissue(tmp_path, "OV", ["T0", "T1"], [("BRCA1", "ES", {"T0": 0.2, "T1": 0.8})])
    df = r.build_spliceseq_psi_table(local_dir=str(tmp_path), tissues=["OV"]).to_pandas()
    assert set(df.gene_symbol) == {"BRCA1"}   # 'Gender' skipped
