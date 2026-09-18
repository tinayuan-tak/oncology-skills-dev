"""THE MAINTENANCE CONTRACT for SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES, named by the comment above
`_SAFETY_ESSENTIAL_PATTERNS` in methods/sc_normal_expression/stats.py.

WHY THIS FILE EXISTS. The safety-essential entry list is a disjunction of label matchers, and an entry
that matches NOTHING is indistinguishable, from inside the code, from a cell type that is genuinely
absent from every shard. So an inert entry reads as coverage while providing none — a silent fail-open
in a veto whose whole job is to say "this target hits a vital organ". Measured 2026-09-18: 4 of the 31
entries then shipped were inert, and two of them (`"kidney proximal tubule"`, `"pneumocyte"`) carried
comments asserting coverage they did not provide. Nothing in the suite could have caught that, because
every existing test fed the matcher HAND-WRITTEN labels — which are, by construction, labels the author
already believed matched. The only instrument that can catch it is the REAL vocabulary.

HOW IT IS TESTED OFFLINE. `sc_normal_cell_type_vocabulary_20260918.json` pins the distinct `cell_type`
vocabulary of all 19 landed shards (670 labels), read live from S3 with no row filter. Refresh it with
`regenerate_cell_type_vocabulary.py` when a shard release lands.

DIRECTIONALITY OF THE SNAPSHOT, which decides what may be asserted against it:
  * "entry E matches >= 1 real label" — SOUND and durable. A release can only add labels, so an entry
    live today stays live unless a label is RENAMED, which this test would then catch as a red.
  * "entry E matches NOTHING anywhere" — sound only AS OF the snapshot. Such entries are therefore an
    explicit, exactly-pinned allowlist, not a `<=` subset check: a new inert entry must be a deliberate
    edit here with a written reason, never a quiet addition to a growing set.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from methods.sc_normal_expression.stats import (
    _SAFETY_ESSENTIAL_PATTERNS as PATTERNS,
)
from methods.sc_normal_expression.stats import (
    SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES as ENTRIES,
)
from methods.sc_normal_expression.stats import (
    _is_safety_essential,
)

SNAPSHOT_PATH = pathlib.Path(__file__).with_name("sc_normal_cell_type_vocabulary_20260918.json")
_SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text())
SHARDS: dict[str, list[str]] = _SNAPSHOT["shards"]
ALL_LABELS: list[str] = sorted(set().union(*map(set, SHARDS.values())))

# The 9 shards queried for EVERY indication (SC_NORMAL_CROSSWALK's non-None organs). A label that
# occurs only outside these can never produce a cross-indication veto: it grades
# origin_tissue_liability for its own indication and is invisible for the rest. So "this entry is
# reachable" and "this entry is reachable OFF-ORIGIN" are two different questions, and only the second
# one is what the killer reads.
#
# Written out as a LITERAL on purpose rather than imported, so it states the intended panel
# independently of the code under test — and then pinned against the crosswalk by
# test_always_on_literal_tracks_the_crosswalk below, so the two cannot drift apart silently. Importing
# it would make every reachability assertion below re-derive from the same source it is checking.
ALWAYS_ON_SHARDS = (
    "heart",
    "liver",
    "kidney",
    "bone_marrow",
    "brain",
    "adrenal_gland",
    "lung",
    "pancreas",
    "colon",  # + 2026-09-18: the `gut` promotion, 8 shards -> 9
)


def _runs(entry) -> tuple[str, ...]:
    """The matcher's own entry->runs rule, restated once here so the tests read declaratively."""
    return (entry,) if isinstance(entry, str) else tuple(entry)


def _matches(entry) -> list[str]:
    pats = [re.compile(r"\b" + re.escape(run) + r"\b") for run in _runs(entry)]
    return [lab for lab in ALL_LABELS if all(p.search(lab.lower()) for p in pats)]


# ---------------------------------------------------------------------------------------------------
# The snapshot is the instrument. Guard the instrument before trusting anything measured with it: if it
# silently emptied, EVERY "matches >= 1" assertion below would flip to a red for the wrong reason, and
# every "matches nothing" assertion would pass vacuously.
# ---------------------------------------------------------------------------------------------------


