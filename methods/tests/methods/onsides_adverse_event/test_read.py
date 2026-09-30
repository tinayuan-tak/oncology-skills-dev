"""onsides_adverse_event.read — hermetic tests (injected rows, no S3).

Pins the onsides_ade_class precedence (boxed-warning severity hoisted above a plain labeled ADE
profile), the coverage-gap default (absent -> no_mapped_drug_ade, NOT "safe"), field passthrough, the
indication-independence of the summary, and the generic reader dispatch signature.
"""

from __future__ import annotations

from onc_methods.onsides_adverse_event.read import read_target_summary


def _row(**kw):
    base = {
        "gene_symbol": "X",
        "n_drugs_mapped": 3,
        "n_meddra_terms": 120,
        "n_boxed_warning_terms": 0,
        "has_boxed_warning": False,
        "n_high_confidence_terms": 0,
        "example_terms": "Nausea|Rash|Diarrhoea",
        "example_boxed_warning_terms": None,
        "example_drugs": "drugA|drugB|drugC",
    }
    base.update(kw)
    return base


def test_boxed_warning_hoisted():
    s = read_target_summary(
        "ERBB2",
        onsides_row=_row(
            n_drugs_mapped=11,
            n_meddra_terms=418,
            has_boxed_warning=True,
            n_boxed_warning_terms=4,
            example_boxed_warning_terms="Cardiomyopathy|Hepatotoxicity|Interstitial lung disease",
            example_drugs="afatinib|lapatinib|neratinib|pertuzumab",
        ),
    )
    assert s["onsides_ade_class"] == "boxed_warning_ade"
    assert s["has_boxed_warning"] is True
    assert s["n_boxed_warning_terms"] == 4
    assert "Cardiomyopathy" in s["onsides_ade_context"]


def test_labeled_profile_when_no_boxed():
    s = read_target_summary(
        "BCL2",
        onsides_row=_row(
            n_drugs_mapped=1,
            n_meddra_terms=83,
            has_boxed_warning=False,
            n_boxed_warning_terms=0,
            example_drugs="venetoclax",
        ),
    )
    assert s["onsides_ade_class"] == "labeled_ade_profile"
    assert s["n_drugs_mapped"] == 1
    assert s["n_meddra_terms"] == 83


def test_absent_is_coverage_gap_not_safe():
    # onsides_row=None with no live read patched would hit S3; inject an explicit sentinel instead by
    # passing a row that classifies as absent is not possible (row present). Use the reader's own
    # None-handling via the injected-None path guarded by monkeypatching the live read.
    import onc_methods.onsides_adverse_event.read as mod

    orig = mod._read_onsides_row
    try:
        mod._read_onsides_row = lambda target: None  # genuine-absence sentinel
        s = read_target_summary("MADEUPGENE")
    finally:
        mod._read_onsides_row = orig
    assert s["onsides_ade_class"] == "no_mapped_drug_ade"
    assert s["n_drugs_mapped"] == 0
    assert s["has_boxed_warning"] is False
    assert "coverage gap" in s["onsides_ade_context"].lower()
    assert "not evidence of safety" in s["onsides_ade_context"].lower()


def test_indication_is_ignored():
    # OnSIDES ADEs are drug-label-derived + indication-independent; the summary must not vary by indication.
    row = _row(n_drugs_mapped=7, n_meddra_terms=200)
    a = read_target_summary("ABL1", indication=None, onsides_row=row)
    b = read_target_summary("ABL1", indication="LAML", onsides_row=row)
    assert a == b


def test_dispatch_signature_accepts_target_and_indication():
    # generic-dispatch reader contract: fn(target=, indication=)
    s = read_target_summary(target="EGFR", indication="LUAD", onsides_row=_row())
    assert s["_data_source"] == "onsides-adverse-event-per-gene-v1"
    assert s["method_version"] == "0.1.0"


def test_field_passthrough():
    s = read_target_summary("KIT", onsides_row=_row(n_high_confidence_terms=5, example_terms="Neutropenia|Pneumonia"))
    assert s["n_high_confidence_terms"] == 5
    assert s["example_terms"] == "Neutropenia|Pneumonia"
    for k in (
        "onsides_ade_class",
        "n_drugs_mapped",
        "n_meddra_terms",
        "has_boxed_warning",
        "n_boxed_warning_terms",
        "example_terms",
    ):
        assert k in s
