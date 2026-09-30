"""impc_mouse_ko_phenotype — IMPC-direct mouse-KO corroboration leg (pure, dict-fixture tested).

Properties under test (no S3): the rollup row -> classifier-row reconstruction (comma-split of packed
top-level MP systems + the viability->developmental lethal synthesis), reuse of the shared
classify_ko_phenotype taxonomy, and the absence coverage-gap path."""

from __future__ import annotations

import importlib
import json

r = importlib.import_module("onc_methods.impc_mouse_ko_phenotype.read")
_ot = importlib.import_module("onc_methods.opentargets_mouse_phenotype.read")
classify = _ot.classify_ko_phenotype


def _row(viability="viable", pairs=None):
    """Synthesize an impc-ko-phenotype-per-gene-v1 rollup row."""
    return {
        "human_gene_symbol": "TESTG",
        "mouse_marker_symbol": "Testg",
        "mgi_accession_id": "MGI:1",
        "orthology_type": "ortholog_one2one",
        "orthology_confidence": 1.0,
        "impc_viability_class": viability,
        "impc_viability_call_raw": viability,
        "n_phenotype_hits": len(pairs or []),
        "top_level_systems": "|".join(sorted({p[1] for p in (pairs or [])})),
        "n_top_level_systems": len({p[1] for p in (pairs or [])}),
        "phenotype_rows_json": json.dumps(
            [{"label": mp, "classes": [top] if top else []} for mp, top in (pairs or [])]
        ),
    }


def test_preweaning_lethal_is_developmental_only():
    """IMPC viability is a PREWEANING screen -> lethal maps to the DEVELOPMENTAL bucket (guardrail),
    never the adult killer (which only OT-MGI literature can assert)."""
    out = classify(r._rows_for_classifier(_row(viability="lethal_preweaning")))
    assert out["ko_phenotype_class"] == "developmental_only"


def test_comma_packed_top_level_systems_split_for_organ_detection():
    """IMPC packs multiple top-level MP systems comma-joined in one field; they must be split so each
    matches the shared classifier's exact severe-organ-class set."""
    row = _row(
        viability="viable",
        pairs=[("abnormal spleen morphology", "immune system phenotype,hematopoietic system phenotype")],
    )
    rows = r._rows_for_classifier(row)
    labels = {c["label"] for row_ in rows for c in row_["modelPhenotypeClasses"]}
    assert "immune system phenotype" in labels and "hematopoietic system phenotype" in labels
    out = classify(rows)
    assert out["ko_phenotype_class"] == "severe_organ_phenotype"


def test_viable_with_no_hits_is_no_phenotype():
    out = classify(r._rows_for_classifier(_row(viability="viable", pairs=[])))
    assert out["ko_phenotype_class"] == "no_phenotype"


def test_absent_gene_is_coverage_gap(monkeypatch):
    """A gene IMPC has not phenotyped (KRAS/BRAF/VHL) -> no_phenotype coverage gap, never a killer."""
    monkeypatch.setattr(r, "_read_impc_row", lambda target: None)
    out = r.read_impc_mouse_ko_phenotype("KRAS")
    assert out["ko_phenotype_class"] == "no_phenotype"
    assert out["impc_viability_class"] == "unmeasured"
    assert "absent from impc-ko-phenotype-per-gene-v1" in out["_note"]
    assert out["evidence_tier"] == "inferred"


def test_emits_impc_provenance_fields(monkeypatch):
    monkeypatch.setattr(
        r,
        "_read_impc_row",
        lambda target: _row(viability="lethal_preweaning", pairs=[("x", "nervous system phenotype")]),
    )
    out = r.read_impc_mouse_ko_phenotype("TESTG")
    assert out["impc_viability_class"] == "lethal_preweaning"
    assert out["ko_phenotype_class"] == "developmental_only"  # preweaning -> developmental guardrail
    assert out["source"].startswith("impc-release-24-0")
    assert out["mouse_marker_symbol"] == "Testg"
