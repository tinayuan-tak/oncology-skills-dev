"""SKILL.md's verdict enumeration must not drift behind the resolver (2026-09-12).

SKILL.md is what Claude reads to decide what a run can return. Its "Emits `decision.json` with:
`headline`: `dependency_verdict` (...)" enumeration had gone stale: it listed 12 of the resolver's
13 tokens, silently omitting `partner_conditional_dependent` — a VERDICT-BEARING rung added for the
synthetic-lethality rescue path (WRN×MSI). A token missing from the doc is a token Claude does not
know can appear, so it gets narrated as an unexpected value or quietly ignored.

This guard pins the doc against `resolvers/dependency.resolver.yaml` (the authoritative enum) so
adding a rung without documenting it fails here rather than in a customer-facing narration.

Insufficient-family tokens are allowed to appear either individually or under the `insufficient*`
glob that both enumerations use as shorthand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"


def _resolver_verdicts() -> set[str] | None:
    from _skills_common.resolver import load_resolver

    spec = load_resolver("dependency")
    if not spec:
        return None
    return {
        r["verdict"] for r in (spec.get("resolve") or []) if isinstance(r, dict) and isinstance(r.get("verdict"), str)
    }


def _mentions(text: str, token: str) -> bool:
    """Whole-word mention of `token`. A plain substring test would let `non_dependent` be satisfied
    by `non_dependent_paralog_buffered`; the word boundary keeps each token independently checked.
    Deliberately permissive about WHERE it appears — the point is to catch a token the doc never
    mentions, not to police which paragraph mentions it."""
    return re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", text) is not None


def test_every_resolver_verdict_is_documented_in_skill_md():
    verdicts = _resolver_verdicts()
    if verdicts is None:
        pytest.skip("dependency.resolver.yaml unavailable (target-contracts not checked out)")
    assert verdicts, "dependency resolver emitted no verdicts — spec load broken"
    text = _SKILL_MD.read_text()
    missing = sorted(v for v in verdicts if not v.startswith("insufficient") and not _mentions(text, v))
    assert not missing, (
        f"dependency verdict token(s) {missing} are emitted by the resolver but appear NOWHERE in "
        f"SKILL.md. Claude reads SKILL.md to know what a run can return — document the token in the "
        f"headline enumeration AND the Verdict resolution ladder."
    )


def test_headline_enumeration_lists_the_full_positive_and_negative_set():
    """Tighter guard on the ONE list Claude reads first: the `headline:` bullet under "What this
    skill does". Every non-insufficient token must be named there, not merely somewhere in the file."""
    verdicts = _resolver_verdicts()
    if verdicts is None:
        pytest.skip("dependency.resolver.yaml unavailable (target-contracts not checked out)")
    text = _SKILL_MD.read_text()
    m = re.search(r"`headline`: `dependency_verdict` \((.*?)\)", text, re.S)
    assert m, "SKILL.md no longer contains the `headline`: `dependency_verdict` (...) enumeration"
    enumeration = m.group(1)
    missing = sorted(v for v in verdicts if not v.startswith("insufficient") and not _mentions(enumeration, v))
    assert not missing, (
        f"verdict token(s) {missing} missing from SKILL.md's headline enumeration (they are in the "
        f"resolver). This is the list Claude reads before a run; keep it total."
    )


def test_skill_md_does_not_claim_more_tokens_than_the_resolver_emits():
    """The reverse drift: a token retired from the resolver but still advertised in the headline
    enumeration promises a verdict that can never appear.

    Scoped to snake_case tokens only. A retired SINGLE-word verdict (`discordant`) could slip
    through, since single lowercase words in that bullet are indistinguishable from prose — an
    accepted residual, because every verdict added since 2026-07 has been multi-word."""
    verdicts = _resolver_verdicts()
    if verdicts is None:
        pytest.skip("dependency.resolver.yaml unavailable (target-contracts not checked out)")
    text = _SKILL_MD.read_text()
    m = re.search(r"`headline`: `dependency_verdict` \((.*?)\)", text, re.S)
    assert m
    claimed = set(re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", m.group(1)))
    stale = sorted(t for t in claimed if t not in verdicts and not t.startswith("insufficient"))
    assert not stale, (
        f"SKILL.md's headline enumeration advertises verdict token(s) {stale} that the resolver never emits"
    )
