"""combo_drug_anchor.read — per-target drug-anchored combination-opportunity reader.

Consumer: combo-crispr-screen evidence card (Phase-I) via the combo-and-resistance skill. Answers,
for a target gene: "when {target} is INHIBITED (by its anchor drug), which OTHER genes become MORE
essential — i.e. what are the co-targeting / combination-therapy opportunities?"

Data: depmap-drug-anchor-combination-per-target-26q3-v1 (derived from DepMap 26Q1 drug-anchor CRISPR
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
Companion: data-catalog:manifests/derived/depmap-drug-anchor-combination-per-target-26q3-v1.yaml
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "depmap-drug-anchor-combination-per-target-26q3-v1"
METHOD_VERSION = "0.1.0"

# Caches ONLY successful reads (a hit or a definitive empty tuple()), keyed by UPPER(target).
# A transient read failure returns None WITHOUT caching, so a later call retries — an @lru_cache
# over the raw read would memoize that None permanently, poisoning the target to data_unavailable
# for the whole process lifetime after one S3 blip. Mirrors structure_features_static: never latch
# a negative cache on a transient error.
_ROWS_CACHE: dict = {}


def _read_rows(target: str) -> Optional[tuple]:
    """Pushdown-read combination rows for one inhibited_target. Returns None on a GENUINE no-object
    (NoSuchKey/404) and RAISES on transient/creds/broken-env (neither cached, so a later call
    retries); empty tuple if the target has no anchor screen (cached). Successful reads are cached.
    The public `combination_opportunities_for_gene` catches the transient raise at its boundary and
    degrades to data_unavailable + a cause-accurate breadcrumb (never propagates)."""
    sym = (target or "").strip().upper()
    if sym in _ROWS_CACHE:
        return _ROWS_CACHE[sym]
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(), filters=[("inhibited_target", "=", sym)])
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # A GENUINELY absent product object (NoSuchKey/404 or pyarrow FileNotFoundError) -> None (NOT
        # cached) -> caller emits data_unavailable with its generic read-failed breadcrumb (unchanged).
        # A transient/creds/broken-env failure is NOT absence -> re-raise so the live-read seam records
        # the REAL cause instead of a generic no-object; not cached, so a later call still retries.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    result = tuple() if tbl.num_rows == 0 else tuple(tbl.to_pylist())
    _ROWS_CACHE[sym] = result
    return result


# A drug-anchor combination/resistance call resting on too few cell lines is UNDERPOWERED: the
# robust tier requires frac_models_significant>=0.5, which at n_models==2 is a single significant
# line (a coin-flip), and no fraction/replication is interpretable below 3 observations. Rows below
# the floor cannot carry the roll-up above the CONTEXT tier — the signal is never erased (an
# underpowered co-target is still a conditional hypothesis), only capped. The raw pre-floor class is
# preserved as `combination_opportunity_class_prefloor` (audit). Empirically only the XPO1 anchor
# (Eltanexor, n_models=2) moves; KRAS (MRTX1133, n=6) and KIT (Avapritinib, n=3) are unchanged.
MIN_POWERED_MODELS = 3

_POSITIVE_COMBINATION_CLASSES = ("robust_combination", "supported_combination", "context_combination")


def _classify(rows: Optional[tuple], min_models: int = 0) -> str:
    """Target-level combination_opportunity_class (strongest co-target wins).

      strong_combination_opportunity   >=1 co-target robust_combination
      combination_opportunity          else >=1 supported_combination
      context_combination_opportunity  else >=1 context_combination
      no_anchor_screen                 target has no anchor-drug screen (coverage gap)
      data_unavailable                 read failure

    min_models: minimum n_models a co-target row must have to carry the roll-up above CONTEXT. With
    the default 0 the classifier is the RAW pre-floor call (all rows eligible — byte-identical to the
    historical behaviour). With min_models=MIN_POWERED_MODELS an underpowered positive signal is
    capped at context_combination_opportunity rather than promoted to strong/moderate.
    """
    if rows is None:
        return "data_unavailable"
    if len(rows) == 0:
        return "no_anchor_screen"
    powered = [r for r in rows if int(r.get("n_models") or 0) >= min_models]
    classes = {r.get("combination_class") for r in powered}
    if "robust_combination" in classes:
        return "strong_combination_opportunity"
    if "supported_combination" in classes:
        return "combination_opportunity"
    if "context_combination" in classes:
        return "context_combination_opportunity"
    # No POWERED row reached a positive tier. If underpowered positive rows exist, the signal is real
    # but underpowered → cap at context (never erase a measured co-target to no-signal).
    if min_models and any(r.get("combination_class") in _POSITIVE_COMBINATION_CLASSES for r in rows):
        return "context_combination_opportunity"
    # Unreachable defensive fallback: every product row is schema-guaranteed to carry a positive
    # combination_class ∈ {robust,supported,context}_combination (non-passing rows are DROPPED at
    # data-catalog materialization — the sanctioned coverage-gap discipline), so a non-empty `rows`
    # either hits a positive branch above or (all-underpowered) the context cap. The former
    # `no_combination_signal` (measured-negative) label was therefore dead; a genuine screened-negative
    # arrives as EMPTY rows (len 0) and is honestly reported as the no_anchor_screen coverage gap.
    # Fall through to that same coverage-gap class.
    return "no_anchor_screen"


def _rank(rows: tuple, top_n: int = 20) -> list:
    ordered = sorted(rows, key=lambda r: r.get("mean_effect_shift") if r.get("mean_effect_shift") is not None else 0.0)
    out = []
    for r in ordered[:top_n]:
        out.append(
            {
                "co_target_gene": r.get("co_target_gene"),
                "anchor_drug": r.get("anchor_drug"),
                "mechanism": r.get("mechanism"),
                "n_models": int(r.get("n_models") or 0),
                "mean_effect_shift": r.get("mean_effect_shift"),
                "min_effect_shift": r.get("min_effect_shift"),
                "n_models_significant": int(r.get("n_models_significant") or 0),
                "frac_models_significant": r.get("frac_models_significant"),
                "combination_class": r.get("combination_class"),
            }
        )
    return out


def combination_opportunities_for_gene(target: str, rows: Optional[tuple] = None) -> dict:
    """Per-target drug-anchored combination-opportunity summary. rows injectable for tests."""
    sym = (target or "").strip().upper()
    read_error = None
    if rows is not None:
        data = rows
    else:
        try:
            data = _read_rows(sym)  # None = genuine no-object (NoSuchKey/404); raises on transient
        except Exception as e:  # noqa: BLE001 — graceful boundary: never propagate a read blip
            # This reader ALREADY owns the honest "read failure -> data_unavailable + breadcrumb"
            # contract; propagating a transient S3/creds/broken-env exception past the public boundary
            # would crash the whole skill run on a blip (worse than a graceful data_unavailable). The
            # refinement over the old blanket masking is that the breadcrumb now names the true cause;
            # _read_rows does not cache a failed load, so a later call still retries.
            data = None
            read_error = f"combo_drug_anchor transient/creds/broken-env read failure: {e}"
    klass_prefloor = _classify(data)  # RAW (audit) — no power floor
    klass = _classify(data, min_models=MIN_POWERED_MODELS)  # POWERED (the reported class)
    n_models_max = max((int(r.get("n_models") or 0) for r in data), default=0) if data else 0
    underpowered = klass != klass_prefloor  # the floor demoted the call
    partners = _rank(data, top_n=20) if data else []
    strongest = partners[0] if partners else None
    anchor = data[0].get("anchor_drug") if data else None
    mechanism = data[0].get("mechanism") if data else None
    out = {
        "combination_opportunity_class": klass,
        "combination_opportunity_class_prefloor": klass_prefloor,  # raw pre-power-floor call (audit)
        "drug_anchor_n_models_max": n_models_max,  # widest cell-line panel behind the call
        "drug_anchor_underpowered": underpowered,  # True iff the power floor demoted it
        "anchor_drug": anchor,
        "anchor_mechanism": mechanism,
        "n_co_targets": len(data) if data else 0,
        "strongest_co_target": (strongest or {}).get("co_target_gene"),
        "strongest_co_target_shift": (strongest or {}).get("mean_effect_shift"),
        "strongest_co_target_class": (strongest or {}).get("combination_class"),
        "top_co_targets": partners,
        "combination_context": _context(sym, klass, strongest, anchor, underpowered, n_models_max),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }
    # A read failure (klass=data_unavailable, from _read_rows returning None) is an infra failure —
    # surface a breadcrumb so it is never mistaken for a benign coverage gap (mirrors exon_window /
    # cd_antigen_backbone). NOT cached upstream, so a later call retries.
    if klass == "data_unavailable":
        out["_live_read_error"] = read_error or (
            "combo_drug_anchor genuine no-object (NoSuchKey/404): drug-anchor combination product absent"
        )
    return out


def _context(
    sym: str,
    klass: str,
    strongest: Optional[dict],
    anchor: Optional[str],
    underpowered: bool = False,
    n_models_max: int = 0,
) -> Optional[str]:
    if underpowered and klass == "context_combination_opportunity":
        s = strongest or {}
        cg, shift = s.get("co_target_gene"), s.get("mean_effect_shift")
        raw_cls = (s.get("combination_class") or "").replace("_", " ")
        shift_txt = f" (mean shift {shift:.2f})" if isinstance(shift, (int, float)) else ""
        return (
            f"{sym} inhibition ({anchor}): UNDERPOWERED combination signal with {cg}{shift_txt} — "
            f"the strongest co-target reads {raw_cls} but the anchor was screened in only "
            f"{n_models_max} cell line(s) (< {MIN_POWERED_MODELS}), so replication is "
            f"uninterpretable; capped at a context-conditional hypothesis pending a wider panel."
        )
    if klass == "no_anchor_screen":
        return (
            f"{sym}: no drug-anchor CRISPR screen (no anchor inhibitor of {sym} in the DepMap "
            f"26Q1 drug-anchor panel — covers KRAS/KIT/XPO1 only). A coverage gap, NOT evidence "
            f"of no combination opportunity."
        )
    if klass == "data_unavailable":
        return f"{sym}: drug-anchor combination product unavailable (read error)."
    s = strongest or {}
    cg, shift, nsig, nm = (
        s.get("co_target_gene"),
        s.get("mean_effect_shift"),
        s.get("n_models_significant"),
        s.get("n_models"),
    )
    if klass == "strong_combination_opportunity":
        return (
            f"{sym} inhibition ({anchor}): ROBUST combination opportunity with {cg} — KO becomes "
            f"more essential under inhibition (mean shift {shift:.2f}, significant in {nsig}/{nm} "
            f"models). A co-targeting hypothesis to pursue."
        )
    if klass == "combination_opportunity":
        return (
            f"{sym} inhibition ({anchor}): combination opportunity with {cg} (mean shift {shift:.2f}, "
            f"significant in {nsig}/{nm} models)."
        )
    if klass == "context_combination_opportunity":
        return (
            f"{sym} inhibition ({anchor}): CONTEXT-specific combination with {cg} — a single model "
            f"shows a strong shift; treat as a conditional hypothesis."
        )
    return None
