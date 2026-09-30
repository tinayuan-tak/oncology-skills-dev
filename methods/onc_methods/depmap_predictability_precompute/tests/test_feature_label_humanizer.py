"""Drift-guard for the canonical feature humanizer (#1942).

`feature_label_of` turns a raw prefix-coded feature token (expr_/cn_/arm_/molsig_/lineage_/...)
into a readable phrase, keyed off feature_class_of(). This pins the phrase for each known class and
verifies the two safety contracts the acceptance criteria name:
  - an UNKNOWN prefix falls back to the raw `feature` (never crashes / never blanks it);
  - `_top_features` stamps the humanized `feature_label` onto every emitted struct.
Verdict-INERT: labels are display-only.
"""

from __future__ import annotations

import numpy as np
import pytest

from onc_methods.depmap_predictability_precompute import cli as e5cli
from onc_methods.depmap_predictability_precompute import features as feat


@pytest.mark.parametrize(
    "feature_name,expected",
    [
        ("own_expression", "own expression"),
        ("own_copy_number", "own copy-number"),
        ("own_mut_hotspot", "own hotspot mutation"),
        ("own_mut_damaging", "own damaging mutation"),
        ("expr_CCND1", "CCND1 expression"),
        ("cn_MDM2", "MDM2 copy-number"),
        ("arm_chr12p", "chr12p arm-level copy-number"),
        ("driver_KRAS_GoF", "KRAS gain-of-function driver"),
        ("driver_TP53_LoF", "TP53 loss-of-function driver"),
        ("lineage_Bowel", "lineage membership"),
        ("fusion_EML4_ALK", "EML4_ALK fusion"),
        ("rppa_AKT", "AKT protein abundance"),
        ("ms_SPINT2", "SPINT2 protein abundance"),
        ("paralog_dep_STAG1", "STAG1 paralog dependency"),
        ("molsig_SBS81", "SBS81 mutational signature"),
        ("msi_high_fraction", "MSI status"),
        ("sv_MYC", "MYC structural variant"),
        ("methyl_CDKN2A", "CDKN2A promoter methylation"),
        ("metab_lactate", "lactate metabolite level"),
    ],
)
def test_feature_label_of_known_prefix(feature_name, expected):
    assert feat.feature_label_of(feature_name) == expected


@pytest.mark.parametrize("bad", ["mystery_TOKEN", "totally_unknown", "", "no_prefix_here"])
def test_feature_label_of_unknown_prefix_falls_back_to_raw(bad):
    # class "other" (or empty) -> return the raw token unchanged; never raises.
    assert feat.feature_label_of(bad) == bad


def test_top_features_stamps_humanized_label():
    names = ["expr_CCND1", "cn_MDM2", "arm_chr12p", "lineage_Bowel", "own_expression"]
    ranks = np.array([0.5, 0.4, 0.3, 0.2, 0.1], dtype=float)
    out = e5cli._top_features(names, ranks, k=5)
    by_feature = {rec["feature"]: rec for rec in out}
    assert by_feature["expr_CCND1"]["feature_label"] == "CCND1 expression"
    assert by_feature["arm_chr12p"]["feature_label"] == "chr12p arm-level copy-number"
    assert by_feature["lineage_Bowel"]["feature_label"] == "lineage membership"
    # every emitted struct carries a non-empty label
    assert all(rec.get("feature_label") for rec in out)
