"""Offline tests for pancan_arm_cnv derivation (pure functions; no S3)."""

from __future__ import annotations

import pandas as pd

from onc_methods.pancan_arm_cnv.read import arm_of, build_arm_calls, build_arm_indication_freq


def test_arm_of_parsing():
    assert arm_of("1p36.33") == "1p"
    assert arm_of("12q24.11") == "12q"
    assert arm_of("Xp22.33") == "Xp"
    assert arm_of("Yq11") == "Yq"
    assert arm_of(None) is None
    assert arm_of("") is None


_GISTIC = pd.DataFrame(
    {
        "Gene Symbol": ["G1", "G2", "G3", "G4", "G5"],
        "Locus ID": [1, 2, 3, 4, 5],
        "Cytoband": ["1p36.33", "1p36.32", "1p11", "1q21", "1q22"],
        "S1": [-1, -2, -1, 0, 0],  # 1p all lost, 1q neutral
        "S2": [0, 0, 1, 1, 2],  # 1p neutral (1/3 gain), 1q gained
    }
)


def test_build_arm_calls():
    ac = build_arm_calls(_GISTIC, threshold=0.5)

    def call(s, arm):
        row = ac[(ac.sample_barcode == s) & (ac.chromosome_arm == arm)].iloc[0]
        return row["arm_call"]

    assert call("S1", "1p") == -1  # 3/3 genes lost -> loss
    assert call("S1", "1q") == 0  # neutral
    assert call("S2", "1p") == 0  # only 1/3 gained -> below 0.5
    assert call("S2", "1q") == 1  # 2/2 gained -> gain
    # loss_frac recorded
    assert ac[(ac.sample_barcode == "S1") & (ac.chromosome_arm == "1p")].iloc[0]["loss_frac"] == 1.0


def test_build_arm_indication_freq():
    ac = build_arm_calls(_GISTIC, threshold=0.5)
    freq = build_arm_indication_freq(ac, {"S1": "COAD", "S2": "COAD"})
    p1 = freq[(freq.chromosome_arm == "1p") & (freq.indication == "COAD")].iloc[0]
    assert p1["n_samples"] == 2 and p1["loss_frequency"] == 0.5  # S1 loss, S2 neutral
    q1 = freq[(freq.chromosome_arm == "1q") & (freq.indication == "COAD")].iloc[0]
    assert q1["gain_frequency"] == 0.5  # S2 gain, S1 neutral


def test_unmapped_barcodes_dropped():
    ac = build_arm_calls(_GISTIC, threshold=0.5)
    freq = build_arm_indication_freq(ac, {"S1": "COAD"})  # S2 unmapped
    assert (freq["n_samples"] == 1).all()  # only S1 counted
