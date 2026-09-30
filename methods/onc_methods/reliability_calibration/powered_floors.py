"""powered_floors — the per-property-KIND `n_effective` floor behind `reliability.powered` (#2327).

WHAT `powered` MEANS, and why the floor is a MEASUREMENT and not a round number. `reliability.powered`
(#2306) is a verdict-INERT (SK#2091) tri-state: `true` / `false` / the `unmeasured` string sentinel. It
answers ONE question — is there enough sample behind THIS property's own `n_effective` anchor for the
measurement to be trusted at face value? A floor is defensible ONLY where `n_effective` is a genuine
sample SIZE (a denominator whose smallness makes the estimate unstable) AND the property's own method
already encodes the size below which it declines to trust the read. Where either is false, the honest
outcome is to keep the kind `unmeasured` and SAY WHY (see `POWERED_FLOOR_UNMEASURED`) — a fabricated
floor on an evidence count or a fixed reference panel would misrepresent it.

THE THREE CALIBRATED KINDS. Each floor is that property's method's OWN power-admissibility guard,
IMPORTED (never re-declared) so a drift in the method reds the pin, not the emit:

  n_cell_lines_evaluated       (CRISPR / crispr_essentiality)           floor = PAN_ESSENTIAL_MIN_PANEL_N
      depmap_chronos_distribution: below this panel size a >=85% strongly-dependent call is routed to
      `common_essential_underpowered` -> insufficient — the method's own statement that a Chronos
      dependency DISTRIBUTION (median, tail, strongly-dependent fraction, selectivity) on a thinner panel
      is a coverage gap, not a trusted read. The same denominator the two `_underpowered` classes are
      decided on. So `powered` on this property IS "did the panel clear the method's own trust floor".

  rnai_n_cell_lines_evaluated  (RNAi / rnai_essentiality)               floor = RNAI_PAN_ESSENTIAL_MIN_PANEL_N
      depmap_demeter_distribution: the identical guard on the DEMETER2 panel. The catalog notes DEMETER2
      panels are materially smaller than CRISPR's, so this floor bites here where it never bites CRISPR.

  n_partner_deficient          (partner_conditional_dependency)         floor = MIN_PARTNER_DEFICIENT_CELLS
      depmap_partner_conditional_dependency: the partner-deficient stratum must reach this size or the
      class is `insufficient_partner_deficient_rate` — the count the deficient-vs-neutral stratification
      test literally rests on. `n_effective` IS that stratum size, so the floor is exactly the method's.

WHY THE FLOORS ARE SINGLE-SOURCED HERE, NOT IN THE CATALOG YET. #2306's catalog RELIABILITY_KEYS shape
does not yet admit a `powered_floor` declaration (that machine-readable shape is #2330, which will rebase
onto this module). Until it lands, the floors live in code exactly as PR#2326 single-sourced its deriver
constants, and dependency.yaml records them as governed `determinants` (value + symbol `source:` +
flip-matrix citation) — documentation mirrors of these constants, never a second authority.
"""

from __future__ import annotations

import functools

# anchor field name -> (onc_methods submodule, constant name). The constant is imported LAZILY (only when
# a calibrated kind is actually resolved) so merely importing this module — or resolving an UNMEASURED
# kind — never pulls a method module in. Mirrors reliability.py::_confound_r_cut's lazy import discipline.
_CALIBRATED_FLOOR_SOURCES = {
    "n_cell_lines_evaluated": ("depmap_chronos_distribution.cli", "PAN_ESSENTIAL_MIN_PANEL_N"),
    "rnai_n_cell_lines_evaluated": ("depmap_demeter_distribution.cli", "RNAI_PAN_ESSENTIAL_MIN_PANEL_N"),
    "n_partner_deficient": ("depmap_partner_conditional_dependency.cli", "MIN_PARTNER_DEFICIENT_CELLS"),
}

# The kinds deliberately kept `unmeasured` (no floor), each with the reason the issue asks for. These are
# NOT holes — they are the honest verdict that `n_effective` is not a power denominator for the kind.
POWERED_FLOOR_UNMEASURED = {
    "n_lineages_evaluated": (
        "the near-fixed DepMap lineage panel breadth (a denominator for n_enriched_lineages), not a "
        "variable sample size; the lineage-selectivity method gates on per-lineage cell counts, not on "
        "the NUMBER of lineages, so there is no method floor to mirror."
    ),
    "n_compounds_evaluated": (
        "an evidence count — the PRISM compounds that survived the per-compound cell-line-intersection "
        "minimum. The concordance class is fixed upstream at precompute time; the method exposes no "
        "minimum NUMBER of compounds, so a power floor on the count would be invented."
    ),
    "n_paralogs_annotated": (
        "a count of annotated paralogs (0 is meaningful — no paralog to buffer), not a sample size. The "
        "buffering class thresholds on the dual-KO GI effect (STRONG_DELTA/PARTIAL_DELTA), never on the "
        "count, so there is no power floor."
    ),
    "n_tissues_tested": (
        "the ~fixed GTEx reference tissue panel (the breadth-fraction denominator), not a variable N; "
        "the normal-tissue method encodes no minimum-tissue-count trust floor to mirror."
    ),
    "n_high_confidence": (
        "the curated ClinGen high-confidence dosage-assertion count; the class already requires >=1 such "
        "assertion, so the count IS the evidence, not an independent power denominator."
    ),
    "n_pathogenic_germline_confident": (
        "the curated ClinVar review-status-filtered confident-pathogenic variant count; the class already "
        "requires >=1, so the count is the evidence itself, not a sample size a floor would gate."
    ),
}


@functools.lru_cache(maxsize=None)
def powered_floor_for(anchor: "str | None") -> "int | None":
    """The calibrated `n_effective` floor for a property-kind, keyed on its `n_effective_anchor`.

    Returns the method's own admissibility constant for the three calibrated kinds, and `None` for every
    other kind (including the six deliberately-unmeasured ones and any unknown anchor) — `None` means the
    deriver keeps `powered: unmeasured`. Only a calibrated kind triggers the lazy method import.
    """
    src = _CALIBRATED_FLOOR_SOURCES.get(anchor)
    if src is None:
        return None
    module_suffix, const = src
    import importlib

    module = importlib.import_module(f"onc_methods.{module_suffix}")
    value = getattr(module, const)
    return int(value)


def calibrated_kinds() -> "frozenset[str]":
    """The anchor field names that carry a calibrated floor — for the flip matrix and its teeth."""
    return frozenset(_CALIBRATED_FLOOR_SOURCES)
