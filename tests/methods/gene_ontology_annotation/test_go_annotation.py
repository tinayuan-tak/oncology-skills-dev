"""GO annotation method: resolver-backed symbol->AC, 3-namespace split, honest data_unavailable.

Two S3-free unit tests (fixture GAF/OBO/sidecar) + one live smoke (skips without S3)."""

from __future__ import annotations

import gzip
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.gene_ontology_annotation import read as _go  # noqa: E402

_GAF = (
    "\t".join(["UniProtKB", "P00001", "TESTG", "enables", "GO:0004672", "PMID:1", "IDA", "", "F"])
    + "\n"
    + "\t".join(["UniProtKB", "P00001", "TESTG", "part_of", "GO:0005634", "GO_REF:1", "IEA", "", "C"])
    + "\n"
    + "\t".join(["UniProtKB", "P00001", "TESTG", "involved_in", "GO:0006468", "PMID:2", "IMP", "", "P"])
    + "\n"
)
_OBO = (
    "[Term]\nid: GO:0004672\nname: protein kinase activity\nnamespace: molecular_function\n\n"
    "[Term]\nid: GO:0005634\nname: nucleus\nnamespace: cellular_component\n\n"
    "[Term]\nid: GO:0006468\nname: protein phosphorylation\nnamespace: biological_process\n"
)


def _fixtures(tmp_path):
    import pandas as pd

    gaf = tmp_path / "goa.gaf.gz"
    with gzip.open(gaf, "wt") as fh:
        fh.write(_GAF)
    obo = tmp_path / "go.obo"
    obo.write_text(_OBO)
    sc = tmp_path / "sidecar.parquet"
    pd.DataFrame([{"hgnc_primary_symbol_at_resolution": "TESTG", "native_row_key": "P00001"}]).to_parquet(sc)
    # clear the lru caches so the fixtures are used
    _go._load_gaf.cache_clear()
    _go._load_obo_names.cache_clear()
    _go._load_symbol_to_ac.cache_clear()
    return str(gaf), str(obo), str(sc)


def test_three_namespace_split_and_resolution(tmp_path):
    gaf, obo, sc = _fixtures(tmp_path)
    s = _go.read_target_summary("TESTG", gaf_path=gaf, obo_path=obo, sidecar_path=sc)
    assert s["uniprot_ac_resolved"] == "P00001"  # resolved via sidecar, not GAF col3
    assert s["n_go_terms_total"] == 3
    assert (s["n_biological_process"], s["n_molecular_function"], s["n_cellular_component"]) == (1, 1, 1)
    assert s["n_go_terms_experimental"] == 2  # IDA + IMP experimental; IEA not
    assert s["top_molecular_function"][0]["name"] == "protein kinase activity"


def test_unresolvable_target_is_data_unavailable(tmp_path):
    gaf, obo, sc = _fixtures(tmp_path)
    s = _go.read_target_summary("NOTAGENE", gaf_path=gaf, obo_path=obo, sidecar_path=sc)
    assert s["annotation_class"] == "data_unavailable"
    assert s["_data_note"] == "target_symbol_not_resolvable"


def test_live_egfr_well_annotated():
    _go._load_gaf.cache_clear()
    _go._load_obo_names.cache_clear()
    _go._load_symbol_to_ac.cache_clear()
    try:
        s = _go.read_target_summary("EGFR")
    except Exception:  # noqa: BLE001
        pytest.skip("no S3")
    if s.get("_data_note"):
        pytest.skip("GO source unreachable (no S3)")
    assert s["annotation_class"] == "well_annotated"
    assert s["n_molecular_function"] > 0 and s["n_cellular_component"] > 0


# --- per-AC product read path (perf: pushdown vs whole GAF+OBO cold-start) ---------------------------
def test_product_path_reconstructs_terms_and_names(tmp_path):
    import pandas as pd

    import methods.gene_ontology_annotation.read as GO

    p = tmp_path / "go.parquet"
    pd.DataFrame(
        [
            {
                "uniprot_ac": "P1",
                "go_id": "GO:1",
                "namespace": "biological_process",
                "evidence": "IDA",
                "go_name": "apoptosis",
            },
            {
                "uniprot_ac": "P1",
                "go_id": "GO:2",
                "namespace": "molecular_function",
                "evidence": "IEA",
                "go_name": "binding",
            },
            {
                "uniprot_ac": "P2",
                "go_id": "GO:9",
                "namespace": "cellular_component",
                "evidence": "IDA",
                "go_name": "nucleus",
            },
        ]
    ).to_parquet(p, index=False)
    terms, names = GO._load_annotation_from_product("P1", product_path=str(p))
    assert {t["go_id"] for t in terms} == {"GO:1", "GO:2"}
    assert names["GO:1"] == "apoptosis" and names["GO:2"] == "binding"
    # absent AC → ([], {}) so the caller emits target_not_in_goa_human (mirrors live gaf miss)
    assert GO._load_annotation_from_product("PZZZ", product_path=str(p)) == ([], {})
    # unreachable product → None (caller falls back to the live GAF+OBO read)
    assert GO._load_annotation_from_product("P1", product_path=str(tmp_path / "nope.parquet")) is None
