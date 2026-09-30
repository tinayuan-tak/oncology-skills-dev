"""depmap_cis_protein_dosage.read — library entry point for cis-feature → own-PROTEIN coupling.

Composes TWO live {ModelID -> value} loaders (mirrors depmap_cis_dosage/read.py, swapping the log2TPM
expression loader for the Gygi-MS protein loader):
  - rel. CN         via depmap_cn_distribution.load_cn_files                 ({ModelID -> relative CN}, bridged)
  - log2 protein    via depmap_protein_abundance.load_abundance_column      ({ModelID -> log2 abundance})
then cli.compute_cis_protein_dosage (CN↔protein Spearman). Target-only; `indication` is accepted for the
dispatcher signature but the correlation is PAN-PANEL (a per-indication protein cis-dosage correlation is
rarely powered — few Gygi lines per lineage — so it is deferred; evidence_scope = pan_no_indication).

Gygi-ONLY on purpose: unlike abundance_dependency, this leg does NOT fall back to Olink NPX — Olink is a
different (relative NPX) scale, so mixing platforms would corrupt the CN↔abundance slope the card compares
against the mRNA slope. A target absent from the Gygi MS panel → cis_protein_dosage_class=data_unavailable.

Returns the cis-feature-protein-coherence card's summary_fields, or a dict with _live_read_error +
cis_protein_dosage_class=data_unavailable when the underlying DepMap data is unreachable.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"

from onc_methods.target_id_sidecar import ensure_aws_profile


def read_cis_protein_dosage(target: str, indication: Optional[str] = None, release_pin: str = "26q3") -> dict:
    """Compute protein cis-dosage (own-CN → own-protein) coupling for target across the DepMap panel.

    `indication` is accepted for dispatcher-signature back-compat but NOT consumed (target-only,
    pan-panel correlation). `release_pin` selects the DepMap release for the CN loader.
    Returns the card's summary_fields, or a dict with _live_read_error when data is unreachable.
    """
    ensure_aws_profile()

    from onc_methods.depmap_cn_distribution import cli as cncli

    def _unavailable(
        err: str, errors: list | None = None, remediation: str | None = None, note: str | None = None
    ) -> dict:
        out = {
            "_live_read_error": err,
            "cis_protein_dosage_class": "data_unavailable",
            "evidence_scope": "pan_no_indication",
            "abundance_layer": "protein_gygi_ms",
        }
        if errors:
            out["errors"] = errors
        if remediation:
            out["_remediation"] = remediation
        if note:
            out["_data_note"] = note
        return out

    # 1. Relative CN (bridged ModelConditionID -> ModelID by load_cn_files)
    cn_by_model, cn_meta, assay_used, cn_errs = cncli.load_cn_files(release_pin=release_pin, target_symbol=target)
    if cn_errs or not cn_by_model:
        return _unavailable(
            cn_errs[0].get("_live_read_error", "cn_read_failed") if cn_errs else "no_cn_for_target",
            errors=cn_errs,
            remediation="Method cannot reach DepMap 26Q3 copy number; verify local cache or AWS credentials.",
        )

    # 2. Gygi-MS protein abundance ({ModelID -> log2 abundance}). Symbol -> UniProt accession resolves
    #    UPSTREAM via the source manifest's target_resolution sidecar; resolve_accession raises on schema
    #    drift (surfaced as _live_read_error) and returns None on a genuine symbol-absence.
    sym = target.upper().strip()
    try:
        from onc_methods.depmap_protein_abundance import cli as protcli

        accession = protcli.resolve_accession(sym)
        prot_by_model, panel_size = protcli.load_abundance_column(accession) if accession else (None, 0)
    except Exception as e:  # noqa: BLE001 — returns a populated dict (not empty); honest _live_read_error
        return _unavailable(
            f"protein_load_failed:{type(e).__name__}",
            errors=[{"_live_read_error": str(e)}],
            remediation="Method cannot reach the Gygi MS protein product; verify credentials.",
        )
    if not prot_by_model:
        # Genuine Gygi miss (target undetected in the MS panel) → honest data_unavailable. NO Olink
        # fallback here (different scale would corrupt the CN↔abundance slope).
        return _unavailable(
            "target_absent_from_gygi_ms", note=f"{sym} undetected in the Gygi MS protein panel (n_panel={panel_size})."
        )

    summary = _cli.compute_cis_protein_dosage(cn_by_model, prot_by_model)
    # Pan-panel correlation → the honest scope is pan_no_indication (within-lineage cis-dosage is a
    # later refinement; the cis_coherence resolver does not gate on evidence_scope at Stage 0).
    summary["evidence_scope"] = "pan_no_indication"
    summary["abundance_layer"] = "protein_gygi_ms"
    summary["n_protein_detected_models"] = len(prot_by_model)
    summary["protein_panel_size"] = panel_size
    summary["_cn_assay_used"] = assay_used  # WGS (primary) or WES (fallback), provenance
    # Comparison hook: the mRNA arm lives on cis-feature-expression-coherence; the skill's _headline
    # divides this leg's slope by that leg's cn_expr_slope_log2tpm_per_cn to get the dosage-buffering ratio.
    summary["mrna_arm_card"] = "cis-feature-expression-coherence"
    return summary
