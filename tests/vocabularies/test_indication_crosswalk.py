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
    offenders = [i["canonical_code"] for i in doc["indications"] if _norm(i.get("depmap_lineage", "")) == "Stomach"]
    assert not offenders, f'"Stomach" is not a DepMap 26Q1 lineage; offenders: {offenders}'


def test_every_depmap_lineage_is_a_real_model_csv_lineage():
    doc = _load()
    bad = {
        i["canonical_code"]: i["depmap_lineage"]
        for i in doc["indications"]
        if i.get("depmap_lineage") and _norm(i["depmap_lineage"]) not in MODEL_CSV_26Q1_LINEAGES
    }
    assert not bad, f"depmap_lineage values absent from DepMap 26Q1 Model.csv: {bad}"


def test_every_indication_has_mesh_ids_well_formed():
    """The mesh_ids lane (indication -> MeSH descriptor ids; the disease_mesh key of the PubTator
    gene-disease-relations product) must be present and well-formed on every indication."""
    import re

    doc = _load()
    mesh_re = re.compile(r"^MESH:[CD]\d+$")
    missing = [i["canonical_code"] for i in doc["indications"] if not i.get("mesh_ids")]
    assert not missing, f"indications missing a mesh_ids lane: {missing}"
    bad = {i["canonical_code"]: [m for m in i["mesh_ids"] if not mesh_re.match(str(m))] for i in doc["indications"]}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"malformed mesh_ids (expect MESH:D#### / MESH:C####): {bad}"


def _alias_to_canonical(doc) -> dict:
    """alias code -> canonical_code, from the `aliases` lane (v1.4.0)."""
    out = {}
    for i in doc["indications"]:
        for a in i.get("aliases") or []:
            out[str(a)] = i["canonical_code"]
    return out


def _resolvable_lineages(doc) -> dict:
    """Every indication STRING a consumer may pass -> its depmap_lineage. Canonical codes plus
    aliases (which inherit their canonical entry's lineage)."""
    by_code = {i["canonical_code"]: i.get("depmap_lineage") for i in doc["indications"]}
    resolvable = dict(by_code)
    for alias, canonical in _alias_to_canonical(doc).items():
        resolvable[alias] = by_code[canonical]
    return resolvable


def test_aliases_are_well_formed():
    """Alias hygiene: an alias may not collide with a canonical code, may not be claimed by two
    different canonical entries, and may not be self-referential."""
    doc = _load()
    codes = {i["canonical_code"] for i in doc["indications"]}
    seen: dict[str, str] = {}
    collide, dupe, selfref = [], {}, []
    for i in doc["indications"]:
        for a in i.get("aliases") or []:
            a = str(a)
            if a == i["canonical_code"]:
                selfref.append(a)
            if a in codes:
                collide.append(a)
            if a in seen and seen[a] != i["canonical_code"]:
                dupe[a] = (seen[a], i["canonical_code"])
            seen[a] = i["canonical_code"]
    assert not collide, f"alias shadows a canonical_code (ambiguous resolution): {sorted(set(collide))}"
    assert not dupe, f"alias claimed by two canonical indications: {dupe}"
    assert not selfref, f"self-referential alias: {sorted(set(selfref))}"


def test_uvm_maps_to_the_eye_lineage():
    """Regression for the 2026-09-12 repair: UVM carried depmap_lineage: null even though DepMap 26Q1
    screens uveal melanoma under the `Eye` lineage (OncotreeCode UM). A null here silently degrades every
    DepMap-scoped read for the indication to pan-lineage."""
    doc = _load()
    uvm = next(i for i in doc["indications"] if i["canonical_code"] == "UVM")
    assert uvm["depmap_lineage"] == "Eye"
    # `Eye` also carries retinoblastoma + non-cancerous retinal lines, so the code set is required.
    assert uvm.get("depmap_oncotree_codes") == ["UM"]


def test_only_thymus_lacks_a_depmap_lineage():
    """A null `depmap_lineage` is legitimate ONLY where DepMap genuinely has no such lineage. THYM is the
    single such case in 26Q1 (no Thymus lineage exists). Any NEW null is a silent pan-lineage fallback for
    a first-class indication and must be justified by extending this allowlist deliberately."""
    doc = _load()
    nulls = {i["canonical_code"] for i in doc["indications"] if not i.get("depmap_lineage")}
    assert nulls == {"THYM"}, (
        f"unexpected null depmap_lineage (silent pan-lineage fallback): {sorted(nulls - {'THYM'})}; "
        f"unexpectedly non-null: {sorted({'THYM'} - nulls)}"
    )


def test_crosswalk_agrees_with_analysis_methods_canonical_map():
    """Cross-repo sync, BIDIRECTIONAL (skipped if the sibling analysis-methods repo isn't on disk).

    Direction 1 (values): every code both sides know must resolve to the SAME lineage.
    Direction 2 (coverage): every code the analysis-methods canonical map knows must be resolvable
    here — as a canonical_code or an alias.

    Direction 2 is the leg this guard lacked until 2026-09-12. The old form was
    `if code in canon and xw and ...`, which iterated the CROSSWALK only, so a code present in the
    methods map but ABSENT here was invisible — and `and xw` additionally excused a null lineage from
    checking at all. Both blind spots were live: the methods map carried LUAD/LUSC/COAD/READ plus the
    GC/LAML/MELANOMA/PDAC synonyms that this file did not, and UVM's lineage was null. Consumers are
    split across the two sources (the lineage ladder reads the methods map; the functional-requirement
    skill reads this file), so a one-way guard let them diverge silently.
    """
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
    resolvable = _resolvable_lineages(doc)

    # Direction 1: agree on every shared code (null included — a null here vs a real lineage there IS
    # a disagreement, which is exactly how the UVM defect hid).
    mism = {
        code: (resolvable[code], canon[code])
        for code in set(canon) & set(resolvable)
        if _norm(resolvable[code] or "") != _norm(canon[code])
    }
    assert not mism, f"crosswalk vs analysis-methods canonical map disagree (code: (crosswalk, methods)): {mism}"

    # Direction 2: the crosswalk must cover the methods map.
    uncovered = sorted(set(canon) - set(resolvable))
    assert not uncovered, (
        "indication codes the analysis-methods canonical map resolves but this crosswalk cannot — add "
        f"each as a canonical_code or an `aliases` entry: {uncovered}"
    )
