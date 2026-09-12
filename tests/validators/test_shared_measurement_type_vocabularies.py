"""Two cards under ONE measurement_type must not spell the SAME summary field's vocabulary differently.

Why this check exists: a measurement_type is the DATA_TO_SKILL_CONTRACT unit, the promise that a consumer
can read one claim the same way whichever card carries it. A vocabulary divergence breaks that promise
SILENTLY — it lives in two files nothing diffs against each other, and the cost lands on whoever writes
the first interpretation rule for the field: they pick one spelling, it matches one card, and the rule is
permanently dead on the other. A dead `equals:` that looks authored is the worst failure shape in the
corpus, because it reads as coverage.

Found `ici_response_expression :: ici_response_class` (no_ici_association vs no_association), now FIXED
at the source — see `test_the_ici_response_null_class_is_spelled_one_way_across_both_cards`.

Hermetic: every behavioural test builds its own two-card directory, so nothing here depends on the live
corpus. `test_live_corpus_has_no_unannotated_divergence` is the ONE deliberate live-corpus test — it is
the ratchet, and it is what fails when someone adds a diverging card.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load("validate_cards")


def _card(cid: str, mt: str, vocab: dict) -> dict:
    return {
        "card_id": cid,
        "version": "1.0.0",
        "measurement_type": mt,
        "outputs": {"summary_fields": list(vocab), "summary_fields_vocabulary": vocab},
    }


def _write(tmp_path: Path, *cards: dict) -> Path:
    for c in cards:
        (tmp_path / f"{c['card_id']}.card.yaml").write_text(yaml.safe_dump(c))
    return tmp_path


def _run(tmp_path: Path) -> str:
    return "\n".join(VC.validate_shared_measurement_type_vocabularies(tmp_path))


# ── the divergence branch ─────────────────────────────────────────────────────────────────────────
def test_divergent_shared_field_is_an_error(tmp_path):
    _write(
        tmp_path,
        _card("card-a", "shared_mt", {"the_class": ["up", "down", "no_assoc"]}),
        _card("card-b", "shared_mt", {"the_class": ["up", "down", "no_association"]}),
    )
    out = _run(tmp_path)
    assert "[ERROR] VOCABULARY_DIVERGENCE" in out
    assert "shared_mt::the_class" in out
    # the message must NAME the offending tokens on each side, not just say "they differ"
    assert "card-a adds ['no_assoc']" in out
    assert "card-b adds ['no_association']" in out
    assert "['down', 'up']" in out  # and the shared core, so the reader sees the scope of the drift


def test_identical_vocabularies_are_silent(tmp_path):
    _write(
        tmp_path,
        _card("card-a", "shared_mt", {"the_class": ["up", "down"]}),
        _card("card-b", "shared_mt", {"the_class": ["down", "up"]}),  # order must not matter
    )
    assert _run(tmp_path) == ""


def test_different_measurement_types_may_diverge_freely(tmp_path):
    _write(
        tmp_path,
        _card("card-a", "mt_one", {"the_class": ["up", "no_assoc"]}),
        _card("card-b", "mt_two", {"the_class": ["up", "no_association"]}),
    )
    assert _run(tmp_path) == ""


def test_a_field_only_one_card_declares_is_not_a_divergence(tmp_path):
    """The check compares SHARED fields. A card carrying an extra field its sibling never emits is
    normal (different products expose different columns) — flagging it would make the check unusable."""
    _write(
        tmp_path,
        _card("card-a", "shared_mt", {"the_class": ["up", "down"], "only_on_a": ["x", "y"]}),
        _card("card-b", "shared_mt", {"the_class": ["up", "down"]}),
    )
    assert _run(tmp_path) == ""


def test_a_single_card_measurement_type_is_never_flagged(tmp_path):
    _write(tmp_path, _card("lonely", "solo_mt", {"the_class": ["up", "down"]}))
    assert _run(tmp_path) == ""


# ── the allowlist branch ──────────────────────────────────────────────────────────────────────────
def test_allowlisted_divergence_downgrades_to_an_annotated_warning(tmp_path, monkeypatch):
    monkeypatch.setitem(VC._VOCABULARY_DIVERGENCE_ALLOWED, ("shared_mt", "the_class"), "because reasons")
    _write(
        tmp_path,
        _card("card-a", "shared_mt", {"the_class": ["up", "no_assoc"]}),
        _card("card-b", "shared_mt", {"the_class": ["up", "no_association"]}),
    )
    out = _run(tmp_path)
    assert "[ERROR]" not in out
    assert "[WARNING] VOCABULARY_DIVERGENCE_ALLOWED" in out
    # the annotation must be SHOWN, not just consulted — an allowlist whose reason is invisible is a
    # mute button, and the reason is the only thing that lets a later reader re-decide.
    assert "because reasons" in out


def test_allowlist_does_not_suppress_a_different_field_of_the_same_type(tmp_path, monkeypatch):
    monkeypatch.setitem(VC._VOCABULARY_DIVERGENCE_ALLOWED, ("shared_mt", "the_class"), "annotated")
    _write(
        tmp_path,
        _card("card-a", "shared_mt", {"the_class": ["up", "no_assoc"], "other": ["p"]}),
        _card("card-b", "shared_mt", {"the_class": ["up", "no_association"], "other": ["q"]}),
    )
    out = _run(tmp_path)
    assert "shared_mt::other" in out and "[ERROR]" in out


def test_every_allowlist_entry_carries_a_substantive_reason():
    """An allowlist is only honest if each entry says WHY. A one-word reason ('legacy', 'known') is a
    mute button, so require enough prose to be re-litigated later."""
    for key, reason in VC._VOCABULARY_DIVERGENCE_ALLOWED.items():
        assert isinstance(reason, str) and len(reason) >= 80, f"{key} needs a substantive reason, got {reason!r}"


# ── the live ratchet ──────────────────────────────────────────────────────────────────────────────
def test_live_corpus_has_no_unannotated_divergence():
    problems = VC.validate_shared_measurement_type_vocabularies(REPO / "cards")
    errors = [p for p in problems if p.startswith("[ERROR]")]
    assert not errors, "unannotated shared-measurement_type vocabulary divergence:\n" + "\n".join(errors)


def test_the_ici_response_null_class_is_spelled_one_way_across_both_cards():
    """The divergence that motivated this whole check, pinned by NAME so its fix cannot silently regress.

    The live ratchet above would also catch a re-divergence, but only as an anonymous ERROR. This says
    which tokens are correct: `no_ici_association` on BOTH cards, and `no_association` on NEITHER. The
    R derive script for imvigor210-ici-response-per-gene-v1 still emits `no_association` — the alignment
    lives in the reader's alias fold (analysis-methods methods/imvigor210_ici_response/read.py), so a
    future reader rewrite that drops the fold must fail here rather than quietly re-splitting the
    vocabulary."""
    vocabs = {}
    for cid in ("ici-response-association", "ici-response-imvigor210"):
        doc = yaml.safe_load((REPO / "cards" / f"{cid}.card.yaml").read_text())
        assert doc["measurement_type"] == "ici_response_expression", cid
        vocabs[cid] = set((doc["outputs"]["summary_fields_vocabulary"])["ici_response_class"])
    a, b = vocabs.values()
    assert a == b, vocabs
    for cid, v in vocabs.items():
        assert "no_ici_association" in v, cid
        assert "no_association" not in v, f"{cid} re-introduced the diverging spelling"


def test_the_live_check_is_not_vacuous():
    """Anti-vacuous-pass guard: the ratchet above must be comparing something. If the corpus ever has no
    measurement_type carrying two cards with a shared vocabulary field, the check passes by construction
    and stops protecting anything — that is a signal to re-scope it, not a green light."""
    import collections

    pairs = collections.defaultdict(lambda: collections.defaultdict(set))
    for p in sorted((REPO / "cards").glob("*.card.yaml")):
        doc = yaml.safe_load(p.read_text()) or {}
        mt = doc.get("measurement_type")
        if not mt:
            continue
        for f, tokens in ((doc.get("outputs") or {}).get("summary_fields_vocabulary") or {}).items():
            if isinstance(tokens, list):
                pairs[mt][f].add(doc.get("card_id"))
    comparable = [(mt, f) for mt, fs in pairs.items() for f, cids in fs.items() if len(cids) > 1]
    assert comparable, "no shared measurement_type/field pair in the corpus — the ratchet compares nothing"
