"""til_fraction_saltz — classification + fail-closed coverage (hermetic)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.til_fraction_saltz.read import (  # noqa: E402
    _classify, read_til_fraction, MIN_N, INDICATION_TO_TCGA_STUDIES,
)


def test_classify_bands():
    assert _classify(6.2, 100) == "til_high"          # PAAD-like
    assert _classify(3.0, 100) == "til_intermediate"  # LUAD-like
    assert _classify(1.3, 100) == "til_low"           # BRCA-like
    assert _classify(6.0, 5) == "data_unavailable"    # below n floor
    assert _classify(None, 100) == "data_unavailable"


def test_no_indication_is_data_unavailable():
    s = read_til_fraction("")
    assert s["til_fraction_class"] == "data_unavailable"


def test_unmapped_indication_is_data_unavailable():
    s = read_til_fraction("ZZZ_NOT_A_CODE")
    assert s["til_fraction_class"] == "data_unavailable"
    assert "no TCGA-study mapping" in s["_data_note"]


def test_min_n_floor_pinned():
    assert MIN_N == 30


def test_ucec_uvm_resolve_to_studies():
    # UCEC + UVM are in the Saltz 13-study coverage set but absent from the dge_deseq2 map;
    # the reader supplement must map them so they resolve rather than data_unavailable. (IM-2 fix)
    assert INDICATION_TO_TCGA_STUDIES.get("UCEC") == ["UCEC"]
    assert INDICATION_TO_TCGA_STUDIES.get("UVM") == ["UVM"]
