"""display_gloss — plain-language readings for the evidence-graph card view + narrator.

The single registry that turns a bare summary field + number into a gauged, plain statement:

    median_chronos = -1.18   ->   "median CRISPR gene-effect (CHRONOS) = -1.18 (CHRONOS; lower = stronger)"

Three primitives, all pure + deterministic + DISPLAY-ONLY (feed no rule/resolver/gate):

  direction_phrase(direction)         3-value display hint -> a plain "lower = stronger" clause.
  gloss(field) -> (label, units)      METRIC_GLOSS for the ~50 salience-promoted metrics, a ~20-rule
                                      affix backstop for the raw L3 tail, else snake->space fallback.
  metric_reading(field, value, ...)   assembles "{label} = {value} ({units}; {direction_phrase})".

Plus the card DESCRIPTION join (the plain "what is this card"), which lives HERE (report_render), NOT the
pure evidence_graph builder:

  card_question(card_id)                        the raw card `question:` contract field (lru-cached).
  card_description(card_id, target, indication)  the same, with {target.symbol}/{indication.label} filled.

Consolidation target (Stage 2): the sandbox HELP map + tp_synthesis_prompt._METRIC_LEGEND both fold into
METRIC_GLOSS so the card view + the narrator bullets read one vocabulary.

Author budget kept small on purpose (contract in the CI coverage test test_display_gloss_coverage.py):
~50 metric entries (one per salience-promoted field) + ~20 affix rules + a handful of direction phrases.
"""
from __future__ import annotations

import functools
import re
from types import SimpleNamespace
from typing import Optional

import yaml

# ── direction phrases (3-value display hint -> plain clause) ─────────────────────────────────────────
# The graph carries `direction` on key_evidence.effect (24/30 salience specs). Normalize token variance
# (case / spacing / a few historical aliases) so a stray `higher_worse` still resolves — a prior organoid
# direction-inversion bug traces to un-normalized tokens.
_DIRECTION_PHRASE = {
    "lower_is_stronger": "lower = stronger",
    "higher_is_stronger": "higher = stronger",
    "higher_is_worse": "higher = worse (liability)",
    "lower_is_worse": "lower = worse (liability)",
    "near_zero_is_independent": "near zero = independent",
}
_DIRECTION_ALIASES = {
    "lower_stronger": "lower_is_stronger", "more_negative_is_stronger": "lower_is_stronger",
    "higher_stronger": "higher_is_stronger", "higher_is_better": "higher_is_stronger",
    "higher_worse": "higher_is_worse", "higher_bad": "higher_is_worse",
    "lower_worse": "lower_is_worse",
}


def _norm_direction(direction) -> Optional[str]:
    if not direction:
        return None
    tok = re.sub(r"\s+", "_", str(direction).strip().lower())
    return _DIRECTION_ALIASES.get(tok, tok)


def direction_phrase(direction) -> Optional[str]:
    """A plain-language reading of a `direction` display hint (None/unknown -> None)."""
    tok = _norm_direction(direction)
    return _DIRECTION_PHRASE.get(tok) if tok else None


