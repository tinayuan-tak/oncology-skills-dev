"""surface_localization_concordance — cell-line ↔ orthogonal surface-localization concordance.

A verdict-INERT JOINER method (target-contracts#966, Surfaceome 26Q3 arc, epic
claude-oncology-skills#2024). It relates the DepMap Consortium Surfaceome 26Q3 PAIRED DIA-MS
surface-vs-wholecell ENRICHMENT call (from depmap_surfaceome_protein_abundance —
`surface_localization_class`) to an ORTHOGONAL, independent wet-lab surface-CONFIRMATION read
(from cspa_surface_confirmation — `surface_confirmation_class`, CSPA extracellular MS capture +
HPA-IF plasma-membrane microscopy), and emits a descriptive `surface_context_concordance_class`
so a target's cell-line surface signal can be read against corroborating surface evidence rather
than in isolation.

DESIGN (see the design note on target-contracts#966): no candidate TUMOR substrate resolves a
surface-specific signal for gastric/esophageal (STAD/ESCA — where the 64-line surfaceome panel is
informative) at tumor target×indication grain (the CPTAC-backed cards exclude STAD/ESCA; the
spatial-surface product is HNSC/NSCLC only). The one surface-localization substrate that IS
populated for gastric/eso targets is the pan-panel, target-grain CSPA/HPA-IF surface-confirmation
read — so this is an orthogonal surface-localization CORROBORATION (target grain), NOT a
tumor-microenvironment concordance. Framed honestly in the emitted `concordance_substrate` and in
the target-contracts card caveats.

This is a thin JOINER: it imports + calls the two existing readers (single source of truth, no
re-derivation), each defensively, mirroring the canonical two-reader-joiner pattern in
methods/cited_literature_evidence/read.py. A genuine coverage gap on either arm never raises (the
child readers return data_unavailable / a measured negative); a transient/infra fault propagates
and degrades the whole read to `_live_read_error` (the generic-dispatch graceful-degradation
contract), never a silent dead axis.

Modules:
    cli  — the concordance classifier + load_and_classify (joins the two child readers) + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
