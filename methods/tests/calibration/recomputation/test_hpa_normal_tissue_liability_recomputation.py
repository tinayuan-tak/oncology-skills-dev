"""T3 recomputation anchors — normal-tissue-liability (#2047, batch E).

normal-tissue-liability is the GTEx/HPA IHC-derived on-target-off-tumor safety card, produced by
``methods.hpa_normal_tissue_liability.cli.load_and_classify(gene)`` ->
``compute_summary(gene, row)``. This re-derives the card summary from the IRREPRODUCIBLE raw input
committed as the anchor's frozen row (JSON — a single HPA master-TSV row, 5 scalar string columns):
the target gene's ``Gene`` / ``Protein tissue distribution`` / ``Protein tissue specificity`` /
``Protein tissue specific Intensity`` / ``Reliability (IH)`` cells.

The offline re-derivation calls the REAL ``compute_summary(gene, row)`` directly on the frozen row —
no S3/zip seam to mock, ``compute_summary`` is a pure function of its ``row`` argument (the capture
tool's own round-trip guard proves the frozen row reproduces the live
``load_and_classify`` read exactly).

BOUNDARY: validates the READ path this reader owns — the gene-symbol lookup, the breadth
classification (``classify_breadth``), the tissue-enrichment parse (``parse_specific_tissues``), the
essential/GI-tissue membership test, the antibody-reliability qualifier, and the
``essential_tissue_flag`` trichotomy. The IHC distribution/specificity/reliability CALLS themselves
are precomputed upstream by HPA (source manifest ``hpa-v25-1``); no aggregation arithmetic lives in
analysis-methods for this card.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.hpa_normal_tissue_liability.cli as cli  # noqa: E402

MIN_ANCHORS = 2
MIN_DISTINCT_FLAGS = 2  # essential_tissue_flag must span >= 2 values across the anchor set

_CARD_FIELDS = (
    "normal_tissue_breadth_class",
    "essential_tissue_flag",
    "hpa_tissue_distribution",
    "hpa_tissue_specificity",
    "hpa_ihc_reliability",
    "essential_tissue_low_reliability",
    "n_essential_tissues_with_expression",
    "essential_tissues_flagged",
    "n_specific_tissues",
    "specific_tissues",
    "safety_tissue_flags",
    "method_version",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.hpa_normal_tissue_liability.json"))


def _row_from_fixture(rel: str) -> dict:
    return json.loads((HERE / rel).read_text())


pytestmark = pytest.mark.skipif(not _anchor_files(), reason="no hpa_normal_tissue_liability anchors committed")


@pytest.mark.parametrize("anchor_path", _anchor_files(), ids=lambda p: p.stem)
def test_rederives_from_raw_substrate(anchor_path: Path):
    anchor = json.loads(anchor_path.read_text())
    row = _row_from_fixture(anchor["row_fixture"])
    summary = cli.compute_summary(anchor["target"], row)
    for f in _CARD_FIELDS:
        assert summary.get(f) == anchor["expected"][f], f"{anchor_path.stem}: {f} != anchor"


def test_fixture_md5_matches_anchors():
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        row = _row_from_fixture(anchor["row_fixture"])
        digest = hashlib.md5(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()  # noqa: S324
        assert digest == anchor["row_md5"], f"{anchor_path.stem}: row fixture md5 drift"


def test_anchor_set_is_not_vacuous():
    files = _anchor_files()
    assert len(files) >= MIN_ANCHORS, f"need >= {MIN_ANCHORS} anchors, found {len(files)}"
    flags = {json.loads(p.read_text())["expected"]["essential_tissue_flag"] for p in files}
    assert len(flags) >= MIN_DISTINCT_FLAGS, (
        f"anchor set spans only {flags} essential_tissue_flag value(s) — need >= {MIN_DISTINCT_FLAGS}"
    )


def test_teeth_blanking_the_intensity_column_drops_the_essential_flag():
    """Teeth: blanking Protein tissue specific Intensity on a `present`-via-enrichment anchor must
    re-derive a DIFFERENT essential_tissue_flag/safety_tissue_flags — proving the trichotomy is a
    live function of the frozen row's enrichment text, not echoed from the anchor. Revert-verified
    the other direction by test_rederives_from_raw_substrate (the un-mutated row reproduces exactly)."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        if not anchor["expected"]["essential_tissues_flagged"]:
            continue  # only anchors where enrichment (not `detected in all`) drives `present`
        row = dict(_row_from_fixture(anchor["row_fixture"]))
        row[cli.HPA_INTENSITY_COL] = None
        summary = cli.compute_summary(anchor["target"], row)
        assert summary["essential_tissues_flagged"] != anchor["expected"]["essential_tissues_flagged"]
        assert summary["safety_tissue_flags"] != anchor["expected"]["safety_tissue_flags"]
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor with enrichment-driven essential_tissues_flagged to perturb"


def test_teeth_flipping_the_distribution_column_moves_the_breadth_class():
    """Teeth: swapping Protein tissue distribution to 'Not detected' must move
    normal_tissue_breadth_class off the anchor's committed value — proving classify_breadth runs
    live on the frozen row, not a self-echo."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        row = dict(_row_from_fixture(anchor["row_fixture"]))
        row[cli.HPA_DIST_COL] = "Not detected"
        summary = cli.compute_summary(anchor["target"], row)
        assert summary["normal_tissue_breadth_class"] == "not_detected_in_normal"
        assert summary["normal_tissue_breadth_class"] != anchor["expected"]["normal_tissue_breadth_class"]
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor to perturb"
