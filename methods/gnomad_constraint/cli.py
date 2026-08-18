"""gnomad_constraint.cli — loader + deterministic constraint classifier + CLI.

Source: gnomad-constraint-per-gene-v1 (data-catalog DERIVED product), file
`gnomad_constraint_per_gene.parquet` — a gene-keyed, per-gene-representative
distillation of the gnomAD v4.1.1 constraint source. One row per gene
(representative = mane_select > canonical > first, resolved at derive time),
8 columns already renamed to the card-contract fields. Emits the card contract
fields for `gnomad-lof-constraint`
(constraint_class + pLI/LOEUF/mis_z/syn_z/obs_lof/exp_lof).

Why the product (was: raw gnomad.v4.1.1.constraint_metrics.tsv.bgz): the raw v4.1.1
flat export is 574 MB / 1.65 GB uncompressed / 221,898 all-transcript rows x 113
columns. This reader does single-gene lookups, and scanning the raw file cost
~13.7 s/gene. The derived product (gnomad-constraint-per-gene-v1, ~1.08 MB, gene-
sorted parquet) collapses the per-gene-representative selection ONCE at derive time,
so a lookup is a small pushdown read (single-digit ms). See the derived manifest for
the transformation.

Thresholds are the card's (target-contracts/cards/gnomad-lof-constraint.card.yaml):
  high_pli 0.9 / high_loeuf 0.45 ; moderate_pli 0.5 / moderate_loeuf 0.6.
LOEUF is the primary metric (Karczewski 2020); pLI corroborates. The high_loeuf
cutoff is gnomAD's v4-recommended value (moved 0.35->0.45 with the v4.1.1 recompute).
Classification is OR across metrics (either metric clearing a band qualifies the
gene) — chosen for a safety-SENSITIVITY signal, where a false negative (missing a
constrained gene) is worse than a false positive; see classify_constraint.
"""

from __future__ import annotations

import os
from typing import Optional

from methods.catalog_query.read import bucket_key_for

METHOD_VERSION = "0.3.0"  # + human_ko_observed_class (v2.1.1 obs_hom_lof)

# --- source location (landed derived manifest gnomad-constraint-per-gene-v1) ---
SOURCE_MANIFEST_ID = "gnomad-constraint-per-gene-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, S3_KEY = bucket_key_for(SOURCE_MANIFEST_ID)
DEFAULT_AWS_PROFILE = "cbg"

# --- product column names (gnomad-constraint-per-gene-v1 parquet schema) ---
COL_GENE = "gene_symbol"
COL_PLI = "pli"
COL_LOEUF = "loeuf"          # LOEUF (lof.oe_ci.upper distilled from the v4.1.1 source)
COL_MIS_Z = "mis_z"
COL_SYN_Z = "syn_z"
COL_OBS_LOF = "obs_lof"
COL_EXP_LOF = "exp_lof"
COL_OBS_HOM_LOF = "obs_hom_lof"   # v2.1.1 observed homozygous-LoF count (natural human KOs)
COL_EXP_HOM_LOF = "exp_hom_lof"

# --- card thresholds (target-contracts/cards/gnomad-lof-constraint.card.yaml) ---
# high_loeuf moved 0.35 -> 0.45 with the gnomAD v4.1.1 recompute (gnomAD's
# v4-recommended cutoff). Under the OR semantics below this is a no-op on current
# classifications (every gene with LOEUF in (0.35, 0.45] already has pLI >= 0.9, so
# it was already highly_constrained via the pLI clause) — verified against the
# v4.1.1 table — but it is the correct forward-looking value.
HIGH_PLI, HIGH_LOEUF = 0.9, 0.45
MOD_PLI, MOD_LOEUF = 0.5, 0.6


def classify_constraint(pli: Optional[float], loeuf: Optional[float]) -> str:
    """Map (pLI, LOEUF) → constraint_class per the card vocabulary.

    Vocabulary: highly_constrained | moderately_constrained | tolerant | indeterminate.
    LOEUF is primary; a gene qualifies for a band if EITHER metric clears it (LOEUF
    preferred, pLI corroborating), so an outlier-missing metric doesn't silently
    downgrade a genuinely constrained gene. `indeterminate` = neither metric present
    (gene absent from the constraint table / filtered).
    """
    if pli is None and loeuf is None:
        return "indeterminate"
    high = (loeuf is not None and loeuf <= HIGH_LOEUF) or (pli is not None and pli >= HIGH_PLI)
    if high:
        return "highly_constrained"
    moderate = (loeuf is not None and loeuf <= MOD_LOEUF) or (pli is not None and pli >= MOD_PLI)
    if moderate:
        return "moderately_constrained"
    return "tolerant"


