"""opentargets_disease_xref.read — MESH -> OT-disease (MONDO/EFO) crosswalk from OT disease dbXRefs.

Greenfield helper: PubTator keys diseases on MESH ids, while the framework/OT world keys on
EFO/MONDO. Open Targets' own `disease` entity carries a `dbXRefs` list per disease that INCLUDES
MESH cross-references — so the crosswalk is built in-house from the pinned opentargets-26-06 mirror,
with no external dependency. Used to scope a PubTator gene×disease-relation product (disease_mesh)
to a framework indication's EFO/MONDO family (efo_ids from indication_crosswalk).

Direction: indication -> efo_ids (MONDO/EFO) -> {MESH ids} via disease.dbXRefs -> filter disease_mesh.

KNOWN LIMITATION (measured 2026-08-28): many OT MONDO *cancer* terms curated into the
indication_crosswalk efo_ids lanes carry NO MESH dbXRef (their xrefs are DOID/EFO/NCIT/UMLS/OMIM),
while PubTator's MESH disease often aligns to a *sibling* MONDO term outside the curated family. So
efo_ids -> MESH can come back empty even for well-covered indications (e.g. COADREAD), and the
consuming reader then honestly falls back to TARGET-LEVEL relations. A robust indication scope for the
PubTator lane needs a curated indication -> MESH-id lane in indication_crosswalk.yaml (mirrors the
existing `mesh_terms` lane) or a MONDO ontology-neighbourhood bridge — tracked as a follow-up.
"""

from __future__ import annotations


def _extract_mesh(dbxrefs) -> list:
    """PURE: from an OT disease `dbXRefs` list, return normalized MESH ids ('MESH:<code>').
    Accepts both 'MESH:...' and legacy 'MSH:...' prefixes (case-insensitive); ignores other xrefs."""
    out = []
    if dbxrefs is None:
        return out
    try:
        items = list(dbxrefs)  # handles python list AND numpy array
    except TypeError:  # scalar / NaN -> no xrefs
        return out
    for x in items:
        s = str(x).strip()
        if ":" not in s:
            continue
        prefix, code = s.split(":", 1)
        if prefix.upper() in ("MESH", "MSH") and code:
            out.append(f"MESH:{code}")
    return out


def mesh_ids_for_efo(efo_ids) -> set:
    """Map OT disease ids (MONDO/EFO) -> set of MESH ids via the OT disease entity dbXRefs.
    Empty set when efo_ids is empty or none of the diseases carry a MESH xref.

    Live read of the OT `disease` entity (id + dbXRefs), filtered in-process to efo_ids. Absence-safe
    via read_entity's discipline (genuine absence -> empty frame -> empty set; env faults propagate)."""
    ids = {str(x) for x in (efo_ids or [])}
    if not ids:
        return set()
    from methods.opentargets_common import read_entity

    df = read_entity("disease", columns=["id", "dbXRefs"])
    out: set = set()
    if df is None or len(df) == 0:
        return out
    for _id, xrefs in zip(df["id"].tolist(), df["dbXRefs"].tolist()):
        if str(_id) in ids:
            out.update(_extract_mesh(xrefs))
    return out


def _main(argv=None):
    import argparse
    import json

    ap = argparse.ArgumentParser(description="MESH ids for a set of OT disease (MONDO/EFO) ids.")
    ap.add_argument("--efo-ids", nargs="+", required=True)
    args = ap.parse_args(argv)
    print(json.dumps(sorted(mesh_ids_for_efo(args.efo_ids)), indent=2))


if __name__ == "__main__":
    _main()
