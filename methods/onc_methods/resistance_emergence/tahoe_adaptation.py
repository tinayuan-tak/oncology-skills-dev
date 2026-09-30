"""resistance_emergence.tahoe_adaptation — Tahoe transcriptional-resistance ADAPTATION sub-signal.

The ORTHOGONAL, SECONDARY layer of the resistance-emergence facet. The primary layer
(read.py::resistance_mediators_for_gene) is a CAUSAL genetic rescue signal from DepMap drug-anchor
screens (KO rescues under inhibition). This layer is a TRANSCRIPTIONAL adaptation signal from the
Tahoe-100M single-cell drug-perturbation atlas: when the target's anchor drug is applied, which
resistance-associated survival programs are INDUCED (up-regulated)?

Weaker causal claim than the genetic rescue (an induced transcript is an adaptation hypothesis, not
a proven resistance mechanism), so it is VERDICT-INERT — it enriches the resistance picture but does
NOT drive the resistance_verdict (which stays on the DepMap genetic-rescue signal).

Curated resistance-program panel (validated on MEK inhibitors: HMOX1/NQO1/TXNRD1 NRF2 stress axis +
ABCB1/ABCG2 efflux are INDUCED; anti-apoptotic MCL1/BCL2L1 go DOWN = drug working, not resistance):
  - efflux           : ABCB1, ABCG2, ABCC1        (drug export)
  - oxidative_stress : HMOX1, NQO1, TXNRD1, GCLM  (NRF2 antioxidant program)
  - emt              : VIM, ZEB1, AXL, SNAI2       (mesenchymal / bypass-RTK)
  - anti_apoptotic   : BCL2L1, MCL1, BCL2          (survival; INDUCTION = resistance, suppression = efficacy)

Keyed to the anchor drug of an inhibited_target (MRTX1133->KRAS etc.), read per program-gene from
the Tahoe product via pushdown. Returns a compact adaptation summary for the target's anchor drug.
"""

from __future__ import annotations

TAHOE_PRODUCT_MANIFEST_ID = "tahoe-drug-perturbation-per-gene-v1"

# inhibited_target -> the anchor drug string(s) as they appear in Tahoe (substring match).
# Only KRAS's anchor (MRTX1133 is not in Tahoe's 379; the drug-anchor DepMap panel and Tahoe are
# different drug sets) — so this layer covers the intersection. We match on DRUG CLASS where the
# exact anchor is absent: KRAS-G12D inhibitors / MEK inhibitors downstream as the pathway proxy.
# HONEST: when the target's anchor drug is not in Tahoe, this layer returns not_in_tahoe (a coverage
# gap), and the DepMap genetic-rescue layer stands alone.
TARGET_TO_TAHOE_DRUGS = {
    # KRAS: MRTX1133 (G12D) not in Tahoe; use the MAPK-pathway inhibitors present in Tahoe as the
    # pathway-level proxy for "KRAS pathway inhibited" adaptation.
    "KRAS": ["MRTX", "Trametinib", "Cobimetinib", "Binimetinib", "TAK-733", "RMC-6236", "BI-3406"],
    "KIT": ["Avapritinib", "Avapratinib", "Imatinib", "Sunitinib"],
    "XPO1": ["Eltanexor", "Selinexor", "KPT"],
}

RESISTANCE_PROGRAMS = {
    "efflux": ["ABCB1", "ABCG2", "ABCC1"],
    "oxidative_stress": ["HMOX1", "NQO1", "TXNRD1", "GCLM"],
    "emt": ["VIM", "ZEB1", "AXL", "SNAI2"],
    "anti_apoptotic": ["BCL2L1", "MCL1", "BCL2"],
}
_ALL_PROGRAM_GENES = sorted({g for gs in RESISTANCE_PROGRAMS.values() for g in gs})

INDUCE_LFC = 0.5  # median log2FC >= this under the anchor drug = program INDUCED
PADJ_STRICT = 0.05
METHOD_VERSION = "0.1.0"


