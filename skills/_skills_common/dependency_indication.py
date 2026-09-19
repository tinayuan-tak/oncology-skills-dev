"""Indication-conditioned dependency reduction + the `dependency` card PREPROCESSOR.

Single home (2026-09-19, Stage 5b) for the logic that reduces the pan-cancer lineage card to the
QUERIED indication's DepMap lineage and writes the resulting class onto the card as
`indication_dependency_class` — the field four interpretation rules (dependency.resolver.yaml rungs
4/5/10/11) fire on. It lives in `_skills_common` (not functional-requirement/scripts/run.py) for one
reason: a preprocessor is registered in `CARD_PREPROCESSORS` and invoked from ALL THREE resolution
paths (standalone dispatcher, target-profile fan-out, compose-dashboard). Logic that lived only in the
skill's run.py would be SILENTLY BYPASSED by the two composed paths — exactly the bug class
card_preprocessors.py's docstring records for genomic-alteration's FDR. run.py imports
`_indication_lineage_read` / `_infer_indication` from here for its ADDITIVE headline by-scope block, so
the classification has a single home rather than being recomputed.

WHY A PREPROCESSOR AT ALL (the architectural constraint): `resolve_verdict` reads only {rule_id} sets,
a rule fires only on a CARD FIELD, and no layer can peek at the run's indication after fired_rules. So
an indication-conditioned verdict requires the class to exist as a card field BEFORE fired_rules — which
is precisely what a card preprocessor is. See interpretation-rules/intracellular-intrinsic.rules.yaml
"E2b" and cards/dependency-lineage-selectivity.card.yaml v3.2.0 for the consuming contract.

NEVER raises: an unreadable crosswalk / absent card degrades to a typed-empty read
(`data_unavailable` / `indication_not_supplied`), never a crash. The pooled pan-cancer verdict is
untouched by everything here.
"""

from __future__ import annotations

import functools

from _skills_common.paths import DEFAULT_CONTRACTS_REPO

__all__ = [
    "_indication_lineage_read",
    "_infer_indication",
    "_indication_lineage_map",
    "_lineage_is_shared",
    "_sublineage_read",
    "_shared_depmap_lineages",
    "_dependency_preprocess",
]


def _card_field(cards, card_id: str, key: str):
    """Graceful summary-field lookup by card id: None when the card is absent OR the key is missing.
    The preprocessor tolerates a missing/excluded card (get_card_field would RAISE on an absent id),
    and the classification must NEVER raise; on a card that IS present the result is identical to
    _skills_common.get_card_field."""
    for c in cards or []:
        if isinstance(c, dict) and c.get("card_id") == card_id:
            return (c.get("summary") or {}).get(key)
    return None


_LINEAGE_DEPENDENCY_CUT = -0.5  # DepMap-standard Chronos threshold for "dependent" (median)
_LINEAGE_UNDERPOWER_FLOOR = 5  # mirrors the card's min_cell_lines_in_lineage


@functools.lru_cache(maxsize=1)
def _indication_lineage_map() -> dict:
    """indication code -> {depmap_lineage, depmap_oncotree_lineage, depmap_oncotree_codes, canonical_code}
    from target-contracts' indication_crosswalk.yaml. Read-only; {} if unavailable (the by-scope layer then
    degrades to a typed-empty indication rung — honest, never a crash). `depmap_oncotree_codes` is the
    OncotreeCode SET present for indications whose coarse DepMap lineage merges >1 disease — it drives the
    sublineage-aware reduction that de-confounds that lineage; absent when the lineage is already pure.

    ALIASES (crosswalk v1.4.0): sub-indication and synonym codes resolve to their canonical entry's lanes.
    Without this, `--indication LUAD` fell through to `{}` and the indication rung reported
    data_unavailable — while SKILL.md advertises LUAD as a worked example, and the analysis-methods
    canonical lineage map has always resolved it. The alias key inherits the canonical entry's lineage
    (LUAD/LUSC → NSCLC → Lung; COAD/READ → COADREAD → Bowel), which is exactly what that map asserts.
    `canonical_code` is carried through so a caller can report WHICH indication actually answered.
    """
    try:
        import yaml

        path = DEFAULT_CONTRACTS_REPO / "vocabularies" / "indication_crosswalk.yaml"
        data = yaml.safe_load(path.read_text()) or {}
        out = {}
        for e in data.get("indications", []):
            code = e.get("canonical_code")
            if not code:
                continue
            out[code] = {
                "depmap_lineage": e.get("depmap_lineage"),
                "depmap_oncotree_lineage": e.get("depmap_oncotree_lineage"),
                "depmap_oncotree_codes": e.get("depmap_oncotree_codes"),
                "canonical_code": code,
            }
        # Second pass so an alias never shadows a canonical code (the crosswalk guards forbid the
        # collision, but resolution order should not depend on that).
        for e in data.get("indications", []):
            code = e.get("canonical_code")
            for alias in e.get("aliases") or []:
                if str(alias) not in out:
                    out[str(alias)] = dict(out[code])
        return out
    except Exception:  # noqa: BLE001 — additive/verdict-inert; absence must not break the spine
        return {}


