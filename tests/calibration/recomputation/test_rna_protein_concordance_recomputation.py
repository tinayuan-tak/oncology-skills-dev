"""T3 recomputation anchors — RNA↔protein concordance card pair (#2046, batch D).

Plan foamy-bird, Stage I / tier T3. Re-derives cellline-rna-protein-concordance +
rna-protein-concordance-tumor from the IRREPRODUCIBLE raw input (the per-ModelID paired RNA/protein
dicts; the matched per-tumor CPTAC rows — committed as lossless parquet) through the REAL
methods.depmap_rna_protein_concordance.read readers. See capture_rna_protein_concordance_anchor.py.

#1510 ADJUDICATION MECHANIZED: #1510 flagged rna_proxy_classified_on as a corpus-tell that shipped
rna_as_biomarker classes MIGHT have been computed on Pearson, not the intended Spearman. The reader
classifies on the SPEARMAN value (read.py:158/505, G10; Pearson only when scipy is unavailable), and
these anchors re-derive that live: rna_proxy_classified_on == 'spearman' and rna_as_biomarker is a
function of the Spearman r. The KRAS cell-line anchor is the decisive witness — Pearson r=0.5524
would classify partial_proxy, but Spearman r=0.3154 classifies poor_proxy, and the reader emits
poor_proxy — so the class provably tracks Spearman, resolving #1510 GREEN on this read path.

Why not the green-for-the-wrong-reason trap: the fixture is the raw INPUT, the expected numbers are
re-derived by the same reader the pipeline runs, and the mutation tests below prove the assertions
have teeth (perturb the input, the re-derived correlation moves).

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.depmap_rna_protein_concordance.read as rd  # noqa: E402

MIN_ANCHORS = 2  # anti-vacuity floor (EPCAM flagship + >=1 other panel target)
MIN_DISTINCT_CLASSES = 2


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — fixture drift guard, not security


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


# ── cell-line grain ──────────────────────────────────────────────────────────────────────────────

CELLLINE_FILES = sorted(ANCHOR_DIR.glob("*.cellline_rna_protein_concordance.json"))
CELLLINE_PARAMS = [
    pytest.param(p, id=p.name.replace(".cellline_rna_protein_concordance.json", "")) for p in CELLLINE_FILES
]


def _cellline_inputs(anchor: dict) -> tuple[dict, dict]:
    rna_tbl = pq.read_table(HERE / anchor["rna_vector_fixture"], columns=["model_id", "rna_log2tpm"])
    prot_tbl = pq.read_table(HERE / anchor["protein_vector_fixture"], columns=["model_id", "protein_log2abundance"])
    rna_by_model = dict(zip(rna_tbl.column("model_id").to_pylist(), rna_tbl.column("rna_log2tpm").to_pylist()))
    prot_by_model = dict(
        zip(prot_tbl.column("model_id").to_pylist(), prot_tbl.column("protein_log2abundance").to_pylist())
    )
    return rna_by_model, prot_by_model


def _rederive_cellline(anchor: dict, rna_by_model: dict, prot_by_model: dict) -> dict:
    with mock.patch.object(
        rd, "_paired_rna_protein", lambda t, release_pin="26q3": (rna_by_model, prot_by_model, None)
    ):
        return rd.read_rna_protein_concordance(anchor["target"], release_pin=anchor["release_pin"])


def test_cellline_anchor_set_is_not_vacuous():
    assert len(CELLLINE_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} cell-line anchors, found {len(CELLLINE_FILES)}"
    )
    classes = {_load(p)["expected"]["rna_as_biomarker"] for p in CELLLINE_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classes; found {sorted(classes)}"
    )
    assert any("epcam" in p.name for p in CELLLINE_FILES), "the EPCAM flagship cell-line anchor is required and missing"


@pytest.mark.parametrize("anchor_path", CELLLINE_PARAMS)
def test_cellline_fixture_md5_matches_anchor(anchor_path: Path):
    anchor = _load(anchor_path)
    assert _md5(HERE / anchor["rna_vector_fixture"]) == anchor["rna_vector_md5"], (
        "RNA vector drifted from the pinned md5"
    )
    assert _md5(HERE / anchor["protein_vector_fixture"]) == anchor["protein_vector_md5"], "protein vector drifted"


@pytest.mark.parametrize("anchor_path", CELLLINE_PARAMS)
def test_cellline_rederives_from_raw_dicts(anchor_path: Path):
    anchor = _load(anchor_path)
    rna_by_model, prot_by_model = _cellline_inputs(anchor)
    assert len(prot_by_model) >= 50, f"protein panel too small ({len(prot_by_model)}) — fixture truncated?"
    summary = _rederive_cellline(anchor, rna_by_model, prot_by_model)
    for k, v in anchor["expected"].items():
        assert summary[k] == v, f"{anchor['target']}: re-derived {k}={summary[k]!r} != pinned {v!r}"
    # #1510: the class provably tracks Spearman, not Pearson.
    assert summary["rna_proxy_classified_on"] == "spearman"


def test_cellline_kras_class_tracks_spearman_not_pearson():
    """The #1510 witness: KRAS Pearson r would classify partial_proxy but Spearman classifies
    poor_proxy — the reader emits the Spearman-driven class."""
    kras = [p for p in CELLLINE_FILES if "kras" in p.name]
    if not kras:
        pytest.skip("no KRAS cell-line anchor")
    anchor = _load(kras[0])
    exp = anchor["expected"]
    assert exp["rna_proxy_classified_on"] == "spearman"
    assert exp["rna_protein_r"] >= 0.4 > exp["rna_protein_spearman"], (
        "expected the Pearson/Spearman pair to straddle the 0.4 boundary (Pearson>=0.4>Spearman)"
    )
    assert exp["rna_as_biomarker"] == "poor_proxy", "class must follow Spearman (< 0.4 -> poor_proxy), not Pearson"


@pytest.mark.parametrize("anchor_path", CELLLINE_PARAMS)
def test_cellline_teeth_shuffling_protein_breaks_the_correlation(anchor_path: Path):
    """Teeth: reversing the protein values relative to their models destroys the RNA↔protein pairing,
    so the re-derived Pearson r must move off the pinned value — proving r is a live function of the
    paired substrate, not echoed from the pin. n_paired is unchanged (same models, permuted values)."""
    anchor = _load(anchor_path)
    rna_by_model, prot_by_model = _cellline_inputs(anchor)
    models = list(prot_by_model)
    reversed_vals = list(prot_by_model.values())[::-1]
    shuffled = dict(zip(models, reversed_vals))
    summary = _rederive_cellline(anchor, rna_by_model, shuffled)
    assert summary["n_paired_models"] == anchor["expected"]["n_paired_models"]
    assert summary["rna_protein_r"] != anchor["expected"]["rna_protein_r"], (
        "shuffling protein left r unchanged (no teeth)"
    )


# ── CPTAC tumor grain ────────────────────────────────────────────────────────────────────────────

TUMOR_FILES = sorted(ANCHOR_DIR.glob("*.tumor_rna_protein_concordance.json"))
TUMOR_PARAMS = [pytest.param(p, id=p.name.replace(".tumor_rna_protein_concordance.json", "")) for p in TUMOR_FILES]


def _tumor_frames(anchor: dict) -> dict:
    rows = pd.read_parquet(HERE / anchor["matched_rows_fixture"])
    return {c: rows[rows["cohort"] == c].drop(columns=["cohort"]).reset_index(drop=True) for c in anchor["cohorts"]}


def _rederive_tumor(anchor: dict, frames_by_cohort: dict) -> dict:
    def _fake(cohort, target=None):
        df = frames_by_cohort.get(cohort)
        return (
            df
            if df is not None
            else pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"])
        )

    with mock.patch.object(rd, "_read_matched_cohort", _fake):
        return rd.read_tumor_rna_protein_concordance(anchor["target"], anchor["indication"])


def test_tumor_anchor_set_is_not_vacuous():
    assert len(TUMOR_FILES) >= MIN_ANCHORS, f"expected >= {MIN_ANCHORS} tumor anchors, found {len(TUMOR_FILES)}"
    classes = {_load(p)["expected"]["rna_as_biomarker"] for p in TUMOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classes; found {sorted(classes)}"
    )
    assert any("epcam" in p.name for p in TUMOR_FILES), "the EPCAM flagship tumor anchor is required and missing"


@pytest.mark.parametrize("anchor_path", TUMOR_PARAMS)
def test_tumor_fixture_md5_matches_anchor(anchor_path: Path):
    anchor = _load(anchor_path)
    assert _md5(HERE / anchor["matched_rows_fixture"]) == anchor["matched_rows_md5"], (
        "matched rows drifted from pinned md5"
    )


@pytest.mark.parametrize("anchor_path", TUMOR_PARAMS)
def test_tumor_rederives_from_matched_rows(anchor_path: Path):
    anchor = _load(anchor_path)
    frames = _tumor_frames(anchor)
    summary = _rederive_tumor(anchor, frames)
    for k, v in anchor["expected"].items():
        assert summary[k] == v, (
            f"{anchor['target']}/{anchor['indication']}: re-derived {k}={summary[k]!r} != pinned {v!r}"
        )
    assert summary["rna_proxy_classified_on"] == "spearman"


@pytest.mark.parametrize("anchor_path", TUMOR_PARAMS)
def test_tumor_teeth_shuffling_protein_breaks_the_correlation(anchor_path: Path):
    """Teeth: reversing protein_log2abundance within the matched rows breaks the per-tumor pairing,
    so the re-derived r must move off the pin — n_paired_tumors unchanged."""
    anchor = _load(anchor_path)
    frames = _tumor_frames(anchor)
    mutated = {c: f.assign(protein_log2abundance=f["protein_log2abundance"].values[::-1]) for c, f in frames.items()}
    summary = _rederive_tumor(anchor, mutated)
    assert summary["n_paired_tumors"] == anchor["expected"]["n_paired_tumors"]
    assert summary["rna_protein_r"] != anchor["expected"]["rna_protein_r"], (
        "shuffling protein left r unchanged (no teeth)"
    )
