"""gen_indication_mesh_ids.py — add/refresh the `mesh_ids` lane on indication_crosswalk.yaml.

The crosswalk already carries a curated `mesh_terms` lane (MeSH descriptor NAMES, for the AACT
ClinicalTrials.gov trial-precedent filter). This lane resolves those names to MeSH descriptor IDs
(the `disease_mesh` key used by the PubTator gene×disease-relations product
`pubtator3-gene-disease-relations-per-gene-v1`), so a reader can scope PubTator relations to an
indication — the OT-disease dbXRefs bridge is lossy (OT MONDO cancer terms often lack a MESH xref).

Provenance: MESH_IDS below was produced by resolving each indication's `mesh_terms` against the NCBI
MeSH database (E-utilities esearch "<term>"[MeSH Terms] -> esummary ds_meshui) on 2026-08-28. Baked in
as a literal so this is deterministic + reviewable without a live NCBI dependency at apply time; rerun
with --regenerate to refresh from NCBI. IDs are authoritative MeSH descriptor UIs (D-codes; a few
supplementary C-record terms resolve to their preferred descriptor and are covered by sibling terms).

Usage:  python scripts/gen_indication_mesh_ids.py         # apply MESH_IDS to the crosswalk (ruamel round-trip)
        python scripts/gen_indication_mesh_ids.py --regenerate   # re-resolve from NCBI, then apply
"""

from __future__ import annotations
import sys
from pathlib import Path

CROSSWALK = Path(__file__).resolve().parents[1] / "vocabularies" / "indication_crosswalk.yaml"

# canonical_code -> [MESH:D...]  (NCBI MeSH resolution of the mesh_terms lane, 2026-08-28)
MESH_IDS = {
    "COADREAD": ["MESH:D003110", "MESH:D012004", "MESH:D015179"],
    "NSCLC": ["MESH:D000077192", "MESH:D002289", "MESH:D008175"],
    "SCLC": ["MESH:D018288", "MESH:D055752"],
    "HNSC": ["MESH:D000077195", "MESH:D006258"],
    "STAD": ["MESH:D013274"],
    "ESCA": ["MESH:D000077277", "MESH:D004938"],
    "PAAD": ["MESH:D010190", "MESH:D021441"],
    "AML": ["MESH:D015470"],
    "CML": ["MESH:D015464", "MESH:D015466"],
    "BRCA": ["MESH:D001943", "MESH:D058922", "MESH:D064726"],
    "PRAD": ["MESH:D011471", "MESH:D064129"],
    "OV": ["MESH:D000077216", "MESH:D010051"],
    "GBM": ["MESH:D005909"],
    "LGG": ["MESH:D001254", "MESH:D005910", "MESH:D009837"],
    "SKCM": ["MESH:D000098943", "MESH:D008545"],
    "BLCA": ["MESH:D001749", "MESH:D002295"],
    "KIRC": ["MESH:D002292", "MESH:D007680"],
    "LIHC": ["MESH:D006528", "MESH:D008113"],
    "CESC": ["MESH:D002583"],
    "UCEC": ["MESH:D014594", "MESH:D016889"],
    "DLBC": ["MESH:D016393", "MESH:D016403"],
}


def _regenerate() -> dict:
    import json, time, urllib.request, urllib.parse
    import yaml

    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"

    def meshid(term):
        q = urllib.parse.urlencode({"db": "mesh", "term": f'"{term}"[MeSH Terms]', "retmode": "json"})
        uid = (
            json.loads(urllib.request.urlopen(base + "esearch.fcgi?" + q, timeout=30).read())
            .get("esearchresult", {})
            .get("idlist", [])
        )
        if not uid:
            return None
        time.sleep(0.34)
        s = json.loads(
            urllib.request.urlopen(base + f"esummary.fcgi?db=mesh&id={uid[0]}&retmode=json", timeout=30).read()
        )
        return s["result"][uid[0]].get("ds_meshui")

    cw = yaml.safe_load(CROSSWALK.read_text())
    out = {}
    for e in cw["indications"]:
        ids = set()
        for term in e.get("mesh_terms") or []:
            mid = meshid(term)
            time.sleep(0.34)
            if mid:
                ids.add(f"MESH:{mid}")
        out[e["canonical_code"]] = sorted(ids)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mapping = _regenerate() if "--regenerate" in argv else MESH_IDS

    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)  # match the file's existing '  - key' list style
    # emit explicit `null` (not blank) so the diff stays minimal vs the original file
    yaml.representer.add_representer(type(None), lambda r, d: r.represent_scalar("tag:yaml.org,2002:null", "null"))
    doc = yaml.load(CROSSWALK.read_text())
    doc["version"] = "1.3.0"
    n = 0
    for e in doc["indications"]:
        ids = mapping.get(e["canonical_code"])
        if ids:
            e["mesh_ids"] = ids
            n += 1
    with CROSSWALK.open("w") as fh:
        yaml.dump(doc, fh)
    print(f"applied mesh_ids to {n}/{len(doc['indications'])} indications")


if __name__ == "__main__":
    main()
