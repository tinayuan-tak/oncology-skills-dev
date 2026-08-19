#!/usr/bin/env python3
"""generate_example_gallery.py — a SIMPLE example-output gallery for collaborators.

Runs a list of focused subskills and renders, for each (subskill, target, indication):
  - the deterministic verdict + per-card summaries + tables (from decision.json), and
  - the card FIGURES (via the existing emit_figures_for_card seam),
into ONE self-contained static HTML page, plus an index.html linking them all.

WHY this exists (and why NOT compose-dashboard): the focused subskills emit decision.json +
summary.yaml + tables/ but NO figures (write_package only globs an empty figures/ dir). The
figure emitters live behind compose-dashboard's heavy compose→execute→synthesize orchestration
(dashboard_spec + data_mode + schema-validation gates + evidence_package envelope). But the
emitter entry point, emit_figures_for_card(card_id, summary, out_root, target, indication), is a
STANDALONE function needing only the per-card summary dict already in decision.json. So this
generator: subprocess-runs each subskill → calls emit_figures_for_card per card → renders HTML.
No envelope, no spec, no schemas, no Bedrock.

FIGURES: static SVG inlined by default (portable — opens anywhere incl. VS Code Simple Browser,
email-friendly). --interactive embeds the .plotly.json interactive twins + inlines plotly.js
(~4.6MB/file, real browser only).

Usage:
  AWS_PROFILE=cbg python generate_example_gallery.py --config examples.yaml --out ~/dev/example-gallery
  AWS_PROFILE=cbg python generate_example_gallery.py --config examples.yaml --out DIR --interactive
  # one-off single row without a config file:
  AWS_PROFILE=cbg python generate_example_gallery.py --skill tumor-presence --target CEACAM5 \
      --indication COADREAD --out DIR
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Which skills/ tree to run the subskills FROM. Defaults to this generator's own repo, but is
# env-overridable (SKILLS_ROOT) so the gallery can render against a DIFFERENT checkout — e.g. the
# merged v2-architecture trunk — without rebasing the gallery branch onto it. Figure emitters are
# resolved from the SAME tree so their card coverage matches the run.
SKILLS_DIR = Path(os.environ.get("SKILLS_ROOT", str(Path(__file__).resolve().parents[2])))  # skills/
FIGURE_EMITTERS_DIR = SKILLS_DIR / "compose-dashboard" / "scripts"

# target-contracts (sibling repo) — for the per-card provenance chain (method/measurement/inputs).
# env-overridable; falls back to the standard sibling checkout.
TARGET_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    str(Path.home() / "rnd-computational-biology-oncology-target-contracts")))


# ---------------------------------------------------------------------------
# card metadata (the provenance-chain front-end: data → method → measurement)
# ---------------------------------------------------------------------------
_CARD_META_CACHE: Optional[dict] = None


def _card_meta() -> dict:
    """card_id -> {question, measurement_type, methods[], required_inputs[], sample_context, measurement,
    tier} from the target-contracts card YAMLs. Indexed by the YAML's own card_id (filename != id for
    some). `sample_context`/`measurement`/`tier` back the scope-hierarchical presence layout (they are
    the same tags run.py's CARD_CONTEXT mirrors); `tier` (target/indication/subtype) maps to the
    pan-cancer/indication/subtype scope rung. Empty {} if the repo is absent — the flow tabs then
    degrade to what's derivable from the run alone, and the presence layout falls back to its static map."""
    global _CARD_META_CACHE
    if _CARD_META_CACHE is not None:
        return _CARD_META_CACHE
    meta: dict = {}
    cards_dir = TARGET_CONTRACTS / "cards"
    if cards_dir.is_dir():
        try:
            import yaml
            import glob as _glob
            for f in _glob.glob(str(cards_dir / "*.yaml")):
                try:
                    d = yaml.safe_load(Path(f).read_text())
                except Exception:  # noqa: BLE001
                    continue
                cid = d.get("card_id")
                if not cid:
                    continue
                meta[cid] = {
                    "question": d.get("question"),
                    "measurement_type": d.get("measurement_type") or d.get("measurement"),
                    "methods": [m.get("call") for m in (d.get("methods") or []) if m.get("call")],
                    "required_inputs": [x.get("product_id") or x.get("card_id")
                                        for x in (d.get("required_inputs") or [])],
                    "sample_context": d.get("sample_context"),
                    "measurement": d.get("measurement") or d.get("measurement_type"),
                    "tier": d.get("tier"),
                }
        except Exception:  # noqa: BLE001
            pass
    _CARD_META_CACHE = meta
    return meta


# ---------------------------------------------------------------------------
# figure emission (reuse the existing standalone seam)
# ---------------------------------------------------------------------------
def _load_emit_figures_for_card():
    """Import emit_figures_for_card from compose-dashboard WITHOUT its orchestration."""
    if str(FIGURE_EMITTERS_DIR) not in sys.path:
        sys.path.insert(0, str(FIGURE_EMITTERS_DIR))
    try:
        from _figure_emitters import emit_figures_for_card  # noqa: E402
        return emit_figures_for_card
    except Exception as e:  # noqa: BLE001 — figures are best-effort; gallery still renders text
        print(f"[gallery] figure emitters unavailable ({type(e).__name__}: {e}); "
              f"pages will show summaries + tables only", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# SVG inlining (adapted from target-profile/scripts/run.py:_inline_svg — kept local to avoid
# importing that 3700-line, Bedrock-dependent module)
# ---------------------------------------------------------------------------
def _inline_svg(svg_path: Path) -> Optional[str]:
    """Return an emitted matplotlib SVG's <svg>...</svg> body for inline embedding, with the fixed
    pt width/height stripped so it scales to the card (viewBox preserves aspect). None on failure."""
    try:
        raw = Path(svg_path).read_text()
        i = raw.find("<svg")
        if i < 0:
            return None
        body = raw[i:]
        end = body.find(">")
        head, rest = body[:end], body[end:]
        head = re.sub(r'\s(width|height)="[^"]*"', "", head)
        return head + rest
    except Exception:  # noqa: BLE001
        return None


def _plotly_bundle() -> Optional[str]:
    """plotly.js source for inlining (--interactive). ~4.6MB; None if plotly absent."""
    try:
        from plotly.offline import get_plotlyjs
        return get_plotlyjs()
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# run a subskill (subprocess — isolates each run, no in-process import coupling)
# ---------------------------------------------------------------------------
def run_subskill(skill: str, target: str, indication: Optional[str], run_dir: Path,
                 synthesize: bool = False, figures: bool = True) -> Optional[dict]:
    """Invoke skills/<skill>/scripts/run.py --target ... [--indication ...] --out <run_dir>.
    With synthesize=True, adds --synthesize so decision.json carries the LLM relevance narrative
    (needs Bedrock; the subskill degrades gracefully to a note if unavailable). Returns the parsed
    decision.json, or None on failure."""
    run_py = SKILLS_DIR / skill / "scripts" / "run.py"
    if not run_py.exists():
        print(f"[gallery] {skill}: run.py not found at {run_py}", file=sys.stderr)
        return None
    cmd = [sys.executable, str(run_py), "--target", target, "--out", str(run_dir)]
    if indication:
        cmd += ["--indication", indication]
    if figures:
        # Emit the per-card figures + plot_data INSIDE the run (figure Stage 3): migrated cards render
        # OFFLINE from persisted plot_data, and the gallery embeds this ONE package (no second live
        # re-plot). Best-effort — a skill that doesn't accept --figures is retried without it.
        cmd += ["--figures"]
    if synthesize:
        cmd += ["--synthesize"]
    print(f"[gallery] running: {skill} {target}" + (f"/{indication}" if indication else ""),
          file=sys.stderr)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    except subprocess.CalledProcessError as e:
        # Not every subskill takes --synthesize / --figures (e.g. genomic-alteration-profile uses a
        # custom main(), not the shared dispatcher). Treat both as best-effort: retry without.
        if synthesize and "--synthesize" in (e.stderr or ""):
            print(f"[gallery] {skill} rejects --synthesize; retrying without it", file=sys.stderr)
            return run_subskill(skill, target, indication, run_dir, synthesize=False, figures=figures)
        if figures and "--figures" in (e.stderr or ""):
            print(f"[gallery] {skill} rejects --figures; retrying without it", file=sys.stderr)
            return run_subskill(skill, target, indication, run_dir, synthesize=synthesize, figures=False)
        print(f"[gallery] {skill} run failed (exit {e.returncode}): {e.stderr[-500:]}", file=sys.stderr)
        return None
    except subprocess.TimeoutExpired:
        print(f"[gallery] {skill} run timed out", file=sys.stderr)
        return None
    dec = run_dir / "decision.json"
    if not dec.exists():
        print(f"[gallery] {skill}: no decision.json produced", file=sys.stderr)
        return None
    return json.loads(dec.read_text())


# ---------------------------------------------------------------------------
# Display curation — make cards DIGESTIBLE, not a raw field dump.
#
# Each card renders as: a human TITLE + a one-line HEADLINE (its primary *_class field) + 3-5
# curated KEY METRICS (prettified labels), with the full field dump + raw CSVs behind a collapsed
# <details>. CARD_DISPLAY gives colleague-quality curation for the showcase cards; any card NOT
# listed falls back to a heuristic (first *_class field = headline, first few scalars = metrics).
# ---------------------------------------------------------------------------
# card_id -> {title, headline (field), metrics [(field,label)]}
CARD_DISPLAY = {
    "cellline-rna-distribution": {
        "title": "Cell-line RNA distribution", "headline": "expression_class",
        # pan-cancer DepMap panel by design (no single indication) → provenance = panel size / lineages
        "metrics": [("median_log2tpm_panel", "Median log2TPM"), ("allgene_percentile", "All-gene %ile"),
                    ("fraction_expressed", "Fraction expressed"), ("control_position_class", "vs controls"),
                    ("n_cell_lines_evaluated", "n cell lines"), ("n_lineages_evaluated", "n lineages")]},
    "tumor-rna-vs-adjacent": {
        # PRESENCE view = the ADJACENT-normal DEG contrast (cell A) that drives the call. The GTEx
        # (population-normal, cell C) metrics are DISPLAY-ONLY and are population-normal SELECTIVITY —
        # owned by tumor-selectivity — so they are dropped from the presence curated view (rendered once
        # as a labeled reference in the normal-comparator band). Verdict-inert: no rule keys on gtex_*.
        "title": "Tumor vs adjacent-normal RNA (DEG)", "headline": "expression_call_class",
        "metrics": [("log2_fc", "log2FC vs adjacent"), ("q_value", "q vs adjacent"),
                    ("n_tumor", "n tumor"), ("n_adjacent", "n adjacent")]},
    "tumor-protein-abundance-cptac": {
        "title": "Tumor protein abundance (CPTAC)", "headline": "protein_expression_class",
        "metrics": [("protein_effect_size", "Effect size (T vs N)"), ("protein_bh_q_value", "q-value"),
                    ("cohort", "Cohort"), ("n_tumor_samples", "n tumor")]},
    "cellline-protein-abundance": {
        "title": "Cell-line protein abundance (DepMap MS)", "headline": "protein_expression_class",
        "metrics": [("median_log2_abundance_panel", "Median log2 abundance"),
                    ("fraction_detected", "Fraction detected"), ("n_cell_lines_evaluated", "n cell lines")]},
    "tumor-elevation-breadth": {
        "title": "Pan-cancer tumor-elevation breadth", "headline": "tumor_elevation_breadth_class",
        "metrics": [("n_cohorts_elevated", "Cohorts elevated"), ("n_cohorts_tested", "Cohorts tested"),
                    ("most_elevated_cohorts", "Most elevated")]},
    "tumor-rna-distribution": {
        # PRESENCE view = the per-sample tumor distribution. The GTEx normal band (matched_normal_tissue /
        # n_normal_samples) is a population-normal reference (selectivity framing) → dropped from the
        # presence metrics and rendered once in the normal-comparator band. Verdict-inert.
        "title": "Tumor RNA distribution (per-sample)", "headline": "tumor_expression_class",
        "metrics": [("median_log2tpm", "Median log2TPM"), ("allgene_percentile", "All-gene %ile"),
                    ("control_position_class", "vs controls"),
                    ("n_tumor_samples", "n tumor (TCGA)"), ("studies", "TCGA studies")]},
    "tumor-rna-distribution-by-subtype": {
        # headline = the subtype VERDICT (pan_subtype_uniform / subtype_enriched / …), not the
        # effect-size adjective — that's the field the framework's subgroup-analysis constraint fires on.
        "title": "RNA by molecular subtype", "headline": "subtype_stratification_class",
        "metrics": [("subtype_effect_size_class", "Effect size (ε²)"),
                    ("subtype_variance_explained", "Variance explained (ε²)"),
                    ("subtype_omnibus_p", "Kruskal–Wallis p"),
                    ("n_subtypes_measured", "Subtypes measured"),
                    ("which_subtypes_separate", "High / low")]},
    "expression-purity-confound": {
        "title": "Tumor-purity confound", "headline": "purity_confound_class",
        "metrics": [("expression_purity_pearson_r", "Purity Pearson r"), ("median_purity", "Median purity")]},
    "cellline-rna-protein-concordance": {
        "title": "RNA-vs-protein concordance", "headline": "rna_as_biomarker",
        "metrics": [("rna_protein_r", "RNA-protein r"), ("n_paired_models", "n paired models")]},
    "tumor-scrna-celltype-expression": {
        "title": "Single-cell per-compartment presence", "headline": "sc_expression_class",
        # provenance FIRST so it's clear the read is indication-specific (atlas + donor/dataset counts)
        "metrics": [("indication", "Indication"), ("product_id", "Atlas"),
                    ("malignant_n_donors", "Malignant donors"), ("n_datasets", "Datasets"),
                    ("n_donor_groups", "Donor groups"),
                    ("malignant_detection_fraction", "Malignant detection"),
                    ("top_microenvironment_compartment", "Top microenv. compartment"),
                    ("n_compartments_measured", "Compartments measured")]},
    "normal-tissue-liability": {
        "title": "Normal-tissue expression liability", "headline": "normal_tissue_breadth_class",
        "metrics": [("n_specific_tissues", "Specific tissues"),
                    ("n_essential_tissues_with_expression", "Essential tissues w/ expr"),
                    ("hpa_tissue_specificity", "HPA specificity")]},
    "target-identity-summary": {
        "title": "Target identity", "headline": "resolution_status",
        "metrics": [("resolved_hgnc_symbol", "HGNC"), ("resolved_uniprot_canonical", "UniProt"),
                    ("resolved_ensembl_id", "Ensembl")]},
    "protein-domains-class": {
        "title": "Protein domains & class", "headline": "protein_features_class",
        "metrics": [("domain_evidence", "Domain evidence"), ("domain_architecture", "Curated domains"),
                    ("interpro_domain_architecture", "InterPro domains"), ("protein_class_primary", "Class")]},
    "ppi-interactome": {
        "title": "Protein-protein interactome", "headline": "interactome_class",
        "metrics": [("n_high_confidence_interactors", "STRING HC partners"),
                    ("n_corum_complexes", "CORUM complexes"),
                    ("physical_interactome_class", "BioGRID physical"),
                    ("n_physical_interactors", "Physical partners")]},
    "signaling-network-mechanism": {
        "title": "Signaling network & MoA", "headline": "network_class",
        "metrics": [("n_upstream_regulators", "Upstream regulators"),
                    ("n_downstream_effectors", "Downstream effectors"), ("moa_classes_present", "MoA classes")]},
    "phospho-pathway-activity": {
        "title": "Phospho pathway activity", "headline": "phospho_activity_class",
        "metrics": [("n_phosphosites", "Phosphosites"), ("max_site_detection_fraction", "Top-site detection"),
                    ("phospho_exceeds_abundance", "Exceeds abundance")]},
    # ── functional-requirement (dependency) cards. Curated so the claim×scope layout renders good
    #    metrics; the *dep_control_* fields carry the INVERTED window semantics (near pan-essential
    #    ceiling = broad-tox liability, NOT a win), surfaced on the CRISPR card.
    "pan-cancer-crispr-dependency-distribution": {
        "title": "CRISPR dependency (pan-cancer)", "headline": "dependency_class",
        "metrics": [("median_chronos_panel", "Median Chronos"),
                    ("fraction_strongly_dependent", "Frac strongly dependent"),
                    ("selectivity_index", "Selectivity index"),
                    ("dep_control_position_class", "vs controls (window)"),
                    ("dep_control_position", "Control position"),
                    ("n_cell_lines_evaluated", "n cell lines")]},
    "pan-cancer-rnai-dependency-distribution": {
        "title": "RNAi dependency (pan-cancer)", "headline": "rnai_dependency_class",
        "metrics": [("rnai_median_dep_score", "Median dep score"),
                    ("rnai_fraction_strongly_dependent", "Frac strongly dependent"),
                    ("rnai_selectivity_index", "Selectivity index"),
                    ("rnai_n_cell_lines_evaluated", "n cell lines")]},
    "crispr-rnai-dependency-concordance": {
        "title": "CRISPR ↔ RNAi concordance", "headline": "concordance_class",
        "metrics": [("fraction_agree", "Fraction agree"),
                    ("fraction_dependent_in_both", "Dependent in both"),
                    ("n_in_both", "n in both assays")]},
    "dependency-lineage-selectivity": {
        "title": "Lineage selectivity", "headline": "enrichment_class",
        # Axis-3 omnibus (ε²) + which lineages separate; the per-lineage table is a BREAKDOWN_PANEL
        "metrics": [("n_enriched_lineages", "Enriched lineages"),
                    ("lineage_omnibus_effect_size_class", "Omnibus effect (ε²)"),
                    ("lineage_variance_explained", "Variance explained (ε²)"),
                    ("median_chronos_panel", "Median Chronos (panel)"),
                    ("n_lineages_evaluated", "n lineages")]},
    "paralog-buffering": {
        "title": "Paralog buffering", "headline": "paralog_buffering_class",
        "metrics": [("strongest_paralog_symbol", "Strongest paralog"),
                    ("strongest_paralog_delta", "Buffer Δ (dual-KO)"),
                    ("n_paralogs_functionally_buffering", "Functional paralogs")]},
    "partner-conditional-dependency": {
        "title": "Partner-conditional (synthetic-lethal)", "headline": "partner_stratification_class",
        "metrics": [("partner", "Partner gene"), ("deficiency_type", "Deficiency"),
                    ("delta_chronos_deficient_vs_neutral", "Δ Chronos (def vs neutral)"),
                    ("partner_stratification_mannwhitney_q", "q (stratification)"),
                    ("n_partner_deficient", "n partner-deficient")]},
    "prism-crispr-concordance": {
        "title": "Chemical-genetic confirmation (PRISM)", "headline": "crispr_prism_concordance_class",
        "metrics": [("best_spearman_r_crispr", "Best r (CRISPR)"),
                    ("best_spearman_r_rnai", "Best r (RNAi)"),
                    ("n_dual_responders", "Dual responders"),
                    ("n_compounds_evaluated", "n compounds")]},
    "cross-consortium-dependency": {
        "title": "Cross-consortium (Broad ↔ Sanger)", "headline": "cross_consortium_class",
        "metrics": [("broad_frac_dependent", "Broad frac dependent"),
                    ("sanger_frac_dependent", "Sanger frac dependent"),
                    ("broad_median_chronos", "Broad median Chronos"),
                    ("sanger_median_chronos", "Sanger median Chronos")]},
    "dependency-predictability": {
        "title": "Omics-predictability of the dependency", "headline": "predictability_class",
        "metrics": [("pred_dominant_feature_class", "Dominant feature"),
                    ("pearson_r_squared_rf", "R² (RF)"),
                    ("pred_n_cell_lines_evaluated", "n cell lines")]},
    "expression-dependency-correlation": {
        "title": "mRNA ↔ dependency (biomarker)", "headline": "correlation_class",
        "metrics": [("pearson_r", "Pearson r"),
                    ("delta_chronos_top_vs_bottom_quartile", "Δ Chronos (hi vs lo expr)"),
                    ("n_cell_lines_evaluated", "n cell lines")]},
    "abundance-dependency": {
        "title": "Protein abundance ↔ dependency (biomarker)", "headline": "abundance_dependency_class",
        "metrics": [("protein_dependency_pearson_r", "Pearson r"),
                    ("abundance_layer", "Proteomics layer"),
                    ("n_paired_models", "n paired models")]},
    "recommended-models": {
        "title": "Patient ↔ model correspondence", "headline": "correspondence_class",
        "metrics": [("n_positive_models_in_lineage", "Positive models in lineage"),
                    ("n_positive_models", "Positive models"),
                    ("depmap_lineage", "DepMap lineage")]},
    "organoid-crispr-dependency": {
        "title": "Organoid-native dependency", "headline": "organoid_dependency_class",
        "metrics": [("median_gene_effect", "Median gene effect"),
                    ("frac_strongly_dependent", "Frac strongly dependent"),
                    ("n_models_screened", "n organoid models")]},
    "subgroup-stratified-dependency": {
        # headline = the descriptive panorama pattern; per-stratum table is a BREAKDOWN_PANEL
        "title": "Dependency by molecular subgroup", "headline": "subtype_dependency_pattern",
        "metrics": [("cross_subgroup_delta_dependency", "Cross-subgroup Δ"),
                    ("n_subgroups_with_data", "Subgroups w/ data"),
                    ("max_subgroup_dependency", "Max subgroup dep"),
                    ("min_subgroup_dependency", "Min subgroup dep")]},
}

# class value -> chip color category (good/neutral/weak/unavailable) for the at-a-glance strip.
_POS = {"broadly_high", "strongly_upregulated", "lineage_restricted", "strongly_supports", "hub",
        "phospho_active", "above_all_positives", "broad", "broadly_tumor_elevated", "physical_hub",
        "well_characterized", "modest_up", "multi_domain", "supports",
        # a target that separates BY subtype (enriched/restricted in some strata) is the informative case
        "subtype_enriched", "subtype_restricted", "subtype_differential",
        # ── dependency (functional-requirement). The therapeutic-WINDOW wins are green; note the
        #    INVERSION — common_essential (pan-essential) is NOT here (it is a broad-tox liability →
        #    neutral). strongly_selective is the sought-after selective dependency.
        "strongly_selective", "strongly_concordant_dependent", "moderately_concordant_dependent",
        "lineage_selective", "partner_conditional_strongly_dependent",
        "partner_conditional_moderately_dependent", "triangulated_target_engaged",
        "crispr_confirmed_engagement", "concordant_dependent", "own_omics_driven",
        "strong_negative", "protein_predicts_dependency", "well_modeled_in_lineage",
        "selective_organoid_dependency", "between_controls",
        "subgroup_specific_dependency"}
_WEAK = {"not_informative", "no_curated_domain", "data_unavailable", "not_phosphoprotein",
         "no_high_confidence_interactors", "neutral_uninformative", "argues_against", "sparse",
         "not_tumor_elevated", "ns", "subtype_axis_unavailable", "no_subtype_axis",
         # depleted = an UNfavorable deviation from pooled; muted so it reads distinct from uniform
         # (neutral) yet not as the sought-after enriched/restricted signal (good/green)
         "subtype_depleted",
         # ── dependency: absent / uninformative / off-target reads (muted)
         "non_dependent", "non_dependent_underpowered", "common_essential_underpowered",
         "no_lineage_enrichment", "not_partner_stratified", "no_partner_mapped",
         "insufficient_partner_deficient_rate", "discordant", "discordant_off_target_likely",
         "thin_evidence", "no_protein_dependency_link", "insufficient_paired_models",
         "poorly_modeled", "not_organoid_dependent", "rare_organoid_dependency",
         "no_correlation", "positive_anomaly", "unpredictable", "no_paralog",
         "not_informative"}


# Some cards carry a per-stratum BREAKDOWN (a list-of-dicts in the summary — e.g. one row per
# molecular subtype). By default the summary table collapses these to "<list, N items>" and the raw
# CSV is buried in the drill-down. A BREAKDOWN_PANELS entry promotes the breakdown into the VISIBLE
# card body as a compact, curated table (chosen columns, per-row signal chip). This is what makes
# the subgroup analysis legible — the framework treats subgroup stratification as a hard constraint.
#   field   : the summary key holding the list-of-dicts
#   label   : the per-row identity column (shown first, bolded)
#   signal  : per-row column whose value colors the row's chip (via _chip_kind); "" = no chip
#   columns : [(row_key, display_label)] to show, in order
BREAKDOWN_PANELS = {
    "tumor-rna-distribution-by-subtype": {
        "title": "Per-subtype expression", "field": "per_subgroup_metrics",
        "label": "stratum_id", "signal": "subtype_signal",
        "columns": [("n_tumor_samples", "n"), ("median_log2tpm", "Median log2TPM"),
                    ("tumor_expression_class", "Class"),
                    ("fraction_tumor_above_normal_p95", "Frac > normal p95"),
                    ("subtype_signal", "Subtype signal")]},
    # dependency — the enriched-lineage hits (the SEL scope rung: which lineages carry the dependency)
    "dependency-lineage-selectivity": {
        "title": "Enriched lineages (dependency)", "field": "enriched_lineages",
        "label": "lineage", "signal": "",
        "columns": [("n", "n lines"), ("median_chronos", "Median Chronos"),
                    ("effect_size", "Effect size"), ("q_value", "q-value"),
                    ("delta_vs_rest", "Δ vs rest")]},
    # dependency — the per-molecular-subgroup panorama (only present on the --subtypes path); the
    # signal column is the per-stratum dependency class, and evidence_state guards underpowered strata.
    "subgroup-stratified-dependency": {
        "title": "Per-subgroup dependency", "field": "per_subgroup_metrics",
        "label": "stratum", "signal": "class",
        "columns": [("subgroup_n", "n"), ("median_chronos", "Median Chronos"),
                    ("class", "Class"), ("evidence_state", "Power")]},
}


def _prettify(key: str) -> str:
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(key)).replace("_", " ").strip()
    return k[:1].upper() + k[1:]


def _fmt_val(v):
    if isinstance(v, float):
        return f"{v:.3g}"
    if isinstance(v, dict):
        return ", ".join(f"{k}: {vv}" for k, vv in list(v.items())[:3])
    if isinstance(v, list):
        return ", ".join(str(x) for x in v[:4]) + ("…" if len(v) > 4 else "")
    return v


def _headline_field(cid: str, summary: dict) -> Optional[str]:
    """Which summary field is the card's one-line takeaway."""
    spec = CARD_DISPLAY.get(cid)
    if spec is not None:
        return spec.get("headline")
    # heuristic: first *_class / *_call scalar (skip boolean provider-call flags)
    for k, v in summary.items():
        if k.startswith("_"):
            continue
        if (k.endswith("_class") or (k.endswith("_call") and not isinstance(v, bool))) and \
                not isinstance(v, (dict, list)):
            return k
    return None


def _chip_kind(val) -> str:
    s = str(val).lower()
    if s in _WEAK or "unavailable" in s or s in ("none", "false", "—", ""):
        return "weak"
    if s in _POS:
        return "good"
    return "neutral"


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
_CSS = """
body{font:14px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f6f7f9;color:#1a1f26}
.wrap{max-width:960px;margin:0 auto;padding:24px}
h1{font-size:23px;margin:0 0 2px}
.sub{color:#667;margin:0 0 14px;font-size:13px}
.verdict{display:inline-block;padding:4px 11px;border-radius:6px;background:#1e3a8a;color:#fff;font-weight:600}
.synth{background:#fff;border:1px solid #e3e6ea;border-left:3px solid #1e3a8a;border-radius:8px;padding:12px 15px;margin:14px 0}
.hero{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:10px;margin:6px 0 14px;overflow-x:auto}
.hero .herofig svg{max-width:100%;height:auto;display:block;margin:0 auto}
.synth .lab{color:#556;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
.synth p{margin:5px 0}
.lab{color:#556;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}
.hint{color:#99a;font-weight:400;text-transform:none;letter-spacing:0;font-size:11px}
/* the unified card list (the "evidence at a glance" table IS this collapsible list) */
.cardlist{border:1px solid #e3e6ea;border-radius:8px;overflow:hidden;background:#fff}
.cardlist .card{border:none;border-top:1px solid #eef0f3;border-radius:0;margin:0}
.cardlist .card:first-child{border-top:none}
/* chips */
.chip{display:inline-block;padding:2px 9px;border-radius:20px;font-size:12px;font-weight:600}
.chip.good{background:#dcfce7;color:#166534} .chip.neutral{background:#eef2ff;color:#3730a3}
.chip.weak{background:#f3f4f6;color:#6b7280}
/* collapsible cards — the card itself is a <details>; header (summary) shows title + chip */
.card{background:#fff;border:1px solid #e3e6ea;border-radius:8px;margin:10px 0;overflow:hidden}
.cardhead{cursor:pointer;list-style:none;display:flex;justify-content:space-between;align-items:center;
  padding:12px 16px;font-size:15px;font-weight:600;user-select:none}
.cardhead::-webkit-details-marker{display:none}
.cardhead::before{content:"\\25b8";color:#889;font-weight:400;margin-right:8px;transition:transform .15s}
details[open]>.cardhead::before{transform:rotate(90deg)}
.cardhead:hover{background:#fafbfc} .ctitle{flex:1}
.cardbody{padding:2px 16px 16px 34px;border-top:1px solid #f0f2f5}
.metrics{display:flex;flex-wrap:wrap;gap:8px 24px;margin:12px 0}
.metric{font-size:13px} .metric .ml{color:#667;font-size:11px;display:block} .metric .mv{font-weight:600}
/* figures — shrunk inline (SVG is vector, stays crisp); click to enlarge */
.figwrap{margin:12px 0} .fig{display:inline-block;margin:0 8px 8px 0;cursor:zoom-in;
  border:1px solid #eef0f3;border-radius:5px;padding:4px;background:#fff;width:380px}
/* EXPLICIT width (not just max-width): the inlined matplotlib SVG has a viewBox but no width/height
   attr (stripped so it scales) — with only max-width many browsers render it at 0×0. width + auto
   height lets the viewBox aspect ratio drive the size. */
.fig svg{width:100%;height:auto;display:block}
.fig.zoomed{position:fixed;inset:4vh 4vw;z-index:50;width:auto;background:#fff;cursor:zoom-out;
  box-shadow:0 8px 40px rgba(0,0,0,.35);overflow:auto;padding:16px}
.fig.zoomed svg{width:92vw;height:auto}
.zbackdrop{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:49;display:none}
.zbackdrop.on{display:block}
/* flow tabs — CSS-only radio tabs: all radios first, one label BAR, one panels container.
   .tabin:nth-of-type(k):checked ~ .tabpanels > .tabpanel:nth-child(k) shows the matching panel. */
.flowtabs{margin:14px 0 8px;border:1px solid #e8ebef;border-radius:6px;overflow:hidden}
.flowtabs .tabin{position:absolute;opacity:0;pointer-events:none}
.tabbar{display:flex;flex-wrap:wrap;background:#f5f6f8;border-bottom:1px solid #e8ebef}
.tablabel{padding:7px 14px;font-size:12px;color:#556;cursor:pointer;border-right:1px solid #e8ebef}
.tablabel:hover{background:#eef1f4}
.tabpanels > .tabpanel{display:none;padding:11px 14px;font-size:12.5px}
/* active label highlight + which panel shows, per checked radio (5 tabs) */
.flowtabs .tabin:nth-of-type(1):checked ~ .tabbar .tablabel:nth-child(1),
.flowtabs .tabin:nth-of-type(2):checked ~ .tabbar .tablabel:nth-child(2),
.flowtabs .tabin:nth-of-type(3):checked ~ .tabbar .tablabel:nth-child(3),
.flowtabs .tabin:nth-of-type(4):checked ~ .tabbar .tablabel:nth-child(4),
.flowtabs .tabin:nth-of-type(5):checked ~ .tabbar .tablabel:nth-child(5){
  background:#fff;color:#111;font-weight:600;box-shadow:inset 0 -2px 0 #1e3a8a}
.flowtabs .tabin:nth-of-type(1):checked ~ .tabpanels > .tabpanel:nth-child(1),
.flowtabs .tabin:nth-of-type(2):checked ~ .tabpanels > .tabpanel:nth-child(2),
.flowtabs .tabin:nth-of-type(3):checked ~ .tabpanels > .tabpanel:nth-child(3),
.flowtabs .tabin:nth-of-type(4):checked ~ .tabpanels > .tabpanel:nth-child(4),
.flowtabs .tabin:nth-of-type(5):checked ~ .tabpanels > .tabpanel:nth-child(5){display:block}
.tabrow{display:flex;gap:12px;padding:3px 0;border-top:1px solid #f4f5f7}
.tabrow:first-child{border-top:none} .tabrow .tk{color:#667;min-width:130px;flex-shrink:0}
.tabempty{color:#889;font-style:italic} .muted{color:#889}
/* full-field drill-down (nested details) */
details.card details{margin:8px 0 0} details.card summary:not(.cardhead){cursor:pointer;color:#2554c7;font-size:12.5px}
.kv{border-collapse:collapse;font-size:12px;margin:8px 0} .kv td{border:1px solid #e8ebef;padding:3px 8px;vertical-align:top}
.kv td:first-child{color:#667;white-space:nowrap}
table{border-collapse:collapse;font-size:12px;margin:8px 0} th,td{border:1px solid #e8ebef;padding:3px 8px;text-align:left;vertical-align:top} th{background:#f5f6f8}
.cardmeta{color:#889;font-size:11px;margin:8px 0 2px}
/* promoted per-stratum breakdown (e.g. per-subtype) — compact, chip in the signal column */
.breakdown{font-size:12px;margin:4px 0 10px} .breakdown td,.breakdown th{padding:3px 9px}
.breakdown tbody tr:nth-child(even){background:#fafbfc} .breakdown .chip{font-size:11px;padding:1px 7px}
.unavail{color:#8a5a2b;background:#fdf6ec;border-radius:6px;padding:7px 11px;font-size:13px;margin:10px 0}
.idx td a{color:#2554c7;text-decoration:none} .idx td a:hover{text-decoration:underline}
.plotly-fig{margin:12px 0}
/* leading 7-question summary table CSS is shared (QUESTION_TABLE_CSS, emitted inline by
   render_question_table_html) so the gallery + target-profile render identically. */
/* the detailed scope layout, demoted to a drill-down */
.drill{margin:10px 0;border:1px solid #e3e6ea;border-radius:8px;background:#fff;overflow:hidden}
.drillhead{cursor:pointer;padding:11px 14px;font-weight:600;font-size:13px;list-style:none;user-select:none}
.drillhead::-webkit-details-marker{display:none}
.drillhead::before{content:"\\25b8";color:#889;margin-right:8px;display:inline-block;transition:transform .15s}
details.drill[open]>.drillhead::before{transform:rotate(90deg)}
.drillbody{padding:2px 12px 12px}
/* scope-hierarchical presence layout: sample-context sections → data-type subsections → scope rungs */
.crumb{font-size:12px;color:#667;margin:14px 0 4px} .crumb b{color:#111}
.crumb .on{background:#1e3a8a;color:#fff;border-radius:4px;padding:1px 7px}
.crumb .off{color:#99a;padding:1px 4px}
.ctxsec{border:1px solid #e3e6ea;border-radius:10px;background:#fff;margin:14px 0;overflow:hidden}
.ctxhead{padding:11px 15px;background:#f5f6f8;border-bottom:1px solid #e8ebef}
.ctxhead .ct{font-size:15px;font-weight:700} .ctxhead .cn{font-size:12px;color:#667;margin-top:2px}
.ctxsec.want-low .ctxhead{background:#fdf6ec}
.subsec{padding:6px 15px 12px} .subsec .dt{font-size:12px;font-weight:600;color:#334;
  text-transform:uppercase;letter-spacing:.04em;margin:12px 0 4px;border-bottom:1px solid #eef0f3;padding-bottom:3px}
.rung{margin:6px 0 6px 6px;border-left:2px solid #e3e6ea;padding-left:10px}
.rung.leads{border-left-color:#1e3a8a}
.scopetag{display:inline-block;font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;
  color:#556;background:#eef2ff;border-radius:4px;padding:1px 6px;margin-right:6px}
.scopetag.leads{background:#1e3a8a;color:#fff} .rungrole{font-size:11px;color:#99a}
.projbox,.emptybox,.refbox{border:1px dashed #d9dde3;border-radius:6px;padding:8px 11px;margin:4px 0;font-size:12.5px}
.emptybox{background:#fafbfc;color:#889} .refbox{background:#fbfcfd;color:#667}
.emptybox .etype{font-size:10.5px;font-weight:700;text-transform:uppercase;color:#a08040;margin-right:6px}
.caveat{font-size:11.5px;color:#8a5a2b;background:#fdf6ec;border-radius:5px;padding:5px 9px;margin:4px 0}
.crosslens{border:1px solid #e3e6ea;border-radius:10px;background:#fff;margin:14px 0;padding:6px 15px 12px}
.crosslens .ct{font-size:14px;font-weight:700;margin:8px 0 2px}
/* functional-requirement claim×scope layout (renderer-only, verdict-inert) */
.claimstrip{display:flex;flex-wrap:wrap;gap:10px;margin:4px 0 8px}
.claim{flex:1 1 200px;min-width:200px;border:1px solid #e3e6ea;border-radius:8px;padding:8px 11px;background:#fff}
.claim .claimhd{font-size:12px;margin-bottom:5px} .claim .claimhd b{color:#1e3a8a}
.corrob{margin-left:8px;color:#667;font-size:11px}
.conflict{color:#8a5a2b;font-size:11px;margin-top:5px}
.claim-read{background:#fff;border:1px solid #e3e6ea;border-left:3px solid #1e3a8a;border-radius:8px;padding:10px 14px;margin:6px 0 4px}
.claim-read ul{margin:6px 0 0;padding-left:18px} .claim-read li{font-size:12px;color:#334}
.claim-sec{margin:6px 0} .secnote{color:#667;font-size:12px;margin:0 0 6px}
.scopegrid{gap:8px 30px}
"""

# tiny vanilla-JS lightbox: click a figure to toggle .zoomed (SVG is vector → crisp at any size).
_ZOOM_JS = """
<div class="zbackdrop" id="zbd"></div>
<script>
(function(){var bd=document.getElementById('zbd');
 function close(){document.querySelectorAll('.fig.zoomed').forEach(function(f){f.classList.remove('zoomed')});bd.classList.remove('on');}
 document.querySelectorAll('.figwrap .fig').forEach(function(f){
   f.addEventListener('click',function(e){e.stopPropagation();
     var open=f.classList.contains('zoomed');close();
     if(!open){f.classList.add('zoomed');bd.classList.add('on');}});});
 bd.addEventListener('click',close);
 document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});})();
</script>
"""


def _esc(v) -> str:
    return html.escape(str(v))


# Verdict-INERT "molecular-form" fields (isoform dominance, splice-switch) that describe WHICH
# transcript/form is expressed — a target-intrinsic question on the same RNA data, not a presence-level
# signal. They ride along on the expression cards but clutter the presence read, so the full-field view
# folds them into a separately-labeled section rather than interleaving them. (Suppression is
# renderer-only — the fields stay on the card for the skills that DO ask the isoform question.)
_MOLECULAR_FORM_PREFIXES = ("isoform", "dominant_isoform", "n_expressed_isoform", "splice", "splicing")


def _is_molecular_form_field(k: str) -> bool:
    kl = k.lower()
    return any(kl.startswith(p) or f"_{p}" in kl for p in _MOLECULAR_FORM_PREFIXES)


def _summary_table(summary: dict, exclude=None) -> str:
    """Scalar summary fields (skip _private + big list/dict values) as a compact KV table.
    `exclude` (a predicate on the field name) drops matching fields — used to fold molecular-form
    (isoform/splice) fields out of the main table into their own labeled section."""
    rows = []
    for k, v in summary.items():
        if k.startswith("_"):
            continue
        if exclude is not None and exclude(k):
            continue
        if isinstance(v, (dict, list)):
            if len(str(v)) > 120:
                rows.append((k, f"<{type(v).__name__}, {len(v)} items>"))
            else:
                rows.append((k, str(v)))
        else:
            rows.append((k, v))
    if not rows:
        return ""
    body = "".join(f"<tr><td>{_esc(_prettify(k))}</td><td>{_esc(_fmt_val(v))}</td></tr>" for k, v in rows)
    return f'<table class="kv"><tbody>{body}</tbody></table>'


def _csv_table(csv_path: Path, max_rows: int = 12) -> str:
    try:
        with open(csv_path) as fh:
            rows = list(csv.reader(fh))
    except Exception:  # noqa: BLE001
        return ""
    if not rows:
        return ""
    head = "".join(f"<th>{_esc(c)}</th>" for c in rows[0])
    body = ""
    for r in rows[1:max_rows + 1]:
        body += "<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r) + "</tr>"
    extra = f'<div class="cardmeta">… {len(rows)-1-max_rows} more rows</div>' if len(rows) - 1 > max_rows else ""
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{extra}"


def _card_figures_html(run_dir: Path, fig_descriptors: list, interactive: bool) -> str:
    """Inline SVGs (static) or plotly specs (interactive) for a card's figure descriptors."""
    out = []
    for f in fig_descriptors or []:
        rel = f.get("path", "")
        if interactive and f.get("dynamic"):
            spec_path = run_dir / str(rel).replace(".svg", ".plotly.json")
            if spec_path.exists():
                try:
                    spec = spec_path.read_text()
                    fid = f.get("id", "fig")
                    out.append(f'<div class="plotly-fig" id="pf_{_esc(fid)}"></div>'
                               f'<script type="application/json" class="plotly-spec" '
                               f'data-target="pf_{_esc(fid)}">{spec}</script>')
                    continue
                except Exception:  # noqa: BLE001
                    pass
        # static (default, or interactive fallback): inline the SVG
        svg = _inline_svg(run_dir / rel)
        if svg:
            out.append(f'<div class="fig">{svg}</div>')
    return "".join(out)


_PLOTLY_BOOT = """
<script>
document.querySelectorAll('script.plotly-spec').forEach(function(s){
  try{var spec=JSON.parse(s.textContent);var el=document.getElementById(s.dataset.target);
      Plotly.newPlot(el, spec.data||[], spec.layout||{}, {responsive:true});}catch(e){}});
</script>
"""


def _card_title(cid: str) -> str:
    spec = CARD_DISPLAY.get(cid)
    return spec["title"] if spec and spec.get("title") else _prettify(cid)


def _card_headline_html(cid: str, summary: dict, missing: bool) -> tuple:
    """Return (headline_html, chip_kind, headline_value) — the card's one-line takeaway."""
    hf = _headline_field(cid, summary)
    val = summary.get(hf) if hf else None
    if missing or val is None:
        return ('<div class="headline"><span class="chip weak">data unavailable</span></div>',
                "weak", "data_unavailable")
    kind = _chip_kind(val)
    return (f'<div class="headline"><span class="chip {kind}">{_esc(val)}</span></div>', kind, val)


def _key_metrics_html(cid: str, summary: dict) -> str:
    """3-5 curated key metrics (prettified labels). Curated list if present, else heuristic scalars."""
    spec = CARD_DISPLAY.get(cid)
    pairs = []
    if spec and spec.get("metrics"):
        for field, label in spec["metrics"]:
            if field in summary and summary[field] is not None:
                pairs.append((label, summary[field]))
    else:
        hf = _headline_field(cid, summary)
        for k, v in summary.items():
            if k.startswith("_") or k == hf or isinstance(v, (dict, list)) or v is None:
                continue
            pairs.append((_prettify(k), v))
            if len(pairs) >= 5:
                break
    if not pairs:
        return ""
    cells = "".join(f'<div class="metric"><span class="ml">{_esc(l)}</span>'
                    f'<span class="mv">{_esc(_fmt_val(v))}</span></div>' for l, v in pairs)
    return f'<div class="metrics">{cells}</div>'


def _breakdown_panel_html(cid: str, summary: dict) -> str:
    """A curated per-stratum breakdown table promoted INTO the visible card body (e.g. one row per
    molecular subtype), when the card has a BREAKDOWN_PANELS entry and the field is a non-empty
    list-of-dicts. Each row: identity (bolded) + chosen columns; the signal column renders as a chip.
    Returns "" if not configured / absent / empty — never raises."""
    spec = BREAKDOWN_PANELS.get(cid)
    if not spec:
        return ""
    rows = summary.get(spec["field"])
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return ""
    label_key, sig_key = spec["label"], spec.get("signal", "")
    cols = spec["columns"]
    head = f"<th>{_esc(_prettify(label_key))}</th>" + "".join(f"<th>{_esc(lbl)}</th>" for _, lbl in cols)
    body = ""
    for r in rows:
        ident = _esc(r.get(label_key, "?"))
        cells = ""
        for key, _lbl in cols:
            v = r.get(key)
            if key == sig_key and v is not None:  # signal column → colored chip
                cells += f'<td><span class="chip {_chip_kind(v)}">{_esc(v)}</span></td>'
            else:
                cells += f"<td>{_esc(_fmt_val(v))}</td>"
        body += f"<tr><td><b>{ident}</b></td>{cells}</tr>"
    return (f'<div class="cardmeta">{_esc(spec.get("title", "Breakdown"))}</div>'
            f'<table class="breakdown"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def _full_details_html(cid: str, summary: dict, tables_dir: Path) -> str:
    """The exhaustive data — all summary fields + this card's CSVs — behind a collapsed <details>.
    Molecular-form (isoform/splice) fields are folded into their own labeled, verdict-inert section so
    they do not clutter the presence-level fields."""
    has_form = any(_is_molecular_form_field(k) for k in summary if not str(k).startswith("_"))
    body = _summary_table(summary, exclude=_is_molecular_form_field if has_form else None)
    form_html = ""
    if has_form:
        form_tbl = _summary_table({k: v for k, v in summary.items() if _is_molecular_form_field(k)})
        form_html = ('<div class="cardmeta"><b>Molecular-form detail</b> (isoform dominance / splicing) '
                     '— verdict-inert; describes WHICH transcript is expressed, not presence level.</div>'
                     + form_tbl)
    csv_html = ""
    if tables_dir.exists():
        for csvf in sorted(tables_dir.glob(f"{cid}_*.csv")):
            csv_html += f'<div class="cardmeta">{_esc(csvf.name)}</div>' + _csv_table(csvf)
    inner = body + form_html + csv_html
    if not inner:
        return ""
    return f'<details><summary>show all fields + tables</summary>{inner}</details>'


def _fill_template(text: Optional[str], target: str, indication: str) -> Optional[str]:
    """Substitute the card-question placeholders ({target.symbol}, {indication.label}, etc.) with the
    run's real values so the Measurement tab reads cleanly instead of showing raw {target.symbol}."""
    if not text:
        return text
    reps = {"{target.symbol}": target, "{target}": target,
            "{indication.label}": indication, "{indication.oncotree_code}": indication,
            "{indication}": indication}
    for k, v in reps.items():
        text = text.replace(k, str(v))
    return text


def _flow_tabs_html(cid: str, summary: dict, fired_for_card: list, uid: str,
                    target: str = "", indication: str = "") -> str:
    """Per-card 'chain of flow' as CSS-only radio tabs: Data → Method → Measurement → Rules → Verdict.
    Reconstructed from card metadata (target-contracts) + the run's fired_rules + _data_source."""
    meta = _card_meta().get(cid, {})
    ds = summary.get("_data_source")
    inputs = meta.get("required_inputs") or []
    methods = meta.get("methods") or []
    mtype = meta.get("measurement_type")
    question = _fill_template(meta.get("question"), target, indication)

    def _panel(items_html):
        return items_html or '<div class="tabempty">— not recorded for this card —</div>'

    # DATA: catalogued inputs + which manifest actually served this run
    data_html = ""
    if inputs:
        data_html += "<div class='tabrow'><span class='tk'>Catalogued inputs</span><span>" + \
            ", ".join(f"<code>{_esc(i)}</code>" for i in inputs) + "</span></div>"
    if ds:
        data_html += f"<div class='tabrow'><span class='tk'>Served this run</span><span><code>{_esc(ds)}</code></span></div>"
    # METHOD
    method_html = "".join(f"<div class='tabrow'><span class='tk'>Method</span><span><code>{_esc(m)}</code></span></div>"
                          for m in methods)
    # MEASUREMENT
    meas_html = ""
    if mtype:
        meas_html += f"<div class='tabrow'><span class='tk'>Measurement type</span><span><code>{_esc(mtype)}</code></span></div>"
    if question:
        meas_html += f"<div class='tabrow'><span class='tk'>Question</span><span>{_esc(question)}</span></div>"
    # RULES: fired rules on this card (field=value + rationale)
    if fired_for_card:
        rules_html = "".join(
            f"<div class='tabrow'><span class='tk'><code>{_esc(r.get('rule_id'))}</code>"
            + (" <b>(driving)</b>" if r.get("dominant") else "") + "</span><span>"
            f"{_esc(r.get('field'))} = <b>{_esc(r.get('value'))}</b>"
            + (f"<br><span class='muted'>{_esc(r.get('rationale_summary'))}</span>" if r.get("rationale_summary") else "")
            + "</span></div>"
            for r in fired_for_card)
    else:
        rules_html = "<div class='tabempty'>No verdict-ladder rules fired on this card (display-only facet).</div>"
    # VERDICT: the dominant fired rule → its class value
    dom = next((r for r in fired_for_card if r.get("dominant")), None)
    if dom:
        verdict_html = (f"<div class='tabrow'><span class='tk'>Driving rule</span>"
                        f"<span><code>{_esc(dom.get('rule_id'))}</code> → <b>{_esc(dom.get('value'))}</b></span></div>")
    elif fired_for_card:
        verdict_html = ("<div class='tabempty'>Rules fired but none is the driving verdict — this card "
                        "informs context, not the headline call (one-directional gate).</div>")
    else:
        verdict_html = "<div class='tabempty'>Descriptive card — contributes context, emits no verdict.</div>"

    tabs = [("Data", data_html), ("Method", method_html), ("Measurement", meas_html),
            ("Rules", rules_html), ("Verdict", verdict_html)]
    # Layout: ALL radios first, then a single label ROW, then a panels container. The CSS
    # `.tabin:nth-of-type(k):checked ~ .tabpanels > .tabpanel:nth-child(k)` shows the matching panel —
    # so labels form one clean tab BAR and exactly one panel shows below (no interleaved stack).
    radios = "".join(
        f'<input type="radio" name="tabs_{uid}" id="t_{uid}_{i}" class="tabin"{" checked" if i==0 else ""}>'
        for i in range(len(tabs)))
    labels = '<div class="tabbar">' + "".join(
        f'<label for="t_{uid}_{i}" class="tablabel">{name}</label>' for i, (name, _) in enumerate(tabs)) + '</div>'
    panels = '<div class="tabpanels">' + "".join(
        f'<div class="tabpanel">{_panel(body)}</div>' for _, body in tabs) + '</div>'
    return f'<div class="flowtabs">{radios}{labels}{panels}</div>'


# The presence matrix hero has its OWN dedicated render path in render_page (the #487 block, which
# re-emits it from the decision so it shows even without --figures). Exclude it here so a
# tumor-presence page does not render the SAME hero TWICE (generic strip + presence-specific block).
_HERO_OWNED_ELSEWHERE = {"figure_presence_context_matrix.svg"}


def _skill_hero_html(run_dir: Path) -> str:
    """Inline any skill-level HERO SVG(s) emitted at the package ROOT (figures/figure_*.svg) — the
    aggregate 'overall view' graphics (e.g. tumor-selectivity's evidence strip) produced by
    run.py --figures skill_figures_fn. These live at figures/figure_*.svg, distinct from the per-card
    figures/cards/<id>/*.svg (which fig_map_from_existing handles). The presence Presence × Context
    matrix is EXCLUDED (rendered by its own block in render_page — see _HERO_OWNED_ELSEWHERE), so a
    presence page shows it once. Returns a self-contained <div> with the SVG(s) inlined, or ''."""
    figs_dir = run_dir / "figures"
    if not figs_dir.is_dir():
        return ""
    svgs = sorted(p for p in figs_dir.glob("figure_*.svg")
                  if p.is_file() and p.name not in _HERO_OWNED_ELSEWHERE)
    if not svgs:
        return ""
    blocks = []
    for svg in svgs:
        try:
            blocks.append(f'<div class="herofig">{svg.read_text(encoding="utf-8")}</div>')
        except Exception:  # noqa: BLE001 — a hero is additive; never break the page
            continue
    if not blocks:
        return ""
    return ('<div class="lab" style="margin:18px 0 6px">Overall view '
            '<span class="hint">— skill-level summary graphic</span></div>'
            '<div class="hero">' + "".join(blocks) + '</div>')


def _card_block_html(c: dict, run_dir: Path, fig_map: dict, interactive: bool, fired_by_card: dict,
                     tables_dir: Path, target: str, indication: str, uid: str,
                     open_: bool = False) -> str:
    """The full collapsible block for one resolved card: headline chip + key metrics + per-stratum
    breakdown + figures + Data→…→Verdict flow tabs + full-field drill-down. Factored out of render_page
    so the flat cardlist AND the scope-hierarchical presence / dependency claim layouts render cards
    identically. `open_` expands the <details> (used to expand the rung at the query's scope depth)."""
    cid = c.get("card_id", "?")
    summary = c.get("summary") or {}
    missing = c.get("_missing", False)
    _, kind, hval = _card_headline_html(cid, summary, missing)
    out = [f'<details class="card"{" open" if open_ else ""} id="c_{_esc(cid)}">',
           f'<summary class="cardhead"><span class="ctitle">{_esc(_card_title(cid))}</span>'
           f'<span class="chip {kind}">{_esc(hval)}</span></summary>',
           '<div class="cardbody">']
    if missing:
        reason = c.get("_missing_reason") or summary.get("_data_note") or "measured gap"
        out.append(f'<div class="unavail">Data unavailable — {_esc(reason)}</div>')
    else:
        out.append(_key_metrics_html(cid, summary))
        out.append(_breakdown_panel_html(cid, summary))   # per-stratum table (e.g. subtype)
    figs = _card_figures_html(run_dir, fig_map.get(cid, []), interactive)
    if figs:
        out.append(f'<div class="figwrap">{figs}</div>')
    out.append(_flow_tabs_html(cid, summary, fired_by_card.get(cid, []), uid=uid,
                               target=target, indication=indication))
    out.append(_full_details_html(cid, summary, tables_dir))
    out.append('</div></details>')
    return "".join(out)


# ── Scope-hierarchical presence layout (renderer-only; skill-gated on tumor-presence) ──────────────
# Regroups the flat per-card list into SAMPLE-CONTEXT sections (patient tumor = the answer / cell-line =
# the proxy / normal = the want-low comparator), each with DATA-TYPE subsections, each a
# pan-cancer → indication|lineage → subtype SCOPE LADDER. Cards PROJECT into cells: a card renders its
# full block once at its "home" rung and compact projections elsewhere (tumor-elevation-breadth carries
# both an RNA and a protein layer); relations (RNA↔protein concordance) live in a cross-lens band. The
# rung at the query's scope depth is expanded ("leads"); broader rungs are backing, narrower are
# drill-down. DISPLAY ONLY — presence_verdict + the ladders are byte-stable and each card still shows its
# own driving rule, so a scope-led layout can never silently contradict the pooled spine.
_SCOPE_ORD = {"pan-cancer": 0, "lineage": 1, "indication": 1, "subtype": 2}


def _query_depth(decision: dict) -> str:
    """Scope depth of the invocation: subtype if a subgroup/subtype was queried, else indication if an
    indication was given, else pan-cancer. Drives which rung leads (is expanded)."""
    for k in ("subtype", "subgroup", "subgroup_id", "target_subtype"):
        if decision.get(k):
            return "subtype"
    return "indication" if decision.get("indication") else "pan-cancer"


# Card `tier` (validated card-schema enum) → the display scope rung. `None`/absent → pan-cancer (the
# only presence card lacking a tier is cellline-rna-distribution, a pan-cancer proxy).
_TIER_TO_SCOPE = {"target": "pan-cancer", "indication": "indication", "subtype": "subtype", None: "pan-cancer"}
# Fallback coordinate for cards whose YAML omits a tag (belt-and-suspenders; the drift test keeps these honest).
_COORD_FALLBACK = {"cellline-rna-distribution": ("cell_line", "bulk_rna", "pan-cancer")}

# ── Policy layer — only what the coordinates can't express ─────────────────────────────────────────
# Section order + framing (sample_context is the row axis); the rung LABELS per section (cell-line's
# middle rung is `lineage`, the cell-line analog of `indication`); data-type order + labels.
_SECTION_POLICY = [
    {"ctx": "tumor", "title": "Patient tumor — the answer", "polarity": "want-high",
     "note": "The primary presence read: is the target expressed in the actual tumor tissue?",
     "rungs": ["pan-cancer", "indication", "subtype"]},
    {"ctx": "cell_line", "title": "Cell-line models — the proxy", "polarity": "want-high",
     "note": "A 2D-culture proxy for tumor expression — read against the tumor lens. Lineage is the "
             "cell-line analog of indication.",
     "rungs": ["pan-cancer", "lineage", "subtype"]},
]
_DATATYPE_ORDER = ["bulk_rna", "bulk_protein_ms", "sc_rna"]
_DATATYPE_LABEL = {"bulk_rna": "Bulk RNA", "bulk_protein_ms": "Bulk protein (MS)",
                   "sc_rna": "Single-cell RNA", "protein_ihc": "IHC"}

# Cards that PROJECT a compact rung at a cell OTHER than their coordinate home (spanning roll-ups + the
# cell-line lineage sub-view). Keyed by the (ctx, data_type, rung) the projection appears at.
_PROJECTIONS = {
    ("tumor", "bulk_rna", "pan-cancer"): {
        "card": "tumor-elevation-breadth",
        "fields": [("rna_tumor_elevation_breadth_class", "Breadth class"),
                   ("rna_tumor_elevation_n_indications_elevated", "Indic. elevated"),
                   ("rna_tumor_elevation_n_indications_tested", "tested")],
        "note": "K-of-N tumor-elevation breadth across indications — a PREVALENCE estimand, not a "
                "per-sample distribution. Full card under Bulk protein."},
    ("cell_line", "bulk_rna", "lineage"): {
        "card": "cellline-rna-distribution",
        "fields": [("n_lineages_evaluated", "Lineages evaluated"),
                   ("n_lineage_restricted_lineages", "Lineage-restricted")],
        "note": "Lineage = the cell-line analog of indication; per-lineage rows live in the card's "
                "per_lineage_stats table (full card at pan-cancer above)."},
}
# Typed-empty slots — an expected (ctx, data_type, rung) with no card, distinguished honestly. `None`
# suppresses the slot entirely (not expected).
_TYPED_EMPTY = {
    ("tumor", "bulk_protein_ms", "subtype"): {"type": "not-yet-built",
        "note": "Tumor protein × subtype — awaiting a per-sample CPTAC protein reader."},
    ("tumor", "sc_rna", "pan-cancer"): {"type": "not-yet-built", "note": "Pan-cancer single-cell tumor atlas not wired."},
    ("tumor", "sc_rna", "subtype"): {"type": "not-yet-built", "note": "Subtype-resolved single-cell not wired."},
    ("cell_line", "sc_rna", "pan-cancer"): {"type": "not-applicable-by-design",
        "note": "No cell-line single-cell layer (by design)."},
}
# Per-card caveats surfaced above the card block.
_CARD_CAVEAT = {
    "cellline-rna-distribution-by-subtype":
        "Grouped by DepMap DRIVER subtype (genotype) — NOT the tumor molecular taxonomy (CMS…). "
        "Cross-lens subtype alignment awaits a cell-line molecular-subtype product."}
# Cross-lens RELATION cards (RNA↔protein concordance) — belong to no single cell; own band.
_PRESENCE_CROSS_LENS = [
    ("cellline-rna-protein-concordance", "Cell-line RNA ↔ protein concordance"),
    ("rna-protein-concordance-tumor", "Tumor RNA ↔ protein concordance"),
]
# Normal-tissue comparator band: two reference notes (Q3 relative context) + the normal cards.
_NORMAL_REF_NOTES = [
    "Adjacent-normal is the DEG denominator — shown inside the tumor Bulk-RNA cards above (not repeated here).",
    "Population-normal (GTEx) is shown for orientation only; the tumor-vs-GTEx SELECTIVITY call is owned "
    "by the tumor-selectivity skill.",
]


def _card_coord(cid: str) -> tuple:
    """(sample_context, data_type/measurement, scope-rung) for a card, read from its DECLARED coordinates
    (card-schema `sample_context` + `measurement` + `tier`). Placement is coordinate-DRIVEN — no hardcoded
    card→cell map — so a card lands where its contract says. Falls back for a tag-less card."""
    m = _card_meta().get(cid, {})
    ctx, dt = m.get("sample_context"), m.get("measurement")
    scope = _TIER_TO_SCOPE.get(m.get("tier")) if "tier" in m else None
    if not (ctx and dt and scope):
        fb = _COORD_FALLBACK.get(cid)
        if fb:
            ctx, dt, scope = ctx or fb[0], dt or fb[1], scope or fb[2]
    return ctx, dt, scope


def _proj_box_html(card: Optional[dict], spec: dict) -> str:
    """Compact projection of a card whose full block lives at another rung (selected fields + a note)."""
    summary = (card or {}).get("summary") or {}
    missing = (card is None) or bool(card.get("_missing", False))
    rows = ""
    for field, label in spec.get("fields", []):
        v = summary.get(field)
        if v is not None:
            rows += (f'<div class="metric"><span class="ml">{_esc(label)}</span>'
                     f'<span class="mv">{_esc(_fmt_val(v))}</span></div>')
    note = spec.get("note", "")
    if missing and not rows:
        return f'<div class="emptybox"><span class="etype">not measured</span>{_esc(note)}</div>'
    return (f'<div class="projbox"><div class="metrics">{rows}</div>'
            + (f'<div class="rungrole">{_esc(note)}</div>' if note else "") + '</div>')


def _empty_box_html(spec: dict) -> str:
    return (f'<div class="emptybox"><span class="etype">{_esc(spec.get("type", "gap"))}</span>'
            f'{_esc(spec.get("note", ""))}</div>')


def _ref_box_html(spec: dict) -> str:
    return f'<div class="refbox">{_esc(spec.get("note", ""))}</div>'


def _presence_scope_html(decision: dict, run_dir: Path, fig_map: dict, interactive: bool,
                         fired_by_card: dict, tables_dir: Path, target: str, indication: str) -> str:
    """The scope-hierarchical presence layout: sample-context sections → data-type subsections → a
    coordinate-placed scope ladder (pan-cancer → indication|lineage → subtype). Placement is DRIVEN by
    each card's declared coordinate (`_card_coord`); the policy dicts add only order, spanning
    projections, typed-empties, per-card caveats, the normal band, and the cross-lens relation band.
    Display-only: each card still shows its own driving rule, and the pooled verdict is unchanged."""
    cards = decision.get("cards", [])
    cards_by_id = {c.get("card_id"): c for c in cards}
    relation_ids = {cid for cid, _ in _PRESENCE_CROSS_LENS}
    qdepth = _query_depth(decision)
    qord = _SCOPE_ORD.get(qdepth, 1)
    uid = [0]

    # Coordinate-driven placement: grid[(ctx, data_type, scope)] = [card_id]. Relations + normal handled
    # separately. `unplaced` (no resolvable coordinate) sinks to the catch-all.
    grid: dict = {}
    normal_ids, unplaced = [], []
    for c in cards:
        cid = c.get("card_id")
        if cid in relation_ids:
            continue
        ctx, dt, scope = _card_coord(cid)
        if ctx == "normal":
            normal_ids.append(cid)
        elif ctx and dt and scope:
            grid.setdefault((ctx, dt, scope), []).append(cid)
        else:
            unplaced.append(cid)

    def _present(cid):
        c = cards_by_id.get(cid)
        return c is not None and not c.get("_missing", False)

    def _render_card(cid, open_, scope, rung_label):
        """Full card block + scope tag + role label + optional caveat; the subtype rung's breakdown is
        rendered INLINE (visible) when the query is at indication depth (subtype is the drill-down)."""
        nonlocal_uid = uid
        nonlocal_uid[0] += 1
        c = cards_by_id[cid]
        o = _SCOPE_ORD.get(scope, 1)
        role = "leads" if open_ else ("backing (broader)" if o < qord else "drill-down (narrower)")
        parts = [f'<div class="rung{" leads" if open_ else ""}">'
                 f'<span class="scopetag{" leads" if open_ else ""}">{_esc(rung_label)}</span>'
                 f'<span class="rungrole">{_esc(role)}</span>']
        if cid in _CARD_CAVEAT:
            parts.append(f'<div class="caveat">{_esc(_CARD_CAVEAT[cid])}</div>')
        # Always-visible subtype decomposition at indication depth: promote the per-stratum breakdown
        # out of the collapsed card so an indication query still SEES every subtype.
        if scope == "subtype" and qord < 2 and not c.get("_missing", False):
            bp = _breakdown_panel_html(cid, c.get("summary") or {})
            if bp:
                parts.append('<div class="cardmeta"><b>How the indication read decomposes across '
                             'subtypes</b> (verdict-inert unless a subtype query leads)</div>' + bp)
        parts.append(_card_block_html(c, run_dir, fig_map, interactive, fired_by_card, tables_dir,
                                      target, indication, uid=f"p{nonlocal_uid[0]}", open_=open_))
        parts.append('</div>')
        return "".join(parts)

    out = []
    for sec in _SECTION_POLICY:
        ctx, rungs = sec["ctx"], sec["rungs"]
        # which data-types to show for this context: any with a placed card, a projection, or a typed-empty
        dts = [dt for dt in _DATATYPE_ORDER
               if any((ctx, dt, r) in grid for r in rungs)
               or any((ctx, dt, r) in _PROJECTIONS for r in rungs)
               or any(_TYPED_EMPTY.get((ctx, dt, r)) for r in rungs)]
        if not dts:
            continue
        wl = " want-low" if sec["polarity"] == "want-low" else ""
        out.append(f'<div class="ctxsec{wl}"><div class="ctxhead"><div class="ct">{_esc(sec["title"])}</div>'
                   f'<div class="cn">{_esc(sec["note"])}</div></div>')
        for dt in dts:
            out.append(f'<div class="subsec"><div class="dt">{_esc(_DATATYPE_LABEL.get(dt, dt))}</div>')
            # headline rung = deepest rung with a PRESENT card that is ≤ query depth (else shallowest);
            # a resolved-but-missing card is rendered as a named gap, never the headline.
            card_ords = [_SCOPE_ORD.get(r, 1) for r in rungs
                         if any(_present(cid) for cid in grid.get((ctx, dt, r), []))]
            le = [o for o in card_ords if o <= qord]
            headline_ord = max(le) if le else (min(card_ords) if card_ords else None)
            for r in rungs:
                placed = grid.get((ctx, dt, r), [])
                if placed:
                    for cid in placed:
                        leads = _present(cid) and _SCOPE_ORD.get(r, 1) == headline_ord
                        out.append(_render_card(cid, open_=leads, scope=r, rung_label=r))
                elif (ctx, dt, r) in _PROJECTIONS:
                    p = _PROJECTIONS[(ctx, dt, r)]
                    out.append(f'<div class="rung"><span class="scopetag">{_esc(r)}</span>'
                               + _proj_box_html(cards_by_id.get(p["card"]), p) + '</div>')
                elif _TYPED_EMPTY.get((ctx, dt, r)):
                    out.append(f'<div class="rung"><span class="scopetag">{_esc(r)}</span>'
                               + _empty_box_html(_TYPED_EMPTY[(ctx, dt, r)]) + '</div>')
            out.append('</div>')  # .subsec
        out.append('</div>')  # .ctxsec

    # Normal-tissue comparator band (want-low): reference notes + the normal cards.
    if normal_ids or _NORMAL_REF_NOTES:
        out.append('<div class="ctxsec want-low"><div class="ctxhead"><div class="ct">'
                   'Normal-tissue comparator — reference only</div><div class="cn">Want-LOW. '
                   'Reference / therapeutic-window framing — NOT a selectivity or safety verdict '
                   '(selectivity owned by tumor-selectivity; safety by on-target-safety-liability).'
                   '</div></div><div class="subsec">')
        for note in _NORMAL_REF_NOTES:
            out.append(_ref_box_html({"note": note}))
        for cid in normal_ids:
            if _present(cid):
                uid[0] += 1
                out.append(_card_block_html(cards_by_id[cid], run_dir, fig_map, interactive,
                                            fired_by_card, tables_dir, target, indication, uid=f"n{uid[0]}"))
        out.append('</div></div>')

    # Cross-lens relations band (RNA↔protein concordance — belong to no single cell).
    rel = []
    for cid, title in _PRESENCE_CROSS_LENS:
        if _present(cid):
            uid[0] += 1
            rel.append(f'<div class="ct">{_esc(title)}</div>'
                       + _card_block_html(cards_by_id[cid], run_dir, fig_map, interactive,
                                          fired_by_card, tables_dir, target, indication, uid=f"x{uid[0]}"))
    if rel:
        out.append('<div class="crosslens"><div class="dt" style="border:none">Cross-lens agreement '
                   '<span class="hint">— RNA↔protein concordance (relations between lenses)</span></div>'
                   + "".join(rel) + '</div>')

    # Catch-all: any resolved card the layout did not place — nothing silently drops.
    leftovers = [cid for cid in unplaced if _present(cid)]
    if leftovers:
        out.append('<div class="crosslens"><div class="dt" style="border:none">Other cards</div>')
        for cid in leftovers:
            uid[0] += 1
            out.append(_card_block_html(cards_by_id[cid], run_dir, fig_map, interactive,
                                        fired_by_card, tables_dir, target, indication, uid=f"o{uid[0]}"))
        out.append('</div>')
    return "".join(out)


def _scope_breadcrumb_html(decision: dict, indication: str) -> str:
    """pan-cancer › INDICATION › subtype eyebrow, active rung highlighted per the query depth."""
    depth = _query_depth(decision)
    active = "subtype" if depth == "subtype" else ("indication" if depth == "indication" else "pan-cancer")
    rungs = [("pan-cancer", "pan-cancer"), ("indication", indication or "indication"), ("subtype", "subtype")]
    inner = ' <span class="off">›</span> '.join(
        f'<span class="{"on" if key == active else "off"}">{_esc(lbl)}</span>' for key, lbl in rungs)
    return (f'<div class="crumb">Query scope: {inner} '
            f'<span class="hint">— the rung at this scope leads; broader = backing, narrower = drill-down</span></div>')


def _question_table_html(decision: dict, h: dict) -> str:
    """The LEADING question × (data · signal · confidence) summary table, rendered by the SHARED
    renderer (`render_question_table_html`) so the gallery and the composed target-profile dashboard
    produce the identical table. GENERIC: prefers the rows the skill already EMITTED on
    `headline['question_table']` (presence 7-question, selectivity 8-question, dependency 7-question all
    emit it); falls back to computing the presence table live for older packages. The caption title +
    signal-header are per-skill (Presence / Selectivity / Dependency). Verdict-inert; best-effort."""
    try:
        if str(SKILLS_DIR) not in sys.path:
            sys.path.insert(0, str(SKILLS_DIR))
        from _skills_common.presence_question_table import (presence_question_table,
                                                            render_question_table_html)
        skill = decision.get("skill", "")
        # per-skill caption title + verdict field + signal-header (default = presence, back-compat)
        title, verdict, sig_hdr = "Presence", h.get("presence_verdict"), "Signal — supports presence →"
        if skill == "functional-requirement":
            title, verdict = "Dependency", h.get("dependency_verdict")
            sig_hdr = "Signal — selective dependency →"
        elif skill == "tumor-selectivity":
            title, verdict = "Selectivity", h.get("selectivity_class")
            sig_hdr = "Signal — tumor-selective →"
        rows = h.get("question_table")           # emitted by the skill (generic, preferred)
        if not rows:                             # fallback: recompute the table live, per skill
            if skill == "functional-requirement":
                from _skills_common.dependency_question_table import dependency_question_table
                rows = dependency_question_table(h, decision.get("cards", []))
            else:
                rows = presence_question_table(h, decision.get("cards", []))
        return render_question_table_html(rows, verdict=verdict, include_css=True,
                                          title=title, signal_header=sig_hdr)
    except Exception as e:  # noqa: BLE001 — the table is additive; never break the page
        print(f"[gallery] question table unavailable ({type(e).__name__}: {e})", file=sys.stderr)
        return ""


# ── functional-requirement (dependency) claim×scope layout ────────────────────────────────────────
# Groups the dependency cards by ORTHOGONAL CLAIM (DEP/SEL/COND/CHEM — the same decomposition the
# skill's own claim_vector emits) rather than a flat by-data-source list, then leads with the
# modality-blind claim strip. Renderer-only + verdict-INERT: the dependency_verdict spine is untouched;
# every card renders via the SHARED _card_block_html (identical to the flat path + the presence layout).
# Any card not placed here falls into a trailing "Other evidence" group — nothing is dropped.
#   (claim_code, title, hint, [card_ids])
_DEP_CLAIM_SECTIONS = [
    ("DEP", "Genetic dependency",
     "is loss-of-function lethal? — CRISPR + RNAi + their agreement",
     ["pan-cancer-crispr-dependency-distribution", "pan-cancer-rnai-dependency-distribution",
      "crispr-rnai-dependency-concordance"]),
    ("SEL", "Context-selectivity",
     "therapeutic window (vs pan-essential ceiling — near it = tox liability) + which lineage",
     ["dependency-lineage-selectivity"]),
    ("COND", "Conditional / synthetic-lethal",
     "does a pooled-negative hide a partner- or paralog-conditional dependency?",
     ["paralog-buffering", "partner-conditional-dependency"]),
    ("CHEM", "Chemical-genetic confirmation",
     "does compound kill track the genetic dependency?",
     ["prism-crispr-concordance"]),
]
# CONFIDENCE band (verdict-inert corroboration; annotates the DEP call, does not resolve it)
_DEP_CONFIDENCE_CARDS = ["cross-consortium-dependency", "dependency-predictability"]
# patient-selection FOLD (verdict-inert biomarker/model facets)
_DEP_FACET_CARDS = ["expression-dependency-correlation", "abundance-dependency",
                    "recommended-models", "organoid-crispr-dependency"]
# molecular-subgroup drill-down (only present on the --subtypes path)
_DEP_SUBTYPE_CARDS = ["subgroup-stratified-dependency"]

_DEP_CLAIM_ORDER = ("DEP", "SEL", "COND", "CHEM")


def _dep_claim_strip_html(headline: dict) -> str:
    """The modality-blind claim strip (DEP/SEL/COND/CHEM each signal×corroboration) + the deterministic
    key-signals headline. Reads the ALREADY-computed headline.claim_vector / key_signals (verdict-inert
    projections run.py emits). Absent → ''. This is what lets the scope-led layout lead with the skill's
    own within-lens integration instead of a data-source dump."""
    cv = headline.get("claim_vector")
    ks = headline.get("key_signals")
    if not isinstance(cv, dict):
        return ""
    chips = []
    for code in _DEP_CLAIM_ORDER:
        claim = cv.get(code)
        if not isinstance(claim, dict):
            continue
        sig = claim.get("signal", "unmeasured")
        corr = claim.get("corroboration", "unmeasured")
        conflict = claim.get("conflict")
        kind = "good" if str(sig) in _POS or str(sig) in ("strong", "moderate") else \
               ("weak" if str(sig) in ("absent", "unmeasured", "negative") else "neutral")
        title = _esc(claim.get("informs", code))
        chips.append(
            f'<div class="claim" title="{title}">'
            f'<div class="claimhd"><b>{code}</b> <span class="hint">{_esc(claim.get("evidence",""))}</span></div>'
            f'<div><span class="chip {kind}">{_esc(sig)}</span>'
            f'<span class="corrob">corrob: {_esc(corr)}</span></div>'
            + (f'<div class="conflict">⚠ {_esc(conflict)}</div>' if conflict else '')
            + '</div>')
    head = ""
    if isinstance(ks, dict) and ks.get("headline"):
        sup = "".join(f"<li>{_esc(s)}</li>" for s in (ks.get("supports") or []))
        cav = f'<div class="conflict">⚠ {_esc(ks["caveat"])}</div>' if ks.get("caveat") else ""
        head = (f'<div class="claim-read"><b>{_esc(ks["headline"])}</b>'
                + (f'<ul>{sup}</ul>' if sup else '') + cav + '</div>')
    return ('<div class="lab" style="margin:18px 0 6px">Dependency claims '
            '<span class="hint">— DEP genetic-dependency · SEL context-selectivity · '
            'COND conditional-SL · CHEM chemical-genetic (signal × corroboration; not additive)</span></div>'
            f'{head}<div class="claimstrip">' + "".join(chips) + '</div>')


def _render_dependency_layout(decision: dict, run_dir: Path, fig_map: dict, fired_by_card: dict,
                              tables_dir: Path, target: str, indication: str, interactive: bool) -> str:
    """functional-requirement claim×scope layout (renderer-only; verdict-inert). Claim sections
    (DEP/SEL/COND/CHEM) → confidence band → patient-selection fold → molecular-subgroup drill-down →
    trailing 'Other evidence' catch-all so no card is dropped."""
    h = decision.get("headline", {}) or {}
    cards = decision.get("cards", []) or []
    by_id = {c.get("card_id"): c for c in cards}
    used: set = set()
    idx = 0
    parts = [_dep_claim_strip_html(h)]

    # forward-compatible scope banner: render dependency_verdict_by_scope when Phase 3/4 emits it
    # (pan-cancer → indication-lineage → subtype). Typed-empty / absent today → nothing rendered.
    by_scope = h.get("dependency_verdict_by_scope")
    if isinstance(by_scope, dict) and by_scope:
        rows = "".join(
            f'<div class="metric"><span class="ml">{_esc(_prettify(k))}</span>'
            f'<span class="mv">{_esc(_fmt_val(v.get("verdict") if isinstance(v, dict) else v))}</span></div>'
            for k, v in by_scope.items())
        parts.append('<div class="lab" style="margin:18px 0 6px">Verdict by scope '
                     '<span class="hint">— pooled pan-cancer vs the queried indication lineage vs '
                     'molecular subgroup</span></div>'
                     f'<div class="metrics scopegrid">{rows}</div>')

    def _section(title: str, hint: str, card_ids: list, note: str = "") -> None:
        nonlocal idx
        present = [cid for cid in card_ids if cid in by_id]
        if not present:
            return
        parts.append(f'<div class="claim-sec"><div class="lab" style="margin:16px 0 6px">{_esc(title)} '
                     f'<span class="hint">— {_esc(hint)}</span></div>')
        if note:
            parts.append(f'<div class="secnote">{_esc(note)}</div>')
        parts.append('<div class="cardlist">')
        for cid in present:
            parts.append(_card_block_html(by_id[cid], run_dir, fig_map, interactive, fired_by_card,
                                          tables_dir, target, indication, uid=f"dep{idx}"))
            used.add(cid)
            idx += 1
        parts.append('</div></div>')

    for code, title, hint, card_ids in _DEP_CLAIM_SECTIONS:
        _section(f"{code} · {title}", hint, card_ids)
        if code == "DEP":
            _section("Confidence", "independent-consortium + omics corroboration (tunes confidence, "
                     "not the verdict)", _DEP_CONFIDENCE_CARDS)
    _section("Biomarker & model context", "patient-selection facets (expression / abundance / "
             "model correspondence) — additive, verdict-inert", _DEP_FACET_CARDS)
    _section("Molecular-subgroup panorama", "dependency within this indication's subgroups "
             "(--subtypes); underpowered strata (n<30) are not over-read", _DEP_SUBTYPE_CARDS)

    # catch-all so nothing is silently dropped (typed-empty discipline)
    leftover = [c for c in cards if c.get("card_id") not in used]
    if leftover:
        parts.append('<div class="claim-sec"><div class="lab" style="margin:16px 0 6px">Other evidence '
                     '<span class="hint">— cards not mapped to a dependency claim</span></div>'
                     '<div class="cardlist">')
        for c in leftover:
            parts.append(_card_block_html(c, run_dir, fig_map, interactive, fired_by_card,
                                          tables_dir, target, indication, uid=f"dep{idx}"))
            idx += 1
        parts.append('</div></div>')
    return "".join(parts)


# Scope-of-driving-verdict → (lamp fill, ink, label). The load-bearing genomic scope facet: at what
# scope the collapsed verdict was earned. Mirrors the selectivity SAFE-lamp palette (green/amber/grey).
_GENOMIC_SCOPE_LAMP = {
    "indication_anchored":      ("#0ca30c", "#ffffff", "indication-anchored"),
    "pan_cancer_extrapolation": ("#fab219", "#1a1a19", "pan-cancer extrapolation"),
    "mixed":                    ("#eab308", "#1a1a19", "mixed (pan-cancer + indication corroboration)"),
    "subtype_specific":         ("#3730a3", "#ffffff", "subtype-specific"),
    "not_applicable":           ("#b8bcc2", "#1a1a19", "n/a"),
    "unclassified":             ("#b8bcc2", "#1a1a19", "unclassified"),
}
_GENOMIC_CLASS_LABEL = {"snv_indel": "SNV/indel", "copy_number": "copy-number", "fusion": "fusion"}


def _genomic_driving_class(rule: str | None) -> str | None:
    """Map a genomic driving_rule_id to the alteration class it belongs to (for the class badge)."""
    if not rule:
        return None
    if rule.startswith("mutant") or rule.startswith("mut-") or rule.startswith("snv-recurrence"):
        return "snv_indel"
    if rule.startswith("cn-") or rule.startswith("amp-expr"):
        return "copy_number"
    if rule.startswith("fusion"):
        return "fusion"
    return None


def _genomic_hero_html(decision: dict, h: dict) -> str:
    """Phase-R hero for genomic-alteration-profile: the collapsed verdict + a CLASS badge (which of
    SNV/indel / copy-number / fusion drove) + a SCOPE lamp (indication-anchored vs pan-cancer
    extrapolation vs mixed) — the two facets the one-word verdict hides. Reads the verdict-inert headline
    blocks genomic_alteration_by_class + genomic_alteration_by_scope. Display-only."""
    verdict = h.get("genomic_alteration_profile") or "insufficient"
    drv = h.get("driving_rule_id") or "—"
    by_scope = h.get("genomic_alteration_by_scope") or {}
    by_class = h.get("genomic_alteration_by_class") or {}
    scope = by_scope.get("scope_of_driving_verdict") or "not_applicable"
    fill, ink, scope_label = _GENOMIC_SCOPE_LAMP.get(scope, _GENOMIC_SCOPE_LAMP["unclassified"])
    dclass = _genomic_driving_class(h.get("driving_rule_id"))

    class_chips = []
    for cls in ("snv_indel", "copy_number", "fusion"):
        entry = by_class.get(cls) or {}
        cv = entry.get("verdict") or "—"
        measured = entry.get("evidence_state") == "measured"
        kind = "good" if (cls == dclass and measured) else ("neutral" if measured else "weak")
        drives = ' ◄ drives' if cls == dclass else ''
        class_chips.append(f'<span class="chip {kind}" title="{_esc(cls)}">'
                           f'{_GENOMIC_CLASS_LABEL[cls]}: {_esc(str(cv))}{drives}</span>')

    scope_chips = []
    for sk, slabel in (("pan_cancer", "pan-cancer"), ("indication", "indication"), ("subtype", "subtype")):
        present = bool((by_scope.get(sk) or {}).get("evidence_present"))
        scope_chips.append(f'<span class="chip {"good" if present else "weak"}">'
                           f'{slabel}: {"evidence" if present else "none"}</span>')

    return (
        '<div class="lab" style="margin:18px 0 6px">Genomic alteration at a glance '
        '<span class="hint">— which alteration CLASS drives, and at what SCOPE it was earned</span></div>'
        '<div class="ghero" style="border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:14px">'
        f'<div style="font-size:18px;font-weight:700">{_esc(str(verdict))}</div>'
        f'<div class="hint" style="margin:2px 0 10px">driving rule: <code>{_esc(str(drv))}</code></div>'
        '<div style="margin-bottom:10px">'
        f'<span style="display:inline-block;padding:3px 12px;border-radius:20px;font-weight:700;'
        f'background:{fill};color:{ink}">scope: {scope_label}</span></div>'
        '<div style="margin-bottom:6px"><span class="hint">class mix — </span>'
        + " ".join(class_chips) + '</div>'
        '<div><span class="hint">evidence by scope — </span>' + " ".join(scope_chips) + '</div>'
        '</div>'
    )


def render_page(decision: dict, run_dir: Path, fig_map: dict, interactive: bool) -> str:
    """One self-contained, DIGESTIBLE HTML page for a subskill run: exec summary + at-a-glance
    evidence strip + per-card (title + headline chip + key metrics + figure + collapsible full data)."""
    skill = decision.get("skill", "?")
    target = decision.get("target", "?")
    indication = decision.get("indication") or "target-grain"
    h = decision.get("headline", {}) or {}
    verdict = h.get("presence_verdict") or h.get("verdict") or h.get("mechanism_verdict") \
        or h.get("genomic_alteration_profile") \
        or next((v for k, v in h.items() if k.endswith("_verdict")), None)
    driving = h.get("driving_rule_id")

    parts = [f'<h1>{_esc(target)} <span style="color:#889;font-weight:400">· {_esc(skill)}</span></h1>',
             f'<p class="sub">{_esc(indication)}'
             + (f' · <span class="verdict">{_esc(verdict)}</span>' if verdict else '')
             + (f' · rule <code>{_esc(driving)}</code>' if driving else '') + '</p>']

    # exec summary — the LLM narrative (if present), as readable paragraphs
    synth = decision.get("llm_synthesis")
    if isinstance(synth, dict) and "_synthesis_error" not in synth:
        parts.append('<div class="synth"><div class="lab">Summary</div>')
        for k, v in synth.items():
            if k.startswith("_"):
                continue
            val = v.get("value") if isinstance(v, dict) and "value" in v else v
            if val is None:
                continue
            parts.append(f'<p><b>{_esc(_prettify(k))}:</b> {_esc(val)}</p>')
        parts.append('</div>')

    # skill-level HERO graphic (e.g. tumor-selectivity's evidence strip, tumor-presence's
    # Presence × Context matrix) — a run.py --figures skill_figures_fn emits it at figures/figure_*.svg
    # (package ROOT, not figures/cards/). Embed it inline at the top so the page leads with the
    # at-a-glance overall view. Additive: absent → nothing rendered.
    hero = _skill_hero_html(run_dir)
    if hero:
        parts.append(hero)

    # Presence × Context hero (skill-level aggregate VIEW) — for any run whose decision carries the
    # per-(measurement, sample_context) reconciliation (tumor-presence). PERSISTS the SVG+JSON into
    # run_dir/figures/ (so publish_run.py ships it to S3) AND inlines it here, high on the page. This
    # is why a tumor-presence gallery page shows the same hero the target-profile dashboard does.
    # Display-only + best-effort (never breaks the page); gated on the field, not on a skill name.
    if h.get("presence_verdict_by_modality"):
        try:
            if str(SKILLS_DIR) not in sys.path:
                sys.path.insert(0, str(SKILLS_DIR))
            from _skills_common.presence_matrix import emit_presence_matrix  # noqa: E402
            _hero_paths = emit_presence_matrix(decision, run_dir / "figures")
            _hero_svg = next((_inline_svg(p) for p in _hero_paths if p.suffix == ".svg"), None)
            if _hero_svg:
                parts.append('<div class="lab" style="margin:18px 0 6px">Presence × context '
                             '<span class="hint">— where RNA / protein / single-cell agree or '
                             'disagree, framed against normal tissue (deterministic VIEW)</span></div>')
                parts.append(f'<div class="hero-matrix" style="max-width:640px">{_hero_svg}</div>')
        except Exception as e:  # noqa: BLE001 — hero is best-effort; the page still renders
            print(f"[gallery] presence hero unavailable ({type(e).__name__}: {e})", file=sys.stderr)

    cards = decision.get("cards", [])
    tables_dir = run_dir / "tables"
    # group fired rules by card_id for the per-card flow tabs
    fired_by_card: dict = {}
    for r in decision.get("fired_rules", []) or []:
        fired_by_card.setdefault(r.get("card_id"), []).append(r)

    # Skill-gated layout. tumor-presence: sample-context × data-type × scope ladder (#549).
    # functional-requirement: the DEP/SEL/COND/CHEM claim×scope layout. Every OTHER skill keeps the
    # flat "Evidence at a glance" collapsible list. All three render each card via the SAME
    # _card_block_html, so the per-card HTML is identical across paths.
    if skill == "tumor-presence" and cards:
        # LEADING view: the 7-question × (data · signal · confidence) summary table — one glance.
        parts.append(_question_table_html(decision, h))
        # Detailed evidence, demoted to a drill-down: the scope-hierarchical layout.
        parts.append('<details class="drill"><summary class="drillhead">Detailed evidence by lens &amp; '
                     'scope <span class="hint">— sample context → data type → pan-cancer / indication '
                     '(lineage) / subtype; the rung at your query scope leads. Display only.</span>'
                     '</summary><div class="drillbody">')
        parts.append(_scope_breadcrumb_html(decision, indication))
        parts.append(_presence_scope_html(decision, run_dir, fig_map, interactive, fired_by_card,
                                          tables_dir, target, indication))
        parts.append('</div></details>')
    elif skill == "functional-requirement":
        # LEADING view: the 7-question dependency summary table via the SHARED generic renderer (reads
        # headline['question_table'] the skill emits). The DEP/SEL/COND/CHEM claim×scope layout is
        # demoted to a drill-down below.
        parts.append(_question_table_html(decision, h))
        parts.append('<details class="drill"><summary class="drillhead">Detailed evidence by dependency '
                     'claim <span class="hint">— DEP genetic-dependency / SEL context-selectivity / '
                     'COND conditional-SL / CHEM chemical-genetic; click a row to expand. Display only.'
                     '</span></summary><div class="drillbody">')
        parts.append(_render_dependency_layout(decision, run_dir, fig_map, fired_by_card,
                                               tables_dir, target, indication, interactive))
        parts.append('</div></details>')
    elif skill == "genomic-alteration-profile" and cards:
        # LEADING view: the class badge (which of SNV/CN/fusion drove) + the scope lamp
        # (indication-anchored vs pan-cancer extrapolation) — the two facets the one-word verdict hides.
        parts.append(_genomic_hero_html(decision, h))
        # Detailed evidence, demoted to a drill-down: the flat per-card list (same _card_block_html).
        parts.append('<details class="drill"><summary class="drillhead">Detailed evidence '
                     '<span class="hint">— per-card: the SNV / copy-number / fusion classes + '
                     'dependency / recurrence / role + cohort context; click a row to expand. '
                     'Display only.</span></summary><div class="drillbody">')
        parts.append('<div class="cardlist">')
        for idx, c in enumerate(cards):
            parts.append(_card_block_html(c, run_dir, fig_map, interactive, fired_by_card, tables_dir,
                                          target, indication, uid=f"{idx}"))
        parts.append('</div></div></details>')
    elif skill == "tumor-selectivity" and cards:
        # LEADING view: the 8-question × (data · signal · confidence) selectivity table (WIN-drives /
        # SAFE-gates), rendered from the emitted headline['question_table'] via the shared renderer.
        parts.append(_question_table_html(decision, h))
        # Detailed evidence, demoted to a drill-down: the flat per-card list (same _card_block_html).
        parts.append('<details class="drill"><summary class="drillhead">Detailed evidence '
                     '<span class="hint">— per-card: axis-A + veto instruments + additive facets; '
                     'click a row to expand. Display only.</span></summary><div class="drillbody">')
        parts.append('<div class="cardlist">')
        for idx, c in enumerate(cards):
            parts.append(_card_block_html(c, run_dir, fig_map, interactive, fired_by_card, tables_dir,
                                          target, indication, uid=f"{idx}"))
        parts.append('</div></div></details>')
    else:
        # ONE unified "Evidence at a glance" section: the table of cards IS the collapsible list.
        # Each row = title + headline chip (collapsed); click to expand INLINE → key metrics + the
        # shrunk-but-vector-crisp plot + the Data→…→Verdict flow tabs + full-field drill-down.
        parts.append('<div class="lab" style="margin:18px 0 6px">Evidence at a glance '
                     '<span class="hint">— click a row to expand</span></div>')
        parts.append('<div class="cardlist">')
        for idx, c in enumerate(cards):
            parts.append(_card_block_html(c, run_dir, fig_map, interactive, fired_by_card, tables_dir,
                                          target, indication, uid=f"{idx}"))
        parts.append('</div>')

    boot = _ZOOM_JS   # click-to-enlarge lightbox (static SVG); always present
    if interactive:
        bundle = _plotly_bundle()
        if bundle:
            boot += f"<script>{bundle}</script>{_PLOTLY_BOOT}"
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<title>{_esc(target)} · {_esc(skill)}</title><style>{_CSS}</style></head>'
            f'<body><div class="wrap">{"".join(parts)}</div>{boot}</body></html>')


def _slug(*parts) -> str:
    return "__".join(re.sub(r"[^A-Za-z0-9]+", "-", str(p)).strip("-") for p in parts if p)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def _load_config(path: Optional[str], skill, target, indication) -> list[dict]:
    if path:
        import yaml
        doc = yaml.safe_load(Path(path).read_text())
        return doc["examples"] if isinstance(doc, dict) else doc
    if skill and target:
        return [{"skill": skill, "target": target, "indication": indication}]
    raise SystemExit("provide --config, or --skill + --target")


def fig_map_from_existing(run_dir: Path) -> dict:
    """Reconstruct the {card_id: [descriptors]} fig_map from an ALREADY-populated data-package —
    figures/cards/<card_id>/figure_*.svg (+ optional .plotly.json twin) — WITHOUT re-running the
    skill or re-invoking the emitters. This is the render-from-existing-dir path: it consumes the
    exact package published to skill-runs (produced by `run.py --figures`), so the HTML never drifts
    from the deterministic run it depicts. Descriptor `path` is relative to run_dir, matching what
    _card_figures_html expects (run_dir / path)."""
    fig_map: dict = {}
    base = run_dir / "figures" / "cards"
    if not base.is_dir():
        return fig_map
    for card_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        descs = []
        for svg in sorted(card_dir.glob("*.svg")):
            d = {"id": svg.stem, "path": svg.relative_to(run_dir).as_posix(), "primary": True}
            if svg.with_suffix(".plotly.json").exists():
                d["dynamic"] = True          # interactive twin available
            descs.append(d)
        if descs:
            fig_map[card_dir.name] = descs
    return fig_map


def _verdict_label(skill: str, decision: dict) -> str:
    h = decision.get("headline", {}) or {}
    v = (h.get("presence_verdict") or h.get("verdict")
         or next((vv for k, vv in h.items() if k.endswith("_verdict")), None))
    if v:
        return v
    return "descriptive" if skill == "target-intrinsic" else "profile (see cards)"


def _write_index(out: Path, index_rows: list, interactive: bool) -> None:
    tr = "".join(
        f"<tr><td>{_esc(s)}</td><td>{_esc(t)}</td><td>{_esc(i)}</td><td>{_esc(v)}</td>"
        f"<td>{'<a href=\"'+_esc(f)+'\">view</a>' if f else '—'}</td></tr>"
        for s, t, i, v, f in index_rows)
    idx = (f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Subskill example gallery</title>'
           f'<style>{_CSS}</style></head><body><div class="wrap"><h1>Subskill example gallery</h1>'
           f'<p class="sub">{len(index_rows)} example run(s)'
           + (' · interactive' if interactive else ' · static') + '</p>'
           f'<table class="idx"><thead><tr><th>skill</th><th>target</th><th>indication</th>'
           f'<th>verdict</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></body></html>')
    (out / "index.html").write_text(idx)
    print(f"[gallery] index.html written → {out}/index.html", file=sys.stderr)


def _render_from_existing(run_dirs: list, out: Path, interactive: bool) -> int:
    """Render HTML from EXISTING data-package dirs (no skill re-run). Writes <run_dir>/dashboard.html
    beside each package (so a publisher can upload it in place) AND a copy + gallery index.html at
    --out. Returns an exit code."""
    out.mkdir(parents=True, exist_ok=True)
    index_rows = []
    for d in run_dirs:
        run_dir = Path(d)
        dec_path = run_dir / "decision.json"
        if not dec_path.exists():
            print(f"[gallery] --from-run-dir: no decision.json in {run_dir}", file=sys.stderr)
            index_rows.append(("?", str(run_dir), "—", "NO decision.json", None))
            continue
        decision = json.loads(dec_path.read_text())
        skill = decision.get("skill"); target = decision.get("target")
        indication = decision.get("indication")
        fig_map = fig_map_from_existing(run_dir)
        page = render_page(decision, run_dir, fig_map, interactive)
        (run_dir / "dashboard.html").write_text(page)          # co-located with the package
        fname = _slug(skill, target, indication or "target") + ".html"
        (out / fname).write_text(page)                          # gallery copy
        index_rows.append((skill, target, indication or "target-grain",
                           _verdict_label(skill, decision), fname))
        print(f"[gallery] {run_dir}/dashboard.html ({len(fig_map)} cards w/ figures)", file=sys.stderr)
    _write_index(out, index_rows, interactive)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", default=None, help="examples.yaml (list of {skill,target,indication})")
    ap.add_argument("--skill", default=None); ap.add_argument("--target", default=None)
    ap.add_argument("--indication", default=None)
    # single canonical output dir by default (avoid proliferating gallery dirs across runs); a run
    # OVERWRITES the same dir in place. Override with --out for a throwaway variant.
    ap.add_argument("--out", type=Path, default=Path.home() / "dev" / "example-gallery")
    ap.add_argument("--interactive", action="store_true",
                    help="embed interactive plotly (inlines ~4.6MB plotly.js/file; real browser only)")
    ap.add_argument("--synthesize", action="store_true",
                    help="pass --synthesize to each subskill so the page includes the LLM relevance "
                         "narrative (needs Bedrock; degrades to a note if unavailable)")
    ap.add_argument("--from-run-dir", action="append", default=None,
                    help="Render HTML from an EXISTING data-package dir (decision.json + figures/) "
                         "WITHOUT re-running the skill; writes <run_dir>/dashboard.html + a gallery "
                         "copy/index at --out. Repeatable. Ignores --synthesize (uses the package's "
                         "existing llm_synthesis). This is the render-from-existing path used to layer "
                         "HTML onto already-published skill-runs packages.")
    args = ap.parse_args(argv)

    # render-from-existing mode: no skill re-run, no emitters — consume packages as-is.
    if args.from_run_dir:
        return _render_from_existing(args.from_run_dir, args.out, args.interactive)

    args.out.mkdir(parents=True, exist_ok=True)
    emit_figures = _load_emit_figures_for_card()
    rows = _load_config(args.config, args.skill, args.target, args.indication)

    index_rows = []
    for row in rows:
        skill, target = row["skill"], row["target"]
        indication = row.get("indication")
        run_dir = args.out / "_runs" / _slug(skill, target, indication or "target")
        run_dir.mkdir(parents=True, exist_ok=True)
        decision = run_subskill(skill, target, indication, run_dir, synthesize=args.synthesize)
        if decision is None:
            index_rows.append((skill, target, indication or "—", "RUN FAILED", None))
            continue
        # Figure Stage 3: embed the figures the run just emitted (--figures) from the persisted
        # data-package — migrated cards were rendered OFFLINE from plot_data during the run, so the
        # gallery does NOT re-plot (no second live read). This is the same artifact --from-run-dir
        # consumes, so the HTML matches the deterministic package.
        fig_map = fig_map_from_existing(run_dir)
        # Fallback (pre-Stage-3 behavior): a skill that produced no --figures package (rejected
        # --figures) gets a live per-card re-plot via the shared emitter, so its figures still show.
        if not fig_map and emit_figures:
            for c in decision.get("cards", []):
                cid, summary = c.get("card_id"), (c.get("summary") or {})
                try:
                    descs = emit_figures(cid, summary, run_dir, target, indication or "")
                    if descs:
                        fig_map[cid] = descs
                except Exception as e:  # noqa: BLE001
                    print(f"[gallery] fig emit {cid}: {type(e).__name__}", file=sys.stderr)
        page = render_page(decision, run_dir, fig_map, args.interactive)
        fname = _slug(skill, target, indication or "target") + ".html"
        (args.out / fname).write_text(page)
        h = decision.get("headline", {}) or {}
        verdict = (h.get("presence_verdict") or h.get("verdict")
                   or next((v for k, v in h.items() if k.endswith("_verdict")), None))
        if not verdict:
            # verdict-free skills (target-intrinsic = descriptive; genomic-alteration-profile emits a
            # multi-class profile, not a single headline verdict) → a readable label, not a blank dash.
            verdict = "descriptive" if skill == "target-intrinsic" else "profile (see cards)"
        index_rows.append((skill, target, indication or "target-grain", verdict, fname))
        print(f"[gallery] wrote {fname} ({len(fig_map)} cards with figures)", file=sys.stderr)

    _write_index(args.out, index_rows, args.interactive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
