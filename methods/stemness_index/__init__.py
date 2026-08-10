"""stemness_index — per-indication mRNAsi tumor-stemness context (Malta 2018, REIMPLEMENTED).

Verdict-INERT cohort-context facet: how stem-like/dedifferentiated is an indication's TCGA cohort?
High mRNAsi tracks dedifferentiation + aggressiveness — a prognostic/aggressiveness cohort prior.

REIMPLEMENTATION: Malta 2018 does NOT distribute per-sample mRNAsi (only the signature WEIGHTS ship,
per the GDC PanCan-Stemness manifest). We reimplement their one-class scoring — per-sample Spearman
corr(expression, mRNAsi weights) over the 12,945-gene signature, PAN-CANCER min-max to [0,1]
(cross-indication comparable) — applied to recount3/TCGA. Faithful reimplementation, NOT the published
per-sample table (carried as an explicit caveat).

Per-indication rollup (median mRNAsi + stemness_class relative to the pan-cancer distribution). Emits
stemness_class ∈ {stem_high, stem_intermediate, stem_low, data_unavailable}. VERDICT-INERT.
"""
from .read import read_stemness_index, METHOD_VERSION  # noqa: F401
