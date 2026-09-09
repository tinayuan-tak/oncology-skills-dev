"""retrieval_lanes Stage-2 relevance gate: pure-core tests (no network).

Guards the PRECISION lever — on-axis / on-target abstracts are kept, genuinely off-topic ones are
dropped, and the floor prevents starvation.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import retrieval_lanes as rl  # noqa: E402


class _Ab:
    def __init__(self, pmid, title="", abstract=""):
        self.pmid, self.title, self.abstract = pmid, title, abstract


def test_axis_tokens_splits_or_and_clause():
    toks = rl._axis_tokens("toxicity OR adverse event OR normal tissue")
    assert toks == ["toxicity", "adverse event", "normal tissue"]
    assert rl._axis_tokens("") == []


def test_axis_match_counts_substring_hits():
    toks = ["toxicity", "normal tissue"]
    assert rl._axis_match("On-target TOXICITY in normal tissue", toks) == 2
    assert rl._axis_match("unrelated text", toks) == 0
    assert rl._axis_match("", toks) == 0


def test_relevance_filter_keeps_on_axis_drops_off_axis():
    # safety axis terms include "toxicity"/"adverse event"/"normal tissue"
    on1 = _Ab("1", title="Hepatic toxicity of the agent")
    on2 = _Ab("2", abstract="serious adverse event reported")
    off1, off2, off3, off4 = (_Ab(str(i), title="nanoparticle synthesis method") for i in (3, 4, 5, 6))
    kept, dropped = rl.relevance_filter([on1, off1, on2, off2, off3, off4], "KRAS", "safety", floor=3)
    kept_ids = [a.pmid for a in kept]
    # both on-axis kept; floor=3 backfills ONE off-axis (first in order = pmid 3); the rest dropped
    assert kept_ids[:2] == ["1", "2"]
    assert "3" in kept_ids and len(kept) == 3
    assert {d["pmid"] for d in dropped} == {"4", "5", "6"}
    assert all(d["reason"] == "off_axis_no_target_match" for d in dropped)


def test_relevance_filter_keeps_target_mention_even_if_off_axis():
    tgt = _Ab("1", abstract="KRAS is amplified here")  # names the target, no safety axis term
    off = _Ab("2", title="unrelated methods")
    kept, dropped = rl.relevance_filter([tgt, off], "KRAS", "safety", floor=1)
    assert [a.pmid for a in kept] == ["1"]  # target-mention → on-signal, kept
    assert [d["pmid"] for d in dropped] == ["2"]


def test_relevance_filter_never_starves_below_floor():
    off = [_Ab(str(i), title="unrelated") for i in range(5)]
    kept, dropped = rl.relevance_filter(off, "KRAS", "safety", floor=3)
    assert len(kept) == 3 and len(dropped) == 2  # floor honored even with zero on-signal
    assert [a.pmid for a in kept] == ["0", "1", "2"]  # order preserved


def test_relevance_filter_empty_input():
    kept, dropped = rl.relevance_filter([], "KRAS", "safety")
    assert kept == [] and dropped == []


def test_retrieve_axis_applies_gate_and_reports_dropped(monkeypatch):
    import pubmed_search as ps

    monkeypatch.setattr(rl, "_retrieve_pmids", lambda *a, **k: ["1", "2", "3", "4"])

    def fake_efetch(pmids, *, category, timeout_s):
        bodies = {
            "1": ("toxicity in liver", ""),
            "2": ("adverse event", ""),
            "3": ("normal tissue expression", ""),
            "4": ("unrelated nanoparticle method", ""),
        }
        return [
            ps.PubMedAbstract(
                pmid=p, title=bodies[p][0], abstract=bodies[p][1], journal="j", year=2021, category=category
            )
            for p in pmids
        ]

    monkeypatch.setattr(ps, "_efetch_abstracts", fake_efetch)
    out = rl.retrieve_axis("KRAS", "COADREAD", "safety", per_cat=4)
    assert [a.pmid for a in out["kept"]] == ["1", "2", "3"]  # 3 on-axis kept
    assert [d["pmid"] for d in out["dropped"]] == ["4"]  # off-axis excess dropped (floor=3 already met)


def test_retrieve_axis_abstracts_wrapper_returns_kept_only(monkeypatch):
    monkeypatch.setattr(rl, "retrieve_axis", lambda *a, **k: {"kept": ["K"], "dropped": [{"pmid": "D"}]})
    assert rl.retrieve_axis_abstracts("KRAS", "COADREAD", "safety") == ["K"]