def _shared_depmap_lineages(lineage_map: dict) -> set:
    """The DepMap lineages that MORE THAN ONE canonical indication maps to.

    Counts CANONICAL codes only. Aliases share their canonical entry's lanes, so counting raw keys
    would read LUAD+LUSC+NSCLC as a 3-way split of `Lung` and make every aliased lineage look shared
    on its own. `canonical_code` is carried on every entry (including alias entries, which copy it
    from the canonical) precisely so this collapse is possible; the dict key is the fallback for a
    hand-built fixture that omits it.

    NOT cached: it is a ~40-entry pass over the already-cached `_indication_lineage_map()`, and caching
    it would go stale under a test that monkeypatches that map — an lru_cache warmed by the real
    crosswalk silently ignores the patch and the test measures nothing.
    """
    by_lineage: dict[str, set] = {}
    for key, xw in (lineage_map or {}).items():
        lineage = xw.get("depmap_lineage") if isinstance(xw, dict) else None
        if not lineage:
            continue
        by_lineage.setdefault(str(lineage), set()).add(xw.get("canonical_code") or key)
    return {lineage for lineage, codes in by_lineage.items() if len(codes) > 1}


def _lineage_is_shared(xw: dict) -> bool:
    """Does the indication's coarse DepMap lineage merge more than one disease?

    DERIVED from the crosswalk rather than hardcoded. This used to be
    `_SHARED_DEPMAP_LINEAGES = {"Lung", "Esophagus/Stomach"}` — a hand-maintained 2-element set that went
    stale the moment another shared lineage was wired. It was wrong for at least two live indications:
    Bowel is 133/146 colorectal adenocarcinoma but also carries anal squamous, small-bowel, appendiceal
    and GI-neuroendocrine models, and Eye is 16/29 uveal melanoma alongside retinoblastoma and
    non-cancerous retinal lines. Both reported shared_lineage_caveat: false on a genuinely confounded
    coarse read.

    Sharedness has TWO INDEPENDENT sources of evidence in the crosswalk and needs BOTH, because
    neither covers the other's cases:

      (a) MULTIPLICITY — ≥2 canonical indications declare the same `depmap_lineage`. This is a property
          of a lane populated 34/35 (only THYM lacks one), so it cannot decay as authoring lags. It is
          the ONLY evidence for GBM and LGG (both `CNS/Brain`, pooled with EACH OTHER), KIRC (`Kidney`,
          with KICH/KIRP), SKCM (`Skin`, with BCC), UCEC (`Uterus`, with UCS) and AML (`Myeloid`, with
          CML) — six LIVE indications.

      (b) STRICT-SUBSET DECLARATION — `depmap_oncotree_codes` present means a curator asserted this
          indication is a strict subset of its coarse lineage. This is the only evidence when the OTHER
          lineage members are not themselves crosswalk indications: `Bowel` is 133/146 colorectal
          adenocarcinoma but also carries anal squamous, small-bowel, appendiceal and GI-neuroendocrine
          models, and `Eye` is 16/29 uveal melanoma alongside retinoblastoma and non-cancerous retinal
          lines. COADREAD and UVM are each the SOLE crosswalk indication on their lineage, so (a) reads
          them as pure.

    Using (b) alone was the previous implementation, on the claim that the code set "is present exactly
    when the indication is a STRICT SUBSET of its coarse lineage." That biconditional is false — the
    field is authored per-indication and filled on only 6 of 35 — so the check inherited the field's
    sparseness and re-shipped, for the six indications in (a), the very bug it replaced the hardcoded
    `{"Lung", "Esophagus/Stomach"}` set to fix. Using (a) alone would symmetrically regress the Bowel
    and Eye cases in (b). The union is what the two lanes jointly know.

    `depmap_oncotree_codes` also remains the RESOLUTION mechanism (see `_sublineage_read`): either
    signal RAISES the caveat, a code set is what lets a run CLEAR it.
    """
    if xw.get("depmap_oncotree_codes"):
        return True
    return str(xw.get("depmap_lineage") or "") in _shared_depmap_lineages(_indication_lineage_map())


