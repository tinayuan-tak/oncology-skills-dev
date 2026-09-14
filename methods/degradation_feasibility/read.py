"""degradation_feasibility.read — per-target degradability feasibility (the degrader-lens E3 slice).

The tractability-small-molecule degrader lens reports `degradability_machinery: not_yet_assessed`
until this method lands. It answers: is this target a tractable DEGRADATION substrate (PROTAC /
molecular glue)? Three in-hand signals, fused with a clear precedence:

  1. CURATED PRECEDENT (target-contracts/vocabularies/degrader_precedent_targets.yaml) — targets with
     clinical/tool PROTAC or molecular-glue precedent (AR, BRD4, BTK, ESR1, ...). Highest confidence:
     the target has been degraded, so feasibility is demonstrated. (PROTAC-DB is license-restricted /
     un-mirrorable, so precedent is captured as curated facts citing it, not by ingesting it.)
  2. NATURAL E3-SUBSTRATE EVIDENCE (ubibrowser-e3-substrate-per-gene-v1) — does a natural E3 ligase
     ubiquitinate this protein? A literature-curated substrate is ubiquitination-competent (accessible
     lysines, E3-reachable) → a positive feasibility prior. ABSENCE is NEUTRAL, not disqualifying
     (PROTACs recruit any E3, creating induced neo-substrates).
  3. LOCATION GATE (surfaceome family, injected) — a cell-SURFACE / SECRETED protein is NOT reachable
     by cytoplasmic E3 ligases, so a classic intracellular PROTAC cannot degrade it (that is an
     ADC/TCE target instead) → degrader_unfavorable_location. This is the one genuinely NEGATIVE call.

degradability_feasibility_class (first match):
  unfavorable_location      — surface/secreted (cytoplasmic-E3-unreachable) → degrader disfavored
  precedented_degradable    — curated PROTAC/glue precedent → feasibility demonstrated
  ubiquitination_substrate  — literature natural E3 substrate → strong ubiquitination-competent prior
  plausible_untested        — no precedent + no literature substrate, but intracellular + (predicted
                              substrate or simply not excluded) → plausible, unproven
  data_unavailable          — target not resolvable / no signal

Additive DISPLAY facet that ALSO feeds the degrader lens (via degrader-channel-only interpretation
rules on the card); the small-molecule verdict spine is untouched.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT")
    or Path(__file__).resolve().parents[2].parent / "rnd-computational-biology-oncology-target-contracts"
)
PRECEDENT_VOCAB_RELPATH = "vocabularies/degrader_precedent_targets.yaml"
PRODUCT_MANIFEST_ID = "ubibrowser-e3-substrate-per-gene-v1"
METHOD_VERSION = "0.1.0"

# surfaceome family_class values that place the target OUTSIDE cytoplasmic-E3 reach.
# BUGFIX (2026-08-09, modality-fit review): the surfaceome product NEVER emits these strings — its
# family_class vocabulary is {kinase_surface, enzyme_surface, transporter, cd_molecule, adhesion,
# gpcr, growth_factor_receptor, immune_receptor, other_surface, not_surface, data_unavailable}. The
# old set had ZERO overlap with it, so `location_excluded` was ALWAYS False → `unfavorable_location`
# (the method's only genuinely NEGATIVE call, and the degrader lens's only rejecting signal) never
# fired: a GPCR / EGFR that a cytoplasmic PROTAC cannot reach got a non-negative degradability read.
# The location gate now keys on the surfaceome card's `is_surface_protein` BOOLEAN (vocab-independent,
# robust to family_class label changes); the string set is kept as a fallback and corrected to the
# REAL surface family_class values (any value other than not_surface / data_unavailable is a surface
# residency call).
# The REAL surfaceome family_class values that denote surface residency (i.e. cytoplasmic-E3-
# unreachable). Any of these → location_excluded when falling back to the string (no boolean given).
_SURFACE_FAMILY_CLASSES = {
    "kinase_surface",
    "enzyme_surface",
    "transporter",
    "cd_molecule",
    "adhesion",
    "gpcr",
    "growth_factor_receptor",
    "immune_receptor",
    "other_surface",
}
# Retained for back-compat with any caller/test still passing the pre-fix literal vocab.
_SURFACE_SECRETED = {"surface", "cell_surface", "secreted", "membrane", "plasma_membrane"}


@lru_cache(maxsize=1)
def _load_precedent(target_contracts_dir: str = None) -> dict:
    """Curated degrader-precedent vocab (entries keyed by HGNC symbol). {} on failure."""
    import yaml

    path = Path(target_contracts_dir or DEFAULT_TARGET_CONTRACTS) / PRECEDENT_VOCAB_RELPATH
    try:
        return (yaml.safe_load(path.read_text()) or {}).get("entries", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _read_e3_substrate(target: str) -> Optional[dict]:
    """Pushdown-read the UbiBrowser per-substrate-gene product for one gene. None if unresolvable."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[("gene_symbol", "=", (target or "").strip().upper())],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        # GENUINE absence (NoSuchKey/404 or pyarrow FileNotFoundError, or 0 rows below) is NEUTRAL for
        # degradability — a target simply not in UbiBrowser is NOT disqualifying -> None. But a
        # TRANSIENT/creds/broken-env failure must NOT be swallowed: silently dropping the e3-substrate
        # signal downgrades a real `ubiquitination_substrate` positive to `plausible_untested`. Re-raise
        # so the live-read seam surfaces a _live_read_error (honest error status), not a masked downgrade.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def degradation_feasibility_for_gene(
    target: str,
    surface_family_class: Optional[str] = None,
    is_surface_protein: Optional[bool] = None,
    target_contracts_dir: Optional[str] = None,
    e3_row: Optional[dict] = None,
    precedent: Optional[dict] = None,
) -> dict:
    """Per-target degradability feasibility. Precedence: unfavorable_location > precedented_degradable
    > ubiquitination_substrate > plausible_untested > data_unavailable.

    Location gate (2026-08-09 bugfix): a cell-surface / secreted protein is NOT reachable by a
    cytoplasmic PROTAC/glue → unfavorable_location. Determined from the surfaceome card's
    `is_surface_protein` BOOLEAN when supplied (robust, vocab-independent); else falls back to the
    family_class string (any value other than not_surface / data_unavailable is a surface call). The
    old `surface_family_class in {surface,cell_surface,...}` test was a DEAD gate (those strings are
    never emitted by the surfaceome product) — see the module-level note.

    surface_family_class / is_surface_protein: injected by the dispatcher from the surfaceome card.
    e3_row / precedent may be injected for tests."""
    sym = (target or "").strip().upper()
    precedent = precedent if precedent is not None else _load_precedent(target_contracts_dir)
    curated = precedent.get(sym)
    row = e3_row if e3_row is not None else _read_e3_substrate(sym)

    e3_evidence = (row or {}).get("e3_substrate_evidence")
    n_lit = int((row or {}).get("n_e3_ligases_literature") or 0)
    e3_ligases = list((row or {}).get("e3_ligases_literature") or [])
    e3_types = list((row or {}).get("e3_types_literature") or [])
    n_pred_conf = int((row or {}).get("n_e3_predicted_confident") or 0)

    # ----- location gate (fixed) -----
    loc = (surface_family_class or "").strip().lower()
    if is_surface_protein is not None:
        # Primary path: the surfaceome card's boolean (vocab-independent).
        location_excluded = bool(is_surface_protein)
    elif loc:
        # Fallback: a real family_class string denotes surface residency, OR a legacy literal
        # ('surface'/'secreted'/...). A non-surface (not_surface/data_unavailable) or an unknown
        # value (e.g. 'intracellular') is NOT excluded.
        location_excluded = (loc in _SURFACE_FAMILY_CLASSES) or (loc in _SURFACE_SECRETED)
    else:
        location_excluded = False
    # location is KNOWN only if the dispatcher supplied a surfaceome signal at all.
    location_known = (is_surface_protein is not None) or bool(loc)

    # ----- precedence -----
    if location_excluded:
        klass = "unfavorable_location"
    elif curated is not None:
        klass = "precedented_degradable"
    elif n_lit >= 1:
        klass = "ubiquitination_substrate"
    elif row is None and not location_known:
        klass = "data_unavailable"
    else:
        klass = "plausible_untested"

    # PROTAC vs molecular-glue: surface the curated modality + recruited E3 (previously DISCARDED).
    # A PROTAC needs a ligandable handle ON the target; a molecular glue does not (it reshapes an E3
    # surface for a neo-substrate). Recording which lets the degrader lens distinguish the two.
    degrader_modality = curated.get("modality") if curated else None
    recruited_e3 = curated.get("recruited_e3") if curated else None

    return {
        "degradability_feasibility_class": klass,
        "e3_substrate_evidence": e3_evidence,
        "n_e3_ligases_literature": n_lit,
        "e3_ligases_literature": e3_ligases,
        "e3_types_literature": e3_types,
        "n_e3_predicted_confident": n_pred_conf,
        "degrader_precedent": bool(curated),
        "degrader_precedent_examples": (list(curated.get("examples", [])) if curated else []),
        "degrader_precedent_modality": degrader_modality,  # PROTAC | molecular_glue (curated) | None
        "degrader_recruited_e3": recruited_e3,  # CRBN | VHL | ... (curated) | None
        "surface_location_excluded": location_excluded,
        "degradability_context": _context(sym, klass, curated, n_lit, e3_ligases, loc, degrader_modality, recruited_e3),
        "method_version": METHOD_VERSION,
        "_data_source": "ubibrowser-v3-human + curated-precedent",
    }


