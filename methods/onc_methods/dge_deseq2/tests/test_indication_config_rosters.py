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

from onc_methods.dge_deseq2 import config as cfg

# derive_pancan_stack._PUBLISHED_INDICATIONS — the 28 published products (sorted); 27 before
# #734 Phase 2 added LAML. The per-indication `cell_b_semantics` vintage payload was removed in
# analysis-methods#727 when the ComBat cell B was deleted; only the roster of published names remains.
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
        "LAML",  # +#734 Phase 2: published against GTEx whole blood (maturation-state caveat)
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
    "LAML": ["LAML"],  # +#734 Phase 2
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
    "LAML": "BLOOD",  # +#734 Phase 2 — GTEx whole blood (NOT bone marrow; recount3's is K-562)
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
    assert len(EXPECTED_PUBLISHED) == 28


def test_composite_indications_matches():
    assert cfg.composite_indications() == EXPECTED_COMPOSITE


def test_tcga_studies_matches():
    assert cfg.indication_to_tcga_studies() == EXPECTED_TCGA
    assert len(EXPECTED_TCGA) == 22


def test_gtex_tissue_matches_and_omits_hnsc():
    got = cfg.indication_to_gtex_tissue()
    assert got == EXPECTED_GTEX
    assert "HNSC" not in got
    assert len(got) == 21


def test_pan_tissue_matches_in_order():
    # list comparison is order-sensitive — this pins the figure row order too.
    assert cfg.pan_tissue_indications() == EXPECTED_PAN_TISSUE
    assert len(EXPECTED_PAN_TISSUE) == 19


# --- the consumer module-level attributes are wired to the projections ----------------------
def test_read_module_attrs_are_config_projections():
    from onc_methods.dge_deseq2 import read

    assert read.INDICATION_TO_TCGA_STUDIES == EXPECTED_TCGA
    assert read.INDICATION_TO_GTEX_TISSUE == EXPECTED_GTEX


def test_pancan_stack_module_attrs_are_config_projections():
    from onc_methods.dge_deseq2 import derive_pancan_stack as d

    assert d._PUBLISHED_INDICATIONS == set(EXPECTED_PUBLISHED)
    assert d._COMPOSITE_INDICATIONS == EXPECTED_COMPOSITE
    # all_indications() sorts the roster; pin it too since it is the stack build order.
    assert d.all_indications() == EXPECTED_PUBLISHED


def test_emit_pan_tissue_module_attr_is_config_projection():
    from onc_methods.dge_deseq2 import emit_pan_tissue as e

    assert e.PAN_TISSUE_INDICATIONS == EXPECTED_PAN_TISSUE


# --- mutation checks: the projections READ the config, they are not hard-coded copies -------
def test_published_flag_gates_published_indications(monkeypatch):
    data = copy.deepcopy(cfg._load())
    data["indications"]["ACC"]["published"] = False
    monkeypatch.setattr(cfg, "_load", lambda: data)
    m = cfg.published_indications()
    assert "ACC" not in m
    assert len(m) == 27  # 28 published, less the one flipped off


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


# --- #734 Phase 2: the staged set is now EMPTY (LAML published, DLBC dropped) ----------------
# Phase 1 (#781) staged LAML + DLBC verdict-inert. Phase 2 (this change) resolved both after
# domain sign-off: LAML -> published (above), DLBC -> excluded (no nodal-lymphoid GTEx normal).
# The `staged` MECHANISM remains for a future candidate; the set it currently projects is empty.
EXPECTED_STAGED: set[str] = set()

# TCGA study codes with no usable matched GTEx normal -> deliberately absent from the config
# entirely (adding one would FABRICATE a matched normal, the failure HNSC's null guard prevents).
# DLBC joined this set in Phase 2 (nodal germinal-center B cells are in neither GTEx spleen nor
# blood); MESO/SARC/THYM/UVM have no GTEx normal tissue at all.
NO_GTEX_NORMAL_STUDIES = {"DLBC", "MESO", "SARC", "THYM", "UVM"}
UNCERTAIN_STUDIES = {"CHOL"}  # bile duct — GTEx has LIVER but no bile-duct normal; not yet staged


def test_staged_set_is_empty_after_phase2():
    # Phase 2 resolved both Phase-1 candidates; nothing is awaiting sign-off.
    assert set(cfg.staged_indications()) == EXPECTED_STAGED


