"""Layer-2 core: safety_verdict_by_modality proves the KRAS worked example.

Reads the merged L0/L1 contracts (modality.enum.yaml::wt_engagement +
wt_loss_safety_conditioning.yaml) from TARGET_CONTRACTS_ROOT. Pure/deterministic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/ on path
from _skills_common.modality_safety import safety_verdict_by_modality

# KRAS/COADREAD real safety fired-set (harvested from a live --verdict-only run):
# 4 germline WT-loss warnings fire; mouse-KO is developmental_only (NOT the lethal warning),
# normal-tissue is broadly_expressed (NOT the protein-liability warning), no pan-essential.
KRAS_FIRED = [
    {"rule_id": "strongly-selective-supportive"},
    {"rule_id": "cn-broadly-neutral-neutral"},
    {"rule_id": "alteration-role-gof-driver-supportive"},
    {"rule_id": "functional-gene-state-sporadic-biallelic-neutral"},
    {"rule_id": "normal-liability-broadly-expressed-neutral"},
    {"rule_id": "highly-constrained-safety-warning"},
    {"rule_id": "oncogene-role-safety-context"},
    {"rule_id": "activating-driver-role-safety-context"},
    {"rule_id": "gene-burden-lof-safety-warning"},
    {"rule_id": "clingen-dominant-loss-safety-warning"},
    {"rule_id": "mouse-ko-developmental-only-neutral"},
    {"rule_id": "clinvar-germline-pathogenic-safety-warning"},
]


def test_kras_modality_split():
    v = safety_verdict_by_modality(KRAS_FIRED)
    # small molecule: WT-loss concerns apply to a WT-engaging SM, but an allele-selective
    # (G12C covalent) agent spares WT -> conditional, NOT a flat hold.
    assert v["small_molecule"]["action"] == "conditional"
    # degrader / RNA remove total protein -> the WT-loss concern stands.
    assert v["degrader"]["action"] == "hold"
    assert v["rna_therapeutic"]["action"] == "hold"
    # surface modalities: WT-loss is not their operative safety axis.
    for ch in ("adc", "bite_tce", "antibody"):
        assert v[ch]["action"] == "not_applicable"
    # the 4 germline WT-loss warnings are attributed as driving rules on the SM/degrader channels
    assert "highly-constrained-safety-warning" in v["degrader"]["driving_rules"]
    assert len(v["degrader"]["driving_rules"]) == 4


def test_no_concern_fired():
    v = safety_verdict_by_modality([{"rule_id": "tolerant-safety-supportive"}])
    assert v["degrader"]["action"] == "no_concern"
    assert v["small_molecule"]["action"] == "no_concern"
    assert v["adc"]["action"] == "not_applicable"


def test_protective_only_derisks_engages_wt():
    v = safety_verdict_by_modality([{"rule_id": "gene-burden-protective-favorable"}])
    assert v["degrader"]["action"] == "supportive"  # full KO de-risked by protective genetics
    assert v["rna_therapeutic"]["action"] == "supportive"
    assert v["small_molecule"]["action"] == "no_concern"  # conditional channel: protective not asserted


def test_deterministic():
    assert safety_verdict_by_modality(KRAS_FIRED) == safety_verdict_by_modality(KRAS_FIRED)


# A highly-constrained NON-GoF target (TSG / housekeeping): a WT-loss concern fires but NO
# allele-selective-eligibility rule -> a pan small-molecule inhibitor engages WT -> hold, NOT conditional.
NONGOF_CONSTRAINED_FIRED = [{"rule_id": "highly-constrained-safety-warning"}]


def test_nongof_constrained_small_molecule_holds():
    v = safety_verdict_by_modality(NONGOF_CONSTRAINED_FIRED)
    assert v["small_molecule"]["action"] == "hold", v["small_molecule"]  # no allele-selective escape
    assert v["degrader"]["action"] == "hold", v["degrader"]


# B4-1 regression (S1): a TUMOR SUPPRESSOR with a spurious IntOGen 'Act' label fires the activating
# eligibility signal but NOT the oncogene-role co-gate (oncokb_gene_type != ONCOGENE). It must NOT earn
# the allele-selective small_molecule escape — a TSG is not drugged by a mutant-selective activator that
# spares WT, so the WT-loss HOLD must stand. (SMARCA2 archetype: oncokb_gene_type=TSG, direction=activating.)
TSG_SPURIOUS_ACTIVATING_FIRED = [
    {"rule_id": "highly-constrained-safety-warning"},
    {"rule_id": "activating-driver-role-safety-context"},  # spurious IntOGen 'Act' on a TSG
    # NOTE: no oncogene-role-safety-context (oncokb_gene_type is NOT ONCOGENE)
]


def test_tsg_spurious_activating_still_holds():
    v = safety_verdict_by_modality(TSG_SPURIOUS_ACTIVATING_FIRED)
    assert v["small_molecule"]["action"] == "hold", v["small_molecule"]  # co-gate blocks the escape
    assert v["degrader"]["action"] == "hold", v["degrader"]
