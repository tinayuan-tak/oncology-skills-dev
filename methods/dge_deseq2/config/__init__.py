"""dge_deseq2.config — single source of truth for indication rosters (S1, #693)
and substrate metadata (S1's deferred (b)-half, #733).

Loads ``config/indications.yaml`` and PROJECTS it into the structures each consumer
previously hard-coded independently:

  * :func:`published_indications`     -> derive_pancan_stack._PUBLISHED_INDICATIONS
  * :func:`composite_indications`     -> derive_pancan_stack._COMPOSITE_INDICATIONS
  * :func:`indication_to_tcga_studies`-> read.INDICATION_TO_TCGA_STUDIES
  * :func:`indication_to_gtex_tissue` -> read.INDICATION_TO_GTEX_TISSUE
  * :func:`pan_tissue_indications`    -> emit_pan_tissue.PAN_TISSUE_INDICATIONS

Pure no-op consolidation: every projection is verdict-identical to the pre-S1 literals,
pinned byte-for-byte by ``tests/test_indication_config_rosters.py``. These are DIFFERENT
sets (a 27-product universe, a 19-row render subset, a 21-key substrate lookup), so each
projection filters the universe on its own membership flag rather than sharing one list.

``config/substrates.yaml`` (#733) is a SEPARATE, smaller file declaring per-substrate
metadata (annotation version, S3 key infix, source manifest id, role) that was previously
scattered as independent literals in ``emit_data_package._SUBSTRATE_INFIX`` and
``read.RECOUNT3_S3_PREFIX``:

  * :func:`substrates`                    -> the full {substrate -> attrs} map
  * :func:`substrate_infix`               -> emit_data_package._SUBSTRATE_INFIX values
  * :func:`substrate_source_manifest_id`  -> read.RECOUNT3_S3_PREFIX's manifest id
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).with_name("indications.yaml")
_SUBSTRATES_PATH = Path(__file__).with_name("substrates.yaml")
_SUBGROUP_AXES_PATH = Path(__file__).with_name("subgroup_axes.yaml")


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(_CONFIG_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    inds = data["indications"]
    render = data["pan_tissue_render"]
    # Fail loud on drift rather than silently mis-projecting: the render roster must be a
    # subset of the published universe (an unknown or unpublished render row is a bug).
    missing = [c for c in render if c not in inds]
    assert not missing, f"pan_tissue_render references unknown indications: {missing}"
    unpublished = [c for c in render if not inds[c].get("published")]
    assert not unpublished, f"pan_tissue_render includes non-published indications: {unpublished}"
    return data


@lru_cache(maxsize=1)
def _load_substrates() -> dict:
    with open(_SUBSTRATES_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["substrates"]


def _indications() -> dict:
    return _load()["indications"]


def published_indications() -> list:
    """The 27 published indications (derive_pancan_stack roster), sorted.

    This is the ``{indication}-dge-tumor-vs-normal-sensitivity-v1`` product universe. Was
    ``cell_b_semantics_map`` (a name -> cell-B vintage dict) until analysis-methods#727 removed
    the ComBat cell B; the vintage payload is gone, only the roster of published names remains.
    """
    return sorted(name for name, attrs in _indications().items() if attrs.get("published"))


def staged_indications() -> dict:
    """Universe-expansion candidates staged but NOT yet published (#734, Phase 1).

    Each staged entry carries ``published: false`` + ``in_read_map: false`` -> it is consumed by
    NO other projection (``published_indications``, ``indication_to_{tcga_studies,gtex_tissue}``,
    ``pan_tissue_indications``, ``composite_indications``), so staging is VERDICT-INERT. The
    recorded ``gtex_tissue`` / ``tcga_studies`` are the Phase-2 matched-normal proposal; each entry
    also carries a non-null ``caveat`` naming the contrast confound that must be signed off before
    its flags may be flipped to a live product. Returns ``{name -> {gtex_tissue, caveat}}``.
    """
    return {
        name: {"gtex_tissue": attrs.get("gtex_tissue"), "caveat": attrs.get("caveat")}
        for name, attrs in _indications().items()
        if attrs.get("staged")
    }


def pancan_stack_excluded_from_roster() -> set:
    """Sensitivity products intentionally excluded from the pancan-stack roster (#791).

    Products that legitimately live on S3 under a ``*-dge-tumor-vs-normal-sensitivity-v1``
    prefix but are NOT pancan-stack members (e.g. NSCLC's pooled LUAD+LUSC composite, SCLC's
    different-method product). ``derive_pancan_stack.assert_roster_matches_published`` subtracts
    this set from the live S3-published listing before diffing against the declared roster, so
    these known, reviewed exclusions don't false-positive as roster drift.
    """
    return set(_load().get("pancan_stack_excluded_from_roster", []))


def composite_indications() -> dict:
    """Composite OncoTree parent -> set of finer sibling cohorts it is the union of."""
    return {
        name: set(attrs["composite_children"])
        for name, attrs in _indications().items()
        if attrs.get("composite_children")
    }


def indication_to_tcga_studies() -> dict:
    """Indication -> recount3 TCGA study codes (read-map entries only)."""
    return {name: list(attrs["tcga_studies"]) for name, attrs in _indications().items() if attrs.get("in_read_map")}


def indication_to_gtex_tissue() -> dict:
    """Indication -> matched recount3 GTEx tissue (read-map entries with a clean match)."""
    return {
        name: attrs["gtex_tissue"]
        for name, attrs in _indications().items()
        if attrs.get("in_read_map") and attrs.get("gtex_tissue") is not None
    }


def pan_tissue_indications() -> list:
    """Ordered pan-indication figure render roster (emit_pan_tissue)."""
    return list(_load()["pan_tissue_render"])


def run_ledger_intent() -> dict:
    """Declared run-ledger product roster per (family, substrate) — S5, #698.

    The recount3 sensitivity roster is the ``published: true`` universe PLUS any
    ``sensitivity_recount3_extra`` (06-driver products that ship without a
    standalone published flag, e.g. the NSCLC composite). Everything else is a
    literal per-family / singleton roster. ``build_run_ledger`` turns this into
    the expected ``{catalog_id -> attrs}`` map and reconciles it bidirectionally
    against the catalog manifests + S3 prefixes; it is NOT the iteration driver.
    """
    intent = _load()["run_ledger_intent"]
    published = published_indications()  # the 27 published indications (sorted)
    return {
        "sensitivity": {
            "recount3": published + list(intent.get("sensitivity_recount3_extra", [])),
            "xena_toil": list(intent.get("sensitivity_xena_toil", [])),
        },
        "adj_vs_gtex": {
            "recount3": list(intent.get("adj_vs_gtex_recount3", [])),
            "xena_toil": list(intent.get("adj_vs_gtex_xena_toil", [])),
        },
        "subgroup": {
            "recount3": list(intent.get("subgroup_recount3", [])),
        },
        "singletons": [dict(s) for s in intent.get("singletons", [])],
    }


@lru_cache(maxsize=1)
def subgroup_axes() -> dict[str, list[dict]]:
    """The by-subgroup DGE curation: ``{INDICATION -> [{axis, assignments_manifest, strata}, ...]}``.

    Config-drive for ``run_subgroup_dge_batch`` (analysis-methods#738): each indication maps to an
    ORDERED list of subgroup axes, each binding a (axis label, assignment-manifest id, strata) triple
    out of ``config/subgroup_axes.yaml``.

    Fail loud on drift rather than silently mis-projecting (mirrors the ``pan_tissue_render`` subset
    assert in :func:`_load`): the set of indications keyed here MUST equal the by-subgroup roster
    declared in ``run_ledger_intent()["subgroup"]["recount3"]``. A drift in EITHER direction (an axis
    curated for an indication the ledger does not expect, or an expected indication with no curated
    axes) is a bug that would desync the orchestrator from the run-ledger.
    """
    with open(_SUBGROUP_AXES_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)["subgroup_axes"]
    keyed = set(data)
    declared = set(run_ledger_intent()["subgroup"]["recount3"])
    assert keyed == declared, (
        f"subgroup_axes indications {sorted(keyed)} != run_ledger_intent subgroup.recount3 "
        f"{sorted(declared)} (drift either way is a bug)"
    )
    return {ind: [dict(ax) for ax in axes] for ind, axes in data.items()}


def subgroup_axis_reconciliation(catalog_root) -> list[str]:
    """Return the mapped-but-MISSING assignment-manifest errors (empty list == clean).

    For every ``(indication, axis)`` in :func:`subgroup_axes`, the mapped ``assignments_manifest``
    id must resolve to a real derived manifest at
    ``{catalog_root}/manifests/derived/{id}.yaml``. Any mapping that does not is returned as a
    human-readable error string. These are the "mapped-but-missing must RED" teeth
    (:mod:`build_run_ledger` folds them into ``--self-check``): a curated axis that points at an
    assignment product no one has landed must fail loud, never green-on-empty (the S5 #698 fail-open
    discipline).
    """
    derived = Path(catalog_root) / "manifests" / "derived"
    errors: list[str] = []
    for ind, axes in subgroup_axes().items():
        for ax in axes:
            mid = ax["assignments_manifest"]
            manifest = derived / f"{mid}.yaml"
            if not manifest.is_file():
                errors.append(
                    f"{ind}/{ax['axis']}: mapped assignments_manifest {mid!r} has no catalog manifest at {manifest}"
                )
    return sorted(errors)


def substrates() -> dict:
    """Per-substrate metadata: annotation_version, s3_key_infix, source_manifest_id, role."""
    return {name: dict(attrs) for name, attrs in _load_substrates().items()}


def substrate_infix(substrate: str) -> str:
    """The catalog-id / S3-key infix for one substrate (e.g. "" for recount3, "-xenatoil")."""
    return _load_substrates()[substrate]["s3_key_infix"]


def substrate_source_manifest_id(substrate: str) -> str:
    """The data-catalog source manifest id backing one substrate."""
    return _load_substrates()[substrate]["source_manifest_id"]
