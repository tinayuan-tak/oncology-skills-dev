"""Guard: the maf-filter (genomic-strata) assignment shards are wired in UNION with the base
directly-tagged shards, so a subtype landscape enumerates molecular/histology AND genomic-driver
strata (TP53_mut, KRAS_G12C, ...) in one pass.

P2 depth expansion (2026-08-05): the -maf shards were materialized but the reader consumed only the
base -v1 shards. This pins (a) the -maf map covers exactly the indications with a landed + verified-
powered -maf shard, (b) every -maf indication is also a base indication (a genomic-only indication
would have no pooled distribution to stratify), and (c) the union helper's shape. S3-free (parses the
module literals + the helper's no-fetch branches; the live union is exercised by the module smoke test)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution.read import (  # noqa: E402
    INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST as BASE,
)
from methods.tcga_gtex_expression_distribution.read import (
    INDICATION_TO_TUMOR_MAF_MANIFEST as MAF,
)
from methods.tcga_gtex_expression_distribution.read import (
    _load_subtype_assignments,
)

# The 4 indication FAMILIES with a landed -maf shard whose strata are VERIFIED powered
# (>=SUBGROUP_N_FLOOR members, checked against the emitted artifact 2026-08-04/05):
#   HNSC (TP53_mut, PIK3CA_mut) · ESCA (TP53_mut) · PAAD (TP53_mut, KRAS_G12D, KRAS_WT) ·
#   NSCLC (KRAS_G12C — thin but real). COADREAD/STAD have no -maf shard.
_VERIFIED_MAF_SHARDS = {
    "tcga-subgroup-assignments-hnsc-maf-v1",
    "tcga-subgroup-assignments-nsclc-maf-v1",
    "tcga-subgroup-assignments-esca-maf-v1",
    "tcga-subgroup-assignments-paad-maf-v1",
}


def test_maf_map_covers_exactly_the_verified_maf_shards():
    assert set(MAF.values()) == _VERIFIED_MAF_SHARDS


def test_every_maf_indication_is_also_a_base_indication():
    # A -maf shard with no base shard would have no pooled distribution to stratify — the union
    # helper returns base_manifest=None and the landscape is subtype_axis_unavailable. Guard against
    # that misconfiguration: every genomic-strata indication must also carry directly-tagged strata.
    for ind in MAF:
        assert ind in BASE, f"{ind!r} has a -maf shard but no base shard — union has nothing to anchor"


def test_maf_aliases_share_one_shard():
    assert MAF["NSCLC"] == MAF["LUAD"] == MAF["LUSC"] == "tcga-subgroup-assignments-nsclc-maf-v1"
    assert MAF["HNSC"] == MAF["HNSCC"] == "tcga-subgroup-assignments-hnsc-maf-v1"
    assert MAF["PAAD"] == MAF["PDAC"] == "tcga-subgroup-assignments-paad-maf-v1"


def test_union_helper_returns_none_for_unlisted_indication():
    # An indication with no base shard → (None, None), no fetch attempted (S3-free branch).
    assignments, manifest = _load_subtype_assignments("BRCA")
    assert assignments is None and manifest is None


def test_coadread_has_base_but_no_maf():
    # Regression pin: COADREAD/STAD deliberately have NO -maf shard — the base map must still carry
    # them and the -maf map must not (adding one later requires verifying its emitted strata first).
    assert "COADREAD" in BASE and "COADREAD" not in MAF
    assert "STAD" in BASE and "STAD" not in MAF