def _sublineage_read(cards, codes: list) -> dict | None:
    """Aggregate the ADDITIVE per_oncotree_code_stats over an indication's OncotreeCode SET —
    the de-confounded read for a SHARED coarse lineage (e.g. STAD = STAD+TSTAD+… separate from ESCA;
    NSCLC = LUAD+LUSC+… separate from SCLC). Returns {n, median_chronos, fraction_strongly_dependent,
    matched_codes, per_code} or None when the field / matching codes are unavailable (→ caller falls back
    to the coarse-lineage path). median is n-WEIGHTED across codes (per-code raw scores aren't retained
    in the summary) — an approximation adequate for the indication-scope classification; the verdict is
    pan-cancer and untouched."""
    rows = _card_field(cards, "dependency-lineage-selectivity", "per_oncotree_code_stats")
    if not isinstance(rows, list) or not rows or not codes:
        return None
    codeset = {str(c) for c in codes}
    matched = [r for r in rows if isinstance(r, dict) and str(r.get("oncotree_code")) in codeset]
    matched = [r for r in matched if isinstance(r.get("n"), (int, float)) and r.get("median_chronos") is not None]
    if not matched:
        return None
    n_total = sum(r["n"] for r in matched)
    if n_total <= 0:
        return None
    wmed = sum(r["median_chronos"] * r["n"] for r in matched) / n_total
    wfrac = sum((r.get("fraction_strongly_dependent") or 0.0) * r["n"] for r in matched) / n_total
    return {
        "n": int(n_total),
        "median_chronos": round(wmed, 4),
        "fraction_strongly_dependent": round(wfrac, 4),
        "matched_codes": sorted(r["oncotree_code"] for r in matched),
        "per_code": [
            {"oncotree_code": r["oncotree_code"], "n": r["n"], "median_chronos": r["median_chronos"]} for r in matched
        ],
    }


def _infer_indication(cards) -> str | None:
    """The queried indication is not threaded into headline_fn (signature is (cards, fired, verdict_pair)),
    but several indication-aware cards echo it (abundance-dependency, recommended-models). Take the first
    non-null `indication` across card summaries; None → the indication rung is typed-empty."""
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        ind = (c.get("summary") or {}).get("indication")
        if isinstance(ind, str) and ind.strip():
            return ind.strip().upper()
    return None


