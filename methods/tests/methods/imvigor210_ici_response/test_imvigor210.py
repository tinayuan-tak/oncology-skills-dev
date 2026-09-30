from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
from onc_methods.imvigor210_ici_response.read import (
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


# ── shared-measurement_type VOCABULARY fold (2026-09-12) ─────────────────────
def test_null_class_is_folded_onto_the_shared_vocabulary(monkeypatch):
    """`measurement_type: ici_response_expression` is carried by TWO cards and they spelled the same
    null class differently: methods/ici_response mints `no_ici_association` in Python, the IMvigor210
    R derive script mints `no_association` and this reader passed it through verbatim. One
    measurement_type must mean one vocabulary, or the first rule author's `equals:` is permanently dead
    on one card while looking authored."""
    import onc_methods.imvigor210_ici_response.read as R

    monkeypatch.setattr(
        R,
        "_rows_for_candidates",
        lambda cands: [{"gene_symbol": "KRAS", "ici_response_class": "no_association"}],
    )
    assert R.read_target_summary("KRAS", "BLCA")["ici_response_class"] == "no_ici_association"


def test_the_fold_leaves_the_real_classes_alone(monkeypatch):
    import onc_methods.imvigor210_ici_response.read as R

    for tok in ("higher_in_responders", "higher_in_nonresponders", "data_unavailable"):
        monkeypatch.setattr(
            R, "_rows_for_candidates", lambda cands, tok=tok: [{"gene_symbol": "KRAS", "ici_response_class": tok}]
        )
        assert R.read_target_summary("KRAS", "BLCA")["ici_response_class"] == tok


def test_the_fold_target_matches_the_sibling_reader():
    """Anti-drift: the folded token must be the one the sibling actually mints, not a third spelling."""
    from onc_methods.imvigor210_ici_response.read import _CLASS_ALIASES

    sibling = Path(REPO) / "onc_methods" / "ici_response" / "read.py"
    assert set(_CLASS_ALIASES.values()) == {"no_ici_association"}
    assert '"no_ici_association"' in sibling.read_text()
