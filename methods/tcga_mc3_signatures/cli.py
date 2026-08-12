#!/usr/bin/env python3
"""tcga_mc3_signatures — per-indication mutational-signature (mutagenic-process) cohort context.

A verdict-INERT, pre-integrated companion facet (tier: indication, entity_grain: cohort): which
mutational PROCESSES shaped an indication's TCGA cohort — APOBEC / MMR-deficiency / HRD / tobacco /
UV / POLE / clock? Sibling to pancanatlas_ddr_context (HRD) and the DepMap model-side MMR signature
arm of genomic_instability_state; this is the PATIENT/tumour arm from TCGA MC3, broadened beyond
MMR/HRD to the full interpretable process set.

Pipeline (all HTTPS/local — routes around the FTP-blocked SigProfiler genome download):
  1. MC3 MAF  --(SBS96 build: trinucleotide context vs Ensembl GRCh37 FASTA)-->  per-sample SBS96
  2. SBS96    --(SigProfilerAssignment.cosmic_fit, COSMIC v3.3 bundled)-->        per-sample activities
  3. activities + TCGA-CDR barcode→type  --(this module: process-class binning + per-cancer rollup)-->
     per-CANCER product (materialized; read grain = pre-aggregated → O(1) skill reads)

Coverage: PAN-CANCER — all 33 TCGA studies (ACC…UVM), via the authoritative PanCanAtlas TCGA-CDR
(Liu 2018, already in the catalog) barcode→cancer-type join (10,216 of 10,294 MC3 samples map).
The product is keyed on the TCGA study code (BRCA/LUAD/…); the reader (read.py) aliases framework
indications → code(s) and pools sample-weighted (COADREAD=COAD+READ, NSCLC=LUAD+LUSC), mirroring
pancanatlas_ddr_context. Indications with no TCGA study (e.g. SCLC) return data_unavailable.

VERDICT-INERT: no resolver rung, no rescue. Surfaces the cohort mutagenic-process prior alongside
the (separate) genomic-alteration verdict; it does NOT itself flip a verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .signatures import SIGNATURE_TO_PROCESS, INFORMATIVE_PROCESSES, NON_BASELINE_PROCESSES

METHOD_VERSION = "0.1.0"

# A sample is "process-high" if that process is a MAJOR contributor (>= this fraction of its assigned
# mutations). 0.30 (not a trace 0.10): per-sample refit against the full COSMIC catalog spreads
# low-level activity across correlated signatures, so a trace threshold mislabels most samples. A
# process is called active only when it dominates a meaningful share — validated against known biology
# (NSCLC→tobacco 60%, CRC/GC MMR ~12-16% MSI subset, PDAC MMR ~0).
PROCESS_HIGH_FRAC = 0.30
# Hypermutation gate: MMR-deficiency and POLE are HYPERMUTATOR phenotypes (MSI/POLE tumours carry
# thousands of mutations). A low-burden tumour CANNOT be MMR/POLE-driven — without this gate the
# unstable low-burden refit spuriously calls e.g. PDAC (median ~50 SNVs) "MMR-dominant". Require an
# elevated SNV burden before either process can be called high. ~300 exonic SNVs ≈ the MSI/hypermutator
# floor for MC3's exome-scale MAF.
HYPERMUTATION_PROCESSES = {"mmr_deficiency", "pole"}
HYPERMUTATOR_MIN_BURDEN = 300
# Cohort class cuts on the fraction of samples that are process-high (mirrors ddr_context cut ladder).
ENRICHED_FRAC = 0.30
INTERMEDIATE_FRAC = 0.10
MIN_COHORT_N = 15   # below → data_unavailable (underpowered cohort)

# Barcode → TCGA study code (BRCA/LUAD/GBM/…) via the PanCanAtlas TCGA-CDR (Liu 2018), which is
# already in the catalog. Authoritative per-patient cancer type — covers all 33 TCGA studies (10,216
# of 10,294 MC3 samples map), so the product is PAN-CANCER keyed on the TCGA study code (mirroring
# pancanatlas_ddr_context, whose reader aliases framework indications → codes + pools sample-weighted).
_CLINICAL_MANIFEST_ID = "gdc-pancanatlas-clinical-2018"
_CDR_FILENAME = "TCGA-CDR-SupplementalTableS1.xlsx"


def _classify(n: int, frac_high: float) -> str:
    if n < MIN_COHORT_N:
        return "data_unavailable"
    if frac_high >= ENRICHED_FRAC:
        return "enriched"
    if frac_high >= INTERMEDIATE_FRAC:
        return "intermediate"
    return "rare"


def _load_barcode_to_type() -> dict:
    """Load the TCGA-CDR per-patient cancer-type map (3-segment patient barcode → TCGA study code).
    Resolves the source S3 prefix from the catalog manifest (no hand-typed path that can drift)."""
    import io
    import subprocess
    import pandas as pd
    from methods.catalog_query.read import s3_uri_for

    uri = s3_uri_for(_CLINICAL_MANIFEST_ID).rstrip("/") + "/" + _CDR_FILENAME
    raw = subprocess.run(["aws", "s3", "cp", uri, "-"], capture_output=True, timeout=180).stdout
    if not raw:
        raise RuntimeError(f"could not load {_CDR_FILENAME} from {uri}")
    cdr = pd.read_excel(io.BytesIO(raw))
    return dict(zip(cdr["bcr_patient_barcode"].astype(str), cdr["type"].astype(str)))


def _sample_to_cancer(sample: str, bc2type: dict):
    """TCGA sample/aliquot barcode → TCGA study code, via the 3-segment patient barcode + CDR map."""
    patient = "-".join(sample.split("-")[:3])
    t = bc2type.get(patient)
    return t if t and t != "nan" else None


def build_per_indication_table(activities_path: str, indmap_path: str | None = None):
    """BUILD-time aggregation. `activities_path` = SigProfilerAssignment Activities.txt
    (rows = samples, cols = SBS signatures). Returns a per-indication DataFrame."""
    import numpy as np
    import pandas as pd

    bc2type = _load_barcode_to_type()
    act = pd.read_csv(activities_path, sep="\t", index_col=0)
    act.index = [str(s) for s in act.index]
    burden = act.sum(axis=1)                        # per-sample total assigned SNV burden (for the gate)
    # per-sample relative contribution of each PROCESS (sum of its signatures / total burden)
    proc_cols = {}
    for proc in INFORMATIVE_PROCESSES:
        sigs = [s for s, p in SIGNATURE_TO_PROCESS.items() if p == proc and s in act.columns]
        proc_cols[proc] = act[sigs].sum(axis=1) if sigs else pd.Series(0, index=act.index)
    rel = pd.DataFrame(proc_cols).div(burden.replace(0, np.nan), axis=0).fillna(0.0)
    # per-sample process-high boolean: major contributor, AND (for hypermutation processes) hypermutator
    high = pd.DataFrame(index=rel.index)
    for pr in INFORMATIVE_PROCESSES:
        h = rel[pr] >= PROCESS_HIGH_FRAC
        if pr in HYPERMUTATION_PROCESSES:
            h = h & (burden >= HYPERMUTATOR_MIN_BURDEN)
        high[pr] = h
    high["indication"] = [_sample_to_cancer(s, bc2type) for s in high.index]  # TCGA study code
    rel_ind = rel.copy(); rel_ind["indication"] = high["indication"]
    high = high[high["indication"].notna()]
    rel_ind = rel_ind[rel_ind["indication"].notna()]

    rows = []
    for ind, g in high.groupby("indication"):
        n = int(len(g))
        gm = rel_ind[rel_ind["indication"] == ind]
        rec = {"indication": str(ind), "n_samples": n}
        frac = {}
        for pr in INFORMATIVE_PROCESSES:
            frac[pr] = float(g[pr].mean())
            rec[f"frac_{pr}_high"] = round(frac[pr], 4)
            rec[f"{pr}_class"] = _classify(n, frac[pr])
            rec[f"mean_{pr}_contribution"] = round(float(gm[pr].mean()), 4)
        enriched = [p for p in NON_BASELINE_PROCESSES if rec[f"{p}_class"] == "enriched"]
        rec["enriched_processes"] = ",".join(enriched) if enriched else "none"
        # dominant = non-baseline process with the highest gated process-high fraction, if that
        # fraction clears the intermediate floor (else the cohort has no dominant non-baseline process)
        nb = {p: frac[p] for p in NON_BASELINE_PROCESSES}
        top = max(nb, key=nb.get) if nb else None
        rec["dominant_process"] = top if (top and nb[top] >= INTERMEDIATE_FRAC) else "no_dominant_process"
        rows.append(rec)
    return pd.DataFrame(rows).sort_values("indication").reset_index(drop=True)


try:
    import click

    @click.command()
    @click.option("--activities", required=True, type=click.Path(exists=True, path_type=Path),
                  help="SigProfilerAssignment Activities.txt (samples × SBS signatures).")
    @click.option("--out", required=True, type=click.Path(path_type=Path),
                  help="Output parquet path for the per-indication signature-context product.")
    def main(activities, out):
        """Build the per-indication mutational-signature context product (materialized rollup)."""
        tbl = build_per_indication_table(str(activities))
        out.parent.mkdir(parents=True, exist_ok=True)
        tbl.to_parquet(out, index=False)
        click.echo(f"wrote {len(tbl)} indications -> {out}")
        click.echo(tbl[["indication", "n_samples", "dominant_process",
                        "enriched_processes"]].to_string(index=False))

    if __name__ == "__main__":
        main()
except ImportError:  # pragma: no cover
    pass