def test_vocabulary_snapshot_is_intact():
    assert len(SHARDS) == 19, f"expected 19 landed shards in the snapshot, got {len(SHARDS)}"
    assert len(ALL_LABELS) == 670, f"expected 670 distinct labels, got {len(ALL_LABELS)}"
    assert _SNAPSHOT["_provenance"]["n_distinct_labels"] == len(ALL_LABELS), (
        "the snapshot's declared label count disagrees with its own payload"
    )
    for shard in ALWAYS_ON_SHARDS:
        assert SHARDS.get(shard), f"always-on shard {shard!r} missing or empty in the snapshot"


def test_always_on_literal_tracks_the_crosswalk():
    """Bind the hand-written panel above to the crosswalk that actually decides which shards a run
    reads. Without this, the two can drift in the direction that MATTERS: promote an organ in
    SC_NORMAL_CROSSWALK and every `reachable_off_origin: False` pin below becomes a stale claim that
    still passes, because the pins are computed against the literal rather than against the code. The
    literal is kept (not replaced by an import) so the reach assertions state intent independently —
    this test is what makes keeping it safe."""
    from methods.normal_tissue_safety_common.essential_organs import SC_NORMAL_ESSENTIAL_TISSUES

    assert set(ALWAYS_ON_SHARDS) == set(SC_NORMAL_ESSENTIAL_TISSUES), (
        "the always-on panel and SC_NORMAL_CROSSWALK disagree; every off-origin reachability pin in "
        "EXPECTED_MATCHES is measured against the literal, so a crosswalk change that is not "
        "mirrored here silently invalidates them.\n"
        f"  in the crosswalk, not in the literal: {sorted(set(SC_NORMAL_ESSENTIAL_TISSUES) - set(ALWAYS_ON_SHARDS))}\n"
        f"  in the literal, not in the crosswalk: {sorted(set(ALWAYS_ON_SHARDS) - set(SC_NORMAL_ESSENTIAL_TISSUES))}"
    )
    assert len(ALWAYS_ON_SHARDS) == len(set(ALWAYS_ON_SHARDS)), "duplicate shard in the literal"


# ---------------------------------------------------------------------------------------------------
# Structural well-formedness of the two entry forms.
# ---------------------------------------------------------------------------------------------------


def test_every_entry_is_a_well_formed_run_or_conjunction():
    """An EMPTY tuple is the catastrophic shape: `all(p.search(ct) for p in ())` is vacuously True, so
    an entry with no runs would flag EVERY cell type in every shard and the veto would fire on all 504
    pairs. It is one deleted line away at any time and produces no error, so it is pinned here rather
    than left to review. Same for an empty string, whose `\\b\\b` matches at any word boundary."""
    for entry in ENTRIES:
        assert isinstance(entry, (str, tuple)), f"{entry!r}: entries are str or tuple[str, ...]"
        runs = _runs(entry)
        assert runs, f"{entry!r}: an entry with no runs matches EVERY label (vacuous `all`)"
        for run in runs:
            assert isinstance(run, str) and run.strip(), f"{entry!r}: run {run!r} is empty"
            assert run == run.lower(), f"{entry!r}: run {run!r} must be lowercase (labels are lowered)"


def test_a_one_run_conjunction_is_exactly_the_string_form():
    """The tuple form must be a strict GENERALISATION, not a second dialect: `("hepatocyte",)` and
    `"hepatocyte"` have to select the same labels, or the two forms have diverged and reviewers can no
    longer reason about the list uniformly."""
    for entry in ENTRIES:
        if isinstance(entry, str):
            assert _matches(entry) == _matches((entry,)), f"{entry!r}: forms disagree"


def test_compiled_patterns_track_the_entry_list():
    assert len(PATTERNS) == len(ENTRIES)
    for entry, runs in zip(ENTRIES, PATTERNS):
        assert len(runs) == len(_runs(entry)), f"{entry!r}: compiled run count differs"


# ---------------------------------------------------------------------------------------------------
# THE HEADLINE GUARD: no entry may be silently inert.
# ---------------------------------------------------------------------------------------------------

# Entries that match nothing in ANY landed shard, each with the reason it is nonetheless kept. Pinned
# EXACTLY (==, not <=) so a newly-inert entry is a red rather than a quiet subset growth.
INTENTIONALLY_INERT = {
    # No eye/cornea shard exists in TISSUE_TO_PRODUCT. Listed so FOLR1's real dose-limiting ocular
    # toxicity (keratopathy) activates automatically if a corneal/limbal normal shard ever lands.
    "corneal epithelial cell",
    "limbal stem cell",
    # Census uses "pulmonary alveolar type 1/2 cell", never "pneumocyte". Kept because "type I
    # pneumocyte" is a live Cell Ontology synonym a future Census release could adopt. Its ORIGINAL
    # comment claimed it covered alveolar type I/II — it did not; the neighbouring entry did, so the
    # arm worked by accident. That false assurance is exactly what this test is here to prevent.
    "pneumocyte",
}


