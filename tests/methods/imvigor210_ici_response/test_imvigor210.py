import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.imvigor210_ici_response.read import (  # noqa: E402
    _UROTHELIAL_INDICATIONS,
    _gene_candidates,
    read_target_summary,
)


def test_out_of_scope_is_data_unavailable():
    s = read_target_summary("PDCD1", "SKCM")  # melanoma — out of scope for IMvigor210 (urothelial)
    assert s["ici_response_class"] == "data_unavailable"
    assert "urothelial-only" in s["_data_note"]


def test_no_indication_is_data_unavailable():
    assert read_target_summary("PDCD1", None)["ici_response_class"] == "data_unavailable"


def test_no_target_is_data_unavailable():
    assert read_target_summary("", "BLCA")["ici_response_class"] == "data_unavailable"


def test_urothelial_scope_pinned():
    assert "BLCA" in _UROTHELIAL_INDICATIONS


def test_legacy_symbol_fold_candidates_1272():
    # #1272: NECTIN4 is stored under its legacy prev-symbol PVRL4 in the IMvigor210 product; the read
    # must query BOTH so either symbol resolves. Bidirectional; plain genes are unchanged.
    assert _gene_candidates("NECTIN4") == ["NECTIN4", "PVRL4"]
    assert _gene_candidates("PVRL4") == ["PVRL4", "NECTIN4"]
    assert _gene_candidates("KRAS") == ["KRAS"]  # no alias → single candidate
