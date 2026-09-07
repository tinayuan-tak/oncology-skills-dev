"""sl_crosswalks — SHARED curated synthetic-lethal / combination crosswalks + pan-essential / scaffold
helpers, the SINGLE SOURCE OF TRUTH for the relational (gene×gene) confidence surfaces.

Extracted from combination-and-vulnerability/scripts/run.py (2026-09-05, literature-and-claims arc) so the
CONSOLIDATED annex (combination-and-vulnerability) AND the two STANDALONE relational skills
(synthetic-lethal-partners, combinatorial-dependency) all key their false-demote guards + inflation scans on
ONE curated corpus rather than drifting copies. Values are BYTE-IDENTICAL to combination-and-vulnerability's
former private constants (its partner_confirmation caveat behaviour is unchanged). PMIDs verified in this
arc's Phase-1 reviews. SET / dict literals (reference-drift guard), never 2-string tuples.

THE TRAP these crosswalks defend against: a STATISTICAL / CURATED / MEASURED relational signal (a curated
SynLethDB edge, a DepMap paralog GI, a co-essentiality delta) OVER-CALLS a CLINICALLY / FUNCTIONALLY
VALIDATED, PORTABLE, DRUGGABLE synthetic lethality. The VALIDATED_* maps are the MILDER false-demote guard
(a canonical validated SL is NOT an over-call); the PAN_ESSENTIAL / SCAFFOLD sets drive the SHARP tiers.
"""

from __future__ import annotations

# NORMALISE the OncoTree code so the COADREAD crosswalks also match the COAD / READ sub-codes.
COMBO_IND_ALIAS = {"COAD": "COADREAD", "READ": "COADREAD"}


def norm_ind(indication) -> str:
    ind = (indication or "").upper().strip()
    return COMBO_IND_ALIAS.get(ind, ind)


# (target, indication) whose TOP relational vulnerability is a CLINICALLY / FUNCTIONALLY-VALIDATED
# combination or synthetic lethality — the MILDER false-demote guard. Spared from the statistical / cell-line
# caveats: these are NOT over-calls. DISCLAIMED / non-exhaustive; an absent (target, indication) degrades to a
# data-derived tier or None.
VALIDATED_COMBINATION_PRECEDENT = {
    ("BRCA1", "BRCA"): (
        "Canonical, clinically-APPROVED synthetic lethality: BRCA-deficiency ↔ PARP1 "
        "(Bryant 2005 PMID 15829966; Farmer 2005 PMID 15829967; clinical PoC Fong 2009 "
        "PMID 19553641; OlympiAD PMID 28578601). NOT a statistical over-call — approved "
        "PARP inhibitors (olaparib/talazoparib)."
    ),
    ("BRCA2", "BRCA"): (
        "Canonical, clinically-APPROVED synthetic lethality: BRCA-deficiency ↔ PARP1 "
        "(Bryant 2005 PMID 15829966; Farmer 2005 PMID 15829967; EMBRACA PMID 30110579). "
        "NOT a statistical over-call — approved PARP inhibitors."
    ),
    ("BRCA1", "OV"): (
        "Canonical, clinically-APPROVED synthetic lethality: BRCA ↔ PARP1 in ovarian "
        "cancer (SOLO-1 maintenance PMID 30345884; Fong 2009 PMID 19553641). NOT an over-call."
    ),
    ("BRCA2", "OV"): (
        "Canonical, clinically-APPROVED synthetic lethality: BRCA ↔ PARP1 in ovarian "
        "cancer (SOLO-1 PMID 30345884). NOT an over-call."
    ),
    ("WRN", "COADREAD"): (
        "Validated-context synthetic lethality: WRN helicase ↔ microsatellite-instability "
        "(MSI-H/dMMR) (Chan 2019 PMID 30971823; Project Score Behan 2019 PMID 30971826; "
        "mechanism — expanded TA repeats — van Wietmarschen 2020 PMID 32999459). Clinical "
        "WRN-helicase inhibitor HRO761 (Ferretti 2024 PMID 38658754; NCT05838768). NOT an "
        "over-call — orthogonally validated + in first-in-human trials. NB the SL is with "
        "MSI STATUS, not the RECQL-family paralogs the DepMap table ranks."
    ),
    ("WRN", "STAD"): (
        "Validated-context WRN ↔ MSI-H synthetic lethality (Chan 2019 PMID 30971823); WRN "
        "inhibitors in MSI-H solid-tumour trials (HRO761 PMID 38658754)."
    ),
    ("WRN", "UCEC"): (
        "Validated-context WRN ↔ MSI-H synthetic lethality (Chan 2019 PMID 30971823); WRN "
        "inhibitors in MSI-H solid-tumour trials (HRO761 PMID 38658754)."
    ),
    ("KRAS", "COADREAD"): (
        "Functionally-validated combination biology: KRAS ↔ SHP2/PTPN11 (Ruess 2018 PMID "
        "29808009; Mainardi 2018 PMID 29808006; Nichols 2018 PMID 30104724) + SOS1 "
        "(BI-3406, Hofmann 2021 PMID 32816843); NF1 loss is a mechanistically-clean "
        "resistance mediator (Awad 2021 PMID 34161704). Leading clinical KRASi combination "
        "strategy (not yet approved) — NOT a statistical over-call."
    ),
    ("KRAS", "PAAD"): (
        "Functionally-validated KRAS ↔ SHP2/PTPN11 + SOS1 combination biology (Ruess/Mainardi "
        "2018 PMID 29808009/29808006; Nichols 2018 PMID 30104724). NOT an over-call."
    ),
    ("KRAS", "LUAD"): (
        "Functionally-validated KRAS ↔ SHP2/PTPN11 + SOS1 combination biology (Mainardi 2018 "
        "PMID 29808006 — SHP2 required for KRAS-mutant NSCLC in vivo). NOT an over-call."
    ),
}

