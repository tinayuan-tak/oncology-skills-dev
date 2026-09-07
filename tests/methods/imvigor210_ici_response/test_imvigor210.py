import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.imvigor210_ici_response.read import read_target_summary, _UROTHELIAL_INDICATIONS  # noqa: E402


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
