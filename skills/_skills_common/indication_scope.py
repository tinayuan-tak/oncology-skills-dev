"""Indication ALIAS → canonical-code resolution for the SUBTYPE SCOPE path.

One question, answered once for the whole fleet: *when a run says `--indication LUAD`, which
registered indication actually answers?*

Every subtype-scope entry point used to answer it by EXACT-MATCHING the code:

  * `tp_common.default_subtypes()` compared `subtype_crosswalk.yaml`'s `canonical_code`, so
    `LUAD` resolved to `([], "unavailable:LUAD")` and the run went whole-cohort;
  * `_live_readers`' seven per-indication subgroup-assignments registries are keyed by canonical
    code, so a `LUAD` run got `no subgroup-assignments shard for indication='LUAD'` while the
    `depmap-subgroup-assignments-nsclc-v1` / `tcga-subgroup-assignments-nsclc-*` shards sat right
    there, already built.

Meanwhile `target-contracts/vocabularies/indication_crosswalk.yaml` v1.4.0 has curated the
mapping the whole time (`NSCLC: aliases: [LUAD, LUSC]`, `COADREAD: aliases: [COAD, READ]`, …).
This module is the single reader of that lane, so the resolution is CURATED, never inferred from
a code's spelling. `functional-requirement/scripts/run.py::_indication_lineage_map` already does
the same two-pass resolution for the DepMap-lineage lanes; this generalises the pattern rather
than adding a second convention.

DEGENERATE-STRATUM HAZARD (why callers get `how`, not just a code). Some aliases are pure
SYNONYMS of their canonical cohort (`GC`→STAD, `PDAC`→PAAD, `LAML`→AML, `DLBCL`→DLBC) and some
are strict SUB-indications (`LUAD`/`LUSC`⊂NSCLC, `COAD`/`READ`⊂COADREAD). The crosswalk does not
distinguish them, and for the lanes here it does not have to: the only place the difference bites
is a subtype axis whose strata CO-DEFINE the cohort — `histology_Adeno` IS (approximately) the
whole LUAD cohort. Stratifying a LUAD run by that axis yields one degenerate stratum with no
cross-stratum contrast, which `tp_fanout._subtype_verdict` cannot detect because it reads a single
stratum's own class. So callers that stratify are expected to drop axes declared
`partition: co_defining` when `how == "alias"`. That guard is DECLARATION-DERIVED, and it is
self-inerting for the synonyms: of the eight indications in `subtype_crosswalk.yaml`, only NSCLC
and ESCA declare a `co_defining` axis, and ESCA has no aliases — so the drop can only ever fire
for exactly the two sub-indication aliases it is meant for.

Fail-soft throughout: an unreadable or absent crosswalk yields `(None, "unknown")` and every
caller keeps its pre-existing whole-cohort behaviour. Never raises.
"""

from __future__ import annotations

import functools
from pathlib import Path

__all__ = ["canonical_subtype_code", "registry_get"]


@functools.lru_cache(maxsize=None)
def _code_index(contracts_repo: str | None = None) -> tuple[dict, dict]:
    """(canonical_by_upper, canonical_by_alias_upper) from indication_crosswalk.yaml.

    Values are the crosswalk's DECLARED canonical_code string (not the upper-cased lookup key),
    because that exact string is what keys the shard registries and `subtype_crosswalk.yaml`.
    `oncotree_code` is indexed as an alias, not as a canonical — it is a synonym spelling of the
    same cohort (`DLBCL`→DLBC, `UM`→UVM), so it belongs in the same lane as `aliases:`.
    """
    try:
        import yaml

        if contracts_repo:
            base = Path(contracts_repo)
        else:
            from _skills_common.paths import DEFAULT_CONTRACTS_REPO

            base = Path(DEFAULT_CONTRACTS_REPO)
        path = base / "vocabularies" / "indication_crosswalk.yaml"
        if not path.exists():
            return {}, {}
        doc = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001 — an unreadable vocab degrades to whole-cohort, never a crash
        return {}, {}

    canonical: dict = {}
    aliases: dict = {}
    entries = [e for e in (doc.get("indications") or []) if isinstance(e, dict)]
    # Two passes so an alias can NEVER shadow a canonical code. The crosswalk validator forbids
    # that collision, but resolution order must not depend on the validator holding.
    for e in entries:
        code = str(e.get("canonical_code") or "").strip()
        if code:
            canonical[code.upper()] = code
    for e in entries:
        code = str(e.get("canonical_code") or "").strip()
        if not code:
            continue
        candidates = list(e.get("aliases") or []) + [e.get("oncotree_code")]
        for alias in candidates:
            key = str(alias or "").strip().upper()
            if key and key not in canonical and key not in aliases:
                aliases[key] = code
    return canonical, aliases


@functools.lru_cache(maxsize=None)
def canonical_subtype_code(indication: str | None, contracts_repo: str | None = None) -> tuple:
    """Resolve an indication code to the registered indication that answers for it.

    Returns `(canonical_code | None, how)` with `how` one of:
      exact   — the code IS a registered `canonical_code` (returned verbatim from the crosswalk)
      alias   — the code is a curated alias / oncotree synonym; the canonical cohort answers, and
                the caller must treat the read as scoped to that WIDER cohort (see module docstring
                for the `partition: co_defining` guard)
      unknown — not registered, or the crosswalk could not be read; callers keep whole-cohort

    On `unknown` the code is `None`, never a guess: this resolver only ever returns a code the
    crosswalk declares.
    """
    key = (indication or "").strip().upper()
    if not key:
        return None, "unknown"
    canonical, aliases = _code_index(contracts_repo)
    if key in canonical:
        return canonical[key], "exact"
    if key in aliases:
        return aliases[key], "alias"
    return None, "unknown"


def registry_get(mapping: dict, indication: str | None, contracts_repo: str | None = None) -> tuple:
    """Look a per-indication registry up by code, falling back to the code's canonical.

    Returns `(value | None, key_used | None, how)`, where `how` describes how the KEY was found:
    `"exact"` the registry names this code itself, `"alias"` the crosswalk redirected to the
    canonical code, `"unknown"` NO entry served this indication (whether or not the code is
    registered — a registered code with no shard and an unregistered code are both misses here).

    The RAW code wins when the registry keys it directly: several registries deliberately carry
    both `COADREAD` and its `COAD`/`READ` aliases, and an explicit entry must never be overridden
    by the crosswalk.
    """
    if not mapping or not indication:
        return None, None, "unknown"
    raw = str(indication).strip()
    if raw in mapping:
        return mapping[raw], raw, "exact"
    code, how = canonical_subtype_code(raw, contracts_repo)
    if code is not None and code in mapping:
        return mapping[code], code, how
    return None, None, "unknown"
