"""Tests for the T1 emission ledger — the (card_id, field, value) triples the corpus emits.

WHY THE SHAPE OF THESE TESTS MATTERS. The natural test for a snapshot generator is

    assert committed == compute_ledger(corpus)

and it is worthless: it compares the snapshot against the very extractor that built it, so any
narrowing of the extractor narrows both sides at once and the test moves with the bug. That is
exactly how the previous rule-role guard was green on a wrong partition (see
test_rule_role_partition.py). So the checks here are of two kinds only:

  1. SYNTHETIC, HERMETIC, MUTATION-PROVED. A hand-built card + package pair where the right
     answer is known independently of the extractor, for each of the four grains and both
     arities. Every gate has a positive AND a negative case, because a gate that only ever fires
     is as broken as one that never does.
  2. PINNED BY NAME on the committed artifact. Never by count — a count moves with a swap, and
     "3 violations" stays true when one is fixed and another appears.

THE FALSE-POSITIVE HISTORY THIS SUITE EXISTS TO PIN. The first working version of the ledger
reported 18 never-observed pairs. Five (28%) were grain errors, not defects:

    4 ARRAY fields   protein_class (102/120 packages), moa_classes_present (114), ... — the walk
                     read summary[field] as a scalar and never descended into a list of tokens.
    1 RECORD field   percentile_crossing_class lives inside per_subgroup_metrics[] items.

and a further class was latent: a `lens_conditional_on: modality` field is legitimately absent
from a corpus built without --modality. The same rate (~20%) is documented independently in
test_card_vocabulary_declaration.py. Grain is therefore resolved BEFORE anything is accused, and
each exclusion is written into the artifact (`ungated_absences`) so it is auditable rather than an
invisible filter.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validators"))
import build_emission_ledger as bel  # noqa: E402

#: Pinned BY NAME, not by count. This WAS a two-file contradiction: the card declared
#: surface_density_class: [high, moderate, low, very_low, unmeasured] while
#: analysis-methods/methods/cptac_protein_deg/read.py emits this token (the "unsupported" grade:
#: a whole-cell abundance estimate that is not a valid surface density) — and that repo's
#: test_abundance_density.py ASSERTS it (test_unsupported_retains_estimate_but_flags_not_surface,
#: test_no_transmembrane_non_gpi_stays_unsupported). The contradiction was RESOLVED deliberately by
#: declaring the token in the card (the emitter's output is intentional and tested). This guard now
#: keeps the reconciliation from silently regressing back into an out-of-vocab contradiction.
ANCHOR_RECONCILED = (
    "surface-abundance-density",
    "surface_density_class",
    "not_surface_density_whole_cell_estimate",
)


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------
def _write_card(root: Path, card_id: str, summary_fields, vocabulary, records=None) -> None:
    outputs: dict = {"summary_fields": summary_fields, "summary_fields_vocabulary": vocabulary}
    if records:
        outputs["summary_fields_record_schemas"] = records
    (root / "cards").mkdir(parents=True, exist_ok=True)
    (root / "cards" / f"{card_id}.card.yaml").write_text(
        yaml.safe_dump({"card_id": card_id, "outputs": outputs}, sort_keys=False)
    )


def _write_package(root: Path, name: str, cards: list[dict]) -> None:
    pkg = root / "corpus" / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "evidence_package.json").write_text(json.dumps({"cards": cards}))


@pytest.fixture
def synthetic(tmp_path, monkeypatch):
    """A repo-shaped sandbox. Floors are lowered here; test_floors_* proves they still bite."""
    monkeypatch.setattr(bel, "CARDS", tmp_path / "cards")
    monkeypatch.setattr(bel, "LEDGER_PATH", tmp_path / "coverage" / "emission_ledger.yaml")
    monkeypatch.setattr(bel, "MIN_PACKAGES", 1)
    monkeypatch.setattr(bel, "MIN_CARDS_WITH_OBSERVATIONS", 1)
    return tmp_path


# ---------------------------------------------------------------------------
# grain resolution — the four-way split that removed a 28% false-positive rate
# ---------------------------------------------------------------------------
def test_grain_is_resolved_four_ways(synthetic):
    _write_card(
        synthetic,
        "c",
        ["plain", {"name": "lensed", "lens_conditional_on": "modality"}, "recs"],
        {
            "plain": ["a", "b"],
            "lensed": ["a", "b"],
            "inside": ["a", "b"],
            "nowhere": ["a", "b"],
        },
        records={"recs": {"inside": {"enum": ["a", "b"], "type": "string"}}},
    )
    grains = {f: s["grain"] for f, s in bel.load_declared()["c"].items()}
    assert grains == {
        "plain": "scalar",
        "lensed": "lens:modality",
        "inside": "record:recs",
        "nowhere": "orphan",
    }
    # Only scalar and record can be accused of never being observed.
    assert bel.gated_grain("scalar") and bel.gated_grain("record:recs")
    assert not bel.gated_grain("lens:modality") and not bel.gated_grain("orphan")


def test_array_field_is_censused_not_accused(synthetic):
    """The 4-field false positive: a list of tokens is data, not an absence."""
    _write_card(synthetic, "c", ["klass"], {"klass": ["kinase", "gpcr", "ligase"]})
    for i in range(3):
        _write_package(synthetic, f"T{i}-IND", [{"card_id": "c", "summary": {"klass": ["kinase", "gpcr"]}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    row = ledger["by_card"]["c"]["klass"]
    assert row["status"] == "observed", "an array of tokens must not read as never-observed"
    assert row["arity"] == "array"
    assert row["observed"] == {"gpcr": 3, "kinase": 3}
    assert row["never_emitted"] == ["ligase"]
    # A package contributes SEVERAL tokens, so top/total is a token share, not a package share.
    assert row["saturation"] is None and "saturation_na" in row
    assert ledger["known_never_observed"]["keys"] == []


def test_record_grain_is_censused_by_descending(synthetic):
    _write_card(
        synthetic,
        "c",
        ["rows"],
        {"klass": ["x", "y"]},
        records={"rows": {"klass": {"enum": ["x", "y"], "type": "string"}}},
    )
    _write_package(
        synthetic,
        "T-IND",
        [{"card_id": "c", "summary": {"rows": [{"klass": "x"}, {"klass": "x"}, {"klass": "y"}]}}],
    )
    row = bel.compute_ledger(synthetic / "corpus")["by_card"]["c"]["klass"]
    assert row["grain"] == "record:rows"
    assert row["observed"] == {"x": 2, "y": 1}
    assert row["status"] == "observed"


# ---------------------------------------------------------------------------
# "no value" has four causes and four different repairs
# ---------------------------------------------------------------------------
def test_four_causes_of_no_value_are_distinguished(synthetic):
    _write_card(synthetic, "absent_card", ["f"], {"f": ["a"]})
    _write_card(synthetic, "absent_field", ["f"], {"f": ["a"]})
    _write_card(synthetic, "empty_array", ["f"], {"f": ["a"]})
    _write_card(synthetic, "all_null", ["f"], {"f": ["a"]})
    _write_package(
        synthetic,
        "T-IND",
        [
            {"card_id": "absent_field", "summary": {"other": "z"}},
            {"card_id": "empty_array", "summary": {"f": []}},
            {"card_id": "all_null", "summary": {"f": None}},
        ],
    )
    reasons = bel.compute_ledger(synthetic / "corpus")["known_never_observed"]["reasons"]
    assert reasons == {
        "absent_card::f": "card_never_emitted",
        "absent_field::f": "field_absent",
        "empty_array::f": "always_empty_array",
        "all_null::f": "always_null",
    }, "collapsing these four reports the wrong defect: 'wire the card' vs 'the producer computes nothing'"


# ---------------------------------------------------------------------------
# out_of_vocab — the gate. Positive path runs offline with no corpus.
# ---------------------------------------------------------------------------
def test_out_of_vocab_is_detected_and_gates(synthetic):
    _write_card(synthetic, "c", ["f"], {"f": ["declared_only"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"f": "undeclared"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    assert ledger["by_card"]["c"]["f"]["out_of_vocab"] == ["undeclared"]
    assert ledger["known_out_of_vocab"]["keys"] == ["c::f::undeclared"]
    # And the hermetic half reproduces it from the committed counts alone — no corpus.
    (synthetic / "coverage").mkdir(exist_ok=True)
    bel.LEDGER_PATH.write_text(yaml.safe_dump(ledger))
    assert bel.self_check_hermetic(ledger) == []  # listed -> quiet
    ledger["known_out_of_vocab"]["keys"] = []  # unlist it -> must red
    errs = bel.self_check_hermetic(ledger)
    assert any("unlisted violation c::f::undeclared" in e for e in errs)


def test_bool_emission_against_string_vocabulary_is_a_type_note_not_a_violation(synthetic):
    """The card schema mandates string-only vocabularies, so ['true','false'] vs Python True is
    dead by construction. Five real cards do this; a naive comparison shipped five false gate hits."""
    _write_card(synthetic, "c", ["flag"], {"flag": ["true", "false"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"flag": True}}])
    row = bel.compute_ledger(synthetic / "corpus")["by_card"]["c"]["flag"]
    assert row["out_of_vocab"] == [], "a bool against a string vocabulary must not gate"
    assert row["observed"] == {"true": 1}
    assert row["emitted_types"] == {"bool": 1}, "but the type mismatch must still be reported"


# ---------------------------------------------------------------------------
# never_observed — the gate that makes the subset_high failure class impossible
# ---------------------------------------------------------------------------
def test_newly_declared_unemitted_scalar_field_reds(synthetic):
    _write_card(synthetic, "c", ["known", "brand_new"], {"known": ["a"], "brand_new": ["x", "y"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"known": "a"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    ledger["known_never_observed"] = {"as_of": "1970-01-01", "keys": [], "reasons": {}}
    errs = bel.self_check_hermetic(ledger)
    assert any("NEW never_observed c::brand_new" in e for e in errs), (
        "declaring a key space no method produces must red — this is the check that would have "
        "stopped a 21-PR arc whose binding conjunct fired ~0x"
    )


@pytest.mark.parametrize(
    "subject,extra_field,extra_vocab,why",
    [
        (
            "lensed",
            [{"name": "lensed", "lens_conditional_on": "modality"}],
            {"lensed": ["a"]},
            "a lens-conditional field is expected-absent in a lens-free corpus",
        ),
        (
            "orphaned",
            [],
            {"orphaned": ["a"]},
            "an orphan vocabulary is already gated by validate_cards; re-gating double-reports it",
        ),
    ],
)
def test_ungated_grains_are_excused_by_name_not_accused(synthetic, subject, extra_field, extra_vocab, why):
    """NEGATIVE CONTROLS. A gate that fires on everything is as broken as one that never fires.

    `anchor` is emitted, so the ONLY absent pair is the subject — otherwise a stray unemitted field
    of my own making satisfies the assertion and the subject is never actually exercised.
    """
    _write_card(synthetic, "c", extra_field + ["anchor"], {**extra_vocab, "anchor": ["a"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"anchor": "a"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    assert ledger["known_never_observed"]["keys"] == [], why
    # Excused BY NAME: a silent filter and a published exclusion are indistinguishable downstream.
    excused = {k for v in ledger["ungated_absences"].values() for k in v}
    assert excused == {f"c::{subject}"}, "the exclusion must be written out, not applied invisibly"
    assert bel.self_check_hermetic(ledger) == [], why


def test_an_absence_in_neither_summary_list_reds(synthetic):
    """The partition guard, and the regression test for a measured vacuity.

    `ungated_absences` originally filtered on row PRESENCE rather than on observations. Since the
    walker writes a row for every declared pair it looks for — absent ones included — the filter
    swallowed every case it existed to publish: the artifact carried `{}` while four orphan
    vocabularies appeared in neither summary list. An absence must always be either gated or
    excused, so that a clean-looking ledger cannot hide a dead field.
    """
    _write_card(synthetic, "c", ["anchor"], {"anchor": ["a"], "orphaned": ["a"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"anchor": "a"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    assert bel.self_check_hermetic(ledger) == []
    ledger["ungated_absences"] = {}  # drop the excuse without fixing the absence
    errs = bel.self_check_hermetic(ledger)
    assert any("unreported absence c::orphaned" in e for e in errs)


# ---------------------------------------------------------------------------
# staleness, integrity, vacuity
# ---------------------------------------------------------------------------
def test_renamed_field_is_stale_not_a_silent_shrink(synthetic):
    _write_card(synthetic, "c", ["f"], {"f": ["a"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"f": "a"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    _write_card(synthetic, "c", ["f_renamed"], {"f_renamed": ["a"]})  # rename, don't regenerate
    errs = bel.self_check_hermetic(ledger)
    assert any("stale entry c::f" in e for e in errs)


def test_narrowing_a_vocabulary_is_reported_as_safety_adverse(synthetic):
    _write_card(synthetic, "c", ["f"], {"f": ["keep", "drop"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"f": "drop"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    assert ledger["known_out_of_vocab"]["keys"] == []
    _write_card(synthetic, "c", ["f"], {"f": ["keep"]})  # narrow it
    errs = bel.self_check_hermetic(ledger)
    assert any("NEW out_of_vocab c::f::drop" in e and "SAFETY-ADVERSE" in e for e in errs), (
        "the card no longer admits a value the corpus still emits — a rule keyed on it is now "
        "pointed at a token the contract rejects"
    )


def test_row_integrity_catches_a_fabricated_count(synthetic):
    """The hermetic half cannot re-measure the corpus, but it need not trust a row's own arithmetic."""
    _write_card(synthetic, "c", ["f"], {"f": ["a", "b"]})
    for i in range(3):
        _write_package(synthetic, f"T{i}-IND", [{"card_id": "c", "summary": {"f": "a"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")
    assert bel.self_check_hermetic(ledger) == []
    ledger["by_card"]["c"]["f"]["observed"]["a"] = 999
    errs = bel.self_check_hermetic(ledger)
    assert any("internally inconsistent" in e for e in errs)


def test_vintage_mismatch_skips_while_same_vintage_drift_still_reds(synthetic):
    """The two halves of one decision, tested together on purpose.

    A vintage mismatch is downgraded to a skip so preland does not red for every developer whose
    corpus is newer than the committed ledger. That downgrade is only safe if the case this half
    exists for — same corpus, different counts — is still fatal. Testing the skip alone would let a
    later widening of the skip condition swallow real count drift.
    """
    _write_card(synthetic, "c", ["f"], {"f": ["a"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"f": "a"}}])
    ledger = bel.compute_ledger(synthetic / "corpus")

    ledger["by_card"]["c"]["f"]["observed"] = {"a": 99}  # same vintage, wrong count
    errs, skipped = bel.self_check_corpus(ledger, synthetic / "corpus")
    assert skipped is None, "a matching vintage must be compared, never skipped"
    assert any("count drift c::f" in e for e in errs)

    ledger["corpus_vintage"] = "target-archetype-corpus-19700101"  # now incomparable
    errs, skipped = bel.self_check_corpus(ledger, synthetic / "corpus")
    assert errs == [], "counts from two corpora are not comparable, so none may be reported"
    assert skipped and "vintage mismatch" in skipped, "and the skip must be announced with a reason"


def test_floors_trip_on_an_empty_corpus(tmp_path, monkeypatch):
    """Anti-vacuity: a ledger that finds nothing reads identically to a clean repo."""
    monkeypatch.setattr(bel, "CARDS", tmp_path / "cards")
    _write_card(tmp_path, "c", ["f"], {"f": ["a"]})
    (tmp_path / "corpus").mkdir()
    ledger = bel.compute_ledger(tmp_path / "corpus")
    errs = bel._floors(ledger)
    assert any("n_packages=0" in e for e in errs)
    assert any("cards_with_observations" in e for e in errs)
    # and main() must REFUSE to write, not write a vacuous artifact
    monkeypatch.setattr(bel, "LEDGER_PATH", tmp_path / "coverage" / "emission_ledger.yaml")
    assert bel.main(["--corpus", str(tmp_path / "corpus")]) == 1
    assert not bel.LEDGER_PATH.exists()


# ---------------------------------------------------------------------------
# the committed artifact
# ---------------------------------------------------------------------------
def test_committed_ledger_passes_the_hermetic_self_check():
    assert bel.LEDGER_PATH.exists(), "coverage/emission_ledger.yaml must be committed"
    ledger = yaml.safe_load(bel.LEDGER_PATH.read_text())
    assert bel.self_check_hermetic(ledger) == []


def test_committed_ledger_keeps_the_anchor_reconciled():
    """Pinned BY NAME: the card/emitter contradiction on this token was resolved deliberately by
    declaring it in the card. This guard keeps that reconciliation from regressing — if the token
    ever drops out of the card's declared vocabulary again, it reappears as an out-of-vocab
    contradiction (analysis-methods still emits and asserts it), and this fails LOUDLY."""
    card_id, field, token = ANCHOR_RECONCILED
    ledger = yaml.safe_load(bel.LEDGER_PATH.read_text())
    row = ledger["by_card"][card_id][field]
    assert token in row["declared"]
    assert token not in row["out_of_vocab"]
    assert f"{card_id}::{field}::{token}" not in ledger["known_out_of_vocab"]["keys"]


def test_committed_ledger_is_not_vacuous():
    ledger = yaml.safe_load(bel.LEDGER_PATH.read_text())
    assert bel._floors(ledger) == []
    counts = ledger["counts"]
    assert counts["pairs"] > 200 and counts["cards_with_observations"] >= 100


def test_absent_provenance_is_not_reported_as_homogeneous(synthetic):
    """`{}` and a single SHA are different facts and must not render identically.

    The heterogeneity warning keyed on `len(producing_shas) > 1`, so a corpus with NO stamps at all
    — every vintage before 20260919 — passed silently as if its provenance had been verified.
    """
    _write_card(synthetic, "c", ["f"], {"f": ["a"]})
    _write_package(synthetic, "T-IND", [{"card_id": "c", "summary": {"f": "a"}}])
    unstamped = bel.compute_ledger(synthetic / "corpus")
    assert unstamped["producing_shas"] == {}
    assert unstamped["provenance"].startswith("unknown"), "absent stamps must say so"

    (synthetic / "corpus" / "T-IND" / "build_sha.json").write_text(json.dumps({"claude-oncology-skills": "abc123"}))
    stamped = bel.compute_ledger(synthetic / "corpus")
    assert stamped["producing_shas"] == {"abc123": 1}
    assert stamped["provenance"] == "homogeneous"

    _write_package(synthetic, "U-IND", [{"card_id": "c", "summary": {"f": "a"}}])
    (synthetic / "corpus" / "U-IND" / "build_sha.json").write_text(json.dumps({"claude-oncology-skills": "def456"}))
    mixed = bel.compute_ledger(synthetic / "corpus")
    assert mixed["provenance"].startswith("heterogeneous"), "two code states, one corpus"
