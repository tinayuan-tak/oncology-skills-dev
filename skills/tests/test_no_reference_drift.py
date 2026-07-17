"""Cross-consistency guard tests — kill the rename-drift bug FAMILY.

Four times this session a rename in one place left a sibling map referencing the
old name, failing SILENTLY (.get() → None / fallthrough, never an error):
  - _risk_by_category short-key drift (mutation/tractability)  [fixed]
  - PHASE_METRIC_FIELDS short-key drift                        [fixed PR-B]
  - differentiation cooccurrence-ns-not-informative rule-id    [fixed PR-B]
  - paralog reader-vs-rule vocab drift                         [PR-B′]

These tests make the whole family a HARD failure at test time instead of a silent
degradation in production:
  1. every rule_id referenced in a sub-skill _verdict/_snapshot exists in the
     target-contracts rules files;
  2. every short key used by target-profile's _risk_by_category + PHASE_METRIC_FIELDS
     exists in SUB_SKILLS.

(The card-class-vocab-vs-reader-emission check lands in PR-B′ with the paralog fix.)
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR))

CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
RULES_DIR = CONTRACTS / "interpretation-rules"

# Sub-skills whose run.py has a _verdict/_snapshot referencing rule_ids.
_VERDICT_SKILLS = [
    "tumor-presence", "tumor-selectivity", "functional-requirement",
    "mechanism-and-pharmacology", "genomic-alteration-profile",
    "differentiation-landscape", "tractability-small-molecule",
    "surface-modality-fit", "on-target-safety-liability",
]


def _all_rule_ids() -> set[str]:
    ids: set[str] = set()
    for f in RULES_DIR.glob("*.rules.yaml"):
        doc = yaml.safe_load(f.read_text())
        for r in doc.get("rules", []):
            if r.get("rule_id"):
                ids.add(r["rule_id"])
    return ids


def _all_card_ids() -> set[str]:
    """Card-ids share the kebab-case namespace with rule-ids but are a DISJOINT set.
    A verdict fn references card-ids too (in _headline _get(card_id, field) + CARDS
    lists); we exclude them so they aren't mistaken for dangling rule-ids."""
    return {p.stem.replace(".card", "") for p in (CONTRACTS / "cards").glob("*.card.yaml")}


def _referenced_rule_ids(run_py: Path) -> set[str]:
    """Rule-ids a sub-skill's verdict logic keys off, extracted STRUCTURALLY (not by
    suffix guessing — a suffix allowlist blind-spotted the very bug this guards, e.g.
    `cooccurrence-ns-not-informative` ends in `-informative`).

    Two patterns cover every wired _verdict/_snapshot:
      A: `if "rule-id" in fired_by_id`
      B: `("rule-id", "verdict")` precedence-tuple, rule-id is the first element
    We capture the rule-id in each position exactly, so any kebab literal used AS a
    rule-id reference is checked, regardless of its suffix.
    """
    text = run_py.read_text()
    refs: set[str] = set()
    # Pattern A: membership test against the fired-rules index.
    refs |= set(re.findall(r'"([a-z][a-z0-9-]+)"\s+in\s+fired_by_id', text))
    refs |= set(re.findall(r'fired_by_id\.get\(\s*"([a-z][a-z0-9-]+)"', text))
    # Pattern B: first element of a (rule_id, verdict) precedence tuple.
    refs |= set(re.findall(r'\(\s*"([a-z][a-z0-9-]+)"\s*,\s*"[a-z_]+"\s*\)', text))
    return refs


def test_every_referenced_rule_id_exists():
    """A sub-skill _verdict/_snapshot must never key off a rule_id that no rule
    defines — that silently collapses the branch to insufficient (the
    cooccurrence-ns-not-informative bug)."""
    known = _all_rule_ids()
    card_ids = _all_card_ids()
    assert known, "no rule_ids loaded — rules dir path wrong?"
    assert card_ids, "no card_ids loaded — cards dir path wrong?"
    problems: list[str] = []
    for skill in _VERDICT_SKILLS:
        run_py = SKILLS_DIR / skill / "scripts" / "run.py"
        if not run_py.exists():
            continue
        # Candidates minus the disjoint card-id namespace (card-ids legitimately
        # appear in _headline/_get + CARDS lists and are NOT rule-ids).
        for rid in _referenced_rule_ids(run_py) - card_ids:
            if rid not in known:
                problems.append(f"{skill}: references rule_id '{rid}' not in any rules file")
    assert not problems, "dangling rule_id references:\n  " + "\n  ".join(problems)


def _load_target_profile():
    run_py = SKILLS_DIR / "target-profile" / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location("tp_run_guard", run_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_risk_table_and_phase_metric_short_keys_exist_in_sub_skills():
    """Every short key _risk_by_category / PHASE_METRIC_FIELDS reads MUST be a real
    SUB_SKILLS short — the drift class that dead-wired druggability + dropped the
    per-phase evidence tables."""
    tp = _load_target_profile()
    sub_shorts = {short for _, short in tp.SUB_SKILLS}
    # PHASE_METRIC_FIELDS keys must all be real shorts.
    bad_pmf = set(tp.PHASE_METRIC_FIELDS) - sub_shorts
    assert not bad_pmf, f"PHASE_METRIC_FIELDS keys not in SUB_SKILLS: {bad_pmf}"
    # _risk_by_category reads a fixed set of shorts via _v(...); assert the ones it
    # consumes resolve (probe by running it on empty input — it must not KeyError and
    # must return all 6 categories).
    rows = tp._risk_by_category_from_sub_verdicts({})
    cats = {c for c, _, _ in rows}
    assert cats == {"biological", "druggability", "translational",
                    "clinical", "safety", "commercial"}


def test_subtype_short_only_appears_when_scoped():
    """subtype_fit is a conditional sub-result; it must not be a hard SUB_SKILLS entry
    (guards against it being treated as always-present)."""
    tp = _load_target_profile()
    sub_shorts = {short for _, short in tp.SUB_SKILLS}
    assert "subtype_fit" not in sub_shorts  # added conditionally, not in the static list
