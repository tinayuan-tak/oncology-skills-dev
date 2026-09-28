"""Genomic-alteration / functional-state / phospho figure emitters.

Part of the _skills_common figure-emitter package (rehomed off the retired compose-dashboard, #654) (Stage-4 split of the monolith).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — type hints (stringized by future-annotations)

from ._common import (  # shared emitter helpers/constants
    TARGET_CONTRACTS,
    _ensure_methods_path,
    _has_live_read_error,
)

# Local cache for downloaded aggregates (non-SageMaker environments)
_LOCAL_AGGREGATE_CACHE = Path.home() / ".cache" / "framework-genomic-aggregates"


def _download_from_s3_if_missing(local_path: Path, s3_key: str, description: str) -> Path:
    """Generic S3 download helper. Returns local_path if exists or after download, None on failure."""
    if local_path.exists():
        return local_path

    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        import boto3
        s3 = boto3.client("s3")
        bucket = "onc-compbio"

        print(f"  Downloading {description}...", flush=True)
        s3.download_file(bucket, s3_key, str(local_path))
        print(f"  Cached to {local_path}", flush=True)
        return local_path
    except Exception as e:
        print(f"  Failed to download {description}: {e}", flush=True)
        return None


def _download_hotspot_aggregate_if_missing(indication: str) -> Path:
    """Download MC3 hotspot aggregate from S3 if not available locally."""
    local_path = _LOCAL_AGGREGATE_CACHE / "gdc_hotspots" / "hotspot_frequency.parquet"
    s3_key = "data-catalog/derived/tcga-mc3-hotspot-frequency-v1/hotspot_frequency.parquet"
    return _download_from_s3_if_missing(local_path, s3_key, "MC3 hotspot aggregate (~28MB)")


def _download_fusion_aggregate_if_missing() -> Path:
    """Download TCGA fusion consensus aggregate from S3 if not available locally."""
    local_path = _LOCAL_AGGREGATE_CACHE / "tcga_fusion" / "fusion_consensus_per_sample_gene.parquet"
    s3_key = "data-catalog/derived/tcga-fusion-consensus-v1/fusion_consensus_per_sample_gene.parquet"
    return _download_from_s3_if_missing(local_path, s3_key, "TCGA fusion consensus (~1MB)")


def _download_splice_aggregate_if_missing() -> Path:
    """Download TCGA SpliceSeq PSI aggregate from S3 if not available locally."""
    local_path = _LOCAL_AGGREGATE_CACHE / "tcga_splice" / "tcga_spliceseq_psi.parquet"
    s3_key = "data-catalog/derived/tcga-spliceseq-psi-per-gene-v1/tcga_spliceseq_psi.parquet"
    return _download_from_s3_if_missing(local_path, s3_key, "TCGA SpliceSeq PSI (~5MB)")


def _download_patient_cn_aggregate_if_missing() -> Path:
    """Download TCGA patient CN aggregate from S3 if not available locally."""
    local_path = _LOCAL_AGGREGATE_CACHE / "tcga_patient_cn" / "patient_cn_per_gene.parquet"
    s3_key = "data-catalog/derived/tcga-patient-cn-per-gene-v1/patient_cn_per_gene.parquet"
    return _download_from_s3_if_missing(local_path, s3_key, "TCGA patient CN (~3MB)")


def _emit_mutation_hotspot_frequency(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the mutation hotspot frequency figures (pie, stacked, lollipop): MC3 somatic
    mutation frequency with hotspot breakdown. Gated on having hotspot data
    (data_unavailable / no mutations → []). On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    # Check for hotspot data - the card has hotspot_frequencies, not mutation_class
    hotspots = summary.get("hotspot_frequencies") or []
    if not hotspots and summary.get("overall_mutation_frequency") is None:
        return []
    _ensure_methods_path()

    # Check for plot_data.parquet (offline rendering path)
    pd_path = out_dir / "plot_data.parquet"
    if pd_path.exists():
        try:
            from methods.gdc_somatic_hotspot.figures import render_from_plot_data

            return render_from_plot_data(pd_path, summary, out_dir, target, indication)
        except Exception:
            pass  # fall through to legacy

    # Legacy live path (no plot_data persisted)
    from methods.gdc_somatic_hotspot import cli as hotspot_cli

    out_dir.mkdir(parents=True, exist_ok=True)
    figures = []

    # Emit lollipop if hotspot data exists
    hotspots = summary.get("hotspot_frequencies") or []
    if hotspots:
        svg = hotspot_cli.emit_hotspot_lollipop(
            hotspots, target, indication, out_dir, TARGET_CONTRACTS
        )
        if svg:
            figures.append({
                "id": "hotspot_lollipop",
                "path": "figure_hotspot_lollipop.svg",
                "type": "mutation_hotspot_lollipop",
                "primary": True,
            })

    # Try to emit pie and stacked figures by loading context data from MC3 aggregate
    try:
        import pyarrow.parquet as pq

        # First try SageMaker path
        aggregate_path = Path("/home/sagemaker-user/data-products-cache/gdc_hotspots") / f"{indication.lower()}_mc3_hotspots.parquet"

        # If SageMaker path doesn't exist, try to download from S3 to local cache
        if not aggregate_path.exists():
            aggregate_path = _download_hotspot_aggregate_if_missing(indication)

        if aggregate_path and aggregate_path.exists():
            # Read INDICATION-SPECIFIC gene frequencies
            table_ind = pq.read_table(
                aggregate_path,
                filters=[("indication", "=", indication)],
                columns=["gene_symbol", "overall_mutation_frequency", "hotspot_protein_change"],
            )

            # Read PAN-CANCER gene frequencies (no indication filter)
            table_pan = pq.read_table(
                aggregate_path,
                columns=["gene_symbol", "overall_mutation_frequency", "hotspot_protein_change", "indication"],
            )

            if table_ind is not None and table_ind.num_rows > 0:
                df_ind = table_ind.to_pandas()
                # Gene-summary rows have null hotspot_protein_change
                gene_summary_ind = df_ind[df_ind["hotspot_protein_change"].isnull()]
                ind_genes = [
                    (row["gene_symbol"], row["overall_mutation_frequency"])
                    for _, row in gene_summary_ind.iterrows()
                    if row["overall_mutation_frequency"] is not None and row["overall_mutation_frequency"] > 0
                ]
                ind_genes.sort(key=lambda x: x[1], reverse=True)

                # Compute pan-cancer frequencies (aggregate across all indications)
                pan_genes = ind_genes  # Default fallback
                if table_pan is not None and table_pan.num_rows > 0:
                    df_pan = table_pan.to_pandas()
                    gene_summary_pan = df_pan[df_pan["hotspot_protein_change"].isnull()]
                    # Average frequency across indications for each gene
                    pan_freq_by_gene = gene_summary_pan.groupby("gene_symbol")["overall_mutation_frequency"].mean()
                    pan_genes = [
                        (gene, freq) for gene, freq in pan_freq_by_gene.items()
                        if freq is not None and freq > 0
                    ]
                    pan_genes.sort(key=lambda x: x[1], reverse=True)

                if ind_genes:
                    ind_freq = summary.get("overall_mutation_frequency", 0)
                    # Look up target's pan-cancer frequency from the computed pan_genes list
                    pan_freq = None
                    for gene, freq in pan_genes:
                        if gene == target:
                            pan_freq = freq
                            break
                    if pan_freq is None:
                        pan_freq = summary.get("pancancer_mutation_frequency", 0) or 0

                    # Limit to 85 genes max to prevent label crowding
                    ind_genes_limited = ind_genes[:85]
                    pan_genes_limited = pan_genes[:85]

                    # Emit pie chart
                    svg = hotspot_cli.emit_mutation_frequency_pie(
                        target, indication, ind_freq, ind_genes_limited, pan_freq, pan_genes_limited,
                        out_dir, TARGET_CONTRACTS
                    )
                    if svg:
                        figures.append({
                            "id": "mutation_frequency_pie",
                            "path": "figure_mutation_frequency_pie.svg",
                            "type": "mutation_frequency_pie",
                            "primary": False,
                        })

                    # Emit stacked bar
                    svg = hotspot_cli.emit_mutation_frequency_stacked(
                        target, indication, ind_freq, ind_genes_limited, pan_freq, pan_genes_limited,
                        out_dir, TARGET_CONTRACTS
                    )
                    if svg:
                        figures.append({
                            "id": "mutation_frequency_stacked",
                            "path": "figure_mutation_frequency_stacked.svg",
                            "type": "mutation_frequency_stacked",
                            "primary": False,
                        })
    except Exception:
        pass  # pie/stacked are additive; failure doesn't break the card

    return figures


def _emit_fusion_rearrangement_landscape(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the fusion rearrangement landscape figures (pie, stacked): TCGA fusion
    frequency with context. Gated on having fusion data (data_unavailable → []).
    On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    # Check for fusion data - field is fusion_class or target_fusion_frequency
    fusion_class = summary.get("fusion_class")
    fusion_freq = summary.get("target_fusion_frequency")
    if fusion_class in (None, "data_unavailable") and fusion_freq is None:
        return []
    _ensure_methods_path()

    figures = []
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check for plot_data_fusion.parquet (offline rendering path)
    pd_path = out_dir / "plot_data_fusion.parquet"
    if pd_path.exists():
        try:
            from methods.tcga_fusion_consensus.figures import render_from_plot_data

            return render_from_plot_data(pd_path, summary, out_dir, target, indication)
        except Exception:
            pass  # fall through to legacy

    # Legacy path: load from aggregate and emit figures
    try:
        import pyarrow.parquet as pq
        from methods.tcga_fusion_consensus.figures import (
            emit_fusion_frequency_pie,
            emit_fusion_frequency_stacked,
        )

        # Load OncoKB driver genes for filtering (oncogenes for fusions - typically the activated partner)
        try:
            from methods.driver_role_overlay.read import _load_oncokb_roles
            roles = _load_oncokb_roles()
            driver_genes = {gene for gene, role in roles.items() if role in ("ONCOGENE", "TSG", "BOTH")}
        except Exception:
            driver_genes = set()

        # Try SageMaker path first, then download
        aggregate_path = Path("/home/sagemaker-user/data-products-cache/tcga_fusion/fusion_consensus_per_sample_gene.parquet")
        if not aggregate_path.exists():
            aggregate_path = _download_fusion_aggregate_if_missing()

        if aggregate_path and aggregate_path.exists():
            # Read fusion data - columns are: sample_key, gene_symbol, tissue, caller_count
            # Map indication to tissue values (tissue column has TCGA codes like COAD, READ, COADREAD)
            tissue_values = _indication_to_tcga_studies(indication)
            # Also check if indication itself is in the tissue column (e.g., COADREAD)
            tissue_values = list(set(tissue_values + [indication.upper()]))

            # Read INDICATION-SPECIFIC data
            table_ind = pq.read_table(
                aggregate_path,
                filters=[("tissue", "in", tissue_values)],
                columns=["gene_symbol", "sample_key"],
            )

            # Read PAN-CANCER data (all tissues)
            table_pan = pq.read_table(
                aggregate_path,
                columns=["gene_symbol", "sample_key"],
            )

            if table_ind is not None and table_ind.num_rows > 0:
                df_ind = table_ind.to_pandas()
                # Compute per-gene fusion frequency for indication, filtered to driver genes
                total_samples_ind = df_ind["sample_key"].nunique()
                gene_counts_ind = df_ind.groupby("gene_symbol")["sample_key"].nunique()
                ind_genes = [(gene, count / total_samples_ind) for gene, count in gene_counts_ind.items()
                             if count > 0 and (gene in driver_genes or gene == target)]
                ind_genes.sort(key=lambda x: x[1], reverse=True)

                # Compute pan-cancer frequencies, filtered to driver genes
                pan_genes = ind_genes  # Default fallback
                if table_pan is not None and table_pan.num_rows > 0:
                    df_pan = table_pan.to_pandas()
                    total_samples_pan = df_pan["sample_key"].nunique()
                    gene_counts_pan = df_pan.groupby("gene_symbol")["sample_key"].nunique()
                    pan_genes = [(gene, count / total_samples_pan) for gene, count in gene_counts_pan.items()
                                 if count > 0 and (gene in driver_genes or gene == target)]
                    pan_genes.sort(key=lambda x: x[1], reverse=True)

                if ind_genes:
                    target_freq_ind = summary.get("target_fusion_frequency", 0) or 0
                    # Look up target's pan-cancer frequency from computed pan_genes
                    target_freq_pan = None
                    for gene, freq in pan_genes:
                        if gene == target:
                            target_freq_pan = freq
                            break
                    if target_freq_pan is None:
                        target_freq_pan = 0
                    n_samples = summary.get("n_samples_indication", total_samples_ind)
                    n_assayed = summary.get("n_assayed_indication", total_samples_ind)

                    # Limit to 85 genes max to prevent label crowding
                    ind_genes_limited = ind_genes[:85]
                    pan_genes_limited = pan_genes[:85]

                    # Emit pie chart
                    svg = emit_fusion_frequency_pie(
                        target, indication, target_freq_ind, n_samples, n_assayed, ind_genes_limited,
                        target_freq_pan, total_samples_pan if table_pan else n_samples, total_samples_pan if table_pan else n_assayed, pan_genes_limited,
                        out_dir, TARGET_CONTRACTS
                    )
                    if svg:
                        figures.append({
                            "id": "fusion_frequency_pie",
                            "path": "figure_fusion_frequency_pie.svg",
                            "type": "fusion_frequency_pie",
                            "primary": True,
                        })

                    # Emit stacked bar
                    svg = emit_fusion_frequency_stacked(
                        target, indication, target_freq_ind, ind_genes_limited,
                        target_freq_pan, pan_genes_limited,
                        out_dir, TARGET_CONTRACTS
                    )
                    if svg:
                        figures.append({
                            "id": "fusion_frequency_stacked",
                            "path": "figure_fusion_frequency_stacked.svg",
                            "type": "fusion_frequency_stacked",
                            "primary": False,
                        })
    except Exception:
        pass  # fusion figures are additive

    return figures


def _indication_to_tcga_studies(indication: str) -> list:
    """Map indication code to TCGA study codes."""
    mapping = {
        "COADREAD": ["COAD", "READ"],
        "COAD": ["COAD"],
        "READ": ["READ"],
        "LUAD": ["LUAD"],
        "LUSC": ["LUSC"],
        "NSCLC": ["LUAD", "LUSC"],
        "BRCA": ["BRCA"],
        "PAAD": ["PAAD"],
        "PDAC": ["PAAD"],
        "SKCM": ["SKCM"],
        "MELANOMA": ["SKCM"],
        "STAD": ["STAD"],
        "GC": ["STAD"],
        "PRAD": ["PRAD"],
        "OV": ["OV"],
        "KIRC": ["KIRC"],
        "GBM": ["GBM"],
        "LGG": ["LGG"],
        "HNSC": ["HNSC"],
        "BLCA": ["BLCA"],
        "LIHC": ["LIHC"],
        "UCEC": ["UCEC"],
        "LAML": ["LAML"],
    }
    return mapping.get(indication.upper(), [indication.upper()])


def _emit_tumor_splice_dysregulation(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the tumor splice dysregulation figures (pie, stacked): TCGA SpliceSeq PSI
    variability. Gated on having splicing data (data_unavailable → []).
    On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    # Check for splice data - field is splicing_dysregulation_class or max_event_psi_std
    splice_class = summary.get("splicing_dysregulation_class")
    psi_std = summary.get("max_event_psi_std")
    if splice_class in (None, "data_unavailable") and psi_std is None:
        return []
    _ensure_methods_path()

    figures = []
    out_dir.mkdir(parents=True, exist_ok=True)

    # Check for plot_data_splicing.parquet (offline rendering path)
    pd_path = out_dir / "plot_data_splicing.parquet"
    if pd_path.exists():
        try:
            from methods.tcga_spliceseq_psi.figures import render_from_plot_data

            return render_from_plot_data(pd_path, summary, out_dir, target, indication)
        except Exception:
            pass  # fall through to legacy

    # Legacy path: load from aggregate and emit figures
    try:
        import pyarrow.parquet as pq
        from methods.tcga_spliceseq_psi.figures import (
            emit_splicing_variability_pie,
            emit_splicing_variability_stacked,
        )

        # Load OncoKB driver genes for filtering (both oncogenes and TSGs for splice)
        try:
            from methods.driver_role_overlay.read import _load_oncokb_roles
            roles = _load_oncokb_roles()
            driver_genes = {gene for gene, role in roles.items() if role in ("ONCOGENE", "TSG", "BOTH")}
        except Exception:
            driver_genes = set()

        # Try SageMaker path first, then download
        aggregate_path = Path("/home/sagemaker-user/data-products-cache/tcga_splice/tcga_spliceseq_psi.parquet")
        if not aggregate_path.exists():
            aggregate_path = _download_splice_aggregate_if_missing()

        if aggregate_path and aggregate_path.exists():
            # Read INDICATION-SPECIFIC splice variability
            # Column is 'indication', values are like 'COADREAD', 'BRCA', etc.
            table_ind = pq.read_table(
                aggregate_path,
                filters=[("indication", "=", indication.upper())],
                columns=["gene_symbol", "max_event_psi_std", "n_variable_events", "n_splice_events"],
            )

            # Read PAN-CANCER splice variability (all indications)
            table_pan = pq.read_table(
                aggregate_path,
                columns=["gene_symbol", "max_event_psi_std", "n_variable_events", "n_splice_events"],
            )

            if table_ind is not None and table_ind.num_rows > 0:
                df_ind = table_ind.to_pandas()
                # Get per-gene max PSI std for indication, filtered to driver genes
                gene_var_ind = df_ind.groupby("gene_symbol")["max_event_psi_std"].max()
                ind_genes = [(gene, var) for gene, var in gene_var_ind.items()
                             if var is not None and var > 0 and (gene in driver_genes or gene == target)]
                ind_genes.sort(key=lambda x: x[1], reverse=True)

                # Compute pan-cancer gene variabilities, filtered to driver genes
                pan_genes = ind_genes  # Default fallback
                if table_pan is not None and table_pan.num_rows > 0:
                    df_pan = table_pan.to_pandas()
                    gene_var_pan = df_pan.groupby("gene_symbol")["max_event_psi_std"].max()
                    pan_genes = [(gene, var) for gene, var in gene_var_pan.items()
                                 if var is not None and var > 0 and (gene in driver_genes or gene == target)]
                    pan_genes.sort(key=lambda x: x[1], reverse=True)

                if ind_genes:
                    target_psi_std_ind = summary.get("max_event_psi_std") or summary.get("target_psi_std_indication", 0)
                    # Look up target's pan-cancer PSI std from computed pan_genes
                    target_psi_std_pan = None
                    for gene, var in pan_genes:
                        if gene == target:
                            target_psi_std_pan = var
                            break
                    if target_psi_std_pan is None:
                        target_psi_std_pan = 0
                    n_var_ind = summary.get("n_variable_events") or summary.get("n_variable_events_indication", 0)
                    n_splice_ind = summary.get("n_splice_events") or summary.get("n_splice_events_indication", 0)

                    # Limit to 85 genes max to prevent label crowding
                    ind_genes_limited = ind_genes[:85]
                    pan_genes_limited = pan_genes[:85]

                    # Emit pie chart
                    svg = emit_splicing_variability_pie(
                        target, indication, target_psi_std_ind, n_var_ind, n_splice_ind, ind_genes_limited,
                        target_psi_std_pan, n_var_ind, n_splice_ind, pan_genes_limited,
                        out_dir, TARGET_CONTRACTS
                    )
                    if svg:
                        figures.append({
                            "id": "splicing_variability_pie",
                            "path": "figure_splicing_variability_pie.svg",
                            "type": "splicing_variability_pie",
                            "primary": True,
                        })

                    # Emit stacked bar
                    svg = emit_splicing_variability_stacked(
                        target, indication, target_psi_std_ind, ind_genes_limited,
                        target_psi_std_pan, pan_genes_limited,
                        out_dir, TARGET_CONTRACTS
                    )
                    if svg:
                        figures.append({
                            "id": "splicing_variability_stacked",
                            "path": "figure_splicing_variability_stacked.svg",
                            "type": "splicing_variability_stacked",
                            "primary": False,
                        })
    except Exception:
        pass  # splice figures are additive

    return figures


def _emit_alteration_role(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the alteration-role evidence card (typed driver classification): the role call +
    the OncoKB/IntOGen evidence it rests on. Gated on alteration_role (data_unavailable → []).
    On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("alteration_role") in (None, "data_unavailable"):
        return []
    _ensure_methods_path()
    from onc_methods.driver_role_overlay import cli as dro

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = dro.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "alteration_role_evidence_card",
            "path": "figure_alteration_role.svg",
            "type": "alteration_role_evidence_card",
            "primary": True,
        },
    ]


def _emit_functional_gene_state(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the functional-gene-state figure (M6): per-arm STACKED composition of the two-hit
    states (patient vs model — wt / monoallelic / biallelic-genetic / uncertain). Gated on the
    presence of at least one arm's state distribution (both data_unavailable → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    # both arms must be structured-absent for the figure to be skipped; else there is a bar to draw.
    patient = summary.get("patient") or {}
    model = summary.get("model") or {}
    if not (patient.get("state_counts") or model.get("state_counts")):
        return []
    _ensure_methods_path()
    from onc_methods.functional_gene_state import cli as fgs

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = fgs.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "functional_gene_state_stacked_bar",
            "path": "figure_functional_gene_state.svg",
            "type": "functional_gene_state_stacked_bar",
            "primary": True,
        },
    ]


def _emit_genomic_event_model_match(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the genomic-event-model-match figure (M11): the tumor event being matched + the
    correspondence class + top genotype-matched models. Gated on having matched models with a real
    correspondence class (data_unavailable / no_target_event with no models → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("event_correspondence_class")
    matched = summary.get("matched_models") or []
    if cls in (None, "data_unavailable", "no_target_event") and not matched:
        return []
    _ensure_methods_path()
    from onc_methods.genomic_event_model_match import cli as gemm

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = gemm.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "genomic_event_model_match_card",
            "path": "figure_genomic_event_model_match.svg",
            "type": "genomic_event_model_match_card",
            "primary": True,
        },
    ]


def _emit_abundance_dependency(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the abundance-dependency figure (Q7): protein-abundance→dependency class + correlation
    stats. Gated on a computed correlation (data_unavailable / insufficient / no-r → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("abundance_dependency_class")
    if (
        cls in (None, "data_unavailable", "insufficient_paired_models")
        or summary.get("protein_dependency_pearson_r") is None
    ):
        return []
    _ensure_methods_path()
    from onc_methods.abundance_dependency import cli as ad

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = ad.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "abundance_dependency_card",
            "path": "figure_abundance_dependency.svg",
            "type": "abundance_dependency_card",
            "primary": True,
        },
    ]


def _emit_phospho_pathway_activity(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the phospho-pathway-activity figure (Q8): activity class + top phosphosites. Gated on the
    target having detected phosphosites (phospho_not_detected / data_unavailable → nothing to plot → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("phospho_activity_class")
    if cls in (None, "data_unavailable", "phospho_not_detected"):
        return []
    _ensure_methods_path()
    from onc_methods.phospho_pathway_activity import cli as ppa

    out_dir.mkdir(parents=True, exist_ok=True)
    svg = ppa.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {
            "id": "phospho_pathway_activity_card",
            "path": "figure_phospho_pathway_activity.svg",
            "type": "phospho_pathway_activity_card",
            "primary": True,
        },
    ]
