"""genie_sv_recurrence — coverage-correct GENIE structural-variant (fusion/rearrangement) breadth.

The GENIE-SV twin of genie_panel_recurrence. TCGA's fusion-consensus product spans 33 tissues but
is shallow (LUAD carries ~5 ALK fusions); GENIE's data_sv.txt carries 56k somatic SV rows across
271k panel tumors (774 ALK-SV NSCLC samples, EML4 the dominant partner). This method surfaces that
breadth as a coverage-correct, verdict-inert DISPLAY facet alongside the TCGA fusion card.

The load-bearing correctness point (identical to the mutation side): GENIE is panel-seq, so a gene's
SV frequency is sv_bearing_covered / n_sv_covered — samples whose panel was queried for SV AND covers
the gene — NEVER sv_bearing / n_total. A sample not SV-profiled (blank `sv` panel) or on a panel that
doesn't cover the gene is not a measured wild-type; it is not-sequenced, and must leave the denominator.

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    genie_sv_recurrence_for_gene,
    build_genie_sv_recurrence_table,
)