# Canonical PARALOG synthetic-lethal pairs — a CONSTITUTIVE genetic-buffering SL (loss of one paralog makes
# the other essential), INDICATION-INDEPENDENT and orthogonally / clinically validated. The false-demote
# guard for canonical paralog SLs. DATA-BLIND-TOLERANT: DepMap ParalogV2 frequently UNDER-calls these as
# no_interaction / 0-strong-lineages, so the guard keys on the paralog partner's PRESENCE, NOT its
# (often-absent) interaction_class. NOTE the partner is typically an UNDRUGGABLE SCAFFOLD (needs a DEGRADER) —
# so membership here must NOT suppress the druggability caveat (which keys only on
# VALIDATED_COMBINATION_PRECEDENT). key target -> (paralog_partner, detail).
VALIDATED_PARALOG_SL = {
    "SMARCA4": (
        "SMARCA2",
        "Canonical paralog synthetic lethality: SMARCA4(BRG1)-loss ↔ SMARCA2(BRM) "
        "(Oike 2013 PMID 23872584; Hoffman 2014 PMID 24520176). NOT a statistical over-call — "
        "orthogonally validated; SMARCA2 needs a DEGRADER (PROTAC Farnaby 2019 PMID 31178587). NB "
        "DepMap ParalogV2 UNDER-calls this pair (reads no_interaction) — the guard is data-blind-tolerant.",
    ),
    "SMARCA2": (
        "SMARCA4",
        "Canonical paralog synthetic lethality: SMARCA2 ↔ SMARCA4 (Hoffman 2014 PMID 24520176). NOT an over-call.",
    ),
    "ARID1A": (
        "ARID1B",
        "Canonical paralog synthetic lethality: ARID1A-loss ↔ ARID1B (Helming 2014 PMID "
        "24562383). NOT an over-call — ARID1B is a non-enzymatic BAF scaffold (degrader / PPI modality).",
    ),
    "ARID1B": (
        "ARID1A",
        "Canonical paralog synthetic lethality: ARID1B ↔ ARID1A (Helming 2014 PMID 24562383). NOT an over-call.",
    ),
    "STAG2": (
        "STAG1",
        "Canonical paralog synthetic lethality: STAG2-mutant ↔ STAG1 (van der Lelij 2017 "
        "PMID 28691904; Benedetti 2017 PMID 28430577). NOT a statistical over-call — genetically "
        "validated; STAG1 is a HEAT-repeat cohesin SCAFFOLD (no catalytic pocket → a DEGRADER is required).",
    ),
    "STAG1": (
        "STAG2",
        "Canonical paralog synthetic lethality: STAG1 ↔ STAG2 (van der Lelij 2017 PMID 28691904). NOT an over-call.",
    ),
    "CDK4": (
        "CDK6",
        "Canonical paralog co-dependency / functional redundancy: CDK4 ↔ CDK6 (cyclin D–CDK4/6–"
        "RB axis) — recovered as an SL paralog pair (Parrish 2021 PMID 34469736), and the therapeutic "
        "paradigm is deliberately DUAL CDK4/6 inhibition (palbociclib class). NOT a statistical "
        "over-call. NB the partner is DRUGGABLE (a small-molecule CDK4/6 inhibitor, not a degrader) — so "
        "CDK4/CDK6 are absent from the scaffold-undruggable set (KO IS reproduced by inhibition here).",
    ),
    "CDK6": (
        "CDK4",
        "Canonical paralog co-dependency: CDK6 ↔ CDK4 (dual CDK4/6 inhibition; Parrish 2021 "
        "PMID 34469736). NOT an over-call — druggable (CDK4/6 inhibitor).",
    ),
    "VPS4A": (
        "VPS4B",
        "Canonical deleted-paralog synthetic lethality: VPS4A ↔ VPS4B (well-established "
        "18q/VPS4B-loss paralog dependency; PMID-verification pending — not cited from this arc's review).",
    ),
    "VPS4B": (
        "VPS4A",
        "Canonical deleted-paralog synthetic lethality: VPS4B-loss ↔ VPS4A (PMID-verification "
        "pending — not cited from this arc's review).",
    ),
}

