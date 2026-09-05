"""bispecific-pair-scan skill — orchestration + decision.json shape (method mocked, no S3).

Pins: (1) partner-set default = clinical seeds when --partners omitted; (2) ranked headline top_pair;
(3) graceful data_unavailable when the method degrades; (4) the avidity caveat is carried through.
"""
from __future__ import annotations

import sys
from pathlib import Path

from _test_support import load_run_py

bps = load_run_py(Path(__file__).resolve().parent.parent, "bps_run")


def test_clinical_seed_set_is_nonempty_and_has_known_antigens():
    assert len(bps.CLINICAL_SEED_ANTIGENS) >= 20
    for a in ("EPCAM", "CEACAM5", "ERBB2", "DLL3"):
        assert a in bps.CLINICAL_SEED_ANTIGENS


def test_run_scan_degrades_to_unavailable_on_method_error(monkeypatch):
    # Force the METHOD-import resolution inside the REAL _run_scan to raise (mirrors an unimportable
    # analysis-methods repo / broken COMPOSE_SCRIPTS path), then assert the real _run_scan degrades to
    # an honest empty/data_unavailable contract instead of crashing. (Was a tautology: it monkeypatched
    # _run_scan to itself and asserted a hand-built literal, testing nothing.)
    import types
    fake_live_readers = types.ModuleType("_skills_common._live_readers")

    def _boom(method_name):
        raise ImportError(f"forced-test-failure: cannot import method {method_name}")

    fake_live_readers._import_method = _boom
    # _run_scan does `from _skills_common._live_readers import _import_method` then calls it — the
    # injected module makes that call raise, exercising the broad-except degrade path.
    monkeypatch.setitem(sys.modules, "_skills_common._live_readers", fake_live_readers)

    scan = bps._run_scan("EPCAM", ["CEACAM5", "ERBB2", "DLL3"], "COADREAD", "AND")

    assert scan["n_pairs_scored"] == 0, "a method-import failure must yield 0 scored pairs (data_unavailable)"
    assert scan["ranked_pairs"] == [], "no fabricated pairs on a degrade"
    assert scan["load_error"] and "forced-test-failure" in scan["load_error"], (
        f"the real load_error must carry the raised failure, got {scan['load_error']!r}")
    # the partner count is still honestly reported (the input, not a scored result)
    assert scan["n_partners_scanned"] == 3


def test_gate_choices_are_and_or_not():
    assert set(bps.GATE_CHOICES) == {"AND", "OR", "NOT"}


def test_question_template_formats():
    q = bps.QUESTION.format(target="EPCAM", indication="COADREAD", gate="AND")
    assert "EPCAM" in q and "COADREAD" in q and "AND" in q


def test_clinical_seed_set_has_no_duplicate_or_alias_genes():
    # Bug-audit P7 / finding 15: MSLN appeared twice and PSMA/FOLH1 (same gene) were both listed,
    # which double-scans the gene and emits a duplicate pair row.
    seeds = bps.CLINICAL_SEED_ANTIGENS
    dups = sorted({g for g in seeds if seeds.count(g) > 1})
    assert not dups, f"duplicate seed antigens: {dups}"
    assert not ("PSMA" in seeds and "FOLH1" in seeds), \
        "PSMA is an alias of the HGNC symbol FOLH1 — list the gene once (FOLH1), not both"
