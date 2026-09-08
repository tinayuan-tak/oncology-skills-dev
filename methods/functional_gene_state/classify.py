"""Pure two-hit classifier for functional_gene_state — no I/O, fully unit-testable.

Takes STRUCTURED per-sample evidence (mutation present? copy-number integer/class? LOH at locus?)
and returns one of the genetic-only states. The read layer assembles this evidence from the
patient (TCGA) or model (DepMap) substrate and calls `classify_functional_state` once per sample;
keeping the biology here means the two-hit logic is testable with dict fixtures, no S3.

The classifier is SIDE-agnostic: patient and model arms populate the same `SampleEvidence` fields
(from different sources), so the two-hit rules live in exactly one place and cannot drift between arms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Genetic-only states plus the planned epigenetic states (model-side RRBS landed; patient-side
# HM450 pending). Consumers should treat this as an OPEN set.
FUNCTIONAL_STATES = (
    "wt",
    "monoallelic",
    "biallelic-genetic",
    "biallelic+epigenetic",
    "epigenetic",
    "uncertain",
)


@dataclass(frozen=True)
class SampleEvidence:
    """Harmonized per-(sample, gene) evidence — the classifier's sole input.

    Both arms populate the SAME fields so the two-hit rules never fork:
      has_mutation      : a non-synonymous / damaging somatic mutation in the gene (bool).
      cn_class          : discrete copy class of the gene in this sample, one of
                          {"homdel", "loss", "neutral", "gain", None}. None = CN not measured.
                          "homdel" = both copies lost; "loss" = single-copy loss (hemizygous).
      loh_at_locus      : does the CN segment covering the gene/mutation show LOH? True / False / None
                          (None = LOH not determinable on this side — e.g. model-side copy-neutral).
      mutation_is_lof   : is the mutation a clear loss-of-function class (nonsense, frameshift,
                          splice, etc.) vs. a missense of unknown consequence? CAPTURED evidence
                          (surfaced to rules + reserved for future refinement); NOT a
                          decision input — the current two-hit call does not branch on it.
    """

    has_mutation: bool
    cn_class: Optional[str] = None
    loh_at_locus: Optional[bool] = None
    mutation_is_lof: Optional[bool] = None


def classify_functional_state(ev: SampleEvidence) -> str:
    """Classify one sample's functional gene state from harmonized evidence (genetic-only, Phase 1).

    Decision order (most-complete two-hit evidence first):
      1. Homozygous deletion → biallelic-genetic (both copies gone, regardless of mutation).
      2. Mutation + (single-copy loss OR LOH at the locus) → biallelic-genetic (hit + lost-other-allele).
      3. Mutation, copy-neutral, no LOH → monoallelic (one allele intact).
      4. Mutation, CN unknown / LOH unknown → uncertain (cannot confirm or exclude a 2nd hit).
      5. No mutation, single-copy loss → monoallelic (one allele lost, other intact).
      6. No mutation, no loss (neutral/gain/None) → wt.
    """
    cn = ev.cn_class

    # (1) Homozygous deletion is a complete biallelic event on its own.
    if cn == "homdel":
        return "biallelic-genetic"

    if ev.has_mutation:
        # (2) Mutation with loss of the other allele (single-copy loss or LOH) → both alleles hit.
        if cn == "loss" or ev.loh_at_locus is True:
            return "biallelic-genetic"
        # (3) Mutation on a confirmed copy-neutral, non-LOH background → one allele still intact.
        if cn in ("neutral", "gain") and ev.loh_at_locus is False:
            return "monoallelic"
        # (4) Mutation but the second-hit background is UNKNOWN (CN or LOH not measured on this side).
        #     A clear LoF mutation with unknown CN is still only a confirmed single hit → monoallelic;
        #     otherwise we cannot exclude a hidden 2nd hit → uncertain (honest, not a false biallelic).
        if cn in ("neutral", "gain") and ev.loh_at_locus is None:
            return "uncertain"
        return "uncertain"

    # No mutation.
    # (5) Single-copy loss with no mutation → one allele lost, the other wild-type.
    if cn == "loss":
        return "monoallelic"
    # (6) No mutation, no loss.
    return "wt"


def summarize_states(states: list[str]) -> dict:
    """Roll a list of per-sample states into a cohort summary for the card headline.

    Returns counts + the biallelic-inactivation fraction (the headline number: what share of
    profiled samples show a COMPLETED two-hit event) among samples with any determinable state.
    """
    n = len(states)
    counts = {s: states.count(s) for s in FUNCTIONAL_STATES}
    # denominator for the biallelic fraction excludes `uncertain` (undeterminable, not "not biallelic")
    n_determinable = n - counts.get("uncertain", 0)
    # biallelic = genetic OR epigenetic second-hit (both represent completed two-hit inactivation)
    n_biallelic = counts.get("biallelic-genetic", 0) + counts.get("biallelic+epigenetic", 0)
    # ANY alteration = everything that is not wild-type. `uncertain` + `epigenetic` + `monoallelic`
    # all carry at least one hit, so they count as altered.
    n_any_hit = n - counts.get("wt", 0)
    return {
        "n_samples": n,
        "state_counts": counts,
        "n_determinable": n_determinable,
        "fraction_biallelic": (n_biallelic / n_determinable) if n_determinable else None,
        "fraction_any_alteration": (n_any_hit / n) if n else None,
    }