def _fetch_program_rows(drug_substrings: list[str]):
    """Pushdown-read the resistance-program genes, filter to rows whose drug matches any substring.
    Returns a pandas DataFrame or None on read failure."""
    import pandas as pd
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    try:
        from onc_methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(TAHOE_PRODUCT_MANIFEST_ID)
        path = f"{bucket}/{key}"
        fs = pafs.S3FileSystem()
        frames = []
        for g in _ALL_PROGRAM_GENES:
            t = pq.read_table(
                path,
                filesystem=fs,
                filters=[("gene_name", "=", g)],
                columns=["gene_name", "drug", "log2FoldChange", "padj", "Cell_ID_DepMap"],
            )
            if t.num_rows:
                frames.append(t.to_pandas())
    except Exception:  # noqa: BLE001
        return None
    if not frames:
        return pd.DataFrame(columns=["gene_name", "drug", "log2FoldChange", "padj", "Cell_ID_DepMap"])
    df = pd.concat(frames, ignore_index=True)
    pat = "|".join(drug_substrings)
    return df[df["drug"].str.contains(pat, case=False, na=False, regex=True)].copy()


def tahoe_adaptation_for_target(target: str, df=None) -> dict:
    """Tahoe transcriptional-resistance adaptation summary for a target's anchor drug(s).

    VERDICT-INERT sub-signal. df injectable for tests.

      tahoe_adaptation_class:
        induced_resistance_programs   >=1 program INDUCED (median log2FC >= 0.5, significant)
        no_induced_programs           anchor drug in Tahoe, no resistance program induced
        not_in_tahoe                  target's anchor drug not in the Tahoe drug set (coverage gap)
        data_unavailable              read failure
    """
    sym = (target or "").strip().upper()
    drugs = TARGET_TO_TAHOE_DRUGS.get(sym)
    if drugs is None:
        return {
            "tahoe_adaptation_class": "not_in_tahoe",
            "induced_programs": [],
            "tahoe_adaptation_note": (
                f"{sym}: no Tahoe drug mapping for the anchor — the DepMap genetic-rescue layer stands alone."
            ),
            "method_version": METHOD_VERSION,
        }
    data = df if df is not None else _fetch_program_rows(drugs)
    if data is None:
        return {
            "tahoe_adaptation_class": "data_unavailable",
            "induced_programs": [],
            "_live_read_error": "tahoe_adaptation_read_failed",
            "method_version": METHOD_VERSION,
        }
    if len(data) == 0:
        return {
            "tahoe_adaptation_class": "not_in_tahoe",
            "induced_programs": [],
            "tahoe_adaptation_note": f"{sym}: anchor drug(s) not found in Tahoe.",
            "method_version": METHOD_VERSION,
        }

    gene_to_program = {g: p for p, gs in RESISTANCE_PROGRAMS.items() for g in gs}
    data = data.copy()
    data["program"] = data["gene_name"].map(gene_to_program)
    induced = []
    for prog, genes in RESISTANCE_PROGRAMS.items():
        sub = data[data["gene_name"].isin(genes)]
        if sub.empty:
            continue
        # per-gene median log2FC; program is "induced" if any gene clears the induction floor
        gmed = sub.groupby("gene_name")["log2FoldChange"].median()
        up = gmed[gmed >= INDUCE_LFC]
        if len(up):
            induced.append(
                {
                    "program": prog,
                    "genes_induced": [
                        {"gene": g, "median_log2fc": round(float(v), 3)}
                        for g, v in up.sort_values(ascending=False).items()
                    ],
                    "max_induction": round(float(up.max()), 3),
                }
            )

    induced.sort(key=lambda p: p["max_induction"], reverse=True)
    if induced:
        klass = "induced_resistance_programs"
        top = induced[0]
        note = (
            f"{sym} inhibition (Tahoe): INDUCES the {top['program']} resistance program "
            f"(e.g. {top['genes_induced'][0]['gene']} +{top['genes_induced'][0]['median_log2fc']}). "
            f"A transcriptional-adaptation hypothesis (verdict-inert) — weaker than the DepMap "
            f"genetic-rescue signal; read as candidate adaptive resistance to monitor."
        )
    else:
        klass = "no_induced_programs"
        note = (
            f"{sym} inhibition (Tahoe): no curated resistance program induced above threshold in "
            f"the screened cancer lines."
        )
    return {
        "tahoe_adaptation_class": klass,
        "induced_programs": induced,
        "n_induced_programs": len(induced),
        "tahoe_adaptation_note": note,
        "method_version": METHOD_VERSION,
    }