# ── the metric registry: field -> (label, units/scale hint) ─────────────────────────────────────────
# ONE entry per salience-promoted field (evidence_salience.SALIENCE_SPECS effect/significance/omnibus/
# extra_scalars). `units` is a short scale token for the parenthetical ("CHRONOS", "log2FC", "%ile"); None
# when the number is already unitless (a fraction/flag). The q/p significance fields all share the one
# `(label, "q")`/`(label, "p")` shape (a lower=stronger convention documented in direction, not repeated
# per field). The CI coverage test asserts every salience field has an entry here.
METRIC_GLOSS: dict = {
    # ── effect metrics ──
    "median_chronos": ("median CRISPR gene-effect (CHRONOS)", "CHRONOS"),
    "median_chronos_panel": ("panel median CRISPR gene-effect (CHRONOS)", "CHRONOS"),
    "median_chronos_hotspot_mutant": ("median CHRONOS in hotspot-mutant lines", "CHRONOS"),
    "rnai_median_dep_score": ("median RNAi dependency score", "dep score"),
    "fraction_agree": ("CRISPR/RNAi agreement fraction", "fraction"),
    "spearman_r_crispr": ("CRISPR-PRISM concordance", "Spearman r"),
    "r2": ("dependency-predictability", "R2"),
    "loeuf_score": ("gnomAD LOEUF (LoF intolerance)", "LOEUF"),
    "highest_tissue_median": ("highest normal-tissue median expression", "TPM"),
    "log2fc_cell_a": ("tumor-vs-normal fold change", "log2FC"),
    "log2_fc": ("tumor-vs-adjacent fold change", "log2FC"),
    "protein_effect_size": ("tumor-vs-normal protein effect size", "effect size"),
    "malignant_detection_fraction": ("malignant-cell detection fraction", "fraction"),
    "fraction_tumor_above_normal_p95": ("tumor fraction above the normal 95th pct", "fraction"),
    "absolute_copies_per_cell": ("surface copies per cell", "copies/cell"),
    "max_detection_fraction": ("max normal cell-type detection fraction", "fraction"),
    "rna_protein_r": ("RNA-protein correlation", "Pearson r"),
    "chembl_best_pchembl": ("best measured potency (ChEMBL)", "pChEMBL"),
    "median_log2auc": ("median PRISM compound activity", "log2 AUC"),
    "cd8_high_minus_low": ("CD8 infiltration delta (antigen high vs low)", "delta fraction"),
    "log2_odds_ratio": ("co-mutation odds ratio", "log2 OR"),
    "activity_z": ("pathway activity", "z-score"),
    "mean_gi": ("mean genetic interaction (dual-KO)", "GI score"),
    "mean_effect_shift": ("mean dependency shift under perturbation", "delta effect"),
    # ── significance metrics (shared q / p convention: lower = stronger) ──
    "q_value": ("FDR q-value", "q"),
    "q_value_cell_a": ("FDR q-value (tumor vs normal)", "q"),
    "bh_q_value": ("BH FDR q-value", "q"),
    "protein_bh_q_value": ("protein BH FDR q-value", "q"),
    "intogen_min_qvalue": ("IntOGen driver q-value", "q"),
    "gi_ttest_pvalue": ("dual-KO t-test p-value", "p"),
    "hotspot_mannwhitney_q": ("hotspot mutant-vs-WT Mann-Whitney q-value", "q"),
    "lineage_omnibus_p": ("cross-lineage omnibus p-value", "p"),
    "pli_score": ("gnomAD pLI (LoF-intolerance probability)", "pLI"),
    "frac_models_significant": ("fraction of models with a significant shift", "fraction"),
    # ── extra scalars ──
    "selectivity_index": ("dependency selectivity index", "index"),
    "mis_z_score": ("gnomAD missense z-score", "z-score"),
    "critical_organ_max": ("max expression in a critical organ", "TPM"),
    "tissue_breadth_fraction": ("normal-tissue breadth fraction", "fraction"),
    "best_spearman_r_crispr": ("best CRISPR concordance", "Spearman r"),
    "best_spearman_r_rnai": ("best RNAi concordance", "Spearman r"),
    "pearson_r_squared_rf": ("predictability (random forest)", "R2"),
    "median_chronos_hotspot_wildtype": ("median CHRONOS in wild-type lines", "CHRONOS"),
    "hotspot_dependency_base_rate": ("hotspot-mutant dependency base rate", "fraction"),
    "intogen_max_pct_samples": ("IntOGen max % samples mutated", "%"),
    "selectivity_allgene_percentile": ("selectivity percentile vs all genes", "%ile"),
    "sig_all_cells": ("significant across all comparator cells", None),
    "normal_p95_log2tpm": ("normal-tissue 95th-percentile expression", "log2 TPM"),
    "distribution_overlap_tumor_normal": ("tumor-normal distribution overlap", "overlap"),
    "best_measured_potency_neglog_m": ("best measured potency", "-log10 M"),
    "alphafold_plddt_mean": ("AlphaFold mean pLDDT (model confidence)", "pLDDT"),
    "n_upstream_regulators": ("upstream regulators in the network", "count"),
    "n_downstream_effectors": ("downstream effectors in the network", "count"),
}