def _indication_lineage_read(cards, indication) -> dict:
    """Reduce the pan-cancer lineage card to the QUERIED indication's DepMap lineage. Reads the
    already-emitted per_lineage_stats + enriched_lineages (guarding the fixture's non-list placeholder)
    + the crosswalk. Returns a typed read {scope:'indication', class, ...}; class ∈
    {selective_in_indication, dependent_not_enriched, not_dependent_in_indication, underpowered,
    not_in_panel, data_unavailable}. NEVER raises; NEVER touches dependency_verdict."""
    read = {
        "scope": "indication",
        "indication": indication,
        "depmap_lineage": None,
        "class": "data_unavailable",
        "is_enriched": False,
        "median_chronos": None,
        "n": None,
        "q_value": None,
        "effect_size": None,
        "shared_lineage_caveat": False,
        "_note": None,
    }
    if not indication:
        read["_note"] = "no indication in query (target-grain run) — indication rung not computed"
        return read
    xw = _indication_lineage_map().get(indication) or {}
    lineage = xw.get("depmap_lineage")
    read["depmap_lineage"] = lineage
    # Distinguish the two ways an indication yields no lineage — they mean opposite things to a reader.
    # UNKNOWN: the code is not in the vocabulary at all (typo, or an indication the framework has not
    # curated) → the indication answer is MISSING, and the pooled verdict must not be read as one.
    # NO-LINEAGE: the code IS curated but DepMap has no such lineage (THYM), so no scoping is possible
    # however good the query — a permanent data boundary, not a lookup failure.
    if not xw:
        read["_note"] = (
            f"indication '{indication}' is not in the framework indication vocabulary "
            "(indication_crosswalk.yaml canonical_code or aliases) — no indication-scoped read is possible; "
            "the pooled verdict is TARGET-GRAIN and must not be read as an answer for this indication"
        )
        return read
    if not lineage:
        read["_note"] = (
            f"indication {indication} is curated but DepMap has no corresponding lineage, so no "
            "indication-scoped dependency read is possible from this panel"
        )
        return read
    read["shared_lineage_caveat"] = _lineage_is_shared(xw)

    # SUBLINEAGE de-confounding (Phase 3b): when the indication maps to a SHARED coarse lineage (STAD/ESCA
    # → Esophagus/Stomach; NSCLC/SCLC → Lung; COADREAD ⊂ Bowel; UVM ⊂ Eye) AND the crosswalk supplies its
    # OncotreeCode set, reduce at
    # the SUBLINEAGE grain (per_oncotree_code_stats aggregated over the code-set) instead of the confounded
    # coarse lineage — this RESOLVES the shared_lineage_caveat rather than merely flagging it. Falls back to
    # the coarse-lineage path when the field or code-set is unavailable (e.g. the offline fixture).
    #
    # The two conditions are now INDEPENDENT, which is the point of the caveat fix. They used to be the
    # same test written twice: the caveat was itself `bool(codes)`, so `and codes` was tautological and
    # the only way to keep a True caveat was for `_sublineage_read` to fail. Sharedness now comes from
    # lineage multiplicity, so a shared lineage with NO authored code set (GBM/LGG, KIRC, SKCM, UCEC,
    # AML) correctly skips this block and KEEPS its caveat instead of silently reading as unconfounded.
    codes = xw.get("depmap_oncotree_codes")
    if read["shared_lineage_caveat"] and codes:
        sub = _sublineage_read(cards, codes)
        if sub is not None:
            read["shared_lineage_caveat"] = False  # resolved at sublineage grain
            read["sublineage_resolved"] = True
            read["matched_oncotree_codes"] = sub["matched_codes"]
            read["per_oncotree_code"] = sub["per_code"]
            n, med = sub["n"], sub["median_chronos"]
            read.update(median_chronos=med, n=n)
            if n < _LINEAGE_UNDERPOWER_FLOOR:
                read.update(
                    **{
                        "class": "underpowered",
                        "_note": f"{indication} sublineage {sub['matched_codes']} n={n} (< floor)",
                    }
                )
            elif med <= _LINEAGE_DEPENDENCY_CUT:
                read.update(
                    **{
                        "class": "dependent_not_enriched",
                        "_note": (
                            f"{indication} sublineage-resolved (codes {sub['matched_codes']}, "
                            f"n={n}): n-weighted median {med:.2f} — dependent, de-confounded "
                            f"from the shared {lineage} lineage"
                        ),
                    }
                )
            else:
                read.update(
                    **{
                        "class": "not_dependent_in_indication",
                        "_note": (
                            f"{indication} sublineage-resolved (codes {sub['matched_codes']}, "
                            f"n={n}): n-weighted median {med:.2f} above the dependency cut"
                        ),
                    }
                )
            return read

    def _row(rows, key):
        if not isinstance(rows, list):
            return None
        return next((r for r in rows if isinstance(r, dict) and r.get(key) == lineage), None)

    enriched = _row(_card_field(cards, "dependency-lineage-selectivity", "enriched_lineages"), "lineage")
    per_lineage = _row(_card_field(cards, "dependency-lineage-selectivity", "per_lineage_stats"), "lineage")

    # 1) queried lineage is a SIGNIFICANT enrichment hit → the dependency IS selective to this indication
    if enriched is not None:
        read.update(
            **{
                "class": "selective_in_indication",
                "is_enriched": True,
                "median_chronos": enriched.get("median_chronos"),
                "n": enriched.get("n"),
                "q_value": enriched.get("q_value"),
                "effect_size": enriched.get("effect_size"),
            }
        )
        read["_note"] = f"{lineage} is a significant lineage-selective hit for this dependency"
        return read
    # 2) present in the full per-lineage table but not an enrichment hit → classify by median depth
    if per_lineage is not None:
        n, med = per_lineage.get("n"), per_lineage.get("median_chronos")
        read.update(median_chronos=med, n=n)
        if isinstance(n, (int, float)) and n < _LINEAGE_UNDERPOWER_FLOOR:
            read.update(**{"class": "underpowered", "_note": f"{lineage} has n={n} (< floor)"})
        elif isinstance(med, (int, float)) and med <= _LINEAGE_DEPENDENCY_CUT:
            read.update(
                **{
                    "class": "dependent_not_enriched",
                    "_note": f"{lineage} is dependent (median {med:.2f}) but not lineage-selectively so",
                }
            )
        else:
            read.update(
                **{
                    "class": "not_dependent_in_indication",
                    "_note": f"{lineage}: median Chronos {med} above the dependency cut",
                }
            )
        return read
    # 3) enriched_lineages had no hit AND the full table is unavailable (fixture placeholder) or the
    #    lineage is genuinely absent from the panel — distinguish only when the table is a real list.
    pls = _card_field(cards, "dependency-lineage-selectivity", "per_lineage_stats")
    if isinstance(pls, list):
        read.update(**{"class": "not_in_panel", "_note": f"{lineage} not among screened lineages"})
    else:
        read["_note"] = (
            f"{lineage} not an enrichment hit; full per-lineage table unavailable this run "
            "(cannot distinguish not-dependent from absent)"
        )
    return read


