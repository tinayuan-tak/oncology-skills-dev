"""T3 recomputation anchors — tumor-rna-vs-adjacent (#2044, batch B).

Plan foamy-bird, Stage I / tier T3. Re-derives the card summary from the IRREPRODUCIBLE raw input
(the target's single DESeq2 gene row from the per-indication tumor-vs-adjacent product, committed
inline in the anchor, + the product's all-gene log2FoldChange null, committed as a lossless parquet)
through the REAL ``methods.dge_deseq2.read.read_dge_gene_row``. See
``capture_tumor_rna_vs_adjacent_anchor.py`` for how an anchor is made.

Why this is not the green-for-the-wrong-reason trap: the fixture is the raw INPUT (the provider's
gene row + the all-gene null), the expected fields are re-derived by the same ``read_dge_gene_row``
the framework runs, and the mutation tests below prove the assertion has teeth (perturb the input and
the re-derived class must move).

BOUNDARY: validates the READ/AGGREGATION path (column normalization, ``expression_call_class``
derivation, all-gene percentile), NOT the upstream DESeq2 run. The adjacent-arm adequacy logic
(#864/#865) is NOT on ``read_dge_gene_row``'s path (sensitivity-family only); ``gtex_log2_fc`` /
``gtex_q_value`` come from a separate reader and are not covered here.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.dge_deseq2.read as rd  # noqa: E402

MIN_ANCHORS = 2  # anti-vacuity floor (EPCAM flagship + >=1 other panel target)
MIN_DISTINCT_CLASSES = 2

_FIELDS = (
    "log2_fc",
    "q_value",
    "n_tumor",
    "n_adjacent",
    "base_mean",
    "is_significant_provider_call",
    "is_actionable_provider_call",
    "is_upregulated_provider_call",
    "expression_call_class",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.tumor_rna_vs_adjacent.json"))


def _load_null_vec(anchor: dict) -> tuple:
    table = pq.read_table(HERE / anchor["null_fixture"], columns=["log2FoldChange"])
    return tuple(float(v) for v in table.column("log2FoldChange").to_pylist())


def _rederive(anchor: dict, raw_gene_row: dict, null_vec: tuple) -> dict:
    """Re-derive through the REAL read_dge_gene_row, feeding ONLY the frozen inputs."""
    one_row = pa.table({k: pa.array([v]) for k, v in raw_gene_row.items()})

    def _fake_read_table(*_a, **_k):
        return one_row

    with (
        mock.patch.object(rd, "_load_manifest", lambda mid: {"s3_uri": "s3://frozen/anchor.parquet"}),
        mock.patch.object(rd, "_get_s3fs", lambda: None),
        mock.patch.object(rd, "_allgene_log2fc_null", lambda mid, column="log2FoldChange": tuple(null_vec)),
        mock.patch("pyarrow.parquet.read_table", _fake_read_table),
    ):
        return rd.read_dge_gene_row(anchor["target"], anchor["manifest_id"], return_field_map=True)


pytestmark = pytest.mark.skipif(not _anchor_files(), reason="no tumor_rna_vs_adjacent anchors committed")


@pytest.mark.parametrize("anchor_path", _anchor_files(), ids=lambda p: p.stem)
def test_tumor_rna_vs_adjacent_rederives_from_raw_substrate(anchor_path: Path):
    anchor = json.loads(anchor_path.read_text())
    null_vec = _load_null_vec(anchor)
    assert len(null_vec) >= 1000, f"all-gene null too small ({len(null_vec)}) — fixture truncated?"

    summary = _rederive(anchor, anchor["raw_gene_row"], null_vec)
    for f in _FIELDS:
        assert summary[f] == anchor[f"expected_{f}"], f"{anchor_path.stem}: {f} re-derivation != anchor"


def test_null_fixture_md5_matches_anchors():
    """The committed all-gene null parquet must be byte-for-byte what each anchor was captured
    against (guards a silently-swapped or regenerated fixture)."""
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        digest = hashlib.md5((HERE / anchor["null_fixture"]).read_bytes()).hexdigest()
        assert digest == anchor["null_fixture_md5"], f"{anchor_path.stem}: null fixture md5 drift"


def test_anchor_set_is_not_vacuous():
    files = _anchor_files()
    assert len(files) >= MIN_ANCHORS, f"need >= {MIN_ANCHORS} anchors, found {len(files)}"
    classes = {json.loads(p.read_text())["expected_expression_call_class"] for p in files}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchor set spans only {classes} — need >= {MIN_DISTINCT_CLASSES} expression_call_class branches"
    )


def test_teeth_flipping_significance_breaks_the_class():
    """Teeth: force the gene non-significant (q_value=0.9) and the re-derived expression_call_class
    must collapse to not_informative for any anchor that was a real up/down call — proving the class
    is computed live from the frozen row, not echoed."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        if anchor["expected_expression_call_class"] == "not_informative":
            continue
        null_vec = _load_null_vec(anchor)
        mutated = dict(anchor["raw_gene_row"])
        mutated["padj"] = 0.9  # non-significant
        summary = _rederive(anchor, mutated, null_vec)
        assert summary["expression_call_class"] == "not_informative"
        assert summary["expression_call_class"] != anchor["expected_expression_call_class"]
        moved += 1
    assert moved >= 1, "teeth vacuous: no significant anchor to perturb (need >=1 non-not_informative anchor)"
