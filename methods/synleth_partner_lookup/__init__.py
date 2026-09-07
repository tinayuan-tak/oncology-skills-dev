"""synleth_partner_lookup — curated synthetic-lethal partner annotation (Gate C).

Gate-C step 2 (complements the paralog-buffering veto-suppressor): the PUBLISHED,
citable SL layer. Inverts SynLethDB v3 (CC-BY-4.0, 37,943 human SL pairs) into a
per-gene partner index (derived synlethdb-sl-partners-per-gene-v1) and provides a
lookup reader.

ANNOTATION, not measurement: a curated SL partner means a pooled `non_dependent`
CRISPR read is NOT a trusted negative (the target may be a genuine dependency in the
partner-altered context — SMARCA2←SMARCA4-loss, ARID1B←ARID1A). It SUPPRESSES a veto
to `insufficient`; it NEVER nominates and NEVER suppresses pan_essential. Fixes the
partner-conditional SL false-negative the paralog suppressor (intra-family) can't catch.

`has_experimental_partner` is the trustworthy tier (CRISPR/RNAi/throughput screen);
computational-only annotation is weaker.

Modules:
    derive — precompute: invert SL pair-list → per-gene partner parquet
    read   — read_target_summary: the live-mode dispatcher entry (point lookup)
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
