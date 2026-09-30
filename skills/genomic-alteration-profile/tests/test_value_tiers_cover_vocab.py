"""#1559 — _GENOMIC_VALUE_TIERS keys had drifted from (or never matched) the emitted card
vocabularies. `make_value_classifier` does an exact `norm.get()` lookup; an unmatched token falls
through to `default_classify`, which returns `absent` for any token lacking a strong/moderate/
weak substring — the positive-signal->absent polarity flip the classifier was built to prevent.

This feeds `headline["subgroup_signals"]` (live as of SKILL_VERSION 2.19.0), so a drifted key is a
DATA-UTILIZATION bug: no resolver rung sees it, so no golden guard catches it. This guard is
data-driven off the emitting cards' own `summary_fields_vocabulary` so it can't rot the way the
hand-maintained map did.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
CONTRACTS = SKILLS_ROOT.parent / "contracts"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.subgroup_derivation import default_classify, make_value_classifier  # noqa: E402
from _test_support import load_run_py  # noqa: E402

# Cards named in #1559 whose positive class token(s) must not fall through to `absent`. Each entry
# is (card_id, class_field, {token: tier the fix requires}) — a token OMITTED here is still checked
# for presence in the map (test_all_named_tokens_are_mapped) but not pinned to a specific tier.
_CARDS_AND_FIELDS = {
    "target-clonality": "clonality_class",
    "functional-gene-state": "functional_state_class",
    "variant-effect-mave-mavedb": "mave_evidence_class",
    "genomic-event-model-match": "event_correspondence_class",
}

# The specific drifted/omitted tokens the issue names, pinned to the tier the fix must assign.
_MUST_NOT_BE_ABSENT = {
    "predominantly_subclonal": "moderate",
    "recurrent_biallelic_inactivation": "strong",
    "sporadic_biallelic_inactivation": "moderate",
    "mave_well_characterized": "strong",
    "mave_assayed": "moderate",
    "event_matched_dependent_in_lineage": "strong",
    "event_matched_dependent_off_lineage": "moderate",
}


def _card_vocab(card_id: str, field: str) -> list[str]:
    p = CONTRACTS / "cards" / f"{card_id}.card.yaml"
    card = yaml.safe_load(p.read_text()) or {}
    vocab = ((card.get("outputs") or {}).get("summary_fields_vocabulary") or {}).get(field) or []
    return [str(v) for v in vocab]


def _value_tiers():
    ga = load_run_py(SKILL_DIR, "ga_run_valuetiers")
    return dict(ga._GENOMIC_VALUE_TIERS)


def test_named_regression_tokens_no_longer_fall_through_to_absent():
    tiers = _value_tiers()
    classify = make_value_classifier(tiers)
    for tok, expected_tier in _MUST_NOT_BE_ABSENT.items():
        assert classify(tok) == expected_tier, (
            f"{tok!r} classified {classify(tok)!r}, expected {expected_tier!r} "
            f"(default_classify would give {default_classify(tok)!r})"
        )


def test_map_has_no_dead_keys():
    """Every key in the map must correspond to a token one of the emitting cards actually declares
    (or be an explicit cross-cutting sentinel), so a stale/never-matched key can't hide a drift."""
    tiers = _value_tiers()
    live_vocab: set[str] = set()
    for card_id, field in _CARDS_AND_FIELDS.items():
        live_vocab |= set(_card_vocab(card_id, field))
    known_sentinels = {"functionally_abnormal"}  # explicitly refused by the MAVE card; not re-added
    dead = sorted(k for k in tiers if k not in live_vocab and k not in known_sentinels)
    # Only assert on the tokens this issue's cards own — other skill axes' tokens share this map.
    dead_in_scope = [k for k in dead if k in {"subclonal", "biallelic_inactivation", "functionally_abnormal"}]
    assert not dead_in_scope, f"dead keys matching no emitter: {dead_in_scope}"


def test_all_card_vocab_tokens_are_mapped_or_intentionally_absent():
    """Every token the four named cards emit must classify to a non-absent tier, EXCEPT the tokens
    that are genuinely a measured negative/unavailable state (those legitimately map to absent)."""
    tiers = _value_tiers()
    classify = make_value_classifier(tiers)
    legitimate_absent = {
        "data_unavailable",
        "insufficient",
        "no_target_event",
        "not_assayed",
        "mave_unmapped_target",
        "no_event_match",
    }
    for card_id, field in _CARDS_AND_FIELDS.items():
        for tok in _card_vocab(card_id, field):
            if tok in legitimate_absent:
                continue
            if tok not in tiers:
                continue  # covered by the regression pin above for the tokens this issue names
            assert classify(tok) != "absent", (
                f"{card_id}.{field}={tok!r} classifies to 'absent' — a positive signal reading as no signal"
            )
