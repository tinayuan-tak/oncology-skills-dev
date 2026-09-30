"""CI guard for the shared essential-normal-organ set (cards review 2026-08-17, S1-3).

Prevents the three normal-tissue liability cards' essential/critical-organ lists from silently
diverging again — the divergence that let a thyroid/adrenal/vascular-toxic target (TSHR) read
`restricted_normal` and reach the surface-modality verdict as `both_viable`.

Enforces:
  1. SINGLE-SOURCE: each card's live essential set == the shared derived set.
  2. S1-3 COVERAGE: every source covers the endocrine/vascular/CNS organs its vocabulary supports.
  3. Each source's names are REAL (subset of that source's actual vocabulary), so no typo'd tissue
     name that can never match.
  4. The dead `ARTERY` GTEx entry is gone; SPLEEN stays out of canonical (held for review).
"""

from onc_methods import normal_tissue_safety_common as eo

# --- 1. single-source: each card imports the shared set (identity / equality) ---


def test_gtex_stats_card_uses_shared_set():
    from onc_methods.tcga_gtex_expression_distribution import stats

    assert set(stats.CRITICAL_NORMAL_TISSUES) == set(eo.GTEX_ESSENTIAL_TISSUES)


def test_hpa_card_uses_shared_set():
    from onc_methods.hpa_normal_tissue_liability import cli

    assert set(cli.ESSENTIAL_TISSUES) == set(eo.HPA_ESSENTIAL_TISSUES)


def test_sc_normal_card_uses_shared_set():
    from onc_methods.sc_normal_expression import read

    assert set(read.SAFETY_ESSENTIAL_TISSUES) == set(eo.SC_NORMAL_ESSENTIAL_TISSUES)


# --- 2. S1-3 coverage: endocrine/vascular/CNS organs a source can represent MUST be essential ---


def test_gtex_covers_required_endocrine_vascular_organs():
    req = eo.required_names(eo.GTEX_CROSSWALK)
    assert {"THYROID", "ADRENAL_GLAND", "PITUITARY", "BLOOD_VESSEL", "BRAIN"} <= req
    assert req <= set(eo.GTEX_ESSENTIAL_TISSUES)  # the S1-3 fix: all required organs covered


def test_hpa_covers_blood_vessel_and_flags_endocrine_substrate_gap():
    # HPA CAN represent vasculature (blood vessel) → it must be essential (was the code omission).
    assert "blood vessel" in eo.HPA_ESSENTIAL_TISSUES
    assert eo.required_names(eo.HPA_CROSSWALK) <= set(eo.HPA_ESSENTIAL_TISSUES)
    # HPA's 16-name field has NO thyroid/adrenal/pituitary — a documented substrate gap, so those
    # canonical organs crosswalk to None (must NOT be silently claimed as covered).
    for organ in ("thyroid", "adrenal_gland", "pituitary"):
        assert eo.HPA_CROSSWALK[organ] is None


def test_hpa_unrepresentable_vital_organs_pinned():
    """The HPA-blind vital-organ set (skills #1793) — the organs the verdict-bearing HPA-IHC
    essential-tissue killer cannot see, which the TPHP HPA-blind safety rung must cover instead.

    Pinned by VALUE on purpose: target-contracts caveat prose (normal-tissue-liability +
    normal-tissue-protein-abundance-tphp cards) and the safety-resolver rung rationale NAME these
    organs. If this set moves (e.g. an HPA_CROSSWALK promotion like muscle/#744), that prose and the
    rung scoping must be re-checked BY HAND — this failure is the tripwire, not a formality."""
    assert eo.HPA_UNREPRESENTABLE_VITAL_ORGANS == {"nerve", "blood", "adrenal_gland", "pituitary", "thyroid"}
    # derivation properties: every member IS an HPA substrate gap...
    for organ in eo.HPA_UNREPRESENTABLE_VITAL_ORGANS:
        assert eo.HPA_CROSSWALK[organ] is None
    # ...and small_intestine is EXCLUDED despite its None: `intestine` (the gut anchor) covers it in
    # HPA, so it is not an unguarded organ and the TPHP rung must not double-claim it.
    assert eo.HPA_CROSSWALK["small_intestine"] is None
    assert "small_intestine" not in eo.HPA_UNREPRESENTABLE_VITAL_ORGANS
    assert "intestine" in eo.HPA_ESSENTIAL_TISSUES


