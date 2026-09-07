"""gdsc_drug_activity — per-gene GDSC (Sanger GDSC1+GDSC2) drug-activity reader.

The ORTHOGONAL cell-line drug-sensitivity comparator to PRISM (depmap_prism_activity):
a different lab (Sanger + MGH vs Broad), assay, and compound library, so a target whose
small-molecule tractability signal REPRODUCES across GDSC and PRISM is far more credible
than either alone. VERDICT-INERT display corroboration in tractability-small-molecule
(the ProCan->Gygi analog): it feeds NO interpretation rule and NO resolver rung.

Modules:
    cli  — loaders (per-gene pushdown + target_resolution sidecar HGNC-alias fallback) +
           load_and_classify + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401 — the GENERIC dispatcher does getattr(pkg, entrypoint)