def test_no_entry_is_silently_inert():
    measured = {e if isinstance(e, str) else tuple(e) for e in ENTRIES if not _matches(e)}
    assert measured == INTENTIONALLY_INERT, (
        "INERT ENTRY SET CHANGED. An entry matching no real label provides no coverage while looking "
        f"like coverage.\n  newly inert (FIX THE ENTRY): {sorted(map(str, measured - INTENTIONALLY_INERT))}"
        f"\n  no longer inert (REMOVE FROM THE ALLOWLIST + drop the 'inert' comment): "
        f"{sorted(map(str, INTENTIONALLY_INERT - measured))}"
    )


def test_the_inert_allowlist_itself_is_not_vacuous():
    """Anti-vacuity for the guard above: if `_matches` were broken so that everything matched, the
    allowlist comparison would still pass whenever the allowlist happened to be empty. Assert the
    allowlist is non-empty AND that its members really are the ones with zero hits."""
    assert INTENTIONALLY_INERT, "an empty allowlist makes the inert check unfalsifiable"
    for entry in INTENTIONALLY_INERT:
        assert entry in ENTRIES, f"{entry!r} is allowlisted but no longer in the entry list"
        assert _matches(entry) == [], f"{entry!r} is allowlisted as inert but matches labels"


# ---------------------------------------------------------------------------------------------------
# Per-entry match counts for the entries this change touched, and the off-origin reachability ledger.
# ---------------------------------------------------------------------------------------------------

# entry -> (n_matching_labels, reachable_off_origin) measured live 2026-09-18 against all 19 shards.
EXPECTED_MATCHES = {
    ("proximal", "tubule"): (4, True),
    ("distal", "tubule"): (3, True),
    ("connecting", "tubule"): (2, True),
    ("kidney", "collecting duct"): (7, True),
    "kidney loop of henle": (7, True),
    "nephron": (3, True),
    "pulmonary alveolar type": (3, True),
    ("alveolar", "epithelial cell"): (2, True),
    "podocyte": (1, True),
    # --- GUT / INTESTINAL EPITHELIUM, added with the `gut -> colon` promotion (2026-09-18).
    # `colonocyte` is the entry that PROVES the promotion did something: it was pinned (3, False)
    # before this change with a comment predicting that "adding colon to SC_NORMAL_CROSSWALK shows
    # up here as a deliberate change in reach". It did — False -> True, measured. Eight more entries
    # flipped with it, and each is written out rather than summarised so that a future de-promotion
    # reds nine specific lines instead of one aggregate.
    "colonocyte": (3, True),
    "crypt": (4, True),
    "transit amplifying cell": (3, True),
    "paneth cell": (3, True),
    ("goblet", "intestine"): (3, True),
    ("goblet", "colon"): (1, True),
    ("intestinal", "epithelial cell"): (1, True),
    ("colon", "epithelial cell"): (1, True),
    "gut absorptive cell": (1, True),
    # `enterocyte` was ALREADY off-origin reachable before this change, which is not the good news it
    # looks like: its 8 labels reach adrenal_gland, lung and pancreas, i.e. Census annotation leakage
    # rather than real ectopic gut. So the pre-change gut arm's only cross-indication reach came from
    # mis-annotation. Pinned to keep that visible — if the leakage is ever cleaned up upstream this
    # drops to on-origin-only and the count moves.
    "enterocyte": (8, True),
    # Reachable, but ONLY in shards queried for their own indication. These grade
    # origin_tissue_liability and can never drive a cross-indication veto, so their coverage is real
    # yet the killer never sees it.
    #
    # ⚠️ `("intestine", "epithelial cell")` is one of THIS change's own additions and is
    # off-origin-INERT: its single label ("epithelial cell of small intestine") occurs in the
    # `small_intestine` shard alone, and `small_intestine` was deliberately NOT promoted to the
    # always-on panel (SC_NORMAL_CROSSWALK maps it to None — the marginal probe measured it improving
    # the panel's worst severity for 2 of 262 genes, both already moderate_severity, so 0 class
    # moves, against ~11% more Census reads on every run). Kept because it DOES grade
    # origin_tissue_liability for GI indications, which is where a small-intestine antigen matters
    # most — but pinned False so nobody reads it as cross-indication coverage. Promoting
    # `small_intestine` later is what flips this line.
    ("intestine", "epithelial cell"): (1, False),
    "keratinocyte": (3, False),
    "basal cell of epidermis": (1, False),
}