def classify_human_ko_observed(obs_hom_lof: Optional[float], pli: Optional[float],
                               loeuf: Optional[float]) -> str:
    """Map (obs_hom_lof, pLI, LOEUF) → human_ko_observed_class (the DIRECT-observation
    complement to the probabilistic constraint class).

    Vocabulary: natural_ko_observed | constrained_no_ko | no_natural_ko | data_unavailable.

    ASYMMETRIC BY DESIGN (see the derived-product cross-release note): observing a natural
    human knockout is a STRONG positive (full loss is demonstrably tolerated), but its ABSENCE
    is WEAK — homozygous LoF is rare in the 125k v2 cohort (only ~12% of genes have any), so
    obs_hom_lof=0 must NOT be read as essentiality; that inference belongs to pLI/LOEUF.
      - obs_hom_lof >= 1                      -> natural_ko_observed  (KO-tolerated reassurance)
      - obs_hom_lof == 0 AND highly constrained (pLI>=0.9 or LOEUF<=0.45)
                                              -> constrained_no_ko    (no natural KO + constrained:
                                                 the essentiality signal is the CONSTRAINT, not the 0)
      - obs_hom_lof == 0 otherwise            -> no_natural_ko        (0 in a 125k cohort; uninformative
                                                 either way — defer to the constraint class)
      - obs_hom_lof is None                   -> data_unavailable     (gene absent from the v2 join)
    """
    if obs_hom_lof is None:
        return "data_unavailable"
    if obs_hom_lof >= 1:
        return "natural_ko_observed"
    highly_constrained = (pli is not None and pli >= HIGH_PLI) or \
                         (loeuf is not None and loeuf <= HIGH_LOEUF)
    return "constrained_no_ko" if highly_constrained else "no_natural_ko"


def _to_float(v):
    try:
        if v is None or v == "" or (isinstance(v, str) and v.upper() in ("NA", "NAN")):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    f = _to_float(v)
    return int(f) if f is not None else None


from methods.target_id_sidecar import ensure_aws_profile


def _local_cache_path() -> str:
    root = os.environ.get("FRAMEWORK_CACHE_ROOT") or os.path.expanduser("~/.cache/framework-gnomad")
    os.makedirs(root, exist_ok=True)
    return os.path.join(root, "gnomad_constraint_per_gene.parquet")


def _download_source(dest: str) -> None:
    """S3 read-through: download the per-gene constraint parquet to the local cache if absent."""
    import boto3  # local import — framework runtime shouldn't require boto3 unless a live read happens
    ensure_aws_profile()
    boto3.client("s3").download_file(S3_BUCKET, S3_KEY, dest)


def load_constraint_row(gene_symbol: str, parquet_path: Optional[str] = None) -> Optional[dict]:
    """Return the per-gene constraint row from gnomad-constraint-per-gene-v1, or None.

    The product is already one-row-per-gene (representative selection done at derive
    time), gene-sorted on gene_symbol. A lookup is a filtered pushdown read on the
    gene_symbol column — no per-transcript scan / representative selection here.

    parquet_path override is for tests (a synthetic parquet); production reads the
    S3 read-through cache.
    """
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    path = parquet_path or _local_cache_path()
    if parquet_path is None and not os.path.exists(path):
        _download_source(path)
    key = gene_symbol.strip().upper()
    table = pq.read_table(path)
    hits = table.filter(pc.equal(pc.utf8_upper(table[COL_GENE]), key)).to_pylist()
    return hits[0] if hits else None


def compute_summary(row: Optional[dict], gene_symbol: str) -> dict:
    """Build the card-contract summary dict from a constraint row (or None → indeterminate)."""
    if row is None:
        return {
            "constraint_class": "indeterminate",
            "pli_score": None, "loeuf_score": None,
            "mis_z_score": None, "syn_z_score": None,
            "obs_lof_count": None, "exp_lof_count": None, "gene_length_bp": None,
            "human_ko_observed_class": "data_unavailable",
            "obs_hom_lof_count": None, "exp_hom_lof_count": None,
            "human_ko_context": None,
            "method_version": METHOD_VERSION,
            "_note": f"{gene_symbol} not in gnomAD v4.1.1 constraint table (indeterminate).",
        }
    pli = _to_float(row.get(COL_PLI))
    loeuf = _to_float(row.get(COL_LOEUF))
    obs_hom = _to_int(row.get(COL_OBS_HOM_LOF))
    ko_class = classify_human_ko_observed(
        _to_float(row.get(COL_OBS_HOM_LOF)), pli, loeuf)
    return {
        "constraint_class": classify_constraint(pli, loeuf),
        "pli_score": pli,
        "loeuf_score": loeuf,
        "mis_z_score": _to_float(row.get(COL_MIS_Z)),
        "syn_z_score": _to_float(row.get(COL_SYN_Z)),
        "obs_lof_count": _to_int(row.get(COL_OBS_LOF)),
        "exp_lof_count": _to_float(row.get(COL_EXP_LOF)),
        "gene_length_bp": None,  # not in the constraint TSV; card field kept for contract, null
        # Human OBSERVED-KO facet — v2.1.1 natural human knockouts. Additive/verdict-inert.
        "human_ko_observed_class": ko_class,
        "obs_hom_lof_count": obs_hom,
        "exp_hom_lof_count": _to_float(row.get(COL_EXP_HOM_LOF)),
        "human_ko_context": _human_ko_context(gene_symbol, ko_class, obs_hom),
        "method_version": METHOD_VERSION,
    }


