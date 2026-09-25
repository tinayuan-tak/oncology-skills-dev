"""S1's deferred (b)-half verdict-identity gate for substrate metadata (analysis-methods#733).

`emit_data_package._SUBSTRATE_INFIX` and `read.RECOUNT3_S3_PREFIX` used to hard-code substrate
metadata (the catalog-id infix, the recount3 source manifest id) independently. Both now project
out of ``config/substrates.yaml``. This is a PURE NO-OP: the projections must be byte-identical
to the pre-#733 literals, which are FROZEN below. Do NOT edit these expected values to match a
change — a diff here means the consolidation moved substrate metadata (a live S3/catalog-id
change), which is out of scope here and belongs in a separate PR.

Mirrors ``test_indication_config_rosters.py``'s pattern for the (a)-half (S1, #693).
"""

from __future__ import annotations

import copy

from methods.dge_deseq2 import config as cfg

# emit_data_package._SUBSTRATE_INFIX, pre-#733
EXPECTED_INFIX = {"recount3": "", "xena_toil": "-xenatoil"}

# The recount3 source manifest id read.RECOUNT3_S3_PREFIX resolved, pre-#733
EXPECTED_RECOUNT3_MANIFEST_ID = "recount3-tcga-gtex-2023-01-04"
EXPECTED_XENA_TOIL_MANIFEST_ID = "xena-toil-tcga-target-gtex-snapshot-2026-09-20"

EXPECTED_ANNOTATION_VERSION = {"recount3": "v26", "xena_toil": "v23"}


def test_substrates_matches_frozen_shape():
    got = cfg.substrates()
    assert set(got) == {"recount3", "xena_toil"}
    for name, attrs in got.items():
        assert set(attrs) == {"annotation_version", "s3_key_infix", "source_manifest_id", "role"}


def test_substrate_infix_matches_frozen_literal():
    got = {name: cfg.substrate_infix(name) for name in ("recount3", "xena_toil")}
    assert got == EXPECTED_INFIX


def test_substrate_source_manifest_id_matches_frozen_literal():
    assert cfg.substrate_source_manifest_id("recount3") == EXPECTED_RECOUNT3_MANIFEST_ID
    assert cfg.substrate_source_manifest_id("xena_toil") == EXPECTED_XENA_TOIL_MANIFEST_ID


def test_annotation_version_matches_frozen_literal():
    got = {name: cfg.substrates()[name]["annotation_version"] for name in ("recount3", "xena_toil")}
    assert got == EXPECTED_ANNOTATION_VERSION


def test_no_cell_b_field_anywhere_in_substrate_metadata():
    # analysis-methods#727 removed ComBat-seq cell B entirely; it never had a substrate axis of
    # its own, so config/substrates.yaml must carry no cell-B-shaped field at all.
    got = cfg.substrates()
    for attrs in got.values():
        assert not any("cell_b" in k.lower() for k in attrs)


# --- the consumer module attributes are wired to the projections ---------------------------
def test_emit_data_package_infix_is_config_projection():
    from methods.dge_deseq2 import emit_data_package as e

    assert e._SUBSTRATE_INFIX == EXPECTED_INFIX


def test_read_recount3_prefix_matches_frozen_literal():
    from methods.dge_deseq2 import read

    # Frozen pre-#733 value (bucket_prefix_for("recount3-tcga-gtex-2023-01-04")[1].rstrip("/")).
    assert read.RECOUNT3_S3_PREFIX == "data-catalog/sources/recount3/tcga-gtex-2023-01-04"


# --- mutation checks: the projections READ the config, they are not hard-coded copies ------
def test_substrate_infix_reads_config(monkeypatch):
    data = copy.deepcopy(cfg._load_substrates())
    data["recount3"]["s3_key_infix"] = "-changed"
    monkeypatch.setattr(cfg, "_load_substrates", lambda: data)
    assert cfg.substrate_infix("recount3") == "-changed"


def test_substrate_source_manifest_id_reads_config(monkeypatch):
    data = copy.deepcopy(cfg._load_substrates())
    data["xena_toil"]["source_manifest_id"] = "some-other-manifest"
    monkeypatch.setattr(cfg, "_load_substrates", lambda: data)
    assert cfg.substrate_source_manifest_id("xena_toil") == "some-other-manifest"