@pytest.mark.parametrize("entry", list(EXPECTED_MATCHES))
def test_entry_match_count_and_off_origin_reach(entry):
    expected_n, expected_reach = EXPECTED_MATCHES[entry]
    # Membership first. Everything below computes patterns from the dict KEY, so it measures the
    # entry->label relation and is completely insensitive to whether the entry is still in the list:
    # measured by mutation 2026-09-18, deleting `"crypt"` from SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES left
    # its `(4, True)` pin GREEN. A pinned entry that no longer exists is the strongest form of the
    # fail-open this whole file guards against, so assert it is really shipped.
    assert entry in ENTRIES, f"{entry!r} has a pinned match count but is no longer in the entry list"
    hits = _matches(entry)
    assert len(hits) == expected_n, f"{entry!r}: expected {expected_n} matching labels, measured {len(hits)}: {hits}"
    reachable = any(lab in SHARDS[shard] for shard in ALWAYS_ON_SHARDS for lab in hits)
    assert reachable is expected_reach, (
        f"{entry!r}: off-origin reachability changed (expected {expected_reach}). An entry that is "
        "reachable only on-origin cannot produce a cross-indication veto."
    )


def test_expected_matches_covers_every_entry_this_change_touched():
    """Anti-vacuity: the parametrized test above proves nothing about entries absent from the dict, so
    pin that the dict actually contains the conjunctive entries — the new, untested-by-anything-else
    entry form."""
    conjunctions = {tuple(e) for e in ENTRIES if not isinstance(e, str)}
    assert conjunctions, "no conjunctive entries found; the tuple form has been reverted"
    missing = conjunctions - set(EXPECTED_MATCHES)
    assert not missing, f"conjunctive entries with no pinned match count: {sorted(map(str, missing))}"


# ---------------------------------------------------------------------------------------------------
# The two label shapes the contiguous form could not express. These are the defect, stated as data.
# ---------------------------------------------------------------------------------------------------

OF_INVERTED = [
    # Census writes the compartment AFTER "of", so no contiguous "<organ> <compartment>" run matches.
    "epithelial cell of proximal tubule",
    "epithelial cell of proximal tubule segment 1",
    "epithelial cell of proximal tubule segment 3",
    "epithelial cell of nephron",
]
INTERPOSED_QUALIFIER = [
    # An anatomical qualifier sits BETWEEN the two required words.
    "kidney proximal convoluted tubule epithelial cell",
    "kidney cortex collecting duct epithelial cell",
    "kidney inner medulla collecting duct epithelial cell",
    "kidney outer medulla collecting duct intercalated cell",
    "kidney distal convoluted tubule epithelial cell",
    "epithelial cell of early distal convoluted tubule",
]


@pytest.mark.parametrize("label", OF_INVERTED + INTERPOSED_QUALIFIER)
def test_non_adjacent_label_forms_are_flagged(label):
    assert label in ALL_LABELS, f"{label!r} is not in the pinned vocabulary — fixture is stale"
    assert _is_safety_essential(label), f"{label!r} is a real vital-organ label that the contiguous-run form missed"


# ---------------------------------------------------------------------------------------------------
# The other direction. A widening that also over-reaches is not a fix, so pin what must stay UNflagged.
# ---------------------------------------------------------------------------------------------------

MUST_NOT_FLAG = [
    # The deliberate false-positive REMOVAL in this change: a stromal fibroblast was being fed into a
    # vital-organ veto by the entry `"alveolar type"`, which matched "alveolar type 1". It reaches
    # shipped fixtures (surface-modality-fit/tests/fixtures/erbb2_coadread.yaml carries it at 0.0769).
    "alveolar type 1 fibroblast cell",
    # Not renal. This is why the collecting-duct fix is a CONJUNCTION with "kidney" rather than a
    # loosening to the bare head noun "collecting duct".
    "airway submucosal gland collecting duct epithelial cell",
]


