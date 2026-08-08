"""combo_drug_anchor.read — per-target drug-anchored combination-opportunity reader.

Consumer: combo-crispr-screen evidence card (Phase-I) via the combo-and-resistance skill. Answers,
for a target gene: "when {target} is INHIBITED (by its anchor drug), which OTHER genes become MORE
essential — i.e. what are the co-targeting / combination-therapy opportunities?"

Data: depmap-drug-anchor-combination-per-target-v1 (derived from DepMap 26Q1 drug-anchor CRISPR
screens). Pushdown on inhibited_target. Signal = essentiality shift under the anchor drug; NEGATIVE
= co-target more essential under inhibition (combination candidate). combination_class robust/
supported/context.

COVERAGE (narrow — the discipline that matters): only single-target anchor inhibitors are screened
(KRAS via MRTX1133, KIT via Avapritinib, XPO1 via Eltanexor). A target with NO anchor drug returns
`combination_class: no_anchor_screen` — a COVERAGE GAP, NOT "no combination exists" (measured-vs-null,
mirroring paralog_genetic_interaction's no_paralog_screened).

Resistance arm (positive-shift / rescued genes) is NOT in this product — the resistance-emergence
card is a deferred follow-on.

License: DepMap Consortium Member Data Use Agreement — Takeda institutional access.
Companion: data-catalog:manifests/derived/depmap-drug-anchor-combination-per-target-v1.yaml
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "depmap-drug-anchor-combination-per-target-v1"
METHOD_VERSION = "0.1.0"


@lru_cache(maxsize=256)
def _read_rows(target: str) -> Optional[tuple]:
    """Pushdown-read combination rows for one inhibited_target. None on read failure;
    empty tuple if the target has no anchor screen."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("inhibited_target", "=", (target or "").strip().upper())])
    except Exception:  # noqa: BLE001
        return None
    if tbl.num_rows == 0:
        return tuple()
    return tuple(tbl.to_pylist())


def _classify(rows: Optional[tuple]) -> str:
    """Target-level combination_opportunity_class (strongest co-target wins).

      strong_combination_opportunity   >=1 co-target robust_combination
      combination_opportunity          else >=1 supported_combination
      context_combination_opportunity  else >=1 context_combination
      no_combination_signal            anchor screened, no co-target passed
      no_anchor_screen                 target has no anchor-drug screen (coverage gap)
      data_unavailable                 read failure
    """
    if rows is None:
        return "data_unavailable"
    if len(rows) == 0:
        return "no_anchor_screen"
    classes = {r.get("combination_class") for r in rows}
    if "robust_combination" in classes:
        return "strong_combination_opportunity"
    if "supported_combination" in classes:
        return "combination_opportunity"
    if "context_combination" in classes:
        return "context_combination_opportunity"
    return "no_combination_signal"


def _rank(rows: tuple, top_n: int = 20) -> list:
    ordered = sorted(rows, key=lambda r: (r.get("mean_effect_shift")
                                          if r.get("mean_effect_shift") is not None else 0.0))
    out = []
    for r in ordered[:top_n]:
        out.append({
            "co_target_gene": r.get("co_target_gene"),
            "anchor_drug": r.get("anchor_drug"),
            "mechanism": r.get("mechanism"),
            "n_models": int(r.get("n_models") or 0),
            "mean_effect_shift": r.get("mean_effect_shift"),
            "min_effect_shift": r.get("min_effect_shift"),
            "n_models_significant": int(r.get("n_models_significant") or 0),
            "frac_models_significant": r.get("frac_models_significant"),
            "combination_class": r.get("combination_class"),
        })
    return out


def combination_opportunities_for_gene(target: str, rows: Optional[tuple] = None) -> dict:
    """Per-target drug-anchored combination-opportunity summary. rows injectable for tests."""
    sym = (target or "").strip().upper()
    data = rows if rows is not None else _read_rows(sym)
    klass = _classify(data)
    partners = _rank(data, top_n=20) if data else []
    strongest = partners[0] if partners else None
    anchor = (data[0].get("anchor_drug") if data else None)
    mechanism = (data[0].get("mechanism") if data else None)
    return {
        "combination_opportunity_class": klass,
        "anchor_drug": anchor,
        "anchor_mechanism": mechanism,
        "n_co_targets": len(data) if data else 0,
        "strongest_co_target": (strongest or {}).get("co_target_gene"),
        "strongest_co_target_shift": (strongest or {}).get("mean_effect_shift"),
        "strongest_co_target_class": (strongest or {}).get("combination_class"),
        "top_co_targets": partners,
        "combination_context": _context(sym, klass, strongest, anchor),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _context(sym: str, klass: str, strongest: Optional[dict], anchor: Optional[str]) -> Optional[str]:
    if klass == "no_anchor_screen":
        return (f"{sym}: no drug-anchor CRISPR screen (no anchor inhibitor of {sym} in the DepMap "
                f"26Q1 drug-anchor panel — covers KRAS/KIT/XPO1 only). A coverage gap, NOT evidence "
                f"of no combination opportunity.")
    if klass == "data_unavailable":
        return f"{sym}: drug-anchor combination product unavailable (read error)."
    if klass == "no_combination_signal":
        return (f"{sym}: anchor screen present ({anchor}) but no co-target passed the combination "
                f"threshold.")
    s = strongest or {}
    cg, shift, nsig, nm = (s.get("co_target_gene"), s.get("mean_effect_shift"),
                           s.get("n_models_significant"), s.get("n_models"))
    if klass == "strong_combination_opportunity":
        return (f"{sym} inhibition ({anchor}): ROBUST combination opportunity with {cg} — KO becomes "
                f"more essential under inhibition (mean shift {shift:.2f}, significant in {nsig}/{nm} "
                f"models). A co-targeting hypothesis to pursue.")
    if klass == "combination_opportunity":
        return (f"{sym} inhibition ({anchor}): combination opportunity with {cg} (mean shift {shift:.2f}, "
                f"significant in {nsig}/{nm} models).")
    if klass == "context_combination_opportunity":
        return (f"{sym} inhibition ({anchor}): CONTEXT-specific combination with {cg} — a single model "
                f"shows a strong shift; treat as a conditional hypothesis.")
    return None