def test_sc_normal_covers_brain_and_adrenal():
    assert "brain" in eo.SC_NORMAL_ESSENTIAL_TISSUES  # the advertised-but-unqueried CNS shard
    assert "adrenal_gland" in eo.SC_NORMAL_ESSENTIAL_TISSUES
    assert eo.required_names(eo.SC_NORMAL_CROSSWALK) <= set(eo.SC_NORMAL_ESSENTIAL_TISSUES)


def test_hpa_represents_skeletal_muscle():
    # muscle is NOT an HPA substrate gap (issue #744): HPA's 16-name grouped-intensity vocabulary
    # CONTAINS `skeletal muscle`, so the muscle=None fail-open — a skeletal-muscle-restricted antigen
    # escaping HPA's essential-tissue killer under a false substrate-absence claim — is closed.
    assert eo.HPA_CROSSWALK["muscle"] == "skeletal muscle"
    assert "skeletal muscle" in eo.HPA_ESSENTIAL_TISSUES


def test_tphp_fills_endocrine_vascular_and_flags_pituitary_gap():
    # T0-3: TPHP DIA-MS PROTEIN resolves the endocrine/vascular/CNS organs HPA-IHC is blind to.
    # It must represent (non-None) the organs HPA cannot: nerve / blood / adrenal / thyroid.
    # (muscle was formerly listed here as an HPA gap — that was the false claim fixed in #744; HPA
    # DOES represent muscle as `skeletal muscle`. TPHP muscle coverage is checked below via req/panel.)
    for organ in ("nerve", "blood", "adrenal_gland", "thyroid"):
        assert eo.HPA_CROSSWALK.get(organ) is None  # HPA substrate gap
        assert eo.TPHP_CROSSWALK[organ] is not None  # TPHP fills it
    assert eo.TPHP_CROSSWALK["muscle"] == "skeletal muscle"  # TPHP still covers muscle
    # It covers 4 of the 5 S1-3 endocrine/vascular/CNS organs (adrenal, thyroid, vasculature, brain) —
    # the S1-3 required-name coverage invariant holds for what TPHP can represent.
    req = eo.required_names(eo.TPHP_CROSSWALK)
    assert {"adrenal gland", "thyroid gland", "artery", "brain"} <= req
    assert req <= set(eo.TPHP_ESSENTIAL_TISSUES)
    # pituitary is absent from the 70-tissue TPHP panel → None (a documented substrate gap, like HPA's),
    # must NOT be silently claimed as covered.
    assert eo.TPHP_CROSSWALK["pituitary"] is None


def test_tphp_names_are_real_tphp_tissues():
    # every TPHP crosswalk value must be a real organism-part in the 70-tissue adult TPHP panel.
    _TPHP_ADULT_PANEL = {
        "adipose tissue",
        "adrenal gland",
        "artery",
        "bladder",
        "blood",
        "blood plasma",
        "blood platelet",
        "bone",
        "bone marrow",
        "brain",
        "bulbourethral gland",
        "cartilage",
        "cochlea",
        "cornea",
        "epididymis",
        "epiglottis",
        "erythrocyte",
        "esophagus",
        "gall bladder",
        "hair",
        "heart",
        "iris",
        "kidney",
        "large intestine",
        "lens",
        "leukocyte",
        "liver",
        "lung",
        "lymph node",
        "lymph vessel",
        "mammary gland",
        "nerve",
        "nose",
        "olfactory epithelium",
        "outer ear",
        "ovary",
        "oviduct",
        "pancreas",
        "parathyroid gland",
        "peritoneum",
        "plant vessel",
        "prostate gland",
        "saliva",
        "salivary gland",
        "sclera",
        "semicircular canal",
        "seminal vesicle",
        "seminiferous tubule",
        "skeletal muscle",
        "skin",
        "small intestine",
        "smooth muscle",
        "spinal cord",
        "spleen",
        "stomach",
        "tear",
        "tendon",
        "testis",
        "throat",
        "thymus",
        "thyroid gland",
        "tongue",
        "tonsil",
        "tympanum",
        "ureter",
        "urine",
        "uterus",
        "vagina",
        "vein",
        "vermiform appendix",
    }
    assert set(eo.TPHP_ESSENTIAL_TISSUES) <= _TPHP_ADULT_PANEL


# --- 3. names are real (subset of each source's actual vocabulary) ---


