#!/usr/bin/env python3
"""structure_features_static.pull — the live PDB + AlphaFold per-UniProt sweep.

Produces the derived product `pdb-alphafold-structure-features-per-uniprot-v1`: one row per reviewed
human SwissProt accession, joining
  - AlphaFold DB (https://alphafold.ebi.ac.uk/api/prediction/{AC}) — summary + the model CIF, from which
    the PER-RESIDUE pLDDT array is parsed (compute.parse_cif_plddt; the CA B-factor column, pure text —
    NO structure library, validated: parsed mean == API globalMetricValue).
  - PDBe best_structures (https://www.ebi.ac.uk/pdbe/api/mappings/best_structures/{AC}) — experimental
    coverage (PDB ids, best resolution, method).
  - InterPro domains (uniprot_protein_features) — per-domain pLDDT-min slicing.
  - TCGA MC3 hotspots (tcga-mc3-hotspot-frequency-v1, 4 indications) — HGVSp hotspot residues where the
    gene is recurrent; elsewhere the pocket-adjacency call is honestly `no_hotspots_annotated`.

Design discipline:
  - STREAM-AND-DISCARD: each CIF is fetched into memory, parsed, discarded — peak disk is ~one CIF (~a few
    MB), never the corpus. Only the final ~sub-MB parquet is written + uploaded.
  - RESUMABLE: per-AC rows appended to a JSONL checkpoint; a re-run skips ACs already in it (mirrors
    pull_interpro.py). A transient HTTP error re-tries with backoff; a definitive 404 (no AF model / no
    PDB) is a VALID "no coverage" row, not a failure.
  - The row-building LOGIC is compute.build_row (unit-tested); this module is the network + I/O shell.

Mirrors the InterPro API-sweep precedent (data-catalog/scripts/pull_interpro.py). The "source" of an
API-derived product is the endpoint + snapshot date (no large corpus mirror) — the source manifests pin
"AlphaFold DB API" + "PDBe API" at the snapshot date; only the small derived parquet lands in S3.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

from . import compute

AF_PREDICTION_URL = "https://alphafold.ebi.ac.uk/api/prediction/{ac}"
PDBE_BEST_URL = "https://www.ebi.ac.uk/pdbe/api/mappings/best_structures/{ac}"
_HTTP_TIMEOUT = 30
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0
_POLITE_DELAY = 0.1  # seconds between ACs — courtesy throttle for the public EBI endpoints


def _http_get(url: str, *, want_json: bool):
    """GET with retry/backoff. Returns (status, payload) where payload is parsed JSON / text / None.
    A 404 is returned as (404, None) — a VALID 'no data' outcome, not retried. Transient errors
    (timeout, 5xx, connection) retry up to _MAX_RETRIES, then return (None, None)."""
    import requests

    last_status = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = requests.get(url, timeout=_HTTP_TIMEOUT)
            last_status = r.status_code
            if r.status_code == 404:
                return 404, None
            if r.status_code == 200:
                return 200, (r.json() if want_json else r.text)
            # 429 / 5xx → retry
        except Exception:  # noqa: BLE001 — network/parse blip → retry
            pass
        time.sleep(_BACKOFF_BASE**attempt)
    return last_status, None


def fetch_alphafold(ac: str) -> dict:
    """AlphaFold summary + per-residue pLDDT (from the model CIF). Returns
    {alphafold_prediction_id, alphafold_model_version, alphafold_plddt_summary_mean, plddt: [...],
     has_alphafold: bool}. Empty/absent model → has_alphafold False, plddt []."""
    status, data = _http_get(AF_PREDICTION_URL.format(ac=ac), want_json=True)
    if status != 200 or not data:
        return {
            "has_alphafold": False,
            "plddt": [],
            "alphafold_prediction_id": None,
            "alphafold_model_version": None,
            "alphafold_plddt_summary_mean": None,
        }
    rec = data[0] if isinstance(data, list) and data else {}
    cif_url = rec.get("cifUrl")
    plddt: list = []
    if cif_url:
        c_status, cif_text = _http_get(cif_url, want_json=False)
        if c_status == 200 and cif_text:
            plddt = compute.parse_cif_plddt(cif_text)  # per-residue; CIF discarded after parse
    return {
        "has_alphafold": True,
        "plddt": plddt,
        "alphafold_prediction_id": rec.get("entryId"),
        "alphafold_model_version": str(rec.get("latestVersion")) if rec.get("latestVersion") is not None else None,
        "alphafold_plddt_summary_mean": rec.get("globalMetricValue"),
    }


def fetch_pdb_entries(ac: str) -> list:
    """PDBe best_structures → [{pdb_id, resolution_angstrom, method}]. 404 / none → []."""
    status, data = _http_get(PDBE_BEST_URL.format(ac=ac), want_json=True)
    if status != 200 or not isinstance(data, dict):
        return []
    recs = data.get(ac) or []
    out = []
    for r in recs:
        if not isinstance(r, dict) or not r.get("pdb_id"):
            continue
        res = r.get("resolution")
        out.append(
            {
                "pdb_id": r.get("pdb_id"),
                "resolution_angstrom": float(res) if isinstance(res, (int, float)) else None,
                "method": r.get("experimental_method") or "unknown",
            }
        )
    return out


def build_ac_row(ac: str, gene_symbol: str, *, domains: list, hotspot_hgvsp: list) -> dict:
    """Fetch AF + PDB for one AC and assemble the derived-parquet row via compute.build_row.
    `domains` (InterPro {start,end}) + `hotspot_hgvsp` (from the MC3 product) are pre-loaded by the caller
    (loaded ONCE across the sweep, not per-AC — the perf discipline). has_structure = has AF or has PDB."""
    af = fetch_alphafold(ac)
    pdb_entries = fetch_pdb_entries(ac)
    has_structure = af["has_alphafold"] or bool(pdb_entries)
    row = compute.build_row(
        ac,
        gene_symbol,
        plddt=af["plddt"],
        domains=domains,
        pdb_entries=pdb_entries,
        hotspot_hgvsp=hotspot_hgvsp,
        alphafold_prediction_id=af["alphafold_prediction_id"],
        alphafold_model_version=af["alphafold_model_version"],
        has_structure=has_structure,
    )
    # Prefer the parsed-CIF mean; fall back to the summary-API mean if the CIF was unreachable.
    if row.get("alphafold_plddt_mean") is None and af.get("alphafold_plddt_summary_mean") is not None:
        row["alphafold_plddt_mean"] = round(float(af["alphafold_plddt_summary_mean"]), 3)
    return row


# ---------------------------------------------------------------------------
# Sweep driver (resumable JSONL checkpoint → parquet)
# ---------------------------------------------------------------------------
def _load_checkpoint(path: Path) -> dict:
    done: dict = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
                if r.get("uniprot_ac"):
                    done[r["uniprot_ac"]] = r
            except json.JSONDecodeError:
                continue
    return done


def run_sweep(
    ac_gene: list,
    *,
    checkpoint: Path,
    domains_by_ac: Optional[dict] = None,
    hotspots_by_gene: Optional[dict] = None,
    limit: Optional[int] = None,
) -> list:
    """Sweep (ac, gene_symbol) pairs → rows, appending to a JSONL checkpoint (resumable). Returns all rows
    (checkpoint + newly fetched). domains_by_ac / hotspots_by_gene are pre-loaded lookups (loaded ONCE)."""
    domains_by_ac = domains_by_ac or {}
    hotspots_by_gene = hotspots_by_gene or {}
    done = _load_checkpoint(checkpoint)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    todo = [(ac, g) for ac, g in ac_gene if ac not in done]
    if limit is not None:
        todo = todo[:limit]
    n = len(todo)
    with checkpoint.open("a") as ck:
        for i, (ac, gene) in enumerate(todo, 1):
            row = build_ac_row(
                ac,
                gene,
                domains=domains_by_ac.get(ac, []),
                hotspot_hgvsp=hotspots_by_gene.get((gene or "").upper(), []),
            )
            ck.write(json.dumps(row, default=str) + "\n")
            ck.flush()
            done[ac] = row
            if i % 250 == 0 or i == n:
                print(f"[structure_pull] {i}/{n} fetched (checkpoint {len(done)} total)", file=sys.stderr)
            time.sleep(_POLITE_DELAY)
    return list(done.values())


def main(argv=None):
    ap = argparse.ArgumentParser(description="PDB+AlphaFold per-UniProt structure-features sweep.")
    ap.add_argument(
        "--ac-list",
        type=Path,
        help="TSV/CSV with columns uniprot_ac,gene_symbol. If omitted, loads the TMbed product's accessions from S3.",
    )
    ap.add_argument("--checkpoint", type=Path, required=True, help="Resumable JSONL checkpoint path.")
    ap.add_argument("--out", type=Path, required=True, help="Output parquet path.")
    ap.add_argument("--limit", type=int, default=None, help="Cap ACs (pilot runs).")
    args = ap.parse_args(argv)

    import pandas as pd

    if args.ac_list:
        acs = pd.read_csv(args.ac_list, sep=None, engine="python")
        ac_gene = list(zip(acs["uniprot_ac"], acs.get("gene_symbol", [""] * len(acs))))
    else:
        ac_gene = _load_ac_substrate()

    domains_by_ac = _load_domains(ac_gene)  # InterPro per-AC (bulk, once)
    hotspots_by_gene = _load_hotspots()  # MC3 4-indication hotspots (bulk, once)
    rows = run_sweep(
        ac_gene,
        checkpoint=args.checkpoint,
        domains_by_ac=domains_by_ac,
        hotspots_by_gene=hotspots_by_gene,
        limit=args.limit,
    )
    df = pd.DataFrame(
        rows,
        columns=[
            "uniprot_ac",
            "gene_symbol",
            "pdb_ids_available",
            "pdb_best_resolution_angstrom",
            "pdb_best_method",
            "alphafold_prediction_id",
            "alphafold_model_version",
            "alphafold_plddt_mean",
            "alphafold_plddt_min",
            "alphafold_plddt_min_domain",
            "n_domains_low_plddt",
            "mutation_hotspot_in_druggable_pocket",
            "hotspot_pocket_adjacency_call",
            "disordered_fraction",
            "method_version",
        ],
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out, index=False)
    print(f"[structure_pull] wrote {len(df)} rows -> {args.out}", file=sys.stderr)


def _load_ac_substrate() -> list:
    """The reviewed-human-SwissProt AC substrate = the TMbed derived product's (accession, gene_symbol)."""
    import os

    os.environ.setdefault("AWS_PROFILE", "cbg")
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    t = pq.read_table(
        "onc-compbio/data-catalog/derived/topology-predictions-tmbed-v1/topology_predictions_tmbed_v1.parquet",
        columns=["accession", "gene_symbol"],
        filesystem=pafs.S3FileSystem(region="us-east-1"),
    )
    d = t.to_pandas()
    return list(zip(d["accession"], d["gene_symbol"].fillna("")))


