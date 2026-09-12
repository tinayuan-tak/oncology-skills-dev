"""No authored template may reach a consumer with its placeholder unresolved.

Corpus prose is templated in TWO places, and only one of them ever interpolated:

  * the 148 card contracts carrying a `question:`  → `display_gloss.card_description` — substituted
  * the 15 per-skill `questions.yaml` registries   → `evidence_graph.build_evidence_graph` — did NOT

So `genomic-alteration-profile/questions.yaml`'s splice-form question shipped the literal string
`is {target.symbol} alternatively spliced ... in {indication.label} tumours?` through
`evidence_graph.questions[].text` into a published `dashboard.html`, `target_profile.md` and
`nomination.json` for KRAS-COADREAD. It was the only placeholder-bearing question text in the fleet, so a
test naming that one question would have gone green and stayed green while the next placeholder anyone
adds elsewhere shipped exactly the same way.

These tests therefore assert the ABSENCE OF THE FAILURE over the whole corpus rather than the presence of
the fix in one path: whatever any skill's registry says, no emitted question text may contain an
unresolved placeholder. That fails for a new placeholder in any of the 15 registries without anyone
remembering this file exists.

The leak was invisible for the usual reason — it is display-only and verdict-INERT, so the graph still
rendered, just with a broken sentence. Note that `build_evidence_graph` emitted `target` / `indication`
in the SAME return dict, twenty lines below the un-substituted text: the substitution inputs were in
scope and simply were never called. A reachability gap, not a data gap.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.display_gloss import card_description, fill_placeholders  # noqa: E402
from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402

# Any `{...}` left in rendered prose. Deliberately broader than the four tokens the substituter knows:
# a template using a spelling nobody implemented (`{gene}`, `{tumour}`) is just as broken on screen, and
# a token-list-shaped assertion would be blind to it.
_UNRESOLVED = re.compile(r"\{[a-z_][a-z_.]*\}", re.I)

_SKILL_DIRS = sorted(p.parent for p in SKILLS.glob("*/questions.yaml"))


def test_the_corpus_under_test_is_not_empty():
    """Falsification floor: if the glob silently found nothing, every test below would pass vacuously."""
    assert len(_SKILL_DIRS) >= 10, f"only {len(_SKILL_DIRS)} skills with a questions.yaml — glob is wrong"
    assert sum(len(load_questions(d)) for d in _SKILL_DIRS) >= 40


@pytest.mark.parametrize("skill_dir", _SKILL_DIRS, ids=lambda p: p.name)
def test_no_emitted_question_text_carries_an_unresolved_placeholder(skill_dir):
    """THE guard. Every question in every skill's registry, projected through the real graph builder."""
    questions = load_questions(skill_dir)
    if not questions:
        pytest.skip(f"{skill_dir.name} has no questions")
    decision = {"skill": skill_dir.name, "target": "KRAS", "indication": "COADREAD"}
    graph = build_evidence_graph(decision, questions=questions)
    leaked = [(q["id"], q["text"]) for q in graph["questions"] if q.get("text") and _UNRESOLVED.search(q["text"])]
    assert not leaked, (
        f"{len(leaked)} question text(s) in {skill_dir.name}/questions.yaml reach consumers with an "
        f"unresolved placeholder: {leaked}. Either interpolate it or drop the placeholder from the text — "
        f"an un-substituted template ships to dashboard.html / target_profile.md / nomination.json."
    )


def test_the_graph_actually_substitutes_rather_than_stripping():
    """The guard above is satisfiable by deleting the placeholder, which would ALSO delete the meaning.
    Pin that the request is substituted IN, not merely that braces are gone."""
    qs = [{"id": "q1", "seq": 1, "text": "Is {target.symbol} altered in {indication.label} tumours?"}]
    graph = build_evidence_graph({"target": "KRAS", "indication": "COADREAD"}, questions=qs)
    text = graph["questions"][0]["text"]
    assert "KRAS" in text and "{" not in text
    assert "altered in" in text  # the authored prose survives


def test_the_real_leaking_question_is_fixed():
    """The measured case: genomic-alteration-profile's splice-form question, the one live leak."""
    qs = load_questions(SKILLS / "genomic-alteration-profile")
    graph = build_evidence_graph({"target": "KRAS", "indication": "COADREAD"}, questions=qs)
    got = next(q["text"] for q in graph["questions"] if q["id"] == "splice_dysregulation")
    assert "{target.symbol}" not in got and "{indication.label}" not in got
    assert "is KRAS alternatively spliced" in got
    assert "Colorectal" in got or "COADREAD" in got  # display label when the crosswalk resolves, else code