def test_gtex_names_are_real_gtex_tissues():
    # window.py's ESSENTIAL_GTEX_TISSUES is the known-good GTEx set (17 names since the 2026-09-18 gut
    # promotions added COLON + SMALL_INTESTINE); every name we emit must
    # be one of them (proves real recount3/GTEx labels AND that stats.py now aligns with the window
    # card — modulo SPLEEN, which the window card keeps and canonical holds).
    from onc_methods.tcga_gtex_tpm_quantiles.window import ESSENTIAL_GTEX_TISSUES as WINDOW_SET

    assert set(eo.GTEX_ESSENTIAL_TISSUES) <= set(WINDOW_SET)
    assert "ARTERY" not in eo.GTEX_ESSENTIAL_TISSUES  # dead entry removed


def test_every_hardcoded_gtex_copy_covers_the_canonical_set():
    """THREE modules hold their own literal `ESSENTIAL_GTEX_TISSUES` instead of importing the derived
    set, and until 2026-09-18 only ONE of them (`tcga_gtex_tpm_quantiles.window`, above) was pinned.
    The other two — `exon_window.classify` and `pair_selectivity_gate.gates` — were guarded by
    NOTHING, so an organ promotion could leave them behind and they would silently stop treating the
    new organ as essential: divergence in the PERMISSIVE direction, which is the exact failure the
    single-source module exists to prevent. Found while landing the `gut` promotion, whose own
    comment asserted all three were pinned when only one was.

    DISCOVERY, not a hardcoded roster, so a FOURTH copy added later is guarded on arrival — the
    failure mode of a literal list is that it does not know what it is missing. Walks `tree.body`
    (module-level assignments) and NOT `ast.walk`, which is not scope-aware and would also match a
    function-local of the same name in some unrelated helper.
    """
    import ast
    import importlib
    from pathlib import Path

    methods_root = Path(eo.__file__).resolve().parents[1]  # .../methods
    copies: dict[str, Path] = {}
    for py in sorted(methods_root.rglob("*.py")):
        if "/tests/" in py.as_posix():
            continue
        for node in ast.parse(py.read_text()).body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            if any(isinstance(t, ast.Name) and t.id == "ESSENTIAL_GTEX_TISSUES" for t in targets):
                copies[py.relative_to(methods_root.parent).with_suffix("").as_posix().replace("/", ".")] = py

    # ANTI-VACUITY: if discovery finds nothing (a renamed constant, a moved tree) every assertion
    # below is skipped silently and this test becomes a green that cannot fail.
    for known in (
        "onc_methods.tcga_gtex_tpm_quantiles.window",
        "onc_methods.exon_window.classify",
        "onc_methods.pair_selectivity_gate.gates",
    ):
        assert known in copies, (
            f"{known} no longer defines a module-level ESSENTIAL_GTEX_TISSUES; discovery found "
            f"{sorted(copies)}. If the copy was replaced by an import of the shared set that is GOOD "
            f"— delete it from this roster. If it was renamed, this guard just went blind."
        )

    canonical = set(eo.GTEX_ESSENTIAL_TISSUES)
    assert canonical, "derived GTEX_ESSENTIAL_TISSUES is empty — every coverage assert below is vacuous"

    for mod in sorted(copies):
        got = set(getattr(importlib.import_module(mod), "ESSENTIAL_GTEX_TISSUES"))
        missing = canonical - got
        assert not missing, (
            f"{mod}.ESSENTIAL_GTEX_TISSUES is MISSING {sorted(missing)} — it is a HARDCODED COPY of "
            f"the set derived from essential_organs.GTEX_CROSSWALK and has drifted. Add the names "
            f"there; do not relax this guard. Extras are allowed (the window card keeps SPLEEN), so "
            f"this is coverage, not equality."
        )


def test_sc_normal_names_have_shards():
    # every always-on tissue must have a real single-cell normal shard.
    from onc_methods.sc_normal_expression.read import TISSUE_TO_PRODUCT

    assert set(eo.SC_NORMAL_ESSENTIAL_TISSUES) <= set(TISSUE_TO_PRODUCT)


# --- 4. SPLEEN held out of canonical (documents the reserved decision) ---


def test_spleen_held_out_of_canonical():
    assert "spleen" not in eo.CANONICAL_VITAL_ORGANS
    # coverage-not-equality means a source MAY still list spleen (the GTEx window card does) without
    # violating the guard; this asserts we haven't quietly promoted it to canonical.