def test_laml_is_published_with_surfaced_caveat():
    # LAML crossed from staged -> published in Phase 2. The accepted maturation-state confound
    # must ride ALONG with the publish (it is the signed-off condition of publishing), so a
    # published LAML with an empty/absent caveat is a regression.
    inds = cfg._load()["indications"]
    laml = inds["LAML"]
    assert laml["published"] is True
    assert laml["in_read_map"] is True
    assert laml["gtex_tissue"] == "BLOOD"  # NOT bone marrow (recount3's is the K-562 cell line)
    caveat = laml.get("caveat")
    assert isinstance(caveat, str) and caveat.strip(), "published LAML must carry its signed-off caveat"
    assert "maturation" in caveat.lower()


def test_dlbc_is_absent_from_the_config():
    # DLBC was staged in Phase 1 and DROPPED in Phase 2 (unpaired in the literature). It must not
    # linger as a staged or published entry, and it is now one of the excluded no-normal studies.
    inds = cfg._load()["indications"]
    assert "DLBC" not in inds
    assert "DLBC" not in cfg.staged_indications()
    assert "DLBC" not in cfg.published_indications()


def test_staged_projection_reads_the_flag_via_injection(monkeypatch):
    # The staged set is empty, so the per-entry invariants above would go VACUOUS. Inject a
    # synthetic staged candidate to prove the MECHANISM still has teeth: staged_indications()
    # surfaces exactly the flagged entry, exposes its caveat + candidate gtex_tissue, and the
    # entry leaks into NO verdict-bearing projection.
    data = copy.deepcopy(cfg._load())
    data["indications"]["ZZZTEST"] = {
        "tcga_studies": ["ZZZ"],
        "gtex_tissue": "BLOOD",
        "published": False,
        "in_read_map": False,
        "staged": True,
        "caveat": "synthetic staged candidate for the mechanism test",
    }
    monkeypatch.setattr(cfg, "_load", lambda: data)

    staged = cfg.staged_indications()
    assert set(staged) == {"ZZZTEST"}, "staged_indications() must READ the flag, not hard-code a set"
    attrs = staged["ZZZTEST"]
    assert attrs["caveat"].strip()
    assert attrs["gtex_tissue"] == "BLOOD"

    # verdict-inert: a staged entry moves no live projection.
    assert "ZZZTEST" not in cfg.published_indications()
    assert "ZZZTEST" not in cfg.indication_to_tcga_studies()
    assert "ZZZTEST" not in cfg.indication_to_gtex_tissue()
    assert "ZZZTEST" not in cfg.pan_tissue_indications()
    assert "ZZZTEST" not in cfg.composite_indications()


def test_clearing_the_staged_flag_drops_the_entry(monkeypatch):
    # Mutation companion: with the flag off, the same synthetic entry disappears from the
    # projection — proving the flag GATES staging (not the entry's mere presence).
    data = copy.deepcopy(cfg._load())
    data["indications"]["ZZZTEST"] = {
        "gtex_tissue": "BLOOD",
        "published": False,
        "in_read_map": False,
        "staged": False,
        "caveat": "synthetic",
    }
    monkeypatch.setattr(cfg, "_load", lambda: data)
    assert "ZZZTEST" not in cfg.staged_indications()


def test_frozen_roster_counts():
    # Belt-and-suspenders alongside the frozen-literal pins above: the roster SIZES after #734
    # Phase 2 (LAML published, DLBC dropped). published/read-map/gtex each +1 for LAML;
    # pan_tissue_render unchanged (LAML is not rendered, like the 8 rarer published indications).
    assert len(cfg.published_indications()) == 28
    assert len(cfg.indication_to_tcga_studies()) == 22
    assert len(cfg.indication_to_gtex_tissue()) == 21
    assert len(cfg.pan_tissue_indications()) == 19


def test_hnsc_null_normal_guard_still_holds():
    # The guard that stops fabricating a matched normal where none exists must survive #734.
    inds = cfg._load()["indications"]
    assert inds["HNSC"]["gtex_tissue"] is None
    assert "HNSC" not in cfg.indication_to_gtex_tissue()


def test_no_gtex_normal_and_uncertain_studies_are_not_present():
    # MESO/SARC/THYM/UVM have no usable GTEx normal; staging one would FABRICATE a matched normal
    # (the failure HNSC's null guard prevents). CHOL is uncertain (no bile-duct normal). None of
    # them may appear in the config at all until a domain call adds them deliberately.
    inds = cfg._load()["indications"]
    for study in NO_GTEX_NORMAL_STUDIES | UNCERTAIN_STUDIES:
        assert study not in inds, f"{study} must not be in the config without a domain sign-off"