def test_an_unresolvable_request_degrades_to_readable_prose_not_a_placeholder():
    """A graph built without target/indication (a --literature-only or fixture decision) must not fall back
    to printing the raw template — the placeholder is worse than the gap."""
    qs = [{"id": "q1", "seq": 1, "text": "Is {target.symbol} altered in {indication.label} tumours?"}]
    text = build_evidence_graph({}, questions=qs)["questions"][0]["text"]
    assert "{" not in text
    assert text == "Is altered in tumours?"  # collapsed whitespace, no double space


# Two card contracts template a token NO substituter has ever implemented — `{driver}` / `{signature}`,
# the gene or signature the card was stratified BY. Unlike target/indication these are per-RUN values that
# `card_description(card_id, target, indication)` has no access to and its only caller
# (`report_render/ir.py`) does not hold either, so they cannot be filled at description time: the fix is to
# reword the question in target-contracts (both cards carry the stratifier as a summary field —
# `driver_gene` — so the prose can name it without a placeholder). Filed there, not fixable from here.
#
# Allow-listed rather than ignored, and the allowlist is SELF-RETIRING: `test_the_card_allowlist_has_not_
# grown` fails if a third card joins, and `..._is_still_needed` fails once target-contracts fixes these
# two, forcing the entry out instead of letting it rot into a permanent exemption.
_CARD_PLACEHOLDER_ALLOWLIST = {
    "mutation-stratified-surface": "{driver}",
    "pathway-stratified-surface": "{signature}",
}


def _leaking_cards() -> dict:
    from _skills_common.paths import target_contracts_root

    cards = sorted((target_contracts_root() / "cards").glob("*.card.yaml"))
    if not cards:
        pytest.skip("target-contracts not available")
    out = {}
    for p in cards:
        cid = p.name.replace(".card.yaml", "")
        d = card_description(cid, "KRAS", "COADREAD")
        if d and _UNRESOLVED.search(d):
            out[cid] = d
    return out


def test_card_descriptions_across_the_whole_contract_corpus_resolve():
    """The other templated path, swept the same way — 148 card contracts carry a `question:`."""
    leaked = {k: v for k, v in _leaking_cards().items() if k not in _CARD_PLACEHOLDER_ALLOWLIST}
    assert not leaked, (
        f"{len(leaked)} card description(s) carry an unresolved placeholder: {list(leaked.items())[:5]}. "
        f"Use `{{target.symbol}}` / `{{indication.label}}` — the only tokens `fill_placeholders` implements — "
        f"or state the value in prose."
    )


def test_the_card_allowlist_has_not_grown():
    """A new unfillable placeholder must not be able to join the exemption silently."""
    leaked = set(_leaking_cards())
    assert leaked <= set(_CARD_PLACEHOLDER_ALLOWLIST), (
        f"new card(s) leaking a placeholder: {sorted(leaked - set(_CARD_PLACEHOLDER_ALLOWLIST))}"
    )


def test_the_card_allowlist_is_still_needed():
    """Fails once target-contracts rewords these questions — that is the signal to DELETE the allowlist,
    so the exemption cannot outlive the defect it documents."""
    leaked = _leaking_cards()
    stale = [cid for cid in _CARD_PLACEHOLDER_ALLOWLIST if cid not in leaked]
    assert not stale, (
        f"{stale} no longer leak a placeholder — target-contracts fixed them. Remove them from "
        f"_CARD_PLACEHOLDER_ALLOWLIST (and delete the allowlist entirely once it is empty)."
    )
    for cid, token in _CARD_PLACEHOLDER_ALLOWLIST.items():
        assert token in leaked[cid], f"{cid} now leaks a DIFFERENT token than the documented {token}"


def test_fill_placeholders_contract():
    """The shared helper both paths now use."""
    assert fill_placeholders(None) is None and fill_placeholders("") is None
    assert fill_placeholders("{target.symbol} in {indication.label}", "KRAS", "COADREAD").startswith("KRAS in ")
    # historical spellings seen in the corpus
    assert fill_placeholders("{target} / {indication}", "KRAS", "COADREAD").startswith("KRAS / ")
    # unrelated braces in prose are left alone rather than raising, which str.format would
    assert fill_placeholders("range {1,2}", "KRAS", "COADREAD") == "range {1,2}"
    # an all-placeholder string collapses to None rather than to whitespace
    assert fill_placeholders("{target.symbol}") is None