def _load_domains(ac_gene: list) -> dict:
    """Bulk-load InterPro type=domain {start,end} per AC (ONCE). Falls back to {} on any read issue
    (per-domain pLDDT then simply unavailable — the row still carries whole-protein pLDDT + PDB)."""
    try:
        import os

        os.environ.setdefault("AWS_PROFILE", "cbg")
        import pyarrow.fs as pafs
        import pyarrow.parquet as pq

        # InterPro product key resolved the same way uniprot_protein_features does.
        from onc_methods.uniprot_protein_features.read import INTERPRO_KEY, S3_BUCKET  # type: ignore

        t = pq.read_table(
            f"{S3_BUCKET}/{INTERPRO_KEY}",
            columns=["uniprot_accession", "interpro_type", "start", "end"],
            filters=[("interpro_type", "==", "domain")],
            filesystem=pafs.S3FileSystem(region="us-east-1"),
        )
        d = t.to_pandas()
        out: dict = {}
        for _, r in d.iterrows():
            ac = str(r["uniprot_accession"])
            s, e = r["start"], r["end"]
            if s == s and e == e:  # not NaN
                out.setdefault(ac, []).append({"start": int(s), "end": int(e)})
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[structure_pull] domain load skipped ({exc}); per-domain pLDDT unavailable", file=sys.stderr)
        return {}


