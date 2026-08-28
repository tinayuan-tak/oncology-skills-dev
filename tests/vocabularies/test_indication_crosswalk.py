"""Guard for vocabularies/indication_crosswalk.yaml `depmap_lineage` values.

Root cause fixed here (lineage-scoping consolidation, 2026-08-16): STAD carried
`depmap_lineage: Stomach`, a lineage that does NOT exist in DepMap 26Q1 Model.csv
(gastric + esophageal are merged into the single "Esophagus/Stomach" lineage). Any
consumer that scoped gastric cell lines on the raw value matched ZERO models.

These guards keep every `depmap_lineage` a REAL DepMap 26Q1 lineage and pin STAD to
the correct merged value.

NOTE: this repo has no pixi env; run with `python -m pytest tests/vocabularies/ -q`.
The crosswalk's `depmap_lineage` column uses an underscored token convention for some
multi-word lineages (e.g. `Head_and_Neck` for the real Model.csv "Head and Neck"), so
the membership check normalizes "_"→" " before comparing — the bogus "Stomach" fails
either way (there is no "Stomach" in the set even after normalization).
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
CROSSWALK = REPO / "vocabularies" / "indication_crosswalk.yaml"

# The 34 non-null OncotreeLineage categories in DepMap 26Q1 Model.csv (frozen from a
# live load 2026-08-16). Mirrors the analysis-methods canonical-map guard.
MODEL_CSV_26Q1_LINEAGES = frozenset({
    "Adrenal Gland", "Ampulla of Vater", "Biliary Tract", "Bladder/Urinary Tract",
    "Bone", "Bowel", "Breast", "CNS/Brain", "Cervix", "Embryonal", "Esophagus/Stomach",
    "Eye", "Fibroblast", "Hair", "Head and Neck", "Kidney", "Liver", "Lung", "Lymphoid",
    "Muscle", "Myeloid", "Normal", "Other", "Ovary/Fallopian Tube", "Pancreas",
    "Peripheral Nervous System", "Pleura", "Prostate", "Skin", "Soft Tissue", "Testis",
    "Thyroid", "Uterus", "Vulva/Vagina",
})


def _load():
    return yaml.safe_load(CROSSWALK.read_text())


def _norm(v: str) -> str:
    return str(v).replace("_", " ").strip()


def test_yaml_well_formed():
    doc = _load()
    assert doc["schema_version"] == 1
    assert isinstance(doc["indications"], list) and doc["indications"]


def test_stad_depmap_lineage_is_esophagus_stomach():
    doc = _load()
    stad = next(i for i in doc["indications"] if i["canonical_code"] == "STAD")
    assert stad["depmap_lineage"] == "Esophagus/Stomach"


def test_no_indication_maps_to_the_bogus_stomach_lineage():
    doc = _load()
    offenders = [i["canonical_code"] for i in doc["indications"]
                 if _norm(i.get("depmap_lineage", "")) == "Stomach"]
    assert not offenders, f'"Stomach" is not a DepMap 26Q1 lineage; offenders: {offenders}'


def test_every_depmap_lineage_is_a_real_model_csv_lineage():
    doc = _load()
    bad = {i["canonical_code"]: i["depmap_lineage"] for i in doc["indications"]
           if i.get("depmap_lineage") and _norm(i["depmap_lineage"]) not in MODEL_CSV_26Q1_LINEAGES}
    assert not bad, f"depmap_lineage values absent from DepMap 26Q1 Model.csv: {bad}"


def test_every_indication_has_mesh_ids_well_formed():
    """The mesh_ids lane (indication -> MeSH descriptor ids; the disease_mesh key of the PubTator
    gene-disease-relations product) must be present and well-formed on every indication."""
    import re
    doc = _load()
    mesh_re = re.compile(r"^MESH:[CD]\d+$")
    missing = [i["canonical_code"] for i in doc["indications"] if not i.get("mesh_ids")]
    assert not missing, f"indications missing a mesh_ids lane: {missing}"
    bad = {i["canonical_code"]: [m for m in i["mesh_ids"] if not mesh_re.match(str(m))]
           for i in doc["indications"]}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"malformed mesh_ids (expect MESH:D#### / MESH:C####): {bad}"


def test_crosswalk_agrees_with_analysis_methods_canonical_map():
    """Cross-repo sync (skipped if the sibling analysis-methods repo isn't on disk):
    for every indication code the analysis-methods canonical map knows, the crosswalk's
    `depmap_lineage` must resolve to the SAME lineage (underscore-normalized)."""
    am = REPO.parent / "rnd-computational-biology-oncology-analysis-methods"
    if not am.exists():
        pytest.skip("sibling analysis-methods repo not on disk")
    import sys
    if str(am) not in sys.path:
        sys.path.insert(0, str(am))
    try:
        from methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE as canon
    except Exception:  # noqa: BLE001
        pytest.skip("analysis-methods canonical map not importable in this env")
    doc = _load()
    mism = {}
    for i in doc["indications"]:
        code = i["canonical_code"]
        xw = i.get("depmap_lineage")
        if code in canon and xw and _norm(xw) != _norm(canon[code]):
            mism[code] = (xw, canon[code])
    assert not mism, f"crosswalk vs analysis-methods canonical map disagree: {mism}"