# ── the `dependency` card PREPROCESSOR (registered in _skills_common.card_preprocessors) ─────────────
# Card-id target enum values written onto `indication_dependency_class` (card v3.2.0 vocabulary):
#   selective_in_indication / dependent_not_enriched / not_dependent_in_indication  (measured)
#   underpowered / not_in_panel / data_unavailable                                  (could-not-look)
#   indication_not_supplied                                                          (target-grain run)
# The first six are exactly _indication_lineage_read's `class`; the seventh is written HERE (never by
# the read) when no card echoes an indication, and DELIBERATELY has no rule / no rung, so a target-grain
# run falls through to the pooled/shape ladder and `lineage_selective` stays reachable.
def _dependency_preprocess(cards: list[dict]) -> dict:
    """Write `indication_dependency_class` onto dependency-lineage-selectivity BEFORE fired_rules, in
    EVERY resolution path (mutates the card summary in place; idempotent). This is what makes the four
    indication-conditioned resolver rungs reachable — until it runs the tokens are consumed-but-never-
    produced.

    ALWAYS writes the field when the card is present. `indication_not_supplied` when NO card echoes a
    queried indication (a target-grain run — the question was not asked, NOT a data gap). Otherwise the
    _indication_lineage_read class, which is `data_unavailable` when an indication WAS recovered but the
    lineage read produced no per-lineage table. A silently-absent field would let the verdict degrade to
    a lower rung with no signal, so the write is unconditional on card presence."""
    card = next(
        (c for c in cards or [] if isinstance(c, dict) and c.get("card_id") == "dependency-lineage-selectivity"),
        None,
    )
    if card is None:
        return {"applied": False, "reason": "no_dependency_lineage_selectivity_card"}
    indication = _infer_indication(cards)
    if not indication:
        read = {
            "scope": "indication",
            "indication": None,
            "class": "indication_not_supplied",
            "_note": "target-grain run — no indication in query; falls through to the pooled/shape ladder",
        }
    else:
        read = _indication_lineage_read(cards, indication)
    summ = card.get("summary")
    if not isinstance(summ, dict):
        summ = {}
        card["summary"] = summ
    summ["indication_dependency_class"] = read["class"]
    return {
        "applied": True,
        "indication": indication,
        "indication_dependency_class": read["class"],
        "read": read,
    }