def _context(sym, klass, curated, n_lit, e3_ligases, loc, degrader_modality=None, recruited_e3=None) -> Optional[str]:
    if klass == "unfavorable_location":
        loc_label = loc or "cell-surface"
        return (
            f"{sym}: {loc_label} protein — outside cytoplasmic-E3 reach, so a classic intracellular "
            f"PROTAC/molecular-glue cannot engage it (an ADC/TCE surface modality applies instead; "
            f"an extracellular-degrader modality such as LYTAC/AbTAC is the exception)."
        )
    if klass == "precedented_degradable":
        ex = ", ".join(curated.get("examples", [])[:2]) if curated else ""
        mod = (
            f" [{degrader_modality}" + (f", recruits {recruited_e3}" if recruited_e3 else "") + "]"
            if degrader_modality
            else ""
        )
        return (
            f"{sym}: documented targeted-degrader precedent"
            f"{' (' + ex + ')' if ex else ''}{mod} — degradation feasibility demonstrated."
        )
    if klass == "ubiquitination_substrate":
        return (
            f"{sym}: natural E3 substrate ({n_lit} curated E3s: {', '.join(e3_ligases[:4])}) — "
            f"ubiquitination-competent; a positive degradability prior (no drug precedent yet)."
        )
    if klass == "plausible_untested":
        return (
            f"{sym}: intracellular, no curated degrader precedent and no literature E3 substrate; "
            f"degradation is plausible but unproven (absence of natural-substrate evidence is NOT "
            f"disqualifying — PROTACs recruit E3s de novo)."
        )
    return None
