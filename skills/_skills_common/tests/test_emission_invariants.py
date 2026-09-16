"""emission_invariants — the GATING half: hermetic, committed fixtures, no corpus, no live data.

The suite this file guards was built to answer "is the emitted data structurally valid before anything
interprets it". Its measured result over 504 corpus packages: 501 packages fail a strict JSON parse,
121,777 non-finite leaves across 50 JSON paths, 115 of 570 published confidence intervals exclude their
own point estimate — and every one of the 501 reduces to 4 producer sites with zero unexplained residue.

★★ **THE ORGANISING CONSTRAINT OF THIS FILE: FOUR OF THE NINE INVARIANTS HAVE ZERO CORPUS FINDINGS**
(``domain_declared``, ``domain_unglossed``, ``interval_order``, ``class_from_unmeasured``). Zero findings
is a legitimate and welcome result — it says the producers respect those properties — but it means those
four invariants are UNEXERCISED, and an unexercised check is indistinguishable from a broken one. So
:func:`test_every_invariant_has_a_positive_fixture` makes "an invariant nothing fires on" a hard failure
in perpetuity. That assertion is the reason this file exists; the per-invariant tests below are its
readable detail.

★★ **AND ONE FIXTURE IS A GUARD ON A REFUTATION RATHER THAN ON A BUG.** ``median_ccf`` sits at exactly
1.5 in the clean control because entering ``CCF`` in ``_UNIT_DOMAINS`` as an "obviously" [0, 1] fraction
produced 10 corpus findings of which all 10 were false — CCF is inferred as ``VAF * 2 / purity`` and the
producer clamps it at 1.5 by design. A mathematical domain constrains the QUANTITY, not a noisy
ESTIMATOR of it. See :func:`test_ccf_at_the_producers_clamp_is_not_a_domain_violation`.

Nothing here reads the corpus. The report-only corpus ratchet lives in
``skills/tests/test_emission_invariants_corpus.py`` behind ``EMISSION_INVARIANTS_CORPUS=1``, because a
504-package sweep is a 60-second measurement and not a merge gate.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import emission_invariants as ei

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "emission"

#: Every fixture package, and what it is for. Named so a reader knows the fixture set is a designed
#: matrix and not an accumulation, and so :func:`test_fixture_corpus_is_discovered` fails loudly when a
#: fixture is added or removed without a decision.
FIXTURE_PURPOSE = {
    "label_leak_non_finite": "producer bug A: pandas label leak, 98.2% of all corpus non-finite values",
    "spearman_ci_mislabelled": "producer bug: a Spearman interval under the Pearson field's prefix",
    "class_from_unmeasured": "positive fixture for an invariant with 0 corpus findings",
    "class_stem_misses_the_banded_number": "a NEGATIVE fixture: the MEASURED blind spot of that invariant",
    "domain_and_interval_order": "positive fixtures for 3 invariants with 0 corpus findings",
    "envelope_only_non_finite": "a shape the corpus has 0 instances of: envelope NaN with clean cards",
    "infinity_sentinel": "±Inf, which pd.isna admits and which wins every argmax",
    "clean_negative_control": "the negative control, deliberately loaded with near-misses",
}

#: invariant name -> the function whose docstring is authoritative for it. Two invariants share a
#: producer in each of two cases, which is why this cannot be derived from the function list.
INVARIANT_PRODUCER = {
    "non_finite": ei._non_finite,
    "non_finite_envelope": ei._non_finite_envelope,
    "domain_declared": ei._domain,
    "domain_unglossed": ei._domain,
    "interval_containment": ei._intervals,
    "interval_order": ei._intervals,
    "class_from_unmeasured": ei._class_from_unmeasured,
    "abstention_incoherent": ei._abstention_coherence,
    "strict_json": ei.strict_json_findings,
}


def scan(fixture: str, *, heuristics: bool = False) -> list[ei.Finding]:
    return ei.scan_package_file(FIXTURES / fixture / "evidence_package.json", heuristics=heuristics)


def by_invariant(findings: list[ei.Finding]) -> dict[str, list[ei.Finding]]:
    out: dict[str, list[ei.Finding]] = {}
    for f in findings:
        out.setdefault(f.invariant, []).append(f)
    return out


def one(findings: list[ei.Finding], invariant: str, field: str) -> ei.Finding:
    """The single finding for (invariant, field), asserting there is exactly one.

    Exactly-one rather than at-least-one on purpose: a duplicated finding is its own defect class here.
    ``rna_protein_r_ci95_low`` ends with BOTH ``_ci95_low`` and ``_low``, and an unguarded pairing loop
    resolved that triple twice and reported 230 corpus violations where there are 115.
    """
    hits = [f for f in findings if f.invariant == invariant and f.field == field]
    assert len(hits) == 1, f"expected exactly one {invariant} on {field!r}, got {[f.field for f in hits]}"
    return hits[0]


# ── liveness: assert the instrument ran before asserting anything about what it found ────────────────


def test_fixture_corpus_is_discovered():
    """``iter_corpus`` finds every fixture. A census that dies makes every later assertion vacuous."""
    found = {p.parent.name for p in ei.iter_corpus(FIXTURES)}
    assert found == set(FIXTURE_PURPOSE), (
        f"fixture set drifted from FIXTURE_PURPOSE; only in dir: {sorted(found - set(FIXTURE_PURPOSE))}, "
        f"only in the map: {sorted(set(FIXTURE_PURPOSE) - found)}"
    )


def test_the_declared_unit_table_is_loaded():
    """The domain invariant degrades SILENTLY to a name-based fallback when ``METRIC_GLOSS`` is absent.

    So a green ``domain_declared`` test proves nothing unless the gloss actually loaded, and the specific
    units the fixtures rely on are still declared as the fixtures assume.
    """
    assert ei.gloss_available(), "METRIC_GLOSS did not import; domain_declared would silently degrade"
    units = ei._gloss_units()
    for field, unit in (("pearson_r", "Pearson r"), ("logrank_p", "p"), ("median_ccf", "CCF")):
        assert units.get(field) == unit, f"{field} is glossed {units.get(field)!r}, fixtures assume {unit!r}"
    assert "cohort_fdr" not in units, (
        "cohort_fdr acquired a METRIC_GLOSS entry, so it now measures domain_declared and no longer "
        "exercises the unglossed name fallback — move that fixture field to another unglossed name"
    )


# ── the assertion this file exists for ──────────────────────────────────────────────────────────────


def test_every_invariant_has_a_positive_fixture():
    """Every name in ``INVARIANTS`` must fire on at least one committed fixture.

    ★★ Four invariants return ZERO findings over all 504 corpus packages, so for those four a green
    corpus sweep is evidence of nothing whatsoever — it cannot distinguish "the producers are clean"
    from "the check is broken". This is the gate that makes the difference, and it is one-sided in the
    useful direction: adding an invariant without a fixture is a hard failure, and it cannot be silenced
    by a corpus that happens not to contain the defect.
    """
    fired: set[str] = set()
    for name in FIXTURE_PURPOSE:
        fired |= {f.invariant for f in scan(name, heuristics=True)}
    missing = set(ei.INVARIANTS) - fired
    assert not missing, f"invariants with no positive fixture, so their green means nothing: {sorted(missing)}"
    unknown = fired - set(ei.INVARIANTS)
    assert not unknown, f"fixtures produced invariants absent from INVARIANTS: {sorted(unknown)}"


def test_fatal_set_matches_the_docstrings():
    """``FATAL_INVARIANTS`` membership iff the producing function's docstring says FATAL.

    The module's tiered posture is that structural invalidity refuses to serialise while everything else
    warns, and that posture is stated in prose. Prose and predicate drifted once already: omitting
    ``non_finite_envelope`` from the set left its docstring claiming FATAL while ``Finding.fatal``
    returned False on 1,220 of 1,858 corpus rows. This is the assertion that comment promised.
    """
    assert set(INVARIANT_PRODUCER) == set(ei.INVARIANTS), (
        "a new invariant must be registered in INVARIANT_PRODUCER so its FATAL claim is checked: "
        f"{sorted(set(ei.INVARIANTS) ^ set(INVARIANT_PRODUCER))}"
    )
    for name, fn in INVARIANT_PRODUCER.items():
        says_fatal = "FATAL" in (fn.__doc__ or "")
        is_fatal = name in ei.FATAL_INVARIANTS
        assert says_fatal == is_fatal, (
            f"{name}: docstring says FATAL={says_fatal} but FATAL_INVARIANTS membership is {is_fatal}"
        )
    assert ei.FATAL_INVARIANTS < set(ei.INVARIANTS), "FATAL_INVARIANTS must be a strict subset of INVARIANTS"


# ── producer bug A: the pandas label leak ───────────────────────────────────────────────────────────


def test_label_leak_is_flagged_and_named_as_a_label_not_a_computation():
    """Bug A — 119,536 leaves / 496 of 504 packages / 98.2% of every non-finite value in the corpus.

    The finding has to say WHICH defect it is, because the two look identical in the data and have
    unrelated fixes: a missing string in an object-dtype pandas column IS ``float('nan')`` and
    ``to_dict(orient="records")`` ships it, so the remedy is ``fillna`` at the frame boundary — not an
    abstain token, not a band-cascade guard, and nothing to do with measuredness.
    """
    findings = scan("label_leak_non_finite")
    name = one(findings, "non_finite", "per_line_concordance[].ccle_name")
    assert name.fatal
    assert "fillna" in name.detail and "LABEL" in name.detail
    assert "pandas" in name.detail, "the detail must name the mechanism, not just the remedy"
    lineage = one(findings, "non_finite", "per_line_concordance[].lineage")
    assert "fillna" in lineage.detail


def test_non_finite_collapses_repeats_per_elided_path():
    """One finding per (card, elided path), with the multiplicity in ``detail`` — NOT one per leaf.

    ★★ This is the regression guard on the traversal bug that cost the module 98% of its own subject
    matter, and it guards BOTH directions of it. The original ``flatten_summary`` skipped lists entirely,
    justified as *"a list element has no stable field identity, so a finding keyed on foo[3] cannot be
    baselined"* — true of the INDEX, false of the KEY. Eliding the index gives an identity MORE stable
    than a scalar path, because it survives a change in list length too. And the collapse matters as much
    as the descent: one field accounts for 119,536 of the corpus's 121,777 non-finite leaves, so emitting
    a row per leaf would make every later "N% of findings are X" a measurement of how many cell lines a
    target has.
    """
    findings = scan("label_leak_non_finite")
    name = one(findings, "non_finite", "per_line_concordance[].ccle_name")
    assert "[]" in name.field and "[0]" not in name.field, "the list index must be elided, not recorded"
    assert "2 leaves under this path" in name.detail, (
        "two NaN leaves under one path must collapse to ONE finding carrying the multiplicity"
    )
    # the third row's lineage IS populated, so that path has one leaf and no multiplicity clause
    lineage = one(findings, "non_finite", "per_line_concordance[].lineage")
    assert "leaves under this path" not in lineage.detail


def test_infinity_is_caught_not_only_nan():
    """±Inf must be flagged, and the reason is not symmetry with NaN — it is worse than NaN.

    ``pd.isna(float("inf"))`` is False, so every isna-based guard in the fleet admits an infinity; and
    ``abs(inf)`` wins every argmax, so an infinity that reaches a ranking puts an UNMEASURED value above
    every measured one. Hence ``math.isfinite`` and never ``pd.isna``.
    """
    findings = by_invariant(scan("infinity_sentinel"))
    fields = {f.field: f.value for f in findings["non_finite"]}
    assert fields == {"selectivity_index": math.inf, "delta_chronos": -math.inf}
    assert all(f.fatal for f in findings["non_finite"])
    assert "strict_json" in findings, "Infinity is also not valid JSON"


# ── the interval invariants ─────────────────────────────────────────────────────────────────────────


def test_interval_containment_flags_the_mislabelled_spearman_interval():
    """The real ALK-NSCLC values, and this invariant is a PROOF rather than a heuristic.

    The interval is built as ``tanh(atanh(r) ± 1.96·se)``. ``tanh`` is monotone and ``se > 0``, so
    ``lo < r < hi`` holds for ANY r and ANY se — the interval mathematically cannot exclude its own point
    estimate. A violation therefore proves two DIFFERENT numbers are in play, which is what the producer
    does: ``read.py:126`` publishes Pearson as ``rna_protein_r``, ``:139`` sets ``_classify_r = spear``,
    and ``:141`` returns that Spearman interval as ``rna_protein_r_ci95_*``.

    ⚠️ Note what this does NOT catch, because the distinction was got wrong once and matters: the
    separate Spearman-SE defect (``1/sqrt(n-3)`` where Spearman needs ``1.06/sqrt(n-3)``, so all 570
    intervals are ~6% too narrow). A width error scales an interval about its centre and can never
    displace containment, so no emission invariant can see it — that one needs recompute-from-source.
    """
    findings = scan("spearman_ci_mislabelled")
    f = one(findings, "interval_containment", "rna_protein_r")
    assert not f.fatal, "a containment violation is a warning, not a refusal to serialise"
    assert "above" in f.detail and "[-0.1726, 0.4246]" in f.detail
    assert "rna_protein_r_ci95_low" in f.detail, "the detail must name the interval legs it used"
    assert [x.invariant for x in findings] == ["interval_containment"], (
        "this fixture is valid strict JSON with in-domain values so the invariant is measured alone"
    )


def test_interval_order_flags_a_reversed_interval():
    """``low > high``, and it must PRE-EMPT the containment finding rather than adding to it.

    A reversed interval cannot contain anything, so reporting both would count one defect twice and put
    a derived symptom in the same red list as its cause.
    """
    findings = scan("domain_and_interval_order")
    f = one(findings, "interval_order", "effect_low")
    assert "0.9" in f.detail and "0.2" in f.detail
    assert not any(x.invariant == "interval_containment" for x in findings)


# ── the domain invariants ───────────────────────────────────────────────────────────────────────────


def test_domain_declared_flags_both_a_ceiling_and_a_floor():
    """A correlation outside [-1, 1] and a p-value below 0.

    Both bounds are checked because a one-sided fixture leaves half of ``_check_domain`` unexercised, and
    the two failures have different causes in practice: a ceiling breach is usually a wrong statistic in
    the field, a floor breach is usually a sign convention.
    """
    findings = scan("domain_and_interval_order")
    ceiling = one(findings, "domain_declared", "pearson_r")
    assert "'Pearson r'" in ceiling.detail and "ceiling 1.0" in ceiling.detail
    floor = one(findings, "domain_declared", "logrank_p")
    assert "'p'" in floor.detail and "floor 0.0" in floor.detail


def test_domain_unglossed_is_reported_under_its_own_name():
    """An unglossed field falls back to the narrow name rule — reported SEPARATELY, never pooled.

    The two rates answer different questions: ``domain_declared`` says a field violated the unit its
    author declared for it, ``domain_unglossed`` says a field violated what its NAME implies. Pooling
    them would let a naming guess inflate a contract violation rate.
    """
    findings = scan("domain_and_interval_order")
    f = one(findings, "domain_unglossed", "cohort_fdr")
    assert "p/q/FDR" in f.detail
    assert "declared unit" not in f.detail


def test_unconstrained_units_do_not_manufacture_findings():
    """``delta_chronos`` at -9.7 must NOT fire. Genuinely unbounded units are LISTED, not omitted.

    ``_UNCONSTRAINED_UNITS`` exists so that "this unit has no domain rule" is a recorded decision rather
    than an oversight. Attaching a plausible-looking bound to a CHRONOS score or a log2 fold change would
    manufacture violations out of real biology.
    """
    findings = scan("domain_and_interval_order")
    assert not [f for f in findings if f.field in ("delta_chronos", "median_ccf", "fraction_agree")]


# ── the two invariants with zero corpus findings that assert something SEMANTIC ──────────────────────


def test_class_from_unmeasured_is_flagged():
    """A substantive ``*_class`` banded from a non-finite number.

    ⚠️⚠️ **THE FIXTURE IS SYNTHETIC AND NO REAL PACKAGE HAS THIS SHAPE.** This invariant returns 0
    findings over all 504 corpus packages, and the case that commissioned it was refuted by the producer
    it accused: ``dge_deseq2/read.py:919`` guards NaN explicitly before taking a max, so there is no
    fall-through to reach, and the favourable-looking SCLC class is a documented backtest-driven
    DEMOTION. ★★ The generalisable error was reading a band cascade's OUTPUT and inferring its CONTROL
    FLOW — a favourable class beside a NaN is equally consistent with a fall-through and with a guarded,
    deliberate demotion. Only the producer can tell you which.

    The invariant is kept, and fixtured, because the property it asserts is still one the fleet should
    hold: the cost of keeping it is this file, and the cost of dropping it is that nothing notices when a
    future cascade does fall through.
    """
    findings = scan("class_from_unmeasured")
    f = one(findings, "class_from_unmeasured", "log2fc_cell_a_class")
    assert f.value == "modest_tumor_selective"
    assert "log2fc_cell_a=nan" in f.detail, "the detail must name the unmeasured input it was banded from"
    assert not f.fatal, "a semantic violation warns; only representability refuses to serialise"


def test_class_from_unmeasured_is_blind_when_the_stem_does_not_name_the_number():
    """The invariant's MEASURED blind spot, pinned — this asserts a FALSE NEGATIVE and wants it to break.

    ★★ **A 0-FINDINGS RESULT IS EVIDENCE ABOUT THE INSTRUMENT UNTIL YOU PROVE THE INSTRUMENT CAN SEE.**
    This invariant's corpus-wide zero was read (in this arc's own plan) as "the producers respect the
    property". They do not: ``structure-features-static`` published ``alphafold_confidence_class = "low"``
    — which ``intracellular-intrinsic.rules.yaml`` keys to ``small_molecule: opposing`` on the stated
    rationale "A MEASURED structural negative ... not an absence" — banded from a NaN, in **10 packages /
    3 targets (APC, KMT2A, MGA)** of 504. This invariant found none of them, because the stem of the class
    field is ``alphafold_confidence`` and the number it bands is ``alphafold_plddt_mean``.

    So the two facts are consistent and the zero was uninterpretable. ★★ **A NAME-STEM PAIRING RULE IS A
    HEURISTIC EVEN WHEN THE CHECK IT FEEDS IS EXACT**, and its failure mode is silence.

    ⚠️ **This test is expected to FAIL if the pairing rule is ever widened, and that is the point.** It is
    an executable statement of a limitation, not a guard on desired behaviour. If it goes red: the blind
    spot closed, so update it and the measured-blind-spot paragraph in ``_class_from_unmeasured``'s
    docstring — do not silence it. The remedy on the plan is a DECLARATION (a class naming the field it
    bands), not a longer candidate list, because no stem rule can be complete.

    ★ The third assertion is the load-bearing one: an assertion of *silence* passes just as happily when
    the fixture is malformed (an abstain token, a string where a number was meant) as when the instrument
    is blind. Renaming exactly one key turns 0 findings into 1, which proves every other precondition
    holds and isolates the name as the only thing standing between silence and a finding.
    """
    findings = scan("class_stem_misses_the_banded_number")

    # What DOES hold on this shape: the structural invariant sees it, and refuses to serialise it.
    assert one(findings, "non_finite", "alphafold_plddt_mean").fatal
    # The blind spot itself.
    assert not [f for f in findings if f.invariant == "class_from_unmeasured"], (
        "the pairing rule widened — good news; update this test and the docstring's blind-spot paragraph"
    )

    # ...and the silence is the PAIRING RULE, not a fixture that fails to encode the defect.
    raw = json.loads((FIXTURES / "class_stem_misses_the_banded_number" / "evidence_package.json").read_text())
    card = raw["cards"][0]
    flat = ei.flatten_summary(card["summary"])
    renamed = {("alphafold_confidence" if k == "alphafold_plddt_mean" else k): v for k, v in flat.items()}
    fired = list(ei._class_from_unmeasured("probe", card["card_id"], renamed))
    assert [(f.field, f.value) for f in fired] == [("alphafold_confidence_class", "low")], (
        "renaming one key must expose the violation; if it does not, the fixture stopped encoding it"
    )


def test_abstention_incoherence_is_opt_in_and_the_clean_control_proves_it():
    """``abstention_incoherent`` must not run by default, and the clean control carries its exact shape.

    ★★ Measured: it fires on 6,080 rows across **504 of 504** packages. A finding that fires on 100% of
    its population carries zero bits about any individual package, and this arc pre-registered exactly
    that rule for the warning channel — anything firing >90% of its runs goes to a calibration register,
    never to a per-run warning — so the rule has to bind this suite's own output too.

    Worse than uninformative: the shape it flags is CORRECT behaviour. The clean control's last card
    abstains in the field whose source is missing (no adjacent-normal cohort ⇒
    ``selectivity_allgene_percentile_class: data_unavailable``) while answering in the fields whose source
    is present. Per-field honesty about per-field availability is the design. A card-grain reading cannot
    tell it from a real contradiction, which is why the remedy is a per-field ``degrades_with:``
    declaration and not a better heuristic over the same information.
    """
    assert scan("clean_negative_control") == []
    opt_in = scan("clean_negative_control", heuristics=True)
    assert [f.invariant for f in opt_in] == ["abstention_incoherent"]
    assert opt_in[0].field == "selectivity_class"
    assert "selectivity_allgene_percentile_class" in opt_in[0].detail


# ── the envelope, and the negative control ──────────────────────────────────────────────────────────


def test_envelope_non_finite_fires_independently_of_the_cards():
    """A NaN in ``synthesis.*`` with entirely clean cards — a shape the corpus has 0 instances of.

    Today ``synthesis.*`` is purely derivative: 0 of 504 packages carry an envelope non-finite without a
    card non-finite, which is what licenses the plan's ordering (fix the four producer sites, and the
    envelope follows). But that is a fact about the current producers, not a property of the artifact, so
    the check must be able to fire alone or the ordering rests on something untested.

    ★ It gets its own invariant name rather than being pooled with ``non_finite`` for two reasons:
    ``synthesis.*`` re-publishes card numbers 3-5× so a shared rate would count one producer bug several
    times; and ``synthesis.claim_vectors`` is what ``build_atlas`` reads, where *verdict-inert is not
    atlas-inert* — a NaN entering a hashed canonical form reports as ordinary digest DRIFT rather than as
    an invalid artifact.
    """
    findings = by_invariant(scan("envelope_only_non_finite"))
    assert "non_finite" not in findings, "the cards are clean; only the envelope check may fire"
    f = one(findings["non_finite_envelope"], "non_finite_envelope", "synthesis.claim_vectors[].magnitude")
    assert f.fatal, "the envelope is the path to build_atlas, so it is as fatal as a card"
    assert f.field.startswith("synthesis."), "the top-level key must be part of the field path"


def test_clean_control_yields_nothing_by_default():
    """Zero findings, and the fixture is deliberately full of NEAR-MISSES rather than empty.

    A negative control containing nothing interesting has not tested anything. Every value in it sits at
    or just inside a boundary the suite checks: an inclusive percentile ceiling at exactly 100.0, a REAL
    zero (which ``is_measured`` admits and a truthiness test would not), a fully populated list so the
    list traversal is proven not to false-positive, a valid CI triple, and unconstrained units at values
    a plausible-looking bound would have rejected.
    """
    assert scan("clean_negative_control") == []


def test_ccf_at_the_producers_clamp_is_not_a_domain_violation():
    """``median_ccf = 1.5`` must stay clean. This test IS the guard on a refutation.

    ★★ CCF is definitionally a fraction of cells, so [0, 1] looks unarguable — and admitting it to
    ``_UNIT_DOMAINS`` produced 10 corpus findings of which **all 10 were false**. It is INFERRED as
    ``VAF * 2 / purity``, a ratio of two noisy quantities, so an unbiased estimator of a boundary-adjacent
    true value overshoots routinely; ``pancan_mutation_ccf/cli.py:39`` clamps it at
    ``CCF_CAP = 1.5  # cap ccf (purity/CN noise can push it >1)`` and the corpus maximum is exactly 1.5 —
    the clamp firing, not a defect.

    **A mathematical domain constrains the QUANTITY, not a noisy ESTIMATOR of it.** Admit a unit only
    when the field is a proportion OF AN OBSERVED SAMPLE (bounded by counting) or bounded by construction
    (Cauchy-Schwarz, a percentile rank, a fixed model scale) — never an inferred proportion. If someone
    re-adds CCF, this fails by name instead of the mistake shipping.
    """
    assert ei._gloss_units().get("median_ccf") == "CCF"
    assert "CCF" not in ei._UNIT_DOMAINS, "CCF constrains an inferred estimator; see this test's docstring"
    assert "CCF" in ei._UNCONSTRAINED_UNITS, "the exclusion must be a RECORDED decision, not an omission"
    assert not [f for f in scan("clean_negative_control") if f.field == "median_ccf"]


# ── properties of the finding record itself ─────────────────────────────────────────────────────────


def test_finding_key_excludes_value_and_detail():
    """The ratchet identity is ``(invariant, package, card_id, field)`` and must stay that way.

    A baseline keyed on the value would red on any numeric drift, which is noise. Keyed on the field, it
    reds only when a NEW field starts violating — which is the one-sided property the corpus ratchet
    needs to avoid redding trunk after a legitimate change.
    """
    f = one(scan("spearman_ci_mislabelled"), "interval_containment", "rna_protein_r")
    assert f.key() == (
        "interval_containment",
        "spearman_ci_mislabelled",
        "cellline-rna-protein-concordance",
        "rna_protein_r",
    )
    assert f.value not in f.key() and f.detail not in f.key()


def test_findings_survive_strict_json_serialisation():
    """``as_dict()`` must serialise under ``allow_nan=False`` — the flag this whole arc is about.

    A report that cannot serialise its own findings is unusable exactly where it is needed most, since
    the commonest finding IS a non-finite value. ``Finding.as_dict`` therefore reprs a non-finite value
    into a string.
    """
    for name in FIXTURE_PURPOSE:
        rows = [f.as_dict() for f in scan(name, heuristics=True)]
        blob = json.dumps(rows, allow_nan=False, sort_keys=True)
        assert json.loads(blob) == rows
    assert (
        one(scan("label_leak_non_finite"), "non_finite", "per_line_concordance[].lineage").as_dict()["value"] == "nan"
    )


def test_the_scan_is_byte_stable():
    """Two sweeps of the fixture corpus must be identical.

    The baseline artifact the corpus ratchet diffs is only trustworthy if it is a pure function of its
    input, so this is asserted rather than assumed — including the ORDER, which ``iter_corpus`` sorts and
    ``_non_finite`` sorts per path.
    """
    a = json.dumps(ei.summarise(ei.scan_corpus(FIXTURES)), sort_keys=True)
    b = json.dumps(ei.summarise(ei.scan_corpus(FIXTURES)), sort_keys=True)
    assert a == b


@pytest.mark.parametrize("fixture", sorted(FIXTURE_PURPOSE))
def test_every_fixture_is_parseable_and_shaped_like_a_package(fixture):
    """Each fixture must be loadable by the permissive parser and carry cards.

    Deliberately NOT a strict parse: **five of the eight** are invalid strict JSON on purpose, which is the
    defect under test. This asserts only that a fixture is a real package the invariants can walk, so a
    typo cannot make a positive test pass by producing zero findings for the wrong reason.

    ⚠️ That count was measured, not remembered — it read "five of the seven" when four of seven carried a
    non-finite token. A prose count beside a growing fixture set drifts silently, which is the same shape
    as the remembered-baseline trap this suite exists to avoid.
    """
    pkg = json.loads((FIXTURES / fixture / "evidence_package.json").read_text())
    assert isinstance(pkg.get("cards"), list) and pkg["cards"], f"{fixture} has no cards"
    assert all(c.get("card_id") for c in pkg["cards"]), f"{fixture} has a card with no card_id"
    assert pkg.get("_fixture"), "every fixture must document what defect it encodes and why"
