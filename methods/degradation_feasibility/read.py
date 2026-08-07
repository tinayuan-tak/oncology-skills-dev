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

DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT",
                   "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
PRECEDENT_VOCAB_RELPATH = "vocabularies/degrader_precedent_targets.yaml"
PRODUCT_MANIFEST_ID = "ubibrowser-e3-substrate-per-gene-v1"
METHOD_VERSION = "0.1.0"

# surfaceome family_class values that place the target OUTSIDE cytoplasmic-E3 reach.
_SURFACE_SECRETED = {"surface", "cell_surface", "secreted", "membrane", "plasma_membrane"}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = "cbg"


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
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("gene_symbol", "=", (target or "").strip().upper())])
    except Exception:  # noqa: BLE001
        return None
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def degradation_feasibility_for_gene(target: str, surface_family_class: Optional[str] = None,
                                     target_contracts_dir: Optional[str] = None,
                                     e3_row: Optional[dict] = None,
                                     precedent: Optional[dict] = None) -> dict:
    """Per-target degradability feasibility. Precedence: unfavorable_location > precedented_degradable
    > ubiquitination_substrate > plausible_untested > data_unavailable.

    surface_family_class: the surfaceome family_class (injected by the dispatcher from the composed
    surfaceome card) for the location gate. e3_row / precedent may be injected for tests."""
    sym = (target or "").strip().upper()
    precedent = precedent if precedent is not None else _load_precedent(target_contracts_dir)
    curated = precedent.get(sym)
    row = e3_row if e3_row is not None else _read_e3_substrate(sym)

    e3_evidence = (row or {}).get("e3_substrate_evidence")
    n_lit = int((row or {}).get("n_e3_ligases_literature") or 0)
    e3_ligases = list((row or {}).get("e3_ligases_literature") or [])
    e3_types = list((row or {}).get("e3_types_literature") or [])
    n_pred_conf = int((row or {}).get("n_e3_predicted_confident") or 0)

    loc = (surface_family_class or "").strip().lower()
    location_excluded = loc in _SURFACE_SECRETED

    # ----- precedence -----
    if location_excluded:
        klass = "unfavorable_location"
    elif curated is not None:
        klass = "precedented_degradable"
    elif n_lit >= 1:
        klass = "ubiquitination_substrate"
    elif row is None and surface_family_class is None:
        klass = "data_unavailable"
    else:
        klass = "plausible_untested"

    return {
        "degradability_feasibility_class": klass,
        "e3_substrate_evidence": e3_evidence,
        "n_e3_ligases_literature": n_lit,
        "e3_ligases_literature": e3_ligases,
        "e3_types_literature": e3_types,
        "n_e3_predicted_confident": n_pred_conf,
        "degrader_precedent": bool(curated),
        "degrader_precedent_examples": (list(curated.get("examples", [])) if curated else []),
        "surface_location_excluded": location_excluded,
        "degradability_context": _context(sym, klass, curated, n_lit, e3_ligases, loc),
        "method_version": METHOD_VERSION,
        "_data_source": "ubibrowser-v3-human + curated-precedent",
    }


def _context(sym, klass, curated, n_lit, e3_ligases, loc) -> Optional[str]:
    if klass == "unfavorable_location":
        return (f"{sym}: {loc} protein — outside cytoplasmic-E3 reach, so a classic intracellular "
                f"PROTAC/molecular-glue cannot engage it (an ADC/TCE surface modality applies instead).")
    if klass == "precedented_degradable":
        ex = ", ".join(curated.get("examples", [])[:2]) if curated else ""
        return (f"{sym}: documented targeted-degrader precedent"
                f"{' ('+ex+')' if ex else ''} — degradation feasibility demonstrated.")
    if klass == "ubiquitination_substrate":
        return (f"{sym}: natural E3 substrate ({n_lit} curated E3s: {', '.join(e3_ligases[:4])}) — "
                f"ubiquitination-competent; a positive degradability prior (no drug precedent yet).")
    if klass == "plausible_untested":
        return (f"{sym}: intracellular, no curated degrader precedent and no literature E3 substrate; "
                f"degradation is plausible but unproven (absence of natural-substrate evidence is NOT "
                f"disqualifying — PROTACs recruit E3s de novo).")
    return None
