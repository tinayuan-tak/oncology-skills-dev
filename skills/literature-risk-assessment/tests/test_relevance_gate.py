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


def test_relevance_filter_requires_target_and_axis_conjunction():
    # safety axis terms include "toxicity"/"adverse event"/"normal tissue". On-signal now requires the
    # target NAMED *and* an axis (or indication) hit — a bare axis word on an off-target paper is a leak.
    on1 = _Ab("1", title="Hepatic toxicity of KRAS inhibition")  # target ∧ axis
    on2 = _Ab("2", abstract="serious adverse event with a KRAS G12C drug")  # target ∧ axis
    # LEAK-1 (old OR kept these on the bare axis word alone): a *different* gene's toxicity, no target
    off1 = _Ab("3", title="TP53 toxicity in normal tissue")
    off2 = _Ab("4", title="EGFR adverse event profile")
    off3 = _Ab("5", title="nanoparticle synthesis method")
    kept, dropped = rl.relevance_filter([on1, off1, on2, off2, off3], "KRAS", "safety", floor=3)
    kept_ids = [a.pmid for a in kept]
    assert kept_ids[:2] == ["1", "2"]  # both target∧axis kept, in order
    assert "3" in kept_ids and len(kept) == 3  # floor=3 backfills ONE off-signal (first in order = pmid 3)
    assert {d["pmid"] for d in dropped} == {"4", "5"}  # off-target axis-word papers dropped past the floor
    assert all(d["reason"] == "off_signal_needs_target_and_axis_or_indication" for d in dropped)


def test_relevance_filter_drops_bare_target_mention_off_axis_off_indication():
    # LEAK-2: the old test `..._keeps_target_mention_even_if_off_axis` enshrined a bare target mention as
    # KEPT. A paper naming the target but off-axis AND off-indication is no longer substantively relevant.
    tgt_only = _Ab("1", abstract="KRAS is amplified here")  # names target; no safety axis term, no disease
    tgt_axis = _Ab("2", title="KRAS knockout mouse toxicity")  # target ∧ axis → the only on-signal
    off = _Ab("3", title="unrelated methods")
    kept, dropped = rl.relevance_filter([tgt_only, tgt_axis, off], "KRAS", "safety", floor=1)
    assert [a.pmid for a in kept] == ["2"]  # only target∧axis on-signal (floor=1 already met)
    assert {d["pmid"] for d in dropped} == {"1", "3"}  # bare target-mention now dropped


def test_relevance_filter_keeps_target_plus_indication_without_axis_word():
    # target ∧ indication (disease phrase-token) is on-signal even with NO axis phrase-token present —
    # the indication leg the old predicate lacked entirely.
    on = _Ab("1", abstract="KRAS mutations in colorectal cancer cohorts")  # target ∧ indication
    off = _Ab("2", title="KRAS structural biology")  # target only: off-axis (safety) and off-indication
    kept, dropped = rl.relevance_filter([on, off], "KRAS", "safety", disease_terms="colorectal cancer", floor=1)
    assert [a.pmid for a in kept] == ["1"]
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
    # none name the target → all off-signal under the conjunction; floor=3 backfills the first three
    assert [a.pmid for a in out["kept"]] == ["1", "2", "3"]
    assert [d["pmid"] for d in out["dropped"]] == ["4"]  # off-signal excess dropped (floor=3 already met)
    # #1613: kept is FULLY backfilled off-signal → n_on_signal must be 0 so the caller abstains rather than
    # grading a fabricated level. (On the old seam this key was absent → KeyError.)
    assert out["n_on_signal"] == 0


def test_retrieve_axis_reports_n_on_signal_for_thin_but_real_axis(monkeypatch):
    # #1613: ONE genuinely on-signal abstract (target ∧ axis) + off-signal noise. The floor still backfills
    # to 3, but n_on_signal reflects the single relevant hit so the caller keeps (does not abstain).
    import pubmed_search as ps

    monkeypatch.setattr(rl, "_retrieve_pmids", lambda *a, **k: ["1", "2", "3"])

    def fake_efetch(pmids, *, category, timeout_s):
        bodies = {
            "1": ("KRAS on-target toxicity in liver", ""),  # target ∧ axis → on-signal
            "2": ("unrelated nanoparticle method", ""),  # off-signal (backfilled by floor)
            "3": ("TP53 adverse event", ""),  # off-target axis word (backfilled by floor)
        }
        return [
            ps.PubMedAbstract(
                pmid=p, title=bodies[p][0], abstract=bodies[p][1], journal="j", year=2021, category=category
            )
            for p in pmids
        ]

    monkeypatch.setattr(ps, "_efetch_abstracts", fake_efetch)
    out = rl.retrieve_axis("KRAS", "COADREAD", "safety", per_cat=3)
    assert out["n_on_signal"] == 1  # one real on-signal abstract → floor backfill is legitimate, do not abstain
    assert [a.pmid for a in out["kept"]] == ["1", "2", "3"]  # on-signal first, then floor backfill


def test_retrieve_axis_abstracts_wrapper_returns_kept_only(monkeypatch):
    monkeypatch.setattr(rl, "retrieve_axis", lambda *a, **k: {"kept": ["K"], "dropped": [{"pmid": "D"}]})
    assert rl.retrieve_axis_abstracts("KRAS", "COADREAD", "safety") == ["K"]
