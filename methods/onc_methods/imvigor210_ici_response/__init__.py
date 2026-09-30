"""imvigor210_ici_response — pan-indication (urothelial) ICI-response + immune-phenotype reader.

Reads imvigor210-ici-response-per-gene-v1 (IMvigor210 atezolizumab mUC): per gene, expression in
responders vs non-responders + the desert/excluded/inflamed IHC-phenotype enrichment. The urothelial
ICI-response leg for immune-context — beyond the melanoma-only ici-response-association card, and
carrying the desert/excluded/inflamed ground-truth the relative CIBERSORT call cannot produce.
Urothelial-scoped → data_unavailable for other indications (honest scope ceiling).
"""

from .read import METHOD_VERSION, read_target_summary  # noqa: F401
