"""emission_invariants — the RATCHET half: one-sided, over a pinned baseline, corpus behind an env var.

Two layers, and the split between them is the design.

**(a) Hermetic, always runs.** Assertions about the BASELINE ARTIFACT itself — that it is canonical,
internally consistent, names only invariants that still exist, and carries a vintage read from each
package's own provenance. These need no corpus, so they run in CI, where there is no corpus.

★★ Without layer (a) the baseline can rot in the one direction that makes a ratchet worthless. Rename an
invariant in ``emission_invariants.py`` and all 53 banked triples name something nothing produces any
more — after which ``observed - baseline`` is empty for the same reason a dead scan's is, and the ratchet
is permanently green while reporting nothing. A ratchet whose baseline vocabulary nobody validates is a
green light wired to a disconnected sensor, and the failure is silent by construction.

**(b) The 504-package sweep, behind ``EMISSION_INVARIANTS_CORPUS=1``.** ~60 seconds and needs a corpus on
disk, so it can never be a required check::

    EMISSION_INVARIANTS_CORPUS=1 pytest skills/tests/test_emission_invariants_corpus.py -rs
    EMISSION_INVARIANTS_CORPUS=1 EMISSION_INVARIANTS_CORPUS_DIR=~/dev/other-corpus pytest ... -rs

**ONE-SIDED, no slack floor.** A ``(invariant, card_id, field)`` triple absent from the baseline is a
regression and fails; a banked triple that no longer fires is progress and only ever prints. The
asymmetry is deliberate: a two-sided ratchet with slack reds trunk immediately after the PR that banks
it, because the very next legitimate fix moves the number past the slack in the good direction.

★★ **One exception, and it is the asymmetry's own blind spot: an invariant losing its LAST witness.**
Partial progress is self-evidencing — other triples of the same invariant still fire, so the check
demonstrably still runs. Total disappearance is not: "every producer was fixed" and "the check stopped
resolving" produce an identical empty set, and the one-sided rule reads the second as the first. So a
banked invariant that now reports nothing at all is a hard failure demanding a re-bank, which is the
cheapest possible way to make a human look at it once. See
:func:`test_the_corpus_introduces_no_red_list_entry_the_baseline_does_not_name` for the measured instance.

**Counts are NOT asserted, here or ever.** ``by_invariant`` rows/packages are banked for human diffing.
A count ceiling reds on a corpus regenerated over a different package set, which is a property of the
substrate rather than of the emitters — and a baseline is a collected set plus a named red list, never a
remembered total. Do not add ``assert total_rows == 3193``; the red list is the pin.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _skills_common import emission_invariants as ei

BASELINE = Path(__file__).resolve().parent / "emission_invariants_baseline.json"

REGENERATE = "python skills/tests/regenerate_emission_invariants_baseline.py <corpus>"

CORPUS_ENV = "EMISSION_INVARIANTS_CORPUS"
CORPUS_DIR_ENV = "EMISSION_INVARIANTS_CORPUS_DIR"

SKIP_REASON = (
    f"corpus sweep is opt-in — run `{CORPUS_ENV}=1 pytest {Path(__file__).name} -rs` (~60s over 504 "
    f"packages; `{CORPUS_DIR_ENV}=<path>` overrides the corpus). ⚠️ THIS SKIP IS NOT A PASS: the "
    "hermetic baseline checks in this file ran, the sweep did not."
)


def load_baseline() -> dict:
    """The banked pre-state, or a failure that names how to produce it."""
    assert BASELINE.is_file(), f"missing baseline {BASELINE}; regenerate with: {REGENERATE}"
    return json.loads(BASELINE.read_text())


def corpus_dir(baseline: dict) -> Path:
    """Where to sweep — override, else derived from the corpus the baseline itself names.

    ★ The default is ``~/dev/<baseline["corpus"]>`` rather than a literal path, so the directory this
    test reaches for and the corpus the artifact describes cannot drift apart. Re-banking against a new
    corpus moves both in one edit.
    """
    override = os.environ.get(CORPUS_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / "dev" / str(baseline["corpus"])


def red_triples(entries) -> set[tuple[str, str, str]]:
    return {tuple(e) for e in entries}


def dark_invariants(banked, observed) -> list[str]:
    """Invariants that banked findings and now report NONE — the one vanished-finding case that fails.

    A pure function of two triple sets so it can be exercised without a corpus; the sweep below is the
    only caller. Grain is the INVARIANT, deliberately: losing some triples is progress, losing all of them
    is indistinguishable from the check going dark. See the module docstring.
    """
    return sorted({inv for inv, _, _ in banked} - {inv for inv, _, _ in observed})


#: The IDENTITY GRAIN of each invariant, measured over the fixture packages (which carry a positive case
#: for all nine) and reproduced by the corpus. A red-list triple is ``(invariant, card_id, field)`` and two
#: invariants deliberately leave part of it EMPTY, which is a statement about what the defect is attached
#: to rather than missing data:
#:
#: * card-scoped — the defect belongs to one field of one card, the ordinary case;
#: * envelope-scoped — ``synthesis.*`` belongs to no card, so the elided JSON path IS the whole identity;
#: * file-scoped — the package as a file does not parse, so there is neither a card nor a field to name.
#:
#: ⚠️ A new invariant must be added to exactly one of these. That is a deliberate hard failure with a
#: corpus-free fix: declaring the grain is the decision, and leaving it undeclared is how an empty
#: ``card_id`` starts reading as an attribution failure instead of as an envelope-level finding.
CARD_SCOPED = frozenset(
    {
        "non_finite",
        "domain_declared",
        "domain_unglossed",
        "interval_containment",
        "interval_order",
        "class_from_unmeasured",
        "abstention_incoherent",
    }
)
ENVELOPE_SCOPED = frozenset({"non_finite_envelope"})
FILE_SCOPED = frozenset({"strict_json"})


# --------------------------------------------------------------------------------------------------
# Layer (a): hermetic — the baseline artifact must stay a usable contract with no corpus present.
# --------------------------------------------------------------------------------------------------


def test_the_baseline_is_canonical_json_and_therefore_regenerated_not_hand_edited():
    """Byte-identical to what the generator writes: ``indent=2, sort_keys=True`` plus a trailing newline.

    A hand-edited ratchet baseline is how a ratchet quietly stops meaning anything — someone shrinks the
    red list by deleting a line instead of fixing a producer. Canonical form does not make that
    impossible, but it makes the shortcut visibly different from the sanctioned route.
    """
    text = BASELINE.read_text() if BASELINE.is_file() else ""
    assert text, f"missing baseline {BASELINE}; regenerate with: {REGENERATE}"
    canonical = json.dumps(json.loads(text), indent=2, sort_keys=True, allow_nan=False) + "\n"
    assert text == canonical, f"{BASELINE.name} is not in canonical form — hand-edited? regenerate: {REGENERATE}"


def test_the_baseline_records_a_live_scan():
    """Liveness before any ceiling: every zero here would make the ratchet pass for the wrong reason.

    An empty ``red_list`` satisfies a one-sided ratchet trivially and forever, so "the census died" and
    "the corpus is clean" must not be allowed to look the same from this side.
    """
    b = load_baseline()
    assert b["n_packages"] > 0, "baseline banked zero packages — the census died before it was written"
    assert b["total_rows"] > 0, "baseline banked zero findings — a permanently green ratchet"
    assert b["red_list"], "baseline banked an empty red list — a permanently green ratchet"
    assert b["gloss_available"] is True, "baseline was banked with METRIC_GLOSS unavailable; domain checks degrade"
    assert b["heuristics"] is False, (
        "baseline was banked with heuristics=True, which includes abstention_incoherent — 6,080 rows on "
        "504/504 packages, a finding that carries zero bits and would swamp the red list"
    )


def test_the_baseline_names_only_invariants_that_still_exist():
    """The rot guard: a banked name the library no longer produces is an unfalsifiable red-list entry.

    ⚠️ SUBSET, not equality, and the direction is chosen. A baseline naming a *dead* invariant is broken
    and must red. A baseline that does not yet cover a *newly added* invariant is merely stale, and it
    cannot be re-banked without a corpus — which CI does not have — so making that red would block the
    very PR that adds an invariant. The stale direction is already covered from two other sides: the
    fixture suite makes an invariant with no positive fixture a hard failure, and layer (b) below reds any
    corpus finding the baseline does not name.
    """
    b = load_baseline()
    live = set(ei.INVARIANTS)
    assert set(b["invariants"]) <= live, f"baseline names retired invariants: {sorted(set(b['invariants']) - live)}"
    assert set(b["by_invariant"]) <= live, f"stale by_invariant keys: {sorted(set(b['by_invariant']) - live)}"
    named = {t[0] for t in b["red_list"]}
    assert named <= live, f"red-list entries name retired invariants: {sorted(named - live)}"
    assert set(b["fatal_invariants"]) <= set(ei.FATAL_INVARIANTS), (
        f"baseline calls these fatal but the library no longer does: "
        f"{sorted(set(b['fatal_invariants']) - set(ei.FATAL_INVARIANTS))}"
    )
    unbanked = live - set(b["invariants"])
    if unbanked:
        print(f"NOTE: {len(unbanked)} invariant(s) added since the baseline was banked: {sorted(unbanked)}")
        print(f"      not a failure here; re-bank with: {REGENERATE}")


def test_every_invariant_declares_an_identity_grain():
    """Adding an invariant forces a decision about what its findings are attached to.

    Without this, a new envelope-level invariant would land with an empty ``card_id`` that reads exactly
    like a card-scoped invariant whose attribution failed — and the shape test below would have to accept
    both, which retires it.
    """
    declared = CARD_SCOPED | ENVELOPE_SCOPED | FILE_SCOPED
    live = set(ei.INVARIANTS)
    assert declared == live, (
        f"grain undeclared for {sorted(live - declared)}; declared-but-retired {sorted(declared - live)}. "
        "Add each new invariant to CARD_SCOPED, ENVELOPE_SCOPED or FILE_SCOPED."
    )
    overlap = (CARD_SCOPED & ENVELOPE_SCOPED) | (CARD_SCOPED & FILE_SCOPED) | (ENVELOPE_SCOPED & FILE_SCOPED)
    assert not overlap, f"an invariant cannot have two grains: {sorted(overlap)}"


def test_the_baseline_red_list_is_sorted_deduplicated_and_shaped_by_grain():
    """The ratchet's diff messages are only readable if the artifact is diffable, an appended duplicate
    would silently absolve a triple twice, and an empty component is only legal at its declared grain.

    ⚠️ Note what the grain costs at the file level: ``strict_json`` collapses to the single triple
    ``('strict_json', '', '')`` no matter how many packages fail, so the red list records THAT the corpus
    contains unparseable packages and never HOW MANY. That is intended — the defect site for a file-level
    failure is the writer, and there is one writer — but it means the 501-of-504 magnitude lives only in
    the banked counts, for a human to diff. It is also why a newly-NaN-emitting producer is caught by
    ``non_finite`` on its own ``(card, field)`` pair rather than by this entry, which is already banked.
    """
    b = load_baseline()
    entries = [tuple(e) for e in b["red_list"]]
    for e in entries:
        assert len(e) == 3, f"red-list entry is not an (invariant, card_id, field) triple: {e}"
        assert all(isinstance(part, str) for part in e), f"red-list entry has a non-string component: {e}"
        inv, card, field = e
        assert inv, f"red-list entry names no invariant: {e}"
        assert bool(card) == (inv in CARD_SCOPED), (
            f"{inv} is {'card' if inv in CARD_SCOPED else 'not card'}-scoped: {e}"
        )
        assert bool(field) == (inv not in FILE_SCOPED), f"{inv} is file-scoped iff it names no field: {e}"
    assert entries == sorted(entries), "red_list is not sorted; regenerate rather than appending by hand"
    assert len(entries) == len(set(entries)), "red_list contains duplicate triples"


def test_the_baseline_vintage_came_from_provenance_not_from_the_directory_name():
    """★★ The guard that caught a real defect while this file's own baseline was being produced.

    ``corpus_vintage`` keeps a path-regex fallback for packages it cannot open, so it answers with a
    well-formed dict either way. Handing it package DIRECTORIES instead of package FILES makes
    ``read_text()`` raise ``IsADirectoryError``, which it catches as ``OSError`` — so a caller's type
    error was absorbed as a data-quality degrade, and every field stayed populated while every date came
    from the directory name. ``dated_from`` is the only field that distinguishes the two, which is why it
    is banked and why this asserts on it rather than on the dates.

    ⇒ When a helper's fallback is broad enough to survive an unreadable input, it is broad enough to
    survive being called wrong. Assert the SOURCE, not merely the shape.
    """
    b = load_baseline()
    v = b["vintage"]
    n = b["n_packages"]
    assert v["n"] == n, f"vintage counted {v['n']} packages but the scan counted {n}"
    assert v["dated_from"]["provenance"] == n, (
        f"only {v['dated_from']['provenance']} of {n} packages were dated from their own generated_at; "
        f"the rest fell back to the path regex, so the banked vintage is a claim about the DIRECTORY NAME"
    )
    assert v["dated_from"]["path"] == 0 and v["dated_from"]["none"] == 0, f"non-provenance dates: {v['dated_from']}"
    assert v["unreadable"] == [], f"packages that would not parse when the vintage was read: {v['unreadable']}"
    assert "unknown" not in v["by_sha"], (
        f"{v['by_sha'].get('unknown')} packages carry no generated_by SHA, so the banked provenance "
        "cannot attribute a finding to the code that wrote it"
    )
    assert sum(v["by_sha"].values()) == n, "by_sha does not sum to the package count"
    assert sum(v["by_date"].values()) == n, "by_date does not sum to the package count"


def test_the_baseline_counts_agree_with_its_own_red_list():
    """Internal consistency: both blocks are projections of one finding set, so they must reconcile.

    This is what catches a partial hand-edit — a triple removed from ``red_list`` while
    ``by_invariant`` still counts the pair it came from.
    """
    b = load_baseline()
    entries = [tuple(e) for e in b["red_list"]]
    by_inv = b["by_invariant"]
    assert set(by_inv) == {t[0] for t in entries}, "by_invariant and red_list disagree about which invariants fired"
    assert sum(s["rows"] for s in by_inv.values()) == b["total_rows"], "per-invariant rows do not sum to total_rows"
    for inv, slot in by_inv.items():
        pairs = {(t[1], t[2]) for t in entries if t[0] == inv}
        assert slot["card_field_pairs"] == len(pairs), (
            f"{inv}: by_invariant declares {slot['card_field_pairs']} (card, field) pairs but the red list "
            f"names {len(pairs)}"
        )
        assert slot["rows"] >= slot["packages"], f"{inv}: fewer rows than packages"
        assert slot["rows"] >= slot["card_field_pairs"], f"{inv}: fewer rows than distinct (card, field) pairs"
        assert slot["packages"] <= b["n_packages"], f"{inv}: more packages than the corpus holds"


def test_an_invariant_going_dark_is_distinguished_from_partial_progress():
    """The positive fixture for the guard that stops the one-sided rule laundering a RETIRED check.

    ★★ Modelled on a live case, not a hypothetical. ``interval_containment`` resolves a TRIPLE — a ``_low``
    sibling, a ``_high`` sibling and a point estimate — so renaming ``rna_protein_r_ci95_*`` to
    ``rna_proxy_r_ci95_*`` without also emitting ``rna_proxy_r`` leaves ``_interval_triples`` with no point
    estimate to resolve, and all 115 corpus findings vanish with **no interval corrected**. Both of this
    invariant's banked triples disappear together, so ``fixed`` would print progress and the ratchet would
    stay green over a check that no longer exists.

    The guard is deliberately coarse-grained — per invariant, not per triple — because the discrimination
    it makes is only available at that grain: a surviving sibling triple PROVES the check still runs, and
    nothing else does.
    """
    ic_a = ("interval_containment", "cellline-rna-protein-concordance", "rna_protein_r")
    ic_b = ("interval_containment", "rna-protein-concordance-tumor", "rna_protein_r")
    nf = ("non_finite", "structure-features-static", "plddt_mean")
    assert {ic_a, ic_b} <= red_triples(load_baseline()["red_list"]), (
        "this fixture models the two interval_containment triples the baseline actually banks, and they "
        f"have moved — re-read the artifact before trusting the case below: {REGENERATE}"
    )
    banked = {ic_a, ic_b, nf}

    assert dark_invariants(banked, banked) == [], "nothing vanished"
    assert dark_invariants(banked, {ic_a, nf}) == [], "one of two triples vanishing is progress, not darkness"
    assert dark_invariants(banked, {nf}) == ["interval_containment"], "the key-rename case must be caught"
    assert dark_invariants(banked, {ic_a, ic_b}) == ["non_finite"], "a producer fixed corpus-wide must be re-banked"
    assert dark_invariants(banked, banked | {("strict_json", "", "")}) == [], "a NEW finding is not darkness"
    assert dark_invariants(set(), {nf}) == [], "an empty baseline has no witness to lose (liveness guards that)"


# --------------------------------------------------------------------------------------------------
# Layer (b): the sweep — opt-in, one-sided, and it must prove the scan ran before it clears anything.
# --------------------------------------------------------------------------------------------------


@pytest.mark.skipif(os.environ.get(CORPUS_ENV) != "1", reason=SKIP_REASON)
def test_the_corpus_introduces_no_red_list_entry_the_baseline_does_not_name():
    b = load_baseline()
    corpus = corpus_dir(b)
    assert corpus.is_dir(), f"corpus not found at {corpus}; point {CORPUS_DIR_ENV} at one"

    # Liveness first, for the same reason the generator asserts it: a one-sided ratchet over an empty
    # observed set is satisfied by a scan that read nothing at all.
    n_packages = sum(1 for _ in ei.iter_corpus(corpus))
    assert n_packages > 0, f"no evidence_package.json under {corpus} — the sweep read nothing"
    assert ei.gloss_available(), "METRIC_GLOSS did not load; the domain invariants are degraded"

    observed = red_triples(ei.summarise(ei.scan_corpus(corpus))["red_list"])
    banked = red_triples(b["red_list"])
    assert observed, f"swept {n_packages} packages and found nothing — verify the scan ran before trusting this green"

    print(f"corpus {corpus.name}: {n_packages} packages, {len(observed)} red-list triples (baseline {len(banked)})")
    fixed = sorted(banked - observed)
    if fixed:
        print(f"PROGRESS: {len(fixed)} banked triple(s) no longer fire — re-bank with: {REGENERATE}")
        for inv, card, field in fixed:
            print(f"  fixed  {inv:22s} {card}/{field}")

    # ★★ The one place a vanished triple must NOT print-and-pass: an invariant that lost its last witness.
    # A dark check and a fully-fixed producer set are the same empty set from here, so this refuses to
    # guess. Expect it to fire on this arc's own producer fixes — that is the point, re-banking is the
    # acknowledgement. The measured instance of the OTHER cause is in the message, because it is live:
    # peer branch fix/concordance-ci-label-and-detection-denominator renames the interval keys without
    # emitting a matching point estimate, which retires the check rather than fixing the intervals.
    dark = dark_invariants(banked, observed)
    assert not dark, (
        f"{len(dark)} banked invariant(s) now report NOTHING: {dark}. Either every producer was fixed — in "
        f"which case re-bank: {REGENERATE} — or the check stopped resolving and this green is empty. "
        "★ interval_containment keys on a TRIPLE (low, high, point estimate): renaming "
        "rna_protein_r_ci95_* to rna_proxy_r_ci95_* without also emitting rna_proxy_r leaves "
        "_interval_triples unable to resolve a point estimate, so all 115 findings vanish with no interval "
        "corrected. Confirm which cause applies before re-banking."
    )

    new = sorted(observed - banked)
    drift = ""
    if corpus.name != b["corpus"]:
        drift = (
            f"\n⚠️ swept {corpus.name} but the baseline was banked on {b['corpus']} — a new triple may be a "
            f"property of the package set rather than of the emitters. Compare denominators before fixing."
        )
    detail = "\n".join(
        f"  {'FATAL' if inv in ei.FATAL_INVARIANTS else 'warn '}  {inv:22s} {card}/{field}" for inv, card, field in new
    )
    assert not new, f"{len(new)} emission invariant finding(s) the baseline does not name:\n{detail}{drift}"
