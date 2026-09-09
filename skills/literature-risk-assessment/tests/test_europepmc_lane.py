"""retrieval_lanes Europe PMC lane (PR-6): the 4th retrieval lane. No network — Stack A's _search is
monkeypatched. Guards numeric-PMID filtering (preprints dropped), the cap, best-effort degradation, and
that the lane is registered in RETRIEVAL_LABEL."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import retrieval_lanes as rl  # noqa: E402


def _fake_result(pmids_and_ids):
    return {"resultList": {"result": [{"pmid": p} if p else {"id": i} for (p, i) in pmids_and_ids]}}


def test_europepmc_pmids_keeps_numeric_pmids_drops_preprints(monkeypatch):
    import _skills_common.literature_retrieval as litret

    # a mix: two real MED PMIDs, one preprint (no pmid, only a PPR id) → preprint dropped
    monkeypatch.setattr(
        litret, "_search", lambda query, **k: _fake_result([("111", None), (None, "PPR123"), ("222", None)])
    )
    assert rl._europepmc_pmids("(KRAS) AND (toxicity)", retmax=10) == ["111", "222"]


def test_europepmc_pmids_respects_cap(monkeypatch):
    import _skills_common.literature_retrieval as litret

    monkeypatch.setattr(litret, "_search", lambda query, **k: _fake_result([(str(i), None) for i in range(10)]))
    assert rl._europepmc_pmids("q", retmax=3) == ["0", "1", "2"]


def test_europepmc_pmids_best_effort_on_failure(monkeypatch):
    import _skills_common.literature_retrieval as litret

    monkeypatch.setattr(litret, "_search", lambda *a, **k: None)  # EPMC returned nothing
    assert rl._europepmc_pmids("q", retmax=5) == []
    monkeypatch.setattr(litret, "_search", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    assert rl._europepmc_pmids("q", retmax=5) == []  # exception → contributes nothing


def test_europepmc_registered_in_retrieval_label():
    assert "europepmc" in rl.RETRIEVAL_LABEL