@pytest.mark.parametrize("label", MUST_NOT_FLAG)
def test_over_reach_labels_stay_unflagged(label):
    assert label in ALL_LABELS, f"{label!r} is not in the pinned vocabulary — fixture is stale"
    assert not _is_safety_essential(label), f"{label!r} must not enter a vital-organ veto"


# The GI compartments the `gut` promotion's rationale names as dose-limiting, and the labels in the
# newly always-on `colon` shard that carry them. Promoting an organ whose most drug-exposed cell type
# no entry matches would ship coverage that reads as coverage and is not — the same fail-open the
# renal block closes below, which is why the organ promotion and the entry additions are one PR.
GUT_DOSE_LIMITING_COMPARTMENTS = {
    "crypt": r"\bcrypt\b",
    "transit amplifying": r"transit amplifying",
    "paneth": r"\bpaneth\b",
    "absorptive": r"colonocyte|enterocyte",
    "goblet": r"\bgoblet\b",
}

# The ONE label in a named compartment above that stays unflagged, pinned so the residual is visible
# and cannot grow silently. Census's bare "goblet cell" carries no organ token, so no conjunction can
# reach it, and flagging the bare run would pull in FIVE airway goblet labels (bronchial / lung /
# nasal / respiratory tract / tracheobronchial) — re-grading the LUNG arm, which is not this change's
# subject and would make its backtest unattributable. Residual cost, stated: an atlas that annotated
# colonic goblet cells ONLY to the bare parent contributes nothing to the veto. The organ-qualified
# labels ("colon goblet cell", "intestine goblet cell", ...) are covered, and the bare label is
# additionally shard-promiscuous (it occurs in adrenal_gland and liver, i.e. annotation leakage).
GUT_KNOWN_RESIDUAL = {"goblet cell"}


def test_the_gut_dose_limiting_compartments_are_covered_in_the_always_on_colon_shard():
    colon = SHARDS["colon"]
    assert "colon" in ALWAYS_ON_SHARDS, "this test is about CROSS-indication reach; colon must be always-on"
    residual: set[str] = set()
    for name, rx in GUT_DOSE_LIMITING_COMPARTMENTS.items():
        labels = [lab for lab in colon if re.search(rx, lab.lower())]
        # Anti-vacuity, per compartment: an empty label list would make "all flagged" trivially true,
        # and a renamed Census label is exactly how that happens.
        assert labels, f"compartment {name!r} matched no label in the colon shard — regex or vocabulary is stale"
        residual |= {lab for lab in labels if not _is_safety_essential(lab)}
    assert residual == GUT_KNOWN_RESIDUAL, (
        "gut dose-limiting coverage in the always-on colon shard changed.\n"
        f"  newly unflagged (a FAIL-OPEN in the promoted organ): {sorted(residual - GUT_KNOWN_RESIDUAL)}\n"
        f"  no longer unflagged (drop from GUT_KNOWN_RESIDUAL): {sorted(GUT_KNOWN_RESIDUAL - residual)}"
    )


def test_the_gut_residual_allowlist_is_not_vacuous():
    """Same anti-vacuity contract as the inert allowlist: an empty residual set would make the check
    above unfalsifiable in the direction that matters."""
    assert GUT_KNOWN_RESIDUAL, "an empty residual set makes the gut coverage check unfalsifiable"
    for label in GUT_KNOWN_RESIDUAL:
        assert label in SHARDS["colon"], f"{label!r} is allowlisted but absent from the colon shard — fixture is stale"
        assert not _is_safety_essential(label), f"{label!r} is allowlisted as unflagged but IS flagged"


def test_the_renal_tubule_compartment_is_covered_completely():
    """The pre-existing list flagged loop of Henle and PART of the collecting duct while leaving the
    proximal tubule, distal convoluted tubule and connecting tubule entirely unflagged. Flagging two
    segments of one functional unit and omitting three is an inconsistency, not a design, so the whole
    tubular compartment is pinned: every label in the vocabulary containing "tubule" must be flagged."""
    tubule_labels = [lab for lab in ALL_LABELS if re.search(r"\btubule\b", lab.lower())]
    assert len(tubule_labels) == 11, f"tubule label count changed: {tubule_labels}"
    unflagged = [lab for lab in tubule_labels if not _is_safety_essential(lab)]
    assert not unflagged, f"renal tubule labels not covered by any entry: {unflagged}"
