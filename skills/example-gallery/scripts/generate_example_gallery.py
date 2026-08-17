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
    """card_id -> {question, measurement_type, methods[], required_inputs[]} from the target-contracts
    card YAMLs. Indexed by the YAML's own card_id (filename != id for some). Empty {} if the repo is
    absent — the flow tabs then degrade to what's derivable from the run alone."""
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
                 synthesize: bool = False) -> Optional[dict]:
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
    if synthesize:
        cmd += ["--synthesize"]
    print(f"[gallery] running: {skill} {target}" + (f"/{indication}" if indication else ""),
          file=sys.stderr)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=900)
    except subprocess.CalledProcessError as e:
        # Not every subskill takes --synthesize (e.g. genomic-alteration-profile uses a custom
        # main(), not the shared dispatcher). Treat --synthesize as best-effort: retry without it.
        if synthesize and "--synthesize" in (e.stderr or ""):
            print(f"[gallery] {skill} rejects --synthesize; retrying without it", file=sys.stderr)
            return run_subskill(skill, target, indication, run_dir, synthesize=False)
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
        "title": "Tumor vs normal RNA (DEG: adjacent + GTEx)", "headline": "expression_call_class",
        # adjacent contrast (cell A, drives the call) + GTEx contrast (cell C, display-only) side by side
        "metrics": [("log2_fc", "log2FC vs adjacent"), ("q_value", "q vs adjacent"),
                    ("gtex_log2_fc", "log2FC vs GTEx"), ("gtex_q_value", "q vs GTEx"),
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
        "title": "Tumor RNA distribution (per-sample)", "headline": "tumor_expression_class",
        "metrics": [("median_log2tpm", "Median log2TPM"), ("allgene_percentile", "All-gene %ile"),
                    ("control_position_class", "vs controls"),
                    ("n_tumor_samples", "n tumor (TCGA)"), ("studies", "TCGA studies"),
                    ("matched_normal_tissue", "Normal (GTEx)"), ("n_normal_samples", "n normal")]},
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
}

# class value -> chip color category (good/neutral/weak/unavailable) for the at-a-glance strip.
_POS = {"broadly_high", "strongly_upregulated", "lineage_restricted", "strongly_supports", "hub",
        "phospho_active", "above_all_positives", "broad", "broadly_tumor_elevated", "physical_hub",
        "well_characterized", "modest_up", "multi_domain", "supports",
        # a target that separates BY subtype (enriched/restricted in some strata) is the informative case
        "subtype_enriched", "subtype_restricted", "subtype_differential"}
_WEAK = {"not_informative", "no_curated_domain", "data_unavailable", "not_phosphoprotein",
         "no_high_confidence_interactors", "neutral_uninformative", "argues_against", "sparse",
         "not_tumor_elevated", "ns", "subtype_axis_unavailable", "no_subtype_axis",
         # depleted = an UNfavorable deviation from pooled; muted so it reads distinct from uniform
         # (neutral) yet not as the sought-after enriched/restricted signal (good/green)
         "subtype_depleted"}


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


def _summary_table(summary: dict) -> str:
    """Scalar summary fields (skip _private + big list/dict values) as a compact KV table."""
    rows = []
    for k, v in summary.items():
        if k.startswith("_"):
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
    """The exhaustive data — all summary fields + this card's CSVs — behind a collapsed <details>."""
    body = _summary_table(summary)   # all non-private fields (prettified)
    csv_html = ""
    if tables_dir.exists():
        for csvf in sorted(tables_dir.glob(f"{cid}_*.csv")):
            csv_html += f'<div class="cardmeta">{_esc(csvf.name)}</div>' + _csv_table(csvf)
    inner = body + csv_html
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


def render_page(decision: dict, run_dir: Path, fig_map: dict, interactive: bool) -> str:
    """One self-contained, DIGESTIBLE HTML page for a subskill run: exec summary + at-a-glance
    evidence strip + per-card (title + headline chip + key metrics + figure + collapsible full data)."""
    skill = decision.get("skill", "?")
    target = decision.get("target", "?")
    indication = decision.get("indication") or "target-grain"
    h = decision.get("headline", {}) or {}
    verdict = h.get("presence_verdict") or h.get("verdict") or h.get("mechanism_verdict") \
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

    cards = decision.get("cards", [])
    tables_dir = run_dir / "tables"
    # group fired rules by card_id for the per-card flow tabs
    fired_by_card: dict = {}
    for r in decision.get("fired_rules", []) or []:
        fired_by_card.setdefault(r.get("card_id"), []).append(r)

    # ONE unified "Evidence at a glance" section: the table of cards IS the collapsible list.
    # Each row = title + headline chip (collapsed); click to expand INLINE → key metrics + the
    # shrunk-but-vector-crisp plot (click to enlarge) + the Data→…→Verdict flow tabs + full-field
    # drill-down. No separate strip (that was the duplication).
    parts.append('<div class="lab" style="margin:18px 0 6px">Evidence at a glance '
                 '<span class="hint">— click a row to expand</span></div>')
    parts.append('<div class="cardlist">')
    for idx, c in enumerate(cards):
        cid = c.get("card_id", "?")
        summary = c.get("summary") or {}
        missing = c.get("_missing", False)
        _, kind, hval = _card_headline_html(cid, summary, missing)
        parts.append(f'<details class="card" id="c_{_esc(cid)}">')
        parts.append(f'<summary class="cardhead"><span class="ctitle">{_esc(_card_title(cid))}</span>'
                     f'<span class="chip {kind}">{_esc(hval)}</span></summary>')
        parts.append('<div class="cardbody">')
        if missing:
            reason = c.get("_missing_reason") or summary.get("_data_note") or "measured gap"
            parts.append(f'<div class="unavail">Data unavailable — {_esc(reason)}</div>')
        else:
            parts.append(_key_metrics_html(cid, summary))
            parts.append(_breakdown_panel_html(cid, summary))   # per-stratum table (e.g. subtype)
        figs = _card_figures_html(run_dir, fig_map.get(cid, []), interactive)
        if figs:
            parts.append(f'<div class="figwrap">{figs}</div>')
        # flow tabs: Data → Method → Measurement → Rules → Verdict (question placeholders filled)
        parts.append(_flow_tabs_html(cid, summary, fired_by_card.get(cid, []), uid=f"{idx}",
                                     target=target, indication=indication))
        parts.append(_full_details_html(cid, summary, tables_dir))
        parts.append('</div></details>')
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
        # emit figures per card (best-effort)
        fig_map = {}
        if emit_figures:
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