# Recurrence floor for a hotspot to count as a druggability signal. The MC3 product is whole-exome
# (any codon), so most hotspot_protein_change rows are passengers / low-recurrence noise — ~19k genes
# carry SOME hotspot, which saturated the pocket call. Requiring hotspot_n_samples >= this
# keeps recurrent oncogenic positions (KRAS G12C n=17, BRAF V600E, etc.) and drops the long tail.
_HOTSPOT_MIN_SAMPLES = 5


def _load_hotspots() -> dict:
    """Bulk-load {GENE -> [HGVSp strings]} of RECURRENT hotspots (hotspot_n_samples >= _HOTSPOT_MIN_SAMPLES)
    from the MC3 product, deduped across indications. Genes with only sub-threshold/passenger variants →
    absent → pocket call `no_hotspots_annotated` (honest). This recurrence filter is half of the
    fix that stops the pocket call from saturating to all-adjacent (the other half is the
    disorder-dominated guard in compute.pocket_adjacency)."""
    try:
        import os

        os.environ.setdefault("AWS_PROFILE", "cbg")
        import pyarrow.fs as pafs
        import pyarrow.parquet as pq

        from onc_methods.gdc_somatic_hotspot import read as hs  # type: ignore

        key = hs._manifest_s3_path(hs._HOTSPOT_FREQUENCY_MANIFEST)  # type: ignore
        if not key:
            return {}
        t = pq.read_table(
            key,
            columns=["gene_symbol", "hotspot_protein_change", "hotspot_n_samples"],
            filesystem=pafs.S3FileSystem(region="us-east-1"),
        )
        d = t.to_pandas().dropna(subset=["hotspot_protein_change"])
        d = d[d["hotspot_n_samples"].fillna(0) >= _HOTSPOT_MIN_SAMPLES]
        out: dict = {}
        for _, r in d.iterrows():
            out.setdefault(str(r["gene_symbol"]).upper(), set()).add(str(r["hotspot_protein_change"]))
        return {g: sorted(v) for g, v in out.items()}
    except Exception as exc:  # noqa: BLE001
        print(
            f"[structure_pull] hotspot load skipped ({exc}); pocket calls will be no_hotspots_annotated",
            file=sys.stderr,
        )
        return {}


if __name__ == "__main__":
    main()
