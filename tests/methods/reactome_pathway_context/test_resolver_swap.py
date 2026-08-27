"""Guard: the HGNC→UniProt crosswalk comes from the Reactome resolver SIDECAR, not a hardcoded map.

Regression for the v0.1 shortcut (a ~30-target inline dict) that failed the standing resolver-sidecar
rule for any target outside the inline set. This pins that the crosswalk is sidecar-backed and resolves
targets that were NEVER in the old inline map (CDH17/GPC3/MSLN).

Also carries an S3-FREE fixture test that drives read.read_target_summary end-to-end on a synthetic
sidecar + UniProt2Reactome + hierarchy (mirrors the ppi_interactome / gene_ontology_annotation
pattern), so reader logic is exercised offline. The live tests narrow their skip to botocore
connectivity/credential errors — a schema-drift / logic bug must SURFACE, not silently skip."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from botocore.exceptions import BotoCoreError, ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.reactome_pathway_context import read as _r  # noqa: E402


# --- S3-free fixture: synthetic sidecar + UniProt2Reactome + hierarchy --------------------------
_U2R = "".join(
    "\t".join(["P00001", f"R-HSA-10{i}", "https://reactome.org/x",
               f"Leaf Pathway {i}", "IEA", "Homo sapiens"]) + "\n"
    for i in range(5)
) + "\t".join(["P00001", "R-HSA-999", "url", "Mouse noise", "IEA", "Mus musculus"]) + "\n"

_PATHWAYS = ("R-HSA-9\tSignal Transduction\tHomo sapiens\n"
             + "".join(f"R-HSA-10{i}\tLeaf Pathway {i}\tHomo sapiens\n" for i in range(5)))

_RELATIONS = "".join(f"R-HSA-9\tR-HSA-10{i}\n" for i in range(5))


def _fixtures(tmp_path):
    import pandas as pd
    u2r = tmp_path / "UniProt2Reactome_All_Levels.txt"
    u2r.write_text(_U2R)
    pathways = tmp_path / "ReactomePathways.txt"
    pathways.write_text(_PATHWAYS)
    relations = tmp_path / "ReactomePathwaysRelation.txt"
    relations.write_text(_RELATIONS)
    sc = tmp_path / "sidecar.parquet"
    pd.DataFrame([{"hgnc_primary_symbol_at_resolution": "TESTG",
                   "native_row_key": "P00001"}]).to_parquet(sc)
    # clear lru caches so the fixtures (distinct cache keys) are the only source
    _r._load_uniprot_to_reactome.cache_clear()
    _r._load_pathway_hierarchy.cache_clear()
    _r._load_hgnc_uniprot_crosswalk.cache_clear()
    return dict(uniprot2reactome_path=str(u2r), pathways_path=str(pathways),
                relations_path=str(relations), sidecar_path=str(sc))


def test_offline_summary_resolves_via_sidecar_and_rolls_up(tmp_path):
    s = _r.read_target_summary("TESTG", **_fixtures(tmp_path))
    assert s["uniprot_ac_resolved"] == "P00001"           # resolved via sidecar, not a hardcoded map
    assert s["pathway_count"] == 5                          # 5 human leaves; the Mus row is filtered
    assert s["top_level_pathways"] == ["Signal Transduction"]
    assert s["is_signaling"] is True
    assert s["pathway_class"] == "partial"                  # 5 <= n < 20
    assert s.get("_data_note") is None


def test_offline_unresolvable_target_is_data_unavailable(tmp_path):
    s = _r.read_target_summary("NOTAGENE", **_fixtures(tmp_path))
    assert s["pathway_class"] == "data_unavailable"
    assert s["_data_note"] == "target_symbol_not_resolvable"


def test_offline_resolvable_but_absent_from_reactome(tmp_path):
    # A bare UniProt-AC that resolves (AC-shape) but has no Homo sapiens rows → honest empty.
    s = _r.read_target_summary("P09999", **_fixtures(tmp_path))
    assert s["pathway_class"] == "data_unavailable"
    assert s["_data_note"] == "target_not_in_reactome_human"


# --- resolver-sidecar discipline guards (live; skip only on real S3/creds failure) --------------
def test_crosswalk_is_sidecar_backed_not_hardcoded():
    # The crosswalk must resolve to the resolver sidecar, and the inline 30-target dict must be gone.
    assert _r.REACTOME_RESOLVER_SIDECAR_S3_KEY.endswith("target_resolution.parquet"), \
        "crosswalk must read the resolver sidecar"
    src = (REPO / "methods" / "reactome_pathway_context" / "read.py").read_text()
    assert '"KRAS": "P01116"' not in src, "the hardcoded inline crosswalk must be removed"


@pytest.mark.parametrize("target", ["CDH17", "GPC3", "MSLN"])
def test_non_inline_targets_now_resolve(target):
    # These were NOT in the former inline crosswalk — they resolve only via the sidecar.
    _r._load_hgnc_uniprot_crosswalk.cache_clear()   # drop any fixture-primed entry
    try:
        xwalk = _r._load_hgnc_uniprot_crosswalk()
    except (BotoCoreError, ClientError):            # narrowed: only S3/creds connectivity → skip
        pytest.skip("resolver sidecar unreachable (no S3)")
    if not xwalk:
        pytest.skip("resolver sidecar unreachable (no S3)")
    assert target in xwalk, f"{target} should resolve to a UniProt AC via the sidecar"


# --- per-AC product read path (perf: pushdown vs whole UniProt2Reactome+hierarchy cold-start) --------
def test_product_path_reconstructs_ordered_pathways_and_toplevels(tmp_path):
    import pandas as pd
    import methods.reactome_pathway_context.read as RE
    p = tmp_path / "re.parquet"
    pd.DataFrame([  # deliberately out of row_order to prove the reader restores source order
        {"uniprot_ac": "P1", "row_order": 1, "pathway_id": "R-2", "pathway_name": "B",
         "evidence_code": "IEA", "url": "u2", "top_level_pathway_name": "Signal Transduction"},
        {"uniprot_ac": "P1", "row_order": 0, "pathway_id": "R-1", "pathway_name": "A",
         "evidence_code": "TAS", "url": "u1", "top_level_pathway_name": "Metabolism"},
    ]).to_parquet(p, index=False)
    pathways, tops = RE._load_pathways_from_product("P1", product_path=str(p))
    assert [x["pathway_id"] for x in pathways] == ["R-1", "R-2"]         # restored to row_order
    assert tops == {"Signal Transduction", "Metabolism"}
    # absent AC → ([], set()) → caller emits target_not_in_reactome_human
    assert RE._load_pathways_from_product("PZZ", product_path=str(p)) == ([], set())
    # unreachable product → None (caller falls back to the live UniProt2Reactome read)
    assert RE._load_pathways_from_product("P1", product_path=str(tmp_path / "nope.parquet")) is None