# Curated common-essential / pan-essential machinery — a co-dependency with one of these is a CORE-FITNESS
# co-fitness artifact (drops out in nearly every line → correlates with everything), NOT a selective
# druggable SL (Hart CEG/CEG2 2015/2017 PMID 26627737/28655737; Behan Project Score demotes these PMID
# 30971826). Prefix match covers ribosome (RPL/RPS/MRPL/MRPS), proteasome (PSM), translation (EIF/EEF),
# RNA-pol (POLR), spliceosome (SNRN/SNRP/PRPF); the explicit set adds named core essentials. DISCLAIMED.
PAN_ESSENTIAL_PREFIXES = ("RPL", "RPS", "MRPL", "MRPS", "PSM", "EIF", "EEF", "POLR", "SNRN", "SNRP", "PRPF", "NDUF")
PAN_ESSENTIAL_GENES = {
    "SF3B1",
    "SF3A1",
    "U2AF1",
    "U2AF2",
    "XAB2",
    "AQR",
    "HSPA9",
    "RUVBL1",
    "RUVBL2",
    "RAN",
    "RANGAP1",
    "NACA",
    "CCT2",
    "TCP1",
    "VCP",
    "RRM1",
    "RRM2",
    "POLD1",
    "POLE",
    "PCNA",
    "RPA1",
    "RPA2",
    "CDK1",
    "PLK1",
    "AURKA",
    "AURKB",
    "KIF11",
    "BUB1B",
    "TOP2A",
    "ANAPC",
    "CDC20",
    "MYC",
    "MAX",
    "SNRPD1",
    "SNRPD2",
    "SNRPD3",
    "COPB1",
    "COPB2",
    "COPA",
    "SEC61A1",
    "NUP",
    "GAPDH",
}


def is_pan_essential(sym) -> bool:
    s = (sym or "").upper().strip()
    if not s:
        return False
    return s in PAN_ESSENTIAL_GENES or any(s.startswith(p) for p in PAN_ESSENTIAL_PREFIXES)


# Curated scaffold / non-enzymatic / historically-undruggable SL partners where a genetic KO is NOT
# reproduced by active-site inhibition — a DEGRADER / molecular-glue / PPI modality is required (the
# KO≠inhibition sub-inflation). DISCLAIMED / non-exhaustive; keyed by symbol → the reason string.
SCAFFOLD_UNDRUGGABLE_PARTNERS = {
    "STAG1": "cohesin HEAT-repeat scaffold, no catalytic pocket (van der Lelij 2017 PMID 28691904)",
    "STAG2": "cohesin scaffold subunit (van der Lelij 2017 PMID 28691904)",
    "SMARCA2": "BAF ATPase needing a DEGRADER — bromodomain/ATPase inhibition insufficient (Farnaby 2019 PMID 31178587)",
    "SMARCA4": "BAF ATPase / scaffold (Hoffman 2014 PMID 24520176)",
    "ARID1A": "non-enzymatic BAF subunit (Helming 2014 PMID 24562383)",
    "ARID1B": "non-enzymatic BAF subunit (Helming 2014 PMID 24562383)",
    "GRB2": "SH2/SH3 adaptor scaffold — historically-undruggable PPI",
    "MYC": "transcription factor — no conventional small-molecule pocket",
    "MYCN": "transcription factor — no conventional small-molecule pocket",
    "CTNNB1": "transcription co-activator / scaffold — historically undruggable",
}


def validated_combination_precedent(target, indication):
    """The (target, indication)-keyed clinically/functionally-validated combination guard, or None."""
    return VALIDATED_COMBINATION_PRECEDENT.get(((target or "").upper().strip(), norm_ind(indication)))


def validated_paralog_sl(target):
    """The (target)-keyed canonical paralog-SL guard → (paralog_partner, detail) or None."""
    return VALIDATED_PARALOG_SL.get((target or "").upper().strip())


__all__ = [
    "COMBO_IND_ALIAS",
    "norm_ind",
    "VALIDATED_COMBINATION_PRECEDENT",
    "VALIDATED_PARALOG_SL",
    "PAN_ESSENTIAL_PREFIXES",
    "PAN_ESSENTIAL_GENES",
    "is_pan_essential",
    "SCAFFOLD_UNDRUGGABLE_PARTNERS",
    "validated_combination_precedent",
    "validated_paralog_sl",
]