# ── affix backstop for the raw L3 tail (fields NOT in the salience registry) ─────────────────────────
# Ordered (substr, units) rules, first match wins; the label is the humanized field, the units come from
# the matched affix. Keeps the long tail (~99 non-salience numeric_anchors) readable without a per-field
# author entry. Substring (not regex) for speed + legibility.
_AFFIX_RULES: list = [
    ("chronos", "CHRONOS"),
    ("log2fc", "log2FC"),
    ("log2_fc", "log2FC"),
    ("log2auc", "log2 AUC"),
    ("log2tpm", "log2 TPM"),
    ("percentile", "%ile"),
    ("pchembl", "pChEMBL"),
    ("neglog_m", "-log10 M"),
    ("loeuf", "LOEUF"),
    ("pli", "pLI"),
    ("odds_ratio", "log2 OR"),
    ("effect_size", "effect size"),
    ("_q_value", "q"),
    ("_qvalue", "q"),
    ("_pvalue", "p"),
    ("_p_value", "p"),
    ("fraction", "fraction"),
    ("_frac", "fraction"),
    ("r_squared", "R2"),
    ("z_score", "z-score"),
    ("_tpm", "TPM"),
]


def _affix_units(field: str) -> Optional[str]:
    f = field.lower()
    for sub, units in _AFFIX_RULES:
        if sub in f:
            return units
    # suffix-only conventions (avoid the substring false-positives of "_p" / "_r" inside a word)
    if f.endswith("_q"):
        return "q"
    if f.endswith("_p"):
        return "p"
    if f.endswith("_r") or f.endswith("_rho"):
        return "correlation r"
    if f.startswith("n_") or f.endswith("_n") or "count" in f:
        return "count"
    if f.startswith("median_"):
        return None
    return None


def humanize(s) -> str:
    """snake_case / SCREAMING_CASE -> 'Sentence case' (the class-value reader for the 'Reads:' line)."""
    if s is None:
        return ""
    return re.sub(r"_+", " ", str(s)).strip().capitalize()


def gloss(field) -> tuple:
    """(label, units_hint) for a metric field. METRIC_GLOSS -> affix backstop -> snake->space fallback."""
    if not field:
        return ("", None)
    if field in METRIC_GLOSS:
        return METRIC_GLOSS[field]
    return (str(field).replace("_", " "), _affix_units(str(field)))


