"""S1 (analysis-methods #693) verdict-identity gate for the roster consolidation.

The rosters that derive_pancan_stack.py, emit_pan_tissue.py, and read/__init__.py used to
hard-code independently now project out of config/indications.yaml. This is a PURE NO-OP: the
projections must be byte-identical to the pre-S1 literals, which are FROZEN below. Do NOT edit
these expected values to match a change — a diff here means the consolidation moved a roster
(and therefore a live verdict), which is out of scope for S1 and belongs in a separate
verdict-diff PR (the reviewer's (a)/(b) split).

The frozen literals were copied verbatim from origin/main @660b9bb (post-S0), pre-consolidation.
"""

import copy

from methods.dge_deseq2 import config as cfg

# derive_pancan_stack._PUBLISHED_INDICATIONS — the 27 published products (sorted). The
# per-indication `cell_b_semantics` vintage payload was removed in analysis-methods#727 when
# the ComBat cell B was deleted; only the roster of published names remains.
EXPECTED_PUBLISHED = sorted(
    [
        "COADREAD",
        "UCEC",
        "ACC",
        "BLCA",
        "BRCA",
        "CESC",
        "COAD",
        "ESCA",
        "GBM",
        "HNSC",
        "KICH",
        "KIRC",
        "KIRP",
        "LGG",
        "LIHC",
        "LUAD",
        "LUSC",
        "OV",
        "PAAD",
        "PCPG",
        "PRAD",
        "READ",
        "SKCM",
        "STAD",
        "TGCT",
        "THCA",
        "UCS",
    ]
)

# derive_pancan_stack._COMPOSITE_INDICATIONS
EXPECTED_COMPOSITE = {"COADREAD": {"COAD", "READ"}, "NSCLC": {"LUAD", "LUSC"}}

# read.INDICATION_TO_TCGA_STUDIES
EXPECTED_TCGA = {
    "COADREAD": ["COAD", "READ"],
    "COAD": ["COAD"],
    "READ": ["READ"],
    "NSCLC": ["LUAD", "LUSC"],
    "LUAD": ["LUAD"],
    "LUSC": ["LUSC"],
    "BRCA": ["BRCA"],
    "PAAD": ["PAAD"],
    "PDAC": ["PAAD"],
    "SKCM": ["SKCM"],
    "STAD": ["STAD"],
    "PRAD": ["PRAD"],
    "OV": ["OV"],
    "KIRC": ["KIRC"],
    "GBM": ["GBM"],
    "LGG": ["LGG"],
    "HNSC": ["HNSC"],
    "BLCA": ["BLCA"],
    "LIHC": ["LIHC"],
    "CESC": ["CESC"],
    "ESCA": ["ESCA"],
}

# read.INDICATION_TO_GTEX_TISSUE (HNSC deliberately absent — no clean GTEx match).
EXPECTED_GTEX = {
    "COADREAD": "COLON",
    "COAD": "COLON",
    "READ": "COLON",
    "NSCLC": "LUNG",
    "LUAD": "LUNG",
    "LUSC": "LUNG",
    "BRCA": "BREAST",
    "PAAD": "PANCREAS",
    "PDAC": "PANCREAS",
    "SKCM": "SKIN",
    "STAD": "STOMACH",
    "PRAD": "PROSTATE",
    "OV": "OVARY",
    "KIRC": "KIDNEY",
    "GBM": "BRAIN",
    "LGG": "BRAIN",
    "BLCA": "BLADDER",
    "LIHC": "LIVER",
    "CESC": "CERVIX_UTERI",
    "ESCA": "ESOPHAGUS",
}

# emit_pan_tissue.PAN_TISSUE_INDICATIONS — ORDER is the figure row order (order-sensitive).
EXPECTED_PAN_TISSUE = [
    "COAD",
    "READ",
    "COADREAD",
    "LUAD",
    "LUSC",
    "BRCA",
    "PAAD",
    "SKCM",
    "STAD",
    "PRAD",
    "OV",
    "KIRC",
    "GBM",
    "LGG",
    "BLCA",
    "LIHC",
    "CESC",
    "ESCA",
    "HNSC",
]


# --- projections match the frozen literals -------------------------------------------------
def test_published_indications_matches_frozen_literal():
    assert cfg.published_indications() == EXPECTED_PUBLISHED
    assert len(EXPECTED_PUBLISHED) == 27


def test_composite_indications_matches():
    assert cfg.composite_indications() == EXPECTED_COMPOSITE


def test_tcga_studies_matches():
    assert cfg.indication_to_tcga_studies() == EXPECTED_TCGA
    assert len(EXPECTED_TCGA) == 21


def test_gtex_tissue_matches_and_omits_hnsc():
    got = cfg.indication_to_gtex_tissue()
    assert got == EXPECTED_GTEX
    assert "HNSC" not in got
    assert len(got) == 20


def test_pan_tissue_matches_in_order():
    # list comparison is order-sensitive — this pins the figure row order too.
    assert cfg.pan_tissue_indications() == EXPECTED_PAN_TISSUE
    assert len(EXPECTED_PAN_TISSUE) == 19


# --- the consumer module-level attributes are wired to the projections ----------------------
def test_read_module_attrs_are_config_projections():
    from methods.dge_deseq2 import read

    assert read.INDICATION_TO_TCGA_STUDIES == EXPECTED_TCGA
    assert read.INDICATION_TO_GTEX_TISSUE == EXPECTED_GTEX


def test_pancan_stack_module_attrs_are_config_projections():
    from methods.dge_deseq2 import derive_pancan_stack as d

    assert d._PUBLISHED_INDICATIONS == set(EXPECTED_PUBLISHED)
    assert d._COMPOSITE_INDICATIONS == EXPECTED_COMPOSITE
    # all_indications() sorts the roster; pin it too since it is the stack build order.
    assert d.all_indications() == EXPECTED_PUBLISHED


def test_emit_pan_tissue_module_attr_is_config_projection():
    from methods.dge_deseq2 import emit_pan_tissue as e

    assert e.PAN_TISSUE_INDICATIONS == EXPECTED_PAN_TISSUE


# --- mutation checks: the projections READ the config, they are not hard-coded copies -------
def test_published_flag_gates_published_indications(monkeypatch):
    data = copy.deepcopy(cfg._load())
    data["indications"]["ACC"]["published"] = False
    monkeypatch.setattr(cfg, "_load", lambda: data)
    m = cfg.published_indications()
    assert "ACC" not in m
    assert len(m) == 26


def test_in_read_map_flag_gates_tcga_studies(monkeypatch):
    data = copy.deepcopy(cfg._load())
    data["indications"]["COAD"]["in_read_map"] = False
    monkeypatch.setattr(cfg, "_load", lambda: data)
    assert "COAD" not in cfg.indication_to_tcga_studies()


def test_null_gtex_tissue_is_excluded(monkeypatch):
    data = copy.deepcopy(cfg._load())
    data["indications"]["BRCA"]["gtex_tissue"] = None
    monkeypatch.setattr(cfg, "_load", lambda: data)
    assert "BRCA" not in cfg.indication_to_gtex_tissue()
