"""resistance_emergence.read — per-target drug-anchored resistance-mediator reader.

Consumer: resistance-emergence-signature evidence card (Phase-I) via the combo-and-resistance skill.
Answers, for a target gene: "when {target} is INHIBITED (by its anchor drug), which gene knockouts
RESCUE the cell — i.e. which genes are candidate mediators of resistance to the {target} inhibitor?"

Data: depmap-drug-anchor-resistance-per-target-v1 (derived from the DepMap 26Q1 drug-anchor CRISPR
screens; the SIGN-MIRROR of the combination product). Pushdown on inhibited_target. Signal =
essentiality shift under the anchor drug; POSITIVE = rescuer KO becomes LESS essential under
inhibition (KO rescues the drug's effect = candidate resistance mediator). resistance_class robust/
supported/context.

SELF-TARGET SUPPRESSION (the discipline the manifest requires): a rescuer_gene == inhibited_target
row is a self-consistency artifact (KO of the drug's own target blunts a mutant-target inhibitor),
NOT a resistance route. This reader drops it before classifying/ranking.

COVERAGE (narrow — the discipline that matters): only single-target anchor inhibitors are screened
(KRAS via MRTX1133, KIT via Avapritinib, XPO1 via Eltanexor). A target with NO anchor drug returns
`resistance_class: no_anchor_screen` — a COVERAGE GAP, NOT "no resistance exists" (measured-vs-null,
mirroring combo_drug_anchor's no_anchor_screen).

License: DepMap Consortium Member Data Use Agreement — Takeda institutional access.
Companion: data-catalog:manifests/derived/depmap-drug-anchor-resistance-per-target-v1.yaml
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "depmap-drug-anchor-resistance-per-target-v1"
METHOD_VERSION = "0.1.0"

# Caches ONLY successful reads (a hit or a definitive empty tuple()), keyed by UPPER(target).
# A transient read failure returns None WITHOUT caching, so a later call retries — an @lru_cache
# over the raw read would memoize that None permanently, poisoning the target to data_unavailable
# for the whole process lifetime after one S3 blip. Mirrors combo_drug_anchor: never latch a
# negative cache on a transient error.
_ROWS_CACHE: dict = {}


def _read_rows(target: str) -> Optional[tuple]:
    """Pushdown-read RAW resistance rows for one inhibited_target. None on read failure (NOT
    cached); empty tuple if the target has no anchor screen (cached). Successful reads are cached.

    Self-target rows are NOT dropped here — the raw row count is what distinguishes "no anchor
    screen" (0 raw rows) from "screened but no non-self mediator" (raw rows exist, all self). The
    self-target drop happens at summary time so that distinction survives."""
    sym = (target or "").strip().upper()
    if sym in _ROWS_CACHE:
        return _ROWS_CACHE[sym]
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("inhibited_target", "=", sym)])
    except Exception:  # noqa: BLE001
        return None
    result = tuple(tbl.to_pylist())
    _ROWS_CACHE[sym] = result
    return result


def _drop_self_target(rows: tuple) -> tuple:
    """Drop rescuer_gene == inhibited_target rows (KO of the drug's own target is a
    self-consistency artifact, not a resistance mediator)."""
    return tuple(r for r in rows if r.get("rescuer_gene") != r.get("inhibited_target"))


def _classify(raw_rows: Optional[tuple], mediators: tuple) -> str:
    """Target-level resistance_emergence_class (strongest rescuer wins).

      strong_resistance_signal    >=1 mediator robust_resistance_mediator
      resistance_signal           else >=1 supported_resistance_mediator
      context_resistance_signal   else >=1 context_resistance_mediator
      no_resistance_signal        anchor screened (raw rows exist) but no non-self mediator passed
      no_anchor_screen            target has no anchor-drug screen (0 raw rows — coverage gap)
      data_unavailable            read failure

    Takes BOTH the raw rows (to detect a genuine no-screen) and the post-self-drop mediators (to
    classify), so an all-self-target result is a real negative (no_resistance_signal), NOT mistaken
    for a coverage gap."""
    if raw_rows is None:
        return "data_unavailable"
    if len(raw_rows) == 0:
        return "no_anchor_screen"
    if len(mediators) == 0:
        return "no_resistance_signal"          # screened, but only the self-target (now dropped)
    classes = {r.get("resistance_class") for r in mediators}
    if "robust_resistance_mediator" in classes:
        return "strong_resistance_signal"
    if "supported_resistance_mediator" in classes:
        return "resistance_signal"
    if "context_resistance_mediator" in classes:
        return "context_resistance_signal"
    return "no_resistance_signal"


def _rank(rows: tuple, top_n: int = 20) -> list:
    # strongest rescue = most POSITIVE mean_effect_shift (mirror of combo's most-negative sort)
    ordered = sorted(rows, key=lambda r: (r.get("mean_effect_shift")
                                          if r.get("mean_effect_shift") is not None else 0.0),
                     reverse=True)
    out = []
    for r in ordered[:top_n]:
        out.append({
            "rescuer_gene": r.get("rescuer_gene"),
            "anchor_drug": r.get("anchor_drug"),
            "mechanism": r.get("mechanism"),
            "n_models": int(r.get("n_models") or 0),
            "mean_effect_shift": r.get("mean_effect_shift"),
            "max_effect_shift": r.get("max_effect_shift"),
            "n_models_significant": int(r.get("n_models_significant") or 0),
            "frac_models_significant": r.get("frac_models_significant"),
            "resistance_class": r.get("resistance_class"),
        })
    return out


def resistance_mediators_for_gene(target: str, rows: Optional[tuple] = None,
                                  include_tahoe_adaptation: bool = True) -> dict:
    """Per-target drug-anchored resistance-mediator summary. rows injectable for tests.

    The PRIMARY signal is the DepMap causal genetic-rescue (drives resistance_emergence_class /
    the skill's resistance_verdict). When include_tahoe_adaptation, an ORTHOGONAL, VERDICT-INERT
    Tahoe transcriptional-adaptation sub-signal is attached under `tahoe_adaptation_*` (which
    resistance-associated survival programs the anchor drug INDUCES). It never changes the primary
    class — a secondary lens, weaker causal claim."""
    sym = (target or "").strip().upper()
    raw = rows if rows is not None else _read_rows(sym)
    non_self = _drop_self_target(raw) if raw else raw
    klass = _classify(raw, non_self or tuple())
    mediators = _rank(non_self, top_n=20) if non_self else []
    strongest = mediators[0] if mediators else None
    # anchor metadata comes from raw rows (present even in the all-self / no-mediator case)
    anchor = (raw[0].get("anchor_drug") if raw else None)
    mechanism = (raw[0].get("mechanism") if raw else None)
    out = {
        "resistance_emergence_class": klass,
        "anchor_drug": anchor,
        "anchor_mechanism": mechanism,
        "n_resistance_mediators": len(non_self) if non_self else 0,
        "strongest_mediator": (strongest or {}).get("rescuer_gene"),
        "strongest_mediator_shift": (strongest or {}).get("mean_effect_shift"),
        "strongest_mediator_class": (strongest or {}).get("resistance_class"),
        "top_resistance_mediators": mediators,
        "resistance_context": _context(sym, klass, strongest, anchor),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }
    # A read failure (klass=data_unavailable, from _read_rows returning None) is an infra failure —
    # surface a breadcrumb so it is never mistaken for a benign coverage gap (mirrors
    # combo_drug_anchor). NOT cached upstream, so a later call retries.
    if klass == "data_unavailable":
        out["_live_read_error"] = "resistance_emergence_read_failed"

    # ORTHOGONAL VERDICT-INERT sub-signal: Tahoe transcriptional-adaptation (which resistance
    # programs the anchor drug INDUCES). Attached as facet fields; NEVER alters resistance_emergence_
    # class (the DepMap genetic-rescue verdict). Failure here degrades to a note, never breaks the
    # primary read.
    if include_tahoe_adaptation:
        try:
            from methods.resistance_emergence.tahoe_adaptation import tahoe_adaptation_for_target
            ta = tahoe_adaptation_for_target(sym)
        except Exception:  # noqa: BLE001
            ta = {"tahoe_adaptation_class": "data_unavailable", "induced_programs": []}
        out["tahoe_adaptation_class"] = ta.get("tahoe_adaptation_class")
        out["tahoe_induced_programs"] = ta.get("induced_programs", [])
        out["tahoe_adaptation_note"] = ta.get("tahoe_adaptation_note")
    return out


def _context(sym: str, klass: str, strongest: Optional[dict], anchor: Optional[str]) -> Optional[str]:
    if klass == "no_anchor_screen":
        return (f"{sym}: no drug-anchor CRISPR screen (no anchor inhibitor of {sym} in the DepMap "
                f"26Q1 drug-anchor panel — covers KRAS/KIT/XPO1 only). A coverage gap, NOT evidence "
                f"of no resistance mechanism.")
    if klass == "data_unavailable":
        return f"{sym}: drug-anchor resistance product unavailable (read error)."
    if klass == "no_resistance_signal":
        return (f"{sym}: anchor screen present ({anchor}) but no rescuer gene passed the resistance "
                f"threshold (after dropping the self-target).")
    s = strongest or {}
    rg, shift, nsig, nm = (s.get("rescuer_gene"), s.get("mean_effect_shift"),
                           s.get("n_models_significant"), s.get("n_models"))
    if klass == "strong_resistance_signal":
        return (f"{sym} inhibition ({anchor}): ROBUST resistance-mediator signal — KO of {rg} RESCUES "
                f"the cell under inhibition (mean shift +{shift:.2f}, significant in {nsig}/{nm} "
                f"models), so {rg} loss is a candidate resistance route to monitor.")
    if klass == "resistance_signal":
        return (f"{sym} inhibition ({anchor}): resistance-mediator signal — KO of {rg} rescues under "
                f"inhibition (mean shift +{shift:.2f}, significant in {nsig}/{nm} models).")
    if klass == "context_resistance_signal":
        return (f"{sym} inhibition ({anchor}): CONTEXT-specific resistance mediator — a single model "
                f"shows a strong rescue by {rg} KO; treat as a conditional hypothesis.")
    return None
