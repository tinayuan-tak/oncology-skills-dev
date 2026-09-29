"""surface_localization_concordance.cli — the concordance classifier + reader join.

Joins two target-grain surface-localization reads into a descriptive, verdict-INERT
`surface_context_concordance_class`:
  * cell-line arm   — depmap_surfaceome_protein_abundance.read_target_summary(target)
                      → `surface_localization_class` ∈ {surface_confirmed, mixed,
                        intracellular_contaminant, insufficient}
                      (DepMap Surfaceome 26Q3 PAIRED DIA-MS surface-vs-wholecell enrichment)
  * orthogonal arm  — cspa_surface_confirmation.read_surface_confirmation(target)
                      → `surface_confirmation_class` ∈ {confirmed_high, confirmed, not_surface,
                        data_unavailable}
                      (CSPA extracellular wet-lab MS capture + HPA-IF plasma-membrane microscopy)

Both arms are target-grain (indication-independent), so the concordance is target-grain.
"""

from __future__ import annotations

from typing import Callable, Optional

from . import METHOD_VERSION

# ── Concordance vocabulary (verdict-INERT display; see target-contracts card) ────────────────────
CLASS_CONCORDANT_SURFACE = "concordant_surface"  # both arms confirm surface localization
CLASS_CONCORDANT_NOT_SURFACE = "concordant_not_surface"  # both arms agree it is NOT a surface antigen
CLASS_DISCORDANT = "discordant"  # one confirms surface, the other measured-negative
CLASS_CELL_LINE_ONLY = "cell_line_only"  # cell-line confirms; orthogonal arm non-committal
CLASS_SURFACE_EVIDENCE_ONLY = "surface_evidence_only"  # orthogonal confirms; cell-line arm non-committal
CLASS_INSUFFICIENT = "insufficient"  # both non-committal, or a residual ambiguous case

# cell-line surface_localization_class tokens that are a MEASURED committal call. `mixed`
# (heterogeneous surface localization) and `insufficient` / `data_unavailable` / None are
# deliberately treated as NON-committal for concordance — a coarse, conservative mapping that keeps
# the facet inert until validated on a target panel (does NOT over-claim concordance from an
# ambiguous cell-line read).
_CL_SURFACE = "surface_confirmed"
_CL_NOT_SURFACE = "intracellular_contaminant"

# orthogonal surface_confirmation_class tokens
_EV_SURFACE = frozenset({"confirmed_high", "confirmed"})
_EV_NOT_SURFACE = "not_surface"
# `data_unavailable` / None → non-committal


def classify_surface_concordance(
    cellline_localization_class: Optional[str],
    orthogonal_confirmation_class: Optional[str],
) -> str:
    """Coarse, symmetric cross-tab of the two arms → surface_context_concordance_class.

    Verdict-INERT. Deliberately conservative: a cell-line `mixed` call and any
    measured-negative-vs-non-committal asymmetry route to `insufficient` rather than over-claiming.
    """
    cl_pos = cellline_localization_class == _CL_SURFACE
    cl_neg = cellline_localization_class == _CL_NOT_SURFACE
    cl_committal = cl_pos or cl_neg
    ev_pos = orthogonal_confirmation_class in _EV_SURFACE
    ev_neg = orthogonal_confirmation_class == _EV_NOT_SURFACE
    ev_committal = ev_pos or ev_neg

    if cl_pos and ev_pos:
        return CLASS_CONCORDANT_SURFACE
    if cl_neg and ev_neg:
        return CLASS_CONCORDANT_NOT_SURFACE
    if (cl_pos and ev_neg) or (cl_neg and ev_pos):
        return CLASS_DISCORDANT
    if cl_pos and not ev_committal:
        return CLASS_CELL_LINE_ONLY
    if ev_pos and not cl_committal:
        return CLASS_SURFACE_EVIDENCE_ONLY
    # residual: measured-negative-vs-non-committal, `mixed` combinations, or both non-committal
    return CLASS_INSUFFICIENT


_SUBSTRATE_NOTE = (
    "cell_line: depmap-surfaceome-paired-per-protein-v1 (DepMap Surfaceome 26Q3 paired DIA-MS "
    "surface-vs-wholecell enrichment); orthogonal: cspa-surface-confirmation-per-uniprot-v1 "
    "(CSPA wet-lab extracellular MS + HPA-IF). Orthogonal surface-localization corroboration "
    "(target grain), NOT a tumor-microenvironment concordance — no tumor surface substrate covers "
    "gastric/esophageal (see target-contracts#966)."
)


def _default_surfaceome_reader() -> Callable[..., dict]:
    from methods.depmap_surfaceome_protein_abundance.read import read_target_summary

    return read_target_summary


def _default_surface_evidence_reader() -> Callable[..., dict]:
    from methods.cspa_surface_confirmation.read import read_surface_confirmation

    return read_surface_confirmation


def load_and_classify(
    target: str,
    *,
    surfaceome_reader: Optional[Callable[..., dict]] = None,
    surface_evidence_reader: Optional[Callable[..., dict]] = None,
) -> dict:
    """Join the two child readers and classify the surface-localization concordance for `target`.

    `surfaceome_reader` / `surface_evidence_reader` are offline injection seams (hermetic tests);
    when None the real sibling readers are imported lazily. Neither child reader raises on a genuine
    coverage gap (they return data_unavailable / a measured negative); a transient/infra fault
    PROPAGATES from here so read_target_summary can surface an honest `_live_read_error` rather than
    a silent dead axis.
    """
    read_cl = surfaceome_reader or _default_surfaceome_reader()
    read_ev = surface_evidence_reader or _default_surface_evidence_reader()

    cl = read_cl(target) or {}
    ev = read_ev(target) or {}

    cl_class = cl.get("surface_localization_class")
    ev_class = ev.get("surface_confirmation_class")
    concordance = classify_surface_concordance(cl_class, ev_class)

    return {
        "surface_context_concordance_class": concordance,
        "cellline_surface_localization_class": cl_class,
        "orthogonal_surface_confirmation_class": ev_class,
        # cell-line arm context (verdict-INERT passthrough)
        "cellline_median_enrichment_log2ratio": cl.get("median_enrichment_log2ratio"),
        "cellline_n_lines_enrichment_evaluated": cl.get("n_lines_enrichment_evaluated"),
        # orthogonal arm context (verdict-INERT passthrough)
        "orthogonal_measured_in_cspa": ev.get("measured_in_cspa"),
        "orthogonal_n_celllines_detected": ev.get("n_celllines_detected"),
        "concordance_substrate": _SUBSTRATE_NOTE,
        "method_version": METHOD_VERSION,
    }


def _empty(note: str) -> dict:
    """The concordance summary when the join could not be computed (infra fault)."""
    return {
        "surface_context_concordance_class": CLASS_INSUFFICIENT,
        "cellline_surface_localization_class": None,
        "orthogonal_surface_confirmation_class": None,
        "cellline_median_enrichment_log2ratio": None,
        "cellline_n_lines_enrichment_evaluated": None,
        "orthogonal_measured_in_cspa": None,
        "orthogonal_n_celllines_detected": None,
        "concordance_substrate": _SUBSTRATE_NOTE,
        "method_version": METHOD_VERSION,
        "_data_note": note,
    }


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Verdict-inert cell-line ↔ orthogonal surface-localization concordance (target grain)."
    )
    ap.add_argument("--target", required=True)
    args = ap.parse_args(argv)
    print(json.dumps(load_and_classify(args.target), indent=2, default=str))


if __name__ == "__main__":
    _main()
