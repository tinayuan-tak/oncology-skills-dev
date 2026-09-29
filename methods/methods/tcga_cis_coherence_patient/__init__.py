"""tcga_cis_coherence_patient — PATIENT arm of cis-feature-expression-coherence.

Composes three existing case-keyed readers (patient expression, per-sample GISTIC CN, HM450 promoter
methylation) and reuses depmap_cis_dosage.compute_cis_dosage to answer, in patient tumours:

  - does copy-number track the gene's OWN expression (amplification-driven cis-coherence)?
  - do promoter-methylated patients express the gene LOWER (epigenetic-silencing cis-coherence)?

The join is entirely at the 3-segment TCGA CASE barcode — the cross-product joinability that
tcga-sample-id-crosswalk-v1 established (R4). VERDICT-INERT additive patient facet: it corroborates
the cell-line cis_coherence verdict, it does not drive it.

Entry point: methods.tcga_cis_coherence_patient.cli.compute_patient_cis_coherence(target, indication).
Card entrypoint (dispatcher convention): read_patient_cis_coherence(target, indication, release_pin).
"""

from .cli import METHOD_VERSION, compute_patient_cis_coherence, read_patient_cis_coherence  # noqa: F401
