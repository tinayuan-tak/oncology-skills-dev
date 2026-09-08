"""Single-source + coverage + no-silent-fallback guards for the indication → DepMap
OncotreeLineage map.

Context: the framework historically forked the indication→lineage crosswalk across
~6 modules. #365 fixed the gastric VALUES (Stomach → Esophagus/Stomach) but left the
maps as forks; the lineage-scoping residual consolidation (2026-08-16) collapsed the
four depmap display CLIs onto ONE canonical literal (depmap_chronos.cli.INDICATION_LINEAGE,
re-exported as depmap_chronos.read.INDICATION_TO_DEPMAP_LINEAGE) and gave it full
framework coverage. These guards keep it that way.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_chronos import cli as chronos_cli  # noqa: E402
from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE  # noqa: E402

# The 34 non-null OncotreeLineage categories in DepMap 26Q1 Model.csv (frozen from a
# live load 2026-08-16; the file also carries a "nan"/missing bucket which is not a
# real lineage). Frozen so this guard runs offline; a live leg below re-confirms it.
MODEL_CSV_26Q1_LINEAGES = frozenset(
    {
        "Adrenal Gland",
        "Ampulla of Vater",
        "Biliary Tract",
        "Bladder/Urinary Tract",
        "Bone",
        "Bowel",
        "Breast",
        "CNS/Brain",
        "Cervix",
        "Embryonal",
        "Esophagus/Stomach",
        "Eye",
        "Fibroblast",
        "Hair",
        "Head and Neck",
        "Kidney",
        "Liver",
        "Lung",
        "Lymphoid",
        "Muscle",
        "Myeloid",
        "Normal",
        "Other",
        "Ovary/Fallopian Tube",
        "Pancreas",
        "Peripheral Nervous System",
        "Pleura",
        "Prostate",
        "Skin",
        "Soft Tissue",
        "Testis",
        "Thyroid",
        "Uterus",
        "Vulva/Vagina",
    }
)

# The full framework indication vocabulary — target-contracts
# vocabularies/indication_crosswalk.yaml `canonical_code` (CML is deferred_iter1b but
# still a first-class code). EVERY one must resolve to a real lineage through the
# single canonical map (no silent pan-lineage fallback for a supported indication).
FRAMEWORK_INDICATION_CODES = (
    "COADREAD",
    "NSCLC",
    "SCLC",
    "HNSC",
    "STAD",
    "ESCA",
    "PAAD",
    "AML",
    "CML",
)

# The four depmap method modules that were consolidated onto the canonical map.
_CONSOLIDATED_MODULES = (
    "methods/depmap_chronos/cli.py",
    "methods/depmap_chronos/read.py",
    "methods/depmap_expression_dependency/cli.py",
    "methods/depmap_expression_distribution/cli.py",
    "methods/depmap_protein_abundance/cli.py",
)

# The ONE module allowed to hold a scalar-dict literal for these names (the canonical
# source). Every other consolidated module must alias-import it.
_CANONICAL_LITERAL_FILE = "methods/depmap_chronos/cli.py"

# Architecturally-distinct maps deliberately NOT consolidated onto the scalar canonical
# (documented, out of this workstream's scope): they are TUPLE-valued (support 1..n
# lineages per indication) and/or paired with an organ-disambiguation sibling map. If
# either is ever reshaped to a plain scalar dict, fold it into the canonical instead.
_DOCUMENTED_NONSCALAR_FORKS = {
    "methods/subgroup_assigner_directly_tagged/cli.py",  # + INDICATION_TO_DEPMAP_ORGAN sibling
    "methods/tcga_aneuploidy_burden/read.py",  # tuple-valued (multi-lineage)
}

_LINEAGE_MAP_NAMES = {"INDICATION_LINEAGE", "INDICATION_TO_DEPMAP_LINEAGE"}


# ---- (a) every canonical value is a REAL Model.csv lineage --------------------------


def test_every_canonical_value_is_a_real_model_csv_lineage():
    """Catches future wrong values like the STAD→"Stomach" latent bug."""
    bad = {v for v in INDICATION_TO_DEPMAP_LINEAGE.values() if v not in MODEL_CSV_26Q1_LINEAGES}
    assert not bad, f"map values not in DepMap 26Q1 Model.csv lineage set: {sorted(bad)}"
    assert "Stomach" not in set(INDICATION_TO_DEPMAP_LINEAGE.values())


def test_frozen_lineage_set_matches_live_model_csv():
    """Opportunistic live leg: confirm the frozen 34-lineage set still equals Model.csv."""
    from methods.depmap_protein_abundance import cli as pa

    try:
        lin_by_model = pa.load_model_lineage()
    except Exception:  # noqa: BLE001 — no S3 / creds → skip
        pytest.skip("Model.csv unreachable (no S3)")
    live = {v for v in lin_by_model.values() if v and str(v) != "nan"}
    if not live:
        pytest.skip("Model.csv unreachable (no S3)")
    assert live == set(MODEL_CSV_26Q1_LINEAGES), (
        "frozen Model.csv lineage set drifted from live; update MODEL_CSV_26Q1_LINEAGES. "
        f"only-live={sorted(live - MODEL_CSV_26Q1_LINEAGES)} "
        f"only-frozen={sorted(set(MODEL_CSV_26Q1_LINEAGES) - live)}"
    )


# ---- (b) single source of truth: one literal, everyone else aliases it --------------


def test_all_consolidated_modules_share_one_map_object():
    from methods.depmap_expression_dependency.cli import INDICATION_LINEAGE as ed
    from methods.depmap_expression_distribution.cli import INDICATION_LINEAGE as edist
    from methods.depmap_protein_abundance.cli import INDICATION_LINEAGE as pa

    for name, obj in (
        ("depmap_chronos.cli", chronos_cli.INDICATION_LINEAGE),
        ("depmap_expression_dependency.cli", ed),
        ("depmap_expression_distribution.cli", edist),
        ("depmap_protein_abundance.cli", pa),
    ):
        assert obj is INDICATION_TO_DEPMAP_LINEAGE, f"{name} does not share the canonical object"


def test_pathway_node_leverage_inherits_canonical_transitively():
    # Read-only sanity: the WS3-owned method imports the stale name and must get the
    # FULL canonical map (so STAD/HNSC/ESCA/AML resolve within-indication), NOT a fork.
    from methods.pathway_node_leverage.cli import INDICATION_LINEAGE as nl

    assert nl is INDICATION_TO_DEPMAP_LINEAGE


def _scalar_lineage_literal_files() -> set[str]:
    """AST-scan the repo: files that assign INDICATION_LINEAGE / INDICATION_TO_DEPMAP_LINEAGE
    to a *scalar-valued* dict literal (str→str). Tuple/list-valued maps are excluded
    (those are the documented multi-lineage forks)."""
    hits: set[str] = set()
    for py in (REPO / "methods").rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(), filename=str(py))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
                continue
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if not (names & _LINEAGE_MAP_NAMES):
                continue
            # scalar-valued iff no value is a Tuple/List
            if any(isinstance(v, (ast.Tuple, ast.List)) for v in node.value.values):
                continue
            hits.add(py.relative_to(REPO).as_posix())
    return hits


def test_only_canonical_module_holds_a_scalar_literal():
    hits = _scalar_lineage_literal_files()
    # remove the documented non-scalar forks defensively (they should already be excluded
    # by the tuple/list filter, but if one is edited to scalar shape we want a clear signal)
    unexpected = hits - {_CANONICAL_LITERAL_FILE} - _DOCUMENTED_NONSCALAR_FORKS
    assert not unexpected, (
        "re-forked scalar indication→lineage literal(s) found — alias-import the canonical "
        f"depmap_chronos.cli.INDICATION_LINEAGE instead: {sorted(unexpected)}"
    )
    assert _CANONICAL_LITERAL_FILE in hits, "canonical scalar literal missing from depmap_chronos/cli.py"


# ---- (c) completeness: every framework indication resolves --------------------------


def test_every_framework_indication_resolves_to_a_real_lineage():
    unresolved = [
        c for c in FRAMEWORK_INDICATION_CODES if INDICATION_TO_DEPMAP_LINEAGE.get(c) not in MODEL_CSV_26Q1_LINEAGES
    ]
    assert not unresolved, f"framework indication codes with no / bogus lineage mapping: {unresolved}"


# ---- (d) no silent pan-lineage fallback: evidence_scope is ALWAYS explicit ----------


def test_lineage_ladder_always_stamps_an_explicit_evidence_scope():
    from methods.depmap_common.lineage_ladder import apply_lineage_ladder

    CLASS_KEY = "mutant_class"

    def compute(mut_models, wt_models):
        # a positive call; enough "lines" that the floor never trips → rung 1 when restricted
        return {CLASS_KEY: "mutant_strongly_dependent"}

    # models: 40 in the STAD lineage, 40 elsewhere
    meta = {}
    for i in range(40):
        meta[f"MUT-{i}"] = {"OncotreeLineage": "Esophagus/Stomach"}
    for i in range(40):
        meta[f"OTH-{i}"] = {"OncotreeLineage": "Lung"}

    # mapped indication with lines → within-indication scope
    mapped = apply_lineage_ladder(compute, CLASS_KEY, meta, "STAD")
    assert mapped.get("evidence_scope") == "within_indication"

    # unmapped / absent indication → EXPLICIT pan scope (never a bare unlabelled pan result)
    for ind in (None, "", "ZZZ_NOT_AN_INDICATION"):
        res = apply_lineage_ladder(compute, CLASS_KEY, meta, ind)
        scope = res.get("evidence_scope")
        assert scope, f"pan fallback for indication={ind!r} left evidence_scope empty"
        assert scope.startswith("pan"), f"unexpected scope {scope!r} for indication={ind!r}"
