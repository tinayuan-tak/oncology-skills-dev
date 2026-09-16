"""Structural invariants on card-emitted data, checkable against a package corpus with NO credentials.

WHY THIS EXISTS. The framework has three mechanisms that would check what a card emits, and at the time
this module was written none of them ran:

  * ``validation_state`` is a hardcoded ``"pass"`` at :mod:`dispatcher` — 56,842 of 56,842 card-runs in
    the 504-package corpus, 0 ``passed_with_warnings``.
  * the 46 per-card ``*.summary.schema.json`` in target-contracts lost their only reader when
    ``_validate_summary`` was deleted with #654 (``4ab52b45``); ``grep -rn "schemas/methods"`` across
    skills returns 0 hits.
  * the 168 ``warning_predicates`` authored across 74 of 148 cards are schema-validated,
    ``THRESHOLD.*``-resolved and paren-linted, their output slot (``warning_ids``) is declared and the
    renderer already prints it — but no evaluator exists anywhere.

So there is no gate between "a method computed a number" and "a card asserts it". What that costs, measured
by this module over all 504 packages:

  * **501 of 504 packages are not valid JSON.** ``json.loads`` accepts ``NaN``/``Infinity`` by default, so
    every in-repo reader round-trips a file no conforming JSON parser elsewhere will accept.
  * **121,777 non-finite leaves across 50 distinct JSON paths.** 98.2% of them are ONE defect:
    ``crispr-rnai-dependency-concordance/per_line_concordance[].ccle_name`` — a cell-line *name* — is
    ``NaN`` in 119,536 leaves across 496 packages, because a missing value in an object-dtype pandas column
    IS ``float('nan')`` and ``to_dict(orient="records")`` ships it untouched.
  * **115 of 570 published confidence intervals exclude their own point estimate**, which is impossible for
    the Fisher-z form that produces them and therefore *proves* two different statistics are in play.
  * Non-finite values reach ``synthesis.claim_vectors`` in 47 packages, and claim vectors are what
    ``build_atlas`` reads — so an invalid artifact enters the frozen atlas as ordinary digest drift.

⚠️⚠️ **AND THE CLAIM THIS MODULE WAS ORIGINALLY WRITTEN TO PROVE IS FALSE. IT IS RECORDED HERE BECAUSE THE
ERROR IS MORE REUSABLE THAN THE FIX.** The commissioning claim was: ``log2fc_cell_a`` is ``NaN`` in 40 of 40
SCLC packages, every comparison against ``NaN`` is False, so an ``if/elif`` band cascade falls through and
emits the FAVOURABLE ``modest_tumor_selective`` — beta-actin declared tumour-selective. The invariant written
to catch it (:func:`_class_from_unmeasured`) returns **0 findings over 504 packages**, and 0 of 262
substantive ``selectivity_class`` values were banded from a non-finite input. Reading the producer shows why:
``methods/dge_deseq2/read.py:919`` guards explicitly with ``row.get(k) == row.get(k)``, so ``raw_max_lfc``
never sees the NaN; ``modest_tumor_selective`` under SCLC is FIX 4b's *deliberate, documented,
backtest-driven demotion* because ``strong`` must not rest on the GTEx arm alone; ``not_informative`` is the
real terminal branch and 6 of 40 packages take it; and the card surfaces its own degradation in three
separate fields (``adjacent_arm_measured``, ``selectivity_evidence_independence``,
``selectivity_allgene_percentile_class``).
★★ **The error: reading a band cascade's OUTPUT and inferring its CONTROL FLOW.** A favourable class next to
a NaN input is equally consistent with a fall-through and with a guarded intentional demotion, and only the
producer can settle which. The sibling ``data_unavailable`` field that looked like the card contradicting
itself is the card being honest at per-field grain about per-field availability — the design, not the defect.
⇒ Prefer invariants over REPRESENTABILITY and INTERNAL CONSISTENCY, which held against every producer here,
to invariants over DOMAIN SEMANTICS, both of which were refuted by the producer's own written rationale (see
:data:`_UNIT_DOMAINS` on CCF and :func:`_abstention_coherence` on the 504/504 fire rate).

WHAT THIS MODULE IS AND IS NOT. It is a *detector*, hermetic and credential-free, so it can gate CI —
which is the gap that :mod:`tests.test_card_output_emission` cannot close, being live-data bound (28
passed / 108 skipped without credentials). It is NOT a fix: the producer bugs it finds are fixed in their
own repos. Each known bug has a fixture here that the relevant invariant must flag, so the guard is
proven to fire rather than asserted to.

★ MEASUREDNESS IS NOT REDEFINED HERE. :func:`field_disposition.is_measured` is already correct — it
rejects ``None``, the declared sentinels case-insensitively, and non-finite floats, while ADMITTING
``0``/``0.0``/``False`` because a zero is a reading. Every invariant below calls it. The defect this
module addresses was never a missing primitive; it was that almost nothing called the one that existed.

────────────────────────────────────────────────────────────────────────────────────────────────────
★★ TWO NAME-BASED HEURISTICS THAT LOOK OBVIOUS AND ARE WRONG. Both were measured before this module was
written, and both are the reason the invariants below are keyed on DECLARED facts instead of on spelling.

(1) ``_low``/``_high`` DOES NOT MEAN "interval bound". Over the corpus, 28 distinct (card, field) pairs
    carry such a suffix and only 8 are interval bounds. The rest are CATEGORY COUNTS and STRATUM
    STATISTICS: ``mutational-signature-context/frac_hrd_high`` is the fraction of samples with high HRD,
    ``genomic-instability-state/n_msi_high`` counts MSI-high models, ``hpa-pathology-cancer-ihc/n_high``
    and ``n_low`` count staining intensities, ``immune-context/cd8_fraction_antigen_high``/``_low`` are
    CD8 fractions in two antigen strata, and ``cd8_high_minus_low`` is their difference. Demanding
    "``frac_hrd_high`` must bracket ``frac_hrd``" is meaningless. :func:`_interval_triples` therefore
    requires the full TRIPLE — a low sibling AND a high sibling AND a resolvable point estimate — which
    cuts 28 candidates to 4 genuine triples. And the point estimate is NOT always the stripped base:
    ``surface-abundance-density`` names it ``estimated_copies_per_cell_median``.

(2) A UNIT CANNOT BE GUESSED FROM A FIELD NAME, so :data:`_UNIT_DOMAINS` keys on the unit token DECLARED
    in :data:`display_gloss.METRIC_GLOSS` (186 fields, 47 unit tokens). Fields with no gloss entry are
    NOT silently name-matched into a domain: they are reported under ``domain_unglossed`` by a separate,
    deliberately narrow fallback, and the two populations are never pooled — a violation rate over
    declared units and a violation rate over guessed units are different measurements.
────────────────────────────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from _skills_common import field_disposition as fd

# ── findings ────────────────────────────────────────────────────────────────────────────────────────

#: Invariants that are STRUCTURAL — the emitted artifact is not REPRESENTABLE, as opposed to not plausible.
#: These are the ones the tiered enforcement posture hard-fails: a NaN and a JSON-invalid file are never a
#: legitimate reading of anything. Everything else warns. ``non_finite_envelope``
#: belongs here for the same reason as ``non_finite``: it is the same defect at a different JSON path, and
#: omitting it once left the module's own docstring claiming FATAL while ``Finding.fatal`` returned False on
#: 1,220 of 1,858 rows. ``test_fatal_set_matches_the_docstrings`` asserts membership here iff the invariant's
#: own docstring says FATAL, so prose and predicate cannot drift again.
FATAL_INVARIANTS = frozenset({"non_finite", "non_finite_envelope", "strict_json"})


@dataclass(frozen=True)
class Finding:
    """One invariant violation, keyed so it can be diffed across corpus vintages.

    ``detail`` carries the arithmetic that makes the violation checkable by hand — a finding a reviewer
    cannot re-derive from its own text is not evidence.
    """

    invariant: str
    package: str
    card_id: str
    field: str
    value: Any
    detail: str

    @property
    def fatal(self) -> bool:
        return self.invariant in FATAL_INVARIANTS

    def key(self) -> tuple:
        """Identity for baselining: deliberately EXCLUDES ``value`` and ``detail``.

        A ratchet keyed on the value would red on any numeric drift, which is noise; keyed on
        (invariant, card, field) it reds only when a NEW field starts violating. ``package`` is kept
        because "115 of 570 runs" and "one card always" need different fixes.
        """
        return (self.invariant, self.package, self.card_id, self.field)

    def as_dict(self) -> dict:
        v = self.value
        if isinstance(v, float) and not math.isfinite(v):
            v = repr(v)  # NaN/Infinity are not JSON-serialisable; that is the whole point of this module
        return {
            "invariant": self.invariant,
            "package": self.package,
            "card_id": self.card_id,
            "field": self.field,
            "value": v,
            "detail": self.detail,
        }


# ── declared-unit domains ───────────────────────────────────────────────────────────────────────────

#: unit token (as declared in ``METRIC_GLOSS``) -> (low, high, integral) with None meaning unbounded.
#:
#: ★ ONLY units whose domain is a MATHEMATICAL property of the quantity appear here. A correlation cannot
#: leave [-1, 1] and a probability cannot leave [0, 1] whatever the biology, so a violation is a defect
#: rather than a surprise. Units that are genuinely unbounded — CHRONOS, log2FC, z-score, effect size,
#: Cohen's d, GI score, delta *, log2 * — are LISTED IN :data:`_UNCONSTRAINED_UNITS` rather than omitted,
#: so that "this unit has no domain rule" is a recorded decision and not an oversight. Adding a plausible
#: bound to one of those would manufacture violations out of real biology.
#:
#: ★★ **AND THE BOUND MUST HOLD FOR THE ESTIMATOR, NOT ONLY FOR THE QUANTITY. THIS IS THE TRAP THAT COST
#: THIS TABLE ITS ONLY FINDINGS.** A mathematical domain constrains the thing being measured; it does not
#: constrain a noisy estimate OF that thing. ``CCF`` (cancer cell fraction) is definitionally a fraction of
#: cells and so "obviously" belongs in [0, 1] — but it is INFERRED as ``VAF * 2 / purity``, a ratio of two
#: noisy quantities, so an unbiased estimator of a boundary-adjacent true value overshoots routinely. The
#: producer knows this and says so: ``pancan_mutation_ccf/cli.py:39`` reads
#: ``CCF_CAP = 1.5  # cap ccf (purity/CN noise can push it >1)``, and the corpus's largest observed
#: ``median_ccf`` is **exactly 1.5** — the clamp firing, not a defect. Entering ``CCF`` here produced
#: **10 findings, all 10 false**, and 0 of the other 22 units produced any. So: admit a unit only when the
#: field is a proportion OF AN OBSERVED SAMPLE (bounded by counting) or a statistic bounded by construction
#: (Cauchy-Schwarz, a percentile rank, a model output on a fixed scale) — never an inferred proportion.
_UNIT_DOMAINS: dict[str, tuple[float | None, float | None, bool]] = {
    # probabilities and proportions
    "fraction": (0.0, 1.0, False),
    "q": (0.0, 1.0, False),
    "p": (0.0, 1.0, False),
    "pLI": (0.0, 1.0, False),
    "PPV": (0.0, 1.0, False),
    "R2": (0.0, 1.0, False),
    "overlap": (0.0, 1.0, False),
    "ε²": (0.0, 1.0, False),
    # correlations: bounded by Cauchy-Schwarz
    "Pearson r": (-1.0, 1.0, False),
    "Spearman r": (-1.0, 1.0, False),
    # signed proportions
    "delta fraction": (-1.0, 1.0, False),
    # percent scales
    "%ile": (0.0, 100.0, False),
    "%": (0.0, 100.0, False),
    "pLDDT": (0.0, 100.0, False),
    # non-negative magnitudes
    "count": (0.0, None, True),
    "df": (0.0, None, True),
    "days": (0.0, None, False),
    "TPM": (0.0, None, False),
    "copies/cell": (0.0, None, False),
    "ratio": (0.0, None, False),
    "χ²": (0.0, None, False),
    "index": (0.0, None, False),
}

#: Units deliberately left unconstrained, with the reason. Asserted against ``METRIC_GLOSS`` by the test
#: suite so a NEW unit token cannot appear without someone deciding which side it belongs on — the
#: failure mode being a unit that silently gets no check because nobody noticed it was added.
_UNCONSTRAINED_UNITS: dict[str, str] = {
    "CCF": (
        "an INFERRED proportion (VAF*2/purity), not a counted one, so the estimator legitimately exceeds "
        "the quantity's [0,1] range; the producer clamps at CCF_CAP=1.5 (pancan_mutation_ccf/cli.py:39) "
        "and the corpus max is exactly 1.5. A [0,1] rule here yields 10 findings and all 10 are false. "
        "An upper rule at the CAP would only restate the producer's own clamp, so there is nothing to check"
    ),
    "CHRONOS": "gene-effect score; unbounded either side, ~-3..+1 in practice but not mathematically",
    "delta CHRONOS": "difference of two unbounded scores",
    "dep score": "RNAi dependency score, same shape as CHRONOS",
    "delta effect": "difference of two unbounded effect scores",
    "effect size": "standardised difference; unbounded",
    "Cohen's d": "standardised difference; unbounded",
    "z-score": "unbounded by construction",
    "GI score": "genetic-interaction score; signed and unbounded",
    "log2FC": "log ratio; unbounded either side",
    "log2 OR": "log odds ratio; unbounded either side",
    "log2": "log abundance; unbounded",
    "log2 TPM": "log1p-transformed TPM; non-negative in practice but the transform is not pinned here",
    "log2 AUC": "log area-under-curve; signed",
    "log2 intensity": "log MS intensity; signed",
    "log2 ratio": "log copy ratio; signed",
    "log2 TPM/methyl": "regression slope; signed and unbounded",
    "log2/CN": "regression slope; signed and unbounded",
    "NPX": "Olink normalised protein expression; log scale, signed",
    "CLR": "centred log-ratio; signed by construction",
    "LOEUF": "non-negative in principle but the upper tail is capped by the source, not by maths",
    "pChEMBL": "-log10 molar potency; non-negative in practice, not guaranteed",
    "-log10 M": "same shape as pChEMBL",
    "ΔEmax": "difference of two response maxima; signed",
    "sig_all_cells": "not a scalar metric (gloss carries units=None)",
    None: "gloss declares no unit — the value is a flag or an identifier, not a measurement",
}

#: The narrow name-based fallback, applied ONLY to fields with no ``METRIC_GLOSS`` entry, and reported
#: under its own invariant name so it is never pooled with the declared-unit result. Kept deliberately
#: small: every pattern here must be one where the SUFFIX IS THE UNIT, which is exactly the property
#: ``_high``/``_low`` lacks (see the module docstring). ``_percentile`` is safe because a field named
#: percentile that is not one would be a naming defect in its own right.
_NAME_DOMAINS: tuple[tuple[re.Pattern, tuple[float | None, float | None, bool], str], ...] = (
    (re.compile(r"(^|_)percentile$"), (0.0, 100.0, False), "name ends in _percentile"),
    (re.compile(r"(^|_)(pvalue|p_value|qvalue|q_value|fdr)$"), (0.0, 1.0, False), "name ends in a p/q/FDR token"),
    (re.compile(r"^n_[a-z0-9_]+$"), (0.0, None, True), "name has the n_* counting prefix"),
)


def _gloss_units() -> dict[str, Any]:
    """``field -> declared unit token`` from ``METRIC_GLOSS``, imported not re-parsed.

    Imported lazily so this module stays importable in contexts where display_gloss is not on the path;
    a missing gloss degrades the domain invariant to its unglossed fallback rather than crashing, and
    :func:`gloss_available` lets a caller assert which mode it is in (a silent degrade to the fallback
    would make a green meaningless).
    """
    try:
        from _skills_common.display_gloss import METRIC_GLOSS
    except Exception:  # pragma: no cover - path-dependent
        return {}
    return {f: u for f, (_lab, u) in METRIC_GLOSS.items()}


def gloss_available() -> bool:
    """True when the declared-unit table loaded. Assert this before quoting a domain violation rate."""
    return bool(_gloss_units())


# ── walking a card summary ──────────────────────────────────────────────────────────────────────────


def flatten_summary(summary: Any, prefix: str = "") -> dict[str, Any]:
    """``{dotted_path: leaf}`` over a card summary. SCALAR FIELDS ONLY — lists are not descended.

    ★★ **TWO TRAVERSALS, AND THE SPLIT IS THE DESIGN, NOT A DUPLICATION.** This one exists for the
    invariants that are *semantic*: a domain check needs the field's declared unit, an interval check
    needs to pair ``x_ci95_low`` with ``x``, a class check needs the class's value-bearing sibling. All
    three need **one value per field name**, so descending a list would collide many values onto one key
    and there is no meaningful "the unit of element 3". Structural invariants have no such need and use
    :func:`iter_all_leaves` instead.

    ⚠️ An earlier version of this docstring justified skipping lists with *"a list element has no stable
    field identity across runs, so a finding keyed on ``foo[3]`` cannot be baselined."* That is true of
    the **index** and false of the **key**, and taking it as a reason to skip lists entirely cost this
    module 98% of its own subject matter: ``per_line_concordance[].ccle_name`` is ``NaN`` in **119,536**
    leaves across 496 of 504 packages — 98.2% of every non-finite value in the corpus — and none of it was
    attributed to a field. Eliding the index (``foo[].bar``) yields an identity that is *more* stable than
    a scalar path, because it is invariant to list length as well.
    """
    out: dict[str, Any] = {}
    if isinstance(summary, dict):
        for k, v in summary.items():
            out.update(flatten_summary(v, f"{prefix}.{k}" if prefix else str(k)))
    elif not isinstance(summary, list):
        out[prefix] = summary
    return out


def iter_all_leaves(node: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every leaf under ``node``, descending lists with the index ELIDED: ``per_line_concordance[].lineage``.

    For the *structural* invariants (non-finite, strict-JSON) — the ones whose question is "is this value
    representable at all", which is well-posed for every leaf regardless of whether it has a declared unit
    or a stable sibling. Repeats are expected and are the caller's business to collapse: a path yielded
    500 times is ONE defect with a blast radius of 500, and a caller that emits 500 findings for it turns
    every rate it later computes into a measure of list length. See :func:`_non_finite`.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            yield from iter_all_leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(node, list):
        for v in node:
            yield from iter_all_leaves(v, f"{prefix}[]")
    else:
        yield prefix, node


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# ── invariant 1: non-finite ─────────────────────────────────────────────────────────────────────────


#: Leaf names whose declared job is to carry a LABEL, not a measurement. A non-finite value here is a
#: different defect with a different fix, so the detail says which: a missing string in an object-dtype
#: pandas column IS ``float('nan')``, and ``DataFrame.to_dict(orient="records")`` carries it into JSON
#: untouched. The remedy is ``fillna`` at the frame boundary, NOT an abstain token in a band cascade.
_LABEL_LEAF = re.compile(r"(^|_)(name|id|symbol|label|lineage|tissue|source|cohort|gene|line|code)$")


def _non_finite(pkg: str, card_id: str, node: Any) -> Iterator[Finding]:
    """No emitted value may be NaN or ±Inf. FATAL. Structural ⇒ descends lists via :func:`iter_all_leaves`.

    Note it must test ``math.isfinite`` and NOT ``pd.isna``: ``pd.isna(inf)`` is False, so an isna-guard
    admits ±Inf, and ±Inf is worse than NaN for ranking because ``abs(inf)`` wins every argmax.

    ★★ **REPEATS ARE COLLAPSED PER (card, elided path), AND THAT IS LOAD-BEARING.** One list-valued field
    (``per_line_concordance[].ccle_name``) accounts for 119,536 of the corpus's 121,777 non-finite leaves.
    Emitting a row each would make ``non_finite`` 98% one defect, so every later "N% of findings are X"
    would really be measuring how many cell lines a target has. The row count therefore answers "how many
    distinct places are broken"; the multiplicity lives in ``detail`` where it cannot contaminate a rate.
    """
    seen: dict[str, tuple[Any, int]] = {}
    for f, v in iter_all_leaves(node):
        if _is_number(v) and not math.isfinite(float(v)):
            first, n = seen.get(f, (v, 0))
            seen[f] = (first, n + 1)
    for f in sorted(seen):
        first, n = seen[f]
        mult = "" if n == 1 else f" ({n} leaves under this path)"
        kind = (
            " — the field's name says it carries a LABEL, so this is a missing string that pandas turned "
            "into a float, not a failed computation; fix it with fillna at the frame boundary"
            if _LABEL_LEAF.search(f.split(".")[-1].replace("[]", ""))
            else ""
        )
        yield Finding("non_finite", pkg, card_id, f, first, f"{first!r} is not a finite number{mult}{kind}")


# ── invariant 2: domain by declared unit ────────────────────────────────────────────────────────────


def _check_domain(lo, hi, integral, v: float) -> str | None:
    if lo is not None and v < lo:
        return f"{v!r} < the domain floor {lo}"
    if hi is not None and v > hi:
        return f"{v!r} > the domain ceiling {hi}"
    if integral and float(v) != int(v):
        return f"{v!r} is not integral"
    return None


def _domain(pkg: str, card_id: str, flat: dict[str, Any], units: dict[str, Any]) -> Iterator[Finding]:
    """A value must lie inside the domain implied by its DECLARED unit (``domain_declared``), or, when
    the field carries no gloss entry, by the narrow name fallback (``domain_unglossed``).

    The two invariant names exist so the rates are never pooled — see the module docstring, heuristic (2).
    """
    for f, v in flat.items():
        if not _is_number(v) or not math.isfinite(float(v)):
            continue  # non-finite is invariant 1's finding; reporting it twice double-counts
        leaf = f.split(".")[-1]
        if leaf in units:
            spec = _UNIT_DOMAINS.get(units[leaf])
            if spec is None:
                continue  # an explicitly unconstrained unit
            why = _check_domain(*spec, float(v))
            if why:
                yield Finding(
                    "domain_declared",
                    pkg,
                    card_id,
                    f,
                    v,
                    f"declared unit {units[leaf]!r}: {why}",
                )
            continue
        for pat, spec, why_pat in _NAME_DOMAINS:
            if pat.search(leaf):
                why = _check_domain(*spec, float(v))
                if why:
                    yield Finding("domain_unglossed", pkg, card_id, f, v, f"{why_pat}: {why}")
                break


# ── invariants 3 and 4: intervals ───────────────────────────────────────────────────────────────────

#: low suffix -> the high suffix it pairs with. Ordered longest-first so ``_ci95_low`` is not eaten by
#: ``_low``.
_PAIRS = (("_ci95_low", "_ci95_high"), ("_ci_lo", "_ci_hi"), ("_lower", "_upper"), ("_low", "_high"), ("_lo", "_hi"))
#: Suffixes a point estimate may carry relative to the interval's base name. ``""`` (the bare base) is
#: tried first; ``_median`` exists because ``surface-abundance-density`` uses it.
_POINT_SUFFIXES = ("", "_median", "_mean", "_best", "_point", "_estimate")
#: Interval markers to strip off the base before looking for the point estimate: ``rna_protein_r_ci95_low``
#: has base ``rna_protein_r_ci95`` but its point estimate is ``rna_protein_r``.
_CI_MARKER = re.compile(r"_ci(95|90|68)?$")


def _interval_triples(leaves: set[str]) -> list[tuple[str, str, str]]:
    """``[(low, high, point)]`` for the fields that are ACTUALLY interval bounds.

    Requires all three legs to exist. See the module docstring, heuristic (1): the suffix alone
    over-selects 28 fields down from which only 4 triples are real.

    ★ EACH low LEAF IS CLAIMED AT MOST ONCE, and that guard is not cosmetic — it was a real
    double-count caught by running this module against the corpus. ``rna_protein_r_ci95_low`` ends with
    BOTH ``_ci95_low`` and ``_low``, so an unguarded loop resolves the same triple twice (via base
    ``rna_protein_r`` and via base ``rna_protein_r_ci95`` → ``_CI_MARKER`` → ``rna_protein_r``) and
    reports 230 violations where there are 115. :data:`_PAIRS` is ordered longest-suffix-first so the
    specific spelling wins; ``claimed`` is what makes that ordering actually bind.
    """
    triples = []
    claimed: set[str] = set()
    for lo_sfx, hi_sfx in _PAIRS:
        for leaf in sorted(leaves):
            if leaf in claimed or not leaf.endswith(lo_sfx):
                continue
            base = leaf[: -len(lo_sfx)]
            hi = base + hi_sfx
            if hi not in leaves:
                continue
            for cand_base in (base, _CI_MARKER.sub("", base)):
                point = next(
                    (cand_base + s for s in _POINT_SUFFIXES if (cand_base + s) in leaves and (cand_base + s) != leaf),
                    None,
                )
                if point:
                    triples.append((leaf, hi, point))
                    claimed.add(leaf)
                    break
    return triples


def _intervals(pkg: str, card_id: str, flat: dict[str, Any]) -> Iterator[Finding]:
    """``low <= point <= high`` (``interval_containment``) and ``low <= high`` (``interval_order``).

    Containment is the invariant that flags the Spearman-CI defect in
    ``depmap_rna_protein_concordance/read.py`` — a Spearman interval built with Pearson's
    ``SE = 1/sqrt(n-3)`` instead of ``1.06/sqrt(n-3)``, so the published band is ~6% too narrow. ★ It
    catches only the 115 of 570 runs where the point estimate falls OUTSIDE the too-narrow band, so it
    is a lower bound on that bug and must be paired with a recompute-from-source check; an invariant
    that detects a fifth of a defect is evidence the defect exists, not a measurement of its size.
    """
    by_leaf = {f.split(".")[-1]: f for f in flat}
    for lo_leaf, hi_leaf, pt_leaf in _interval_triples(set(by_leaf)):
        lo, hi, pt = (flat[by_leaf[x]] for x in (lo_leaf, hi_leaf, pt_leaf))
        if not all(_is_number(x) and math.isfinite(float(x)) for x in (lo, hi, pt)):
            continue  # an unmeasured leg is invariant 1's or invariant 5's finding, not an interval defect
        lo, hi, pt = float(lo), float(hi), float(pt)
        if lo > hi:
            yield Finding(
                "interval_order",
                pkg,
                card_id,
                by_leaf[lo_leaf],
                lo,
                f"low {lo!r} > high {hi!r} ({hi_leaf})",
            )
        elif not (lo <= pt <= hi):
            side = "below" if pt < lo else "above"
            yield Finding(
                "interval_containment",
                pkg,
                card_id,
                by_leaf[pt_leaf],
                pt,
                f"point estimate {pt!r} lies {side} its own interval [{lo!r}, {hi!r}] ({lo_leaf} .. {hi_leaf})",
            )


# ── invariant 5 / 7: abstention coherence ───────────────────────────────────────────────────────────

#: Vocabulary that means "no reading was obtained". Sourced from ``field_disposition`` so this module
#: cannot drift from the primitive that already defines measuredness; the extra tokens are class-level
#: abstentions that are not value-level sentinels (a class field says ``not_informative``, a number field
#: says ``data_unavailable``).
#:
#: ⚠️ **MEASURED INCOMPLETE, DELIBERATELY NOT WIDENED — and the failure direction is why.** The corpus
#: emits class-level abstentions this set does not contain (``unavailable`` 4, ``no_compounds_found`` 485,
#: ``insufficient_paired_samples`` 40, ``insufficient_paired_models`` 6). A too-NARROW abstain set
#: produces false POSITIVES; a too-wide one produces SILENCE. For a checker the noisy direction is the
#: safe one, so this stays narrow.
#:
#: ★★ **AND THE PATTERN FIX IS REFUTED — "we looked and found nothing" and "we could not look" are
#: different claims, and the token cannot tell you which.** Measured over 504 packages:
#: ``startswith("no_")`` matches **46 distinct tokens**, overwhelmingly SUBSTANTIVE measured negatives —
#: ``no_interaction`` 502, ``no_extracellular_domain`` 375, ``no_correlation`` 290,
#: ``no_recurrent_fusion`` 360 (the plan's canonical rare-and-decisive signal) — mixed in with genuine
#: abstentions like ``no_compounds_found``. ``startswith("insufficient")`` matches **11**, and it splits
#: the same way: ``insufficient_paired_samples`` is an abstention while ``insufficient_amp_expr_rate``
#: (394) and ``insufficient_mutation_rate`` (246) are measured rates below a cut. So a prefix rule would
#: silence real violations to remove triageable noise — the wrong trade for a checker.
#:
#: This is the same shape as ENUMERATION-vs-DEFICIENCY counts (``n_lineages_evaluated == 0`` means
#: nothing was evaluated; ``n_domains_low_plddt == 0`` means evaluated and clean) and it has the same
#: remedy: the distinction is about the MEASUREMENT PROCESS, not about the value, so only a declaration
#: can carry it. Widening this set is also **measured inert**: with the stem pairing as it stands,
#: ``_class_from_unmeasured`` returns **0 findings over all 504 packages**, so no token added here would
#: change a single live result today.
_EXTRA_ABSTAIN = frozenset({"not_informative", "not_assessed", "not_evaluable", "indeterminate", "unknown"})


def abstain_tokens() -> frozenset[str]:
    base = frozenset(str(s).strip().lower() for s in getattr(fd, "UNMEASURED_SENTINELS", ()))
    return base | _EXTRA_ABSTAIN


def _is_abstain(v: Any) -> bool:
    return isinstance(v, str) and v.strip().lower() in abstain_tokens()


def _class_fields(flat: dict[str, Any]) -> list[str]:
    """Fields that band a number into a label. Name-based, and that is safe here for a reason the
    ``_high`` trap does not undermine: ``_class`` is a FRAMEWORK suffix applied by the card author to
    mark exactly this, not a domain word that happens to appear in metric names."""
    return [f for f in flat if f.split(".")[-1].endswith(("_class", "_verdict", "_call"))]


def _abstention_coherence(pkg: str, card_id: str, flat: dict[str, Any]) -> Iterator[Finding]:
    """A card asserts "no data" in one class field and a substantive class in another.

    ⚠️⚠️ **NOT RUN BY DEFAULT — THIS HEURISTIC WAS MEASURED AND IT CANNOT DISCRIMINATE.** Opt in via
    ``scan_package(..., heuristics=True)``. Measured over the 504-package corpus: **6,080 rows across
    504 of 504 packages** (12.1 per package, 61 distinct ``(card, field)`` pairs). A finding that fires on
    100% of its population carries zero bits about any individual package, and the arc that commissioned
    this module pre-registered exactly that rule for the warning channel — *any predicate firing >90% or
    <1% of its runs goes to a calibration register, never to a per-run warning* — so it must apply to this
    module's own output too, or the suite becomes the non-discrimination problem it was built to diagnose.

    ★★ **AND THE 100% IS NOT MERELY UNINFORMATIVE — THE SHAPE IT FLAGS IS CORRECT BEHAVIOUR.** The
    motivating case (``tumor-vs-normal-selectivity`` under SCLC, which has no adjacent-normal cohort) turns
    out to be a card that abstains in the fields whose source is missing and answers in the fields whose
    source is present: ``adjacent_arm_measured=False``, ``selectivity_evidence_independence=
    'population_normal_only'``, ``selectivity_allgene_percentile_class='data_unavailable'``, alongside a
    substantive ``selectivity_class``. Per-field honesty about per-field availability is the DESIGN. A
    card-grain reading cannot tell it apart from a genuine contradiction, so at card grain there is no
    signal to extract — which is why the remedy is the ``degrades_with:`` declaration (a per-field source
    statement) and not a better heuristic over the same information.

    Kept in the module rather than deleted because the measurement is the finding: it is the evidence that
    the card grain is the wrong grain, and a later session tempted to re-derive it should read this instead
    of re-running it. The exact, non-heuristic half is :func:`_class_from_unmeasured`.
    """
    classes = _class_fields(flat)
    if not classes:
        return
    abstaining = [f for f in classes if _is_abstain(flat[f])]
    substantive = [f for f in classes if isinstance(flat[f], str) and not _is_abstain(flat[f])]
    if abstaining and substantive:
        for f in substantive:
            yield Finding(
                "abstention_incoherent",
                pkg,
                card_id,
                f,
                flat[f],
                f"card also abstains in {len(abstaining)} sibling class field(s) "
                f"({', '.join(sorted(abstaining)[:3])}) — one of the two readings is wrong",
            )


def _class_from_unmeasured(pkg: str, card_id: str, flat: dict[str, Any]) -> Iterator[Finding]:
    """A ``*_class`` may not be substantive when the number it bands is not measured.

    ⚠️ **The CHECK is exact; the PAIR FORMATION is a naming convention.** An earlier version of this
    docstring claimed "EXACT, not heuristic, because the pairing is by name stem" — the *because* is
    backwards, and the claim is withdrawn. ``math.isfinite`` on a resolved pair is exact, but the pair
    itself is guessed from ``stem = leaf[:-len("_class")]`` plus ``(stem, stem_value, stem_score)``, so
    when a class field's stem is not the name of the number it bands, **no pair forms and this invariant
    is silent on a real violation.** An exact predicate over a heuristically-formed pair is a heuristic
    instrument whose failure mode is a false negative, which is the worst mode available to a checker.

    ★★ MEASURED BLIND SPOT, 2026-09-15 — this is why the docstring changed. On
    ``structure-features-static``, ``alphafold_confidence_class`` yields stem ``alphafold_confidence``, so
    this searches ``alphafold_confidence`` / ``_value`` / ``_score``. **The card emits none of them.** The
    number it actually bands is ``alphafold_plddt_mean``, which shares no stem with the class field. That
    number is NaN in **78 of 504 corpus packages / 48 targets**, and the class is published as the
    substantive token ``"low"`` — banded from a NaN — in **10 packages / 3 targets (APC, KMT2A, MGA)**,
    where ``intracellular-intrinsic.rules.yaml`` keys ``== "low"`` to ``small_molecule: opposing`` on the
    stated rationale "A MEASURED structural negative for the SM modality, not an absence". This invariant
    returned **0 findings** on all of them. Fixed producer-side in analysis-methods PR #646.

    ⇒ ★★ **A 0-FINDINGS RESULT IS EVIDENCE ABOUT THE INSTRUMENT UNTIL YOU PROVE THE INSTRUMENT CAN SEE.**
    Do not read this invariant's corpus-wide zero as "the producers respect the property". Read it as
    "no pair formed, or none that formed was unmeasured", and check which.

    ⚠️ The SCLC case this was originally written for is **refuted** and must not be cited as its witness:
    ``dge_deseq2/read.py:919`` guards NaN explicitly before taking ``max``, and ``modest_tumor_selective``
    under SCLC is FIX 4b's documented, backtest-driven demotion, not a fall-through. See the plan's
    REVISION §4/§4a.

    ⇒ The remedy is a **declaration** (Stage 3 ``degrades_with:`` / a class naming the field it bands), not
    a longer candidate list. Corroborating instance from peer session ``1972e09f``:
    ``cellline-protein-abundance-procan`` emits ``protein_expression_class = lineage_restricted`` on 85 of
    343 cards while ``per_lineage_stats == []`` — same family, and also invisible here because a structured
    list is not a number and shares no stem with the token. Their proposed fix (pair on the **token's**
    stem, so ``low`` → ``n_domains_low_plddt``) was measured on this card: **139 fires, 10 true, 129 false
    (7.2% precision), 0 missed**. Usable as an admission filter intersected with ``non_finite``; not usable
    alone, because the premise "the companion evidence field must be non-zero" holds for a companion that
    ENUMERATES evidence and inverts for one that COUNTS DEFICIENCIES (``n_domains_low_plddt == 0`` means
    evaluated and clean — ACTB has pLDDT 95.2 and zero low-pLDDT domains, correctly).
    """
    by_leaf = {f.split(".")[-1]: f for f in flat}
    for leaf, f in sorted(by_leaf.items()):
        if not leaf.endswith("_class"):
            continue
        v = flat[f]
        if not isinstance(v, str) or _is_abstain(v):
            continue
        stem = leaf[: -len("_class")]
        for cand in (stem, f"{stem}_value", f"{stem}_score"):
            if cand in by_leaf and cand != leaf:
                src = flat[by_leaf[cand]]
                if _is_number(src) and not math.isfinite(float(src)):
                    yield Finding(
                        "class_from_unmeasured",
                        pkg,
                        card_id,
                        f,
                        v,
                        f"class {v!r} was banded from {cand}={src!r}, which is not a finite number — "
                        f"every comparison against it is False, so a band cascade falls through to its "
                        f"final else",
                    )
                break


# ── invariant 1b: non-finite OUTSIDE the cards ──────────────────────────────────────────────────────


def _non_finite_envelope(package: dict, pkg: str) -> Iterator[Finding]:
    """Non-finite values anywhere in the package that is NOT ``cards[]``. FATAL. Reported separately.

    ★ **Separately named so the two rates are never pooled, because they need different fixes and one is
    derived from the other.** ``synthesis.*`` largely re-publishes card numbers into the evidence graph,
    the capsules and the claim vectors, so a card defect appears here 3-5 times over and a shared rate
    would count one producer bug as several. Measured: 978 leaves in ``skill_reports`` / 282 in
    ``evidence_capsules`` / 120 in ``claim_vectors``.

    ★★ It is still worth its own invariant rather than being dropped as redundant, and the reason is the
    recorded rule that *verdict-inert ≠ atlas-inert*: ``synthesis.claim_vectors`` is what ``build_atlas``
    reads, so a non-finite value that reaches it reaches the frozen atlas — where a NaN entering a hashed
    canonical form reports as ordinary digest DRIFT rather than as an invalid artifact.
    """
    for key, node in package.items():
        if key == "cards":
            continue
        for f in _non_finite(pkg, "", node):
            yield Finding(
                "non_finite_envelope",
                pkg,
                "",
                f"{key}{f.field}" if f.field.startswith(".") else f"{key}.{f.field}",
                f.value,
                f.detail,
            )


# ── invariant 6: strict JSON ────────────────────────────────────────────────────────────────────────


def _raise_constant(tok: str):
    raise ValueError(tok)


def strict_json_findings(pkg: str, raw: str) -> list[Finding]:
    """The persisted artifact must parse as STRICT JSON. FATAL.

    ``json.loads`` accepts the non-standard ``NaN``/``Infinity`` literals by default, which is exactly
    why no in-repo reader ever noticed: Python's permissive parser silently round-trips a file that no
    conforming JSON reader elsewhere will accept. ``ACTB-SCLC/evidence_package.json`` carries 265 literal
    ``NaN`` tokens.

    ⚠️ The reported count is a regex over the RAW TEXT, so a string VALUE that happens to spell ``NaN``
    inflates it — the detail says so rather than claiming a precision it does not have. This is not a
    hypothetical: writing fixture files whose own prose described the tokens they carry inflated the count
    from 2 to 5. Same shape as the settled ``warning_predicates`` 74-vs-78 trap, where a comment
    documenting a deliberately ABSENT key grep-matched as though the key were declared. The count is a
    blast-radius hint for a human; the FINDING is the parse failure, and that part is exact.
    """
    try:
        json.loads(raw, parse_constant=_raise_constant)
    except ValueError as exc:
        tok = str(exc)
        n = len(re.findall(r"\b(NaN|-?Infinity)\b", raw))
        return [
            Finding(
                "strict_json",
                pkg,
                "",
                "",
                tok,
                f"file does not parse as strict JSON; first non-standard constant {tok!r}. "
                f"{n} occurrence(s) of a NaN/Infinity token in the RAW TEXT — an upper bound on the "
                f"blast radius, since a string value spelling the token is counted too",
            )
        ]
    return []


# ── the sweep ───────────────────────────────────────────────────────────────────────────────────────

#: Every invariant this module implements, in report order. Named so a test can assert the set is
#: complete rather than trusting that a loop covers it.
INVARIANTS = (
    "non_finite",
    "non_finite_envelope",
    "domain_declared",
    "domain_unglossed",
    "interval_containment",
    "interval_order",
    "class_from_unmeasured",
    "abstention_incoherent",
    "strict_json",
)


def scan_package(
    package: dict, name: str, *, units: dict[str, Any] | None = None, heuristics: bool = False
) -> list[Finding]:
    """Every field-level invariant over one already-parsed evidence package.

    ``heuristics=False`` (the default) runs only the invariants whose violations are DEFECTS. Set it True
    to add :func:`_abstention_coherence`, which fires on 504 of 504 corpus packages and is retained as a
    measurement rather than as a check — read its docstring before acting on its output.
    """
    units = _gloss_units() if units is None else units
    out: list[Finding] = []
    for card in package.get("cards") or []:
        cid = card.get("card_id") or ""
        flat = flatten_summary(card.get("summary") or {})
        # `_`-prefixed keys are private-by-convention and already filtered by write_package; they are
        # legal and undeclared, so excluding them here keeps this module from relitigating a settled
        # question (contracts #776) about which keys must be declared.
        flat = {f: v for f, v in flat.items() if not f.split(".")[-1].startswith("_")}
        # ★ the structural check gets the RAW summary (lists and all); the semantic ones get `flat`.
        out += list(_non_finite(name, cid, card.get("summary") or {}))
        out += list(_domain(name, cid, flat, units))
        out += list(_intervals(name, cid, flat))
        out += list(_class_from_unmeasured(name, cid, flat))
        if heuristics:
            out += list(_abstention_coherence(name, cid, flat))
    out += list(_non_finite_envelope(package, name))
    return out


def scan_package_file(path: Path, *, units: dict[str, Any] | None = None, heuristics: bool = False) -> list[Finding]:
    """:func:`scan_package` plus the file-level strict-JSON invariant."""
    name = path.parent.name
    raw = path.read_text()
    out = strict_json_findings(name, raw)
    out += scan_package(json.loads(raw), name, units=units, heuristics=heuristics)
    return out


def iter_corpus(corpus: Path) -> Iterator[Path]:
    """``evidence_package.json`` paths under a corpus directory, sorted for byte-stable output."""
    return iter(sorted(corpus.glob("*/evidence_package.json")))


def scan_corpus(corpus: Path, *, heuristics: bool = False) -> list[Finding]:
    units = _gloss_units()
    out: list[Finding] = []
    for p in iter_corpus(corpus):
        out += scan_package_file(p, units=units, heuristics=heuristics)
    return out


def summarise(findings: Iterable[Finding]) -> dict:
    """Counts by invariant and by ``(invariant, card_id, field)``, for a baseline artifact.

    ★ Reports a distinct-PACKAGE count alongside the row count. A row count alone cannot distinguish
    "one card is always wrong" from "many cards are occasionally wrong", and those need different fixes —
    the same degeneracy that invalidated a 33-pair correlation result measured over 2 targets.
    """
    findings = list(findings)
    by_inv: dict[str, dict] = {}
    for f in findings:
        slot = by_inv.setdefault(f.invariant, {"rows": 0, "packages": set(), "pairs": set()})
        slot["rows"] += 1
        slot["packages"].add(f.package)
        slot["pairs"].add((f.card_id, f.field))
    return {
        "total_rows": len(findings),
        "by_invariant": {
            k: {"rows": v["rows"], "packages": len(v["packages"]), "card_field_pairs": len(v["pairs"])}
            for k, v in sorted(by_inv.items())
        },
        "red_list": sorted({(f.invariant, f.card_id, f.field) for f in findings}),
    }