def _fmt_num(v):
    """Compact scalar display (sig-figs for tiny p/q, short decimal otherwise). Mirrors ir._fmt_num."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "" if v is None else str(v)
    if isinstance(v, float) and v != 0 and abs(v) < 1e-3:
        return f"{v:.2e}"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _anchor_by_role(gv: dict) -> dict:
    out = {}
    for a in ((gv.get("frame") or {}).get("anchors") or []):
        if isinstance(a, dict) and a.get("role"):
            out[a["role"]] = a
    return out


def _past_or_short(x, cut, direction) -> Optional[str]:
    """'past' when x is on the STRONGER/worse side of the cut (per direction), else 'short of'. None when
    either value is missing/non-numeric."""
    if not isinstance(x, (int, float)) or isinstance(x, bool) or not isinstance(cut, (int, float)) or isinstance(cut, bool):
        return None
    d = _norm_direction(direction)
    if d in ("lower_is_stronger", "lower_is_worse"):
        return "past" if x <= cut else "short of"
    if d in ("higher_is_stronger", "higher_is_worse"):
        return "past" if x >= cut else "short of"
    return None


def _anchor_label(a: dict) -> str:
    return str(a.get("label") or a.get("role") or "").replace("_", " ")


def gauge_string(gv: dict) -> str:
    """A plain-language, PRE-GAUGED reading of one interpretation ruler (a gauged_value), e.g.
    'median CHRONOS in hotspot-mutant lines -1.73 vs hotspot wildtype -0.59 (Δ-1.14, past the -0.5 cut)'
    or 'between controls — median CRISPR gene-effect (CHRONOS) -0.46 between non essential floor -0.04 and
    pan essential ceiling -1.50, short of the -0.5 cut'. The words backend for text/md/pptx + the narrator;
    the HTML backend draws the visual ruler. '' when gv is empty."""
    if not isinstance(gv, dict) or gv.get("value") is None:
        return ""
    label, _units = gloss(gv.get("metric"))
    value = gv.get("value")
    head = f"{label} {_fmt_num(value)}" if label else _fmt_num(value)
    frame = gv.get("frame") or {}
    kind = frame.get("kind")
    anchors = _anchor_by_role(gv)
    direction = gv.get("direction")
    cut = anchors.get("cut") or {}

    if kind == "comparator_delta":
        seg = head
        comp = anchors.get("comparator") or {}
        if comp.get("value") is not None:
            seg += f" vs {_anchor_label(comp)} {_fmt_num(comp['value'])}"
        dtc = gv.get("distance_to_cut")
        tail = []
        if dtc is not None:
            tail.append(f"Δ{_fmt_num(dtc)}")
        ps = _past_or_short(dtc, cut.get("value"), direction)   # the cut is on the DELTA here
        if ps and cut.get("value") is not None:
            tail.append(f"{ps} the {_fmt_num(cut['value'])} cut")
        if tail:
            seg += f" ({', '.join(tail)})"
        return seg

    if kind == "floor_cut_ceiling":
        seg = head
        fc = []
        for role in ("floor", "ceiling"):
            a = anchors.get(role) or {}
            if a.get("value") is not None:
                fc.append(f"{_anchor_label(a)} {_fmt_num(a['value'])}")
        if fc:
            seg += " between " + " and ".join(fc)
        ps = _past_or_short(value, cut.get("value"), direction)
        if ps and cut.get("value") is not None:
            seg += f", {ps} the {_fmt_num(cut['value'])} cut"
        pos = gv.get("position")
        return f"{humanize(pos).lower()} — {seg}" if pos else seg

    if kind == "distance_to_cut":
        seg = head
        ps = _past_or_short(value, cut.get("value"), direction)
        if ps and cut.get("value") is not None:
            seg += f", {ps} the {_fmt_num(cut['value'])} cut"
        return seg

    if kind == "percentile":
        return f"{_fmt_num(value)}th percentile ({label})" if label else f"{_fmt_num(value)}th percentile"

    # no / unknown frame → the glossed reading alone
    return metric_reading(gv.get("metric"), value, direction)


def metric_reading(field, value, direction=None, include_direction: bool = True) -> str:
    """A plain-language reading of one metric: '{label} = {value} ({units}; {direction_phrase})'.
    Omits the parenthetical parts that are absent, so a unitless flag still reads cleanly."""
    label, units = gloss(field)
    out = f"{label} = {_fmt_num(value)}" if label else _fmt_num(value)
    extras = []
    if units:
        extras.append(units)
    dp = direction_phrase(direction) if include_direction else None
    if dp:
        extras.append(dp)
    if extras:
        out += f" ({'; '.join(extras)})"
    return out


# ── card DESCRIPTION join (report_render-side; the builder stays pure) ───────────────────────────────
@functools.lru_cache(maxsize=1024)
def card_question(card_id: str) -> Optional[str]:
    """The raw `question:` contract field for a card (the plain 'what is this card'). None when the card
    is absent/unreadable or carries no question. Fail-soft (a description is display sugar; never break a
    render). Mirrors _skills_common.card_input_manifest_ids' cached card.yaml read."""
    try:
        from _skills_common.paths import target_contracts_root
        p = target_contracts_root() / "cards" / f"{card_id}.card.yaml"
        if not p.exists():
            return None
        spec = yaml.safe_load(p.read_text()) or {}
        q = spec.get("question")
        return q if isinstance(q, str) and q.strip() else None
    except Exception:  # noqa: BLE001 — display-only; never break the render
        return None


@functools.lru_cache(maxsize=256)
def indication_label(indication: Optional[str]) -> Optional[str]:
    """A human display label for an indication code (crosswalk display_name), else the code itself."""
    if not indication:
        return None
    ind = indication.upper()
    try:
        from _skills_common.evidence_salience import _crosswalk_entries
        for e in _crosswalk_entries():
            codes = {str(e.get("canonical_code") or "").upper(), str(e.get("oncotree_code") or "").upper()}
            if ind in codes and isinstance(e.get("display_name"), str):
                return e["display_name"]
    except Exception:  # noqa: BLE001
        pass
    return indication


def card_description(card_id: str, target: Optional[str] = None,
                     indication: Optional[str] = None) -> Optional[str]:
    """The card `question:` with {target.symbol} / {indication.label} filled in (never left as a raw
    placeholder — an un-interpolated description reads broken). None when the card carries no question."""
    q = card_question(card_id)
    if not q:
        return None
    tsym = target or ""
    ilab = indication_label(indication) or (indication or "")
    # exact-token replace (robust to stray braces elsewhere in the prose; safer than str.format)
    q = q.replace("{target.symbol}", tsym).replace("{indication.label}", ilab)
    # a couple of historical placeholder spellings seen in the corpus
    q = q.replace("{target}", tsym).replace("{indication}", ilab)
    return re.sub(r"\s{2,}", " ", q).strip() or None


__all__ = ["direction_phrase", "gloss", "metric_reading", "gauge_string", "humanize", "METRIC_GLOSS",
           "card_question", "card_description", "indication_label"]
