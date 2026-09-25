"""Guards for the `capsule:` projection contract (genomic-alteration production review, PR-3).

WHY THIS EXISTS. `_skills_common/evidence_capsule.emit_capsules` projects each card's summary into a
compact capsule — a `class` plus a handful of `numeric_anchors` — and that projection is what the
dashboard and the evidence graph actually SHOW. Absent a `capsule:` declaration the emitter guesses:

  · `class`           ← the ALPHABETICAL-FIRST `*_class` summary field;
  · `numeric_anchors` ← the alphabetically-first FOUR fields whose name contains one of ~29
                        `_ANCHOR_HINTS` substrings ("effect_size", "median", "fraction", …).

Both guesses fail silently and verdict-INERTLY, which is exactly why nothing caught them: the capsule
still renders, just with the wrong numbers. Measured on the genomic axis before this PR — 10 of the 12
cards the `genomic_alteration` resolver consumes had no declaration, and:

  · alteration-role's driving field `alteration_role` has no `_class` suffix, so `class` was None on
    EVERY run, and neither of its numerics matches a hint, so `numeric_anchors` was []. Both halves
    of its capsule were empty, always.
  · copy-number-distribution (ABL1/CML) reported class `recurrently_deleted` while surfacing four
    alphabetical `cn_fraction_*` values; `cn_recurrent_deletion_score` 0.2016 (vs the 0.2 cut that SET
    that class) and `cn_recurrent_amplification_score` 0.047 were structurally unreachable, because
    "score" is not an `_ANCHOR_HINTS` substring.
  · mutation-stratified-dependency has 11 hint-matching fields, so the cap at 4 dropped its own
    headline gauges — `hotspot_effect_size` and the `median_chronos_hotspot_{mutant,wildtype}` pair the
    salience ruler is cut against.

The two cards that DID declare a capsule are precisely the two where the alphabetical class pick is
wrong (`driver_recurrence_class` vs `pooled_driver_recurrence_class`; `mut_dominant_mutation_class`
vs `mutation_landscape_class`) — i.e. the other 10 agreed with the heuristic only by luck.

WHAT IS PINNED HERE (fleet-level; the per-card structural checks live in
validate_cards._capsule_contract_check so `contracts-validate` enforces them on every card):
  1. the 12 genomic_alteration-consumed cards ALL declare primary_class + numeric_anchors — FAIL-CLOSED,
     so a new genomic card cannot ship on the heuristic;
  2. a declared `primary_class` must be a field the card's GATING rules read (the mirror-guard
     property: the capsule must show the class the verdict turns on), with a SHRINK-ONLY debt list;
  3. the remaining resolver-consumed cards without a declaration are counted as DECLARED DEBT with a
     shrink-only ceiling — the other resolvers are out of scope for this PR, but the debt is visible.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


def _load_validator():
    spec = importlib.util.spec_from_file_location("_vc_capsule", REPO / "validators" / "validate_cards.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_vc_capsule"] = mod
    spec.loader.exec_module(mod)
    return mod


VC = _load_validator()

# The cards the `genomic_alteration` resolver consumes — every one of them can move a gate verdict, so
# every one of them owes an explicit capsule projection. Read from the generated consumption map rather
# than hand-listed, so a card entering the axis lands in the fail-closed set automatically.
GENOMIC_RESOLVER = "genomic_alteration"

# DECLARED DEBT (shrink-only). `primary_class` names a field the card's gating rules do NOT read.
# Both are display-layer picks made before the mirror-guard property was checkable, and both belong to
# axes outside this PR's scope; fixing either means deciding which class the SURFACE verdict turns on,
# which is a surface-axis review, not a genomic one. test_primary_class_debt_list_only_shrinks fails if
# an entry stops being a real mismatch, so a fix cannot leave a stale exemption behind.
_PRIMARY_CLASS_GATING_DEBT = {
    "surface-abundance-density": "surface_density_class",
    "tumor-scrna-celltype-expression": "sc_expression_class",
}

# DECLARED DEBT (shrink-only): resolver-consumed cards still running on the capsule HEURISTIC. 31 before
# this PR, 21 after (the 10 genomic ones are declared here). Ceiling, not an allowlist of names — the
# point is that the number can only go down, and a NEW resolver-consumed card without a declaration
# pushes it up and fails.
_UNDECLARED_CAPSULE_CEILING = 21


def _consumption() -> dict[str, dict]:
    doc = yaml.safe_load((REPO / "coverage" / "card_resolver_consumption.yaml").read_text()) or {}
    return doc.get("detail") or {}


def _gating_read_fields() -> dict[str, set[str]]:
    """{card_id: {field, ...}} read by a GATING rule's `when` clause.

    NB the rule id key is `rule_id`, not `id` — keying on `id` yields an empty read-set for every card
    and makes every assertion below vacuously true.
    """
    partition = yaml.safe_load((REPO / "coverage" / "rule_role_partition.yaml").read_text()) or {}
    gating = set(partition.get("gating") or [])
    assert gating, "rule_role_partition.yaml carries no `gating` list — the read-map would be empty"
    reads: dict[str, set[str]] = defaultdict(set)
    for path in sorted((REPO / "interpretation-rules").glob("*.rules.yaml")):
        for rule in (yaml.safe_load(path.read_text()) or {}).get("rules") or []:
            when = rule.get("when") or {}
            if when.get("card_id") and when.get("field") and rule.get("rule_id") in gating:
                reads[when["card_id"]].add(when["field"])
    assert reads, "no gating rule parsed — check the `rule_id` / `when.card_id` keys"
    return reads


def _genomic_cards(consumption: dict) -> list[str]:
    """Cards whose rules feed the genomic_alteration resolver gate, keyed on BOTH the `resolvers`
    gate list AND the per-rule `rules` list. A card listed as consumed by the gate MUST carry at
    least one rule id — a gate cannot be fed via no rule — so an empty `rules` here means the
    consumption snapshot's `detail` is internally inconsistent (e.g. hand-edited, or a rule renamed
    without regenerating). Asserting it makes the genomic fail-closed set depend on the same
    per-rule detail that validate_card_resolver_consumption now guards, rather than on the
    card-level gate flag alone."""
    out = []
    for c, d in consumption.items():
        if GENOMIC_RESOLVER in (d.get("resolvers") or []):
            assert d.get("rules"), (
                f"{c}: consumption snapshot lists it as consumed by {GENOMIC_RESOLVER} but its "
                f"detail.rules is empty — a card cannot feed a resolver gate via zero rules; "
                f"regenerate coverage/card_resolver_consumption.yaml."
            )
            out.append(c)
    return sorted(out)


# ── 1. the genomic axis is fail-closed ────────────────────────────────────────────────────────────
def test_every_genomic_resolver_card_declares_a_capsule_projection(cards_by_id):
    """FAIL-CLOSED for the genomic axis: a card that can move the genomic_alteration verdict must say
    which class and which numbers its capsule shows, rather than inheriting an alphabetical guess."""
    cards, consumption = cards_by_id, _consumption()
    genomic = _genomic_cards(consumption)
    assert len(genomic) >= 12, f"genomic consumption set shrank to {len(genomic)} — check the map"

    missing_block, missing_class, missing_anchors = [], [], []
    for cid in genomic:
        capsule = (cards[cid] or {}).get("capsule")
        if not isinstance(capsule, dict):
            missing_block.append(cid)
            continue
        if not capsule.get("primary_class"):
            missing_class.append(cid)
        if not capsule.get("numeric_anchors"):
            missing_anchors.append(cid)
    assert not missing_block, f"genomic verdict-driving cards with no capsule: block: {missing_block}"
    assert not missing_class, (
        f"genomic capsules with no primary_class (class falls back to alphabetical): {missing_class}"
    )
    assert not missing_anchors, (
        f"genomic capsules with no numeric_anchors (anchors fall back to the hint scan, capped at 4): {missing_anchors}"
    )


# ── 2. the mirror-guard property: primary_class is what the verdict turns on ───────────────────────
def test_declared_primary_class_is_a_field_the_gating_rules_read(cards_by_id):
    """The capsule's whole job is to show the reader WHY the verdict landed where it did. If
    `primary_class` names a field no gating rule keys on, the capsule shows a class that moved nothing.

    Scoped to cards that HAVE gating rules: a card no gating rule reads is verdict-inert at the
    resolver layer, so its capsule class is a pure display choice and there is nothing to mirror.
    """
    cards, reads = cards_by_id, _gating_read_fields()
    offenders = {}
    for cid, doc in cards.items():
        pc = ((doc or {}).get("capsule") or {}).get("primary_class")
        if not pc or not reads.get(cid):
            continue
        if pc not in reads[cid] and _PRIMARY_CLASS_GATING_DEBT.get(cid) != pc:
            offenders[cid] = (pc, sorted(reads[cid]))
    assert not offenders, (
        f"capsule primary_class is not gating-read (declare it in the debt list or fix it): {offenders}"
    )


def test_primary_class_debt_list_only_shrinks(cards_by_id):
    """A debt list that outlives its debt is worse than no list — it silently exempts a card that has
    since been fixed or renamed. Every entry must still be a REAL, reachable mismatch."""
    cards, reads = cards_by_id, _gating_read_fields()
    stale = {}
    for cid, pc in _PRIMARY_CLASS_GATING_DEBT.items():
        doc = cards.get(cid)
        if doc is None:
            stale[cid] = "card no longer exists"
        elif ((doc.get("capsule") or {}).get("primary_class")) != pc:
            stale[cid] = f"no longer declares primary_class {pc!r}"
        elif not reads.get(cid):
            stale[cid] = "card has no gating rules — the check would skip it anyway"
        elif pc in reads[cid]:
            stale[cid] = f"{pc!r} IS gating-read now — remove the exemption"
    assert not stale, f"stale entries in _PRIMARY_CLASS_GATING_DEBT: {stale}"


# ── 3. the remaining debt is counted, not hidden ───────────────────────────────────────────────────
def test_undeclared_capsule_debt_only_shrinks(cards_by_id):
    """Resolver-consumed cards still on the heuristic. The other resolvers' axes are out of scope for
    this PR, but the count is a ratchet: it may fall as axes are reviewed and must never rise, so a new
    verdict-bearing card cannot quietly join the heuristic bucket."""
    cards, consumption = cards_by_id, _consumption()
    undeclared = sorted(c for c in consumption if not isinstance((cards.get(c) or {}).get("capsule"), dict))
    assert len(undeclared) <= _UNDECLARED_CAPSULE_CEILING, (
        f"{len(undeclared)} resolver-consumed cards have no capsule: (ceiling {_UNDECLARED_CAPSULE_CEILING}): "
        f"{undeclared}"
    )
    assert not (set(undeclared) & set(_genomic_cards(consumption))), "a genomic card regressed to the heuristic"


# ── 4. the per-card structural checks actually FAIL (falsification) ────────────────────────────────
def _report(tmp_path: Path, card: dict):
    p = tmp_path / "synthetic.card.yaml"
    p.write_text(yaml.safe_dump(card))
    return VC.validate_card_file(p)


def _base(capsule: dict) -> dict:
    return {
        "card_id": "synthetic-capsule-card",
        "version": "1.0.0",
        "question": "Synthetic capsule card for {target.symbol} in {indication.label}?",
        "applies_when": ["target.depmap_screened == true"],
        "required_inputs": [{"product_id": "some-manifest-v1"}],
        "methods": [{"call": "depmap-chronos"}],
        "outputs": {
            "summary_fields": ["median_chronos_panel", "dependency_class", "n_lines"],
            "summary_fields_vocabulary": {"dependency_class": ["strong", "weak", "data_unavailable"]},
        },
        "caveats": ["A caveat long enough to satisfy the minLength constraint."],
        "schema_version": 1,
        "capsule": capsule,
    }


def test_a_wellformed_capsule_declaration_is_clean(tmp_path):
    r = _report(
        tmp_path,
        _base(
            {
                "primary_class": "dependency_class",
                "categorical_fields": ["dependency_class"],
                "numeric_anchors": ["median_chronos_panel", "n_lines"],
            }
        ),
    )
    assert "CAPSULE_" not in "\n".join(r.errors + r.warnings), r.errors


@pytest.mark.parametrize(
    "capsule,token",
    [
        ({"primary_class": "dependency_clas"}, "CAPSULE_UNDECLARED_FIELD"),
        ({"categorical_fields": ["no_such_field"]}, "CAPSULE_UNDECLARED_FIELD"),
        ({"numeric_anchors": ["median_chronos_pane1"]}, "CAPSULE_UNDECLARED_FIELD"),
        ({"numeric_anchors": ["dependency_class"]}, "CAPSULE_CATEGORICAL_AS_NUMERIC"),
    ],
)
def test_a_broken_capsule_declaration_errors(tmp_path, capsule, token):
    """Each mutation is a real failure mode: a typo'd class (degrades to the alphabetical pick), a
    renamed categorical, a typo'd anchor (degrades to the hint scan), and a class token in a numeric
    anchor slot ('splice_exon_skip_class = exon_skip' rendered as a number)."""
    r = _report(tmp_path, _base(capsule))
    assert not r.ok, f"{capsule} validated clean"
    assert token in "\n".join(r.errors), r.errors


def test_the_live_fleet_passes_the_per_card_capsule_checks(card_reports):
    """The same check over every real card — this is what would have caught a declaration drifting off
    a renamed field. Runs the whole validator, but only capsule findings are asserted on, so unrelated
    pre-existing warnings on other cards do not couple into this test. Consumes the session-scoped
    `card_reports` fixture (validated once per session) rather than re-running the validator here."""
    findings = []
    for r in card_reports.values():
        findings += [m for m in r.errors + r.warnings if "CAPSULE_" in m]
    assert not findings, findings