def _human_ko_context(gene_symbol: str, ko_class: str, obs_hom: Optional[int]) -> Optional[str]:
    """Human-readable one-liner for the observed-KO facet (audit / LLM context)."""
    if ko_class == "natural_ko_observed":
        return (f"{gene_symbol}: {obs_hom} healthy individual(s) homozygous for a predicted-LoF "
                f"variant in gnomAD v2.1.1 (natural human knockout) — full loss is tolerated in "
                f"the population; on-target safety reassurance for a full-KO modality.")
    if ko_class == "constrained_no_ko":
        return (f"{gene_symbol}: no observed homozygous LoF in gnomAD v2.1.1 AND the gene is "
                f"LoF-constrained — consistent with essentiality (the signal is the constraint, "
                f"not the zero count).")
    if ko_class == "no_natural_ko":
        return (f"{gene_symbol}: no observed homozygous LoF in gnomAD v2.1.1 — uninformative in a "
                f"~125k cohort (hom-LoF is rare even for tolerant genes); defer to the constraint class.")
    return None


def _load_takeda_style(target_contracts_dir):
    """Load the Takeda mplstyle + palette (idempotent). Returns the palette module."""
    import sys as _sys
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path
    style_path = _Path(target_contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    _sys.path.insert(0, str(_Path(target_contracts_dir) / "plot_styles"))
    import takeda_palette  # type: ignore
    return takeda_palette


def emit_constraint_gauge(summary: dict, target_symbol: str, out_dir, target_contracts_dir):
    """Emit the constraint_scores_gauge_panel figure for gnomad-lof-constraint.

    Two horizontal gauges (pLI 0-1, LOEUF 0-2) with the card's constraint-band
    reference lines (pLI>=0.9 / LOEUF<=0.35 = highly-constrained safety concern).
    Summary-driven (thin lookup) — draws from pli_score/loeuf_score/constraint_class
    already in the summary; no data reload. On indeterminate/missing scores, emits a
    placeholder panel explaining the gap (so the dashboard shows a cell, not nothing).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from pathlib import Path as _Path

    pal = _load_takeda_style(target_contracts_dir)
    out_dir = _Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "figure_constraint_scores_gauge_panel.svg"

    pli = summary.get("pli_score")
    loeuf = summary.get("loeuf_score")
    klass = summary.get("constraint_class", "indeterminate")

    fig, axes = plt.subplots(2, 1, figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    concern = klass == "highly_constrained"
    bar_color = pal.REFLINE_KILLER["color"] if concern else "#0a2540"

    if pli is None and loeuf is None:
        for ax in axes:
            ax.axis("off")
        axes[0].text(0.5, 0.5, f"{target_symbol}: no gnomAD constraint scores\n"
                     f"(constraint_class = {klass})", ha="center", va="center", fontsize=10)
        fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
        return out_path

    # pLI gauge (0-1; >=0.9 = constrained)
    ax = axes[0]
    ax.barh([0], [pli if pli is not None else 0], color=bar_color, height=0.5)
    ax.axvline(HIGH_PLI, color=pal.REFLINE_KILLER["color"], linestyle="--", linewidth=1,
               label=f"high-constraint (pLI≥{HIGH_PLI})")
    ax.set_xlim(0, 1); ax.set_yticks([]); ax.set_xlabel("pLI (prob. LoF-intolerant)")
    ax.set_title(f"{target_symbol} — gnomAD LoF constraint  [{klass}]")
    ax.legend(loc="lower right", fontsize=7)

    # LOEUF gauge (0-2; <=HIGH_LOEUF = constrained — LOWER is more constrained)
    ax = axes[1]
    ax.barh([0], [loeuf if loeuf is not None else 0], color=bar_color, height=0.5)
    ax.axvline(HIGH_LOEUF, color=pal.REFLINE_KILLER["color"], linestyle="--", linewidth=1,
               label=f"high-constraint (LOEUF≤{HIGH_LOEUF})")
    ax.set_xlim(0, 2); ax.set_yticks([]); ax.set_xlabel("LOEUF (obs/exp LoF upper CI)")
    ax.legend(loc="lower right", fontsize=7)

    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="gnomAD LoF-constraint lookup for a gene.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--parquet", default=None,
                    help="local per-gene parquet override (tests); default reads S3 cache")
    args = ap.parse_args()
    row = load_constraint_row(args.target, parquet_path=args.parquet)
    print(json.dumps(compute_summary(row, args.target), indent=2))
