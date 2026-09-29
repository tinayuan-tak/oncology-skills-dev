"""dgidb_drug_gene.read — per-target known-drug / druggable-category tractability (the PHARMACOLOGY leg).

Complements the tractability-small-molecule gate's STRUCTURE leg (structure-features-static /
structure-ligandability-per-protein-v1) with a KNOWN-DRUG signal: has a drug actually been
catalogued against this gene, and is it in a recognized druggable-genome category? Reads the
per-gene DGIdb rollup (dgidb-drug-gene-per-gene-v1, gene-symbol keyed).

known_drug_tractability_class (first match — strongest wins, mirrors the product's druggability_tier):
  approved_drug_tractable   — >=1 APPROVED-drug interaction (a drug against this target is approved)
  clinically_actionable     — DGIdb CLINICALLY ACTIONABLE category (clinically-relevant drug, not
                              necessarily approved for this gene)
  druggable_genome          — DGIdb DRUGGABLE GENOME category (recognized druggable family), no
                              approved drug / clinical-actionability flag yet
  interaction_only          — has catalogued drug interactions but no druggable category / approval
  category_only             — in a druggable family category but no interaction rows
  no_known_drug_evidence    — gene absent from DGIdb (coverage gap — NOT 'undruggable')

Ordering note vs the product's tier: we hoist APPROVED-drug above clinically_actionable for the
verdict-facing class (an approved drug is the harder pharmacology fact), while the product keeps the
DGIdb-native tier. Both are carried.

FORWARD-vs-RETROSPECTIVE: this is complementary to the PRISM cell-line cards. PRISM asks "does a
compound kill THIS cell line"; DGIdb asks "is there ANY catalogued drug-gene interaction (approved,
tool, or indirect) + druggable-category membership" — a broader, target-intrinsic pharmacology prior.
Absence in DGIdb is a coverage gap, never evidence of undruggability (measured-vs-null discipline).

STALENESS: the underlying DGIdb data self-reports Dec-2023 / v5.0.11 (the source is tagged 2026-06b
but repackaged). See the data-catalog source manifest dgidb-2026-06b.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.roots import contracts_root

PRODUCT_MANIFEST_ID = "dgidb-drug-gene-per-gene-v1"
# DIRECTNESS metadata source (2026-09-04): the per-(gene,drug) directional product carries
# `interaction_types` (inhibitor / antagonist / binder / …). The per-gene rollup above AGGREGATES away
# interaction_type, so a gene's `n_drug_interactions` counts INDIRECT-inclusive records (pathway
# compounds, and even assay dyes / antibodies / shRNA constructs). This second product lets the reader
# count TYPED, DIRECT small-molecule-engaging interactions — the signal that separates a genuine drug
# target (BRAF 44, BTK 64, IDH1 10) from an undruggable TF/scaffold whose interactions are all indirect
# (CTNNB1 1, MYC 0). Reading it is additive: `known_drug_tractability_class` is UNCHANGED (Design B2).
DIRECTIONAL_MANIFEST_ID = "dgidb-drug-target-directional-v1"
METHOD_VERSION = "0.3.0"  # 0.3.0 (2026-09-07, CASE-008 verdict-moving): + MODALITY signal
# (approved_drug_modality) from the curated biologics_precedent_targets.yaml
# crosswalk (via TARGET_CONTRACTS_ROOT). A BIOLOGICS-ONLY approved antigen
# (no approved SM) now resolves approved_drug_engagement_class=approved_biologic_only
# (new; takes precedence over approved_direct/indirect) so the resolver's
# SM-supportive approved-drug rung can be gated on modality. known_drug_tractability_class
# UNCHANGED. Dual-modality targets (EGFR/ERBB2/MET) carry NO biologics_only flag in the vocab and
# are NOT demoted — the osimertinib guard.
# 0.2.0 (2026-09-04): + directness metadata (n_direct_interactions,
# direct_engagement_class, approved_drug_engagement_class) from the directional
# product; known_drug_tractability_class UNCHANGED. Additive/verdict-inert here.

# ── MODALITY crosswalk (CASE-008) ────────────────────────────────────────────────────────────────
# DGIdb's has_approved_drug is modality-BLIND — it tabulates an approved drug of ANY modality against the
# gene, so a biologics-only antigen (DLL3 TCE, FOLR1/NECTIN4 ADC) can credit the DRUG axis as small-
# molecule tractability. The pragmatic modality source is the curated target-contracts crosswalk
# biologics_precedent_targets.yaml (entries carry a `modality:` tag + an explicit `biologics_only:` flag).
# The gate is FAIL-SAFE / positive-only: a target is demoted ONLY when its entry carries
# `biologics_only: true`. Dual-modality targets with an approved small molecule (EGFR/ERBB2/MET) carry NO
# such flag and are NEVER demoted (the osimertinib guard); an entry with the flag absent, or an
# unreadable/absent crosswalk → prior modality-blind behaviour (byte-stable). So this reader can land
# BEFORE the vocab is flagged with zero behaviour change.
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
DEFAULT_TARGET_CONTRACTS = Path(contracts_root())
BIOLOGICS_PRECEDENT_VOCAB_RELPATH = "vocabularies/biologics_precedent_targets.yaml"

# The DGIdb interaction_type tokens that denote a DIRECT small-molecule engaging mechanism (the compound
# ACTS ON the target). Excludes antibody / vaccine (not SM) and untyped/other records (which do not
# establish direct engagement — the inflation noise). Deliberately BROAD across binding MoAs (inhibitor,
# antagonist, agonist, modulator, blocker, binder) so a target druggable via a non-inhibitor mechanism is
# never false-demoted; narrowing only raises the risk of a false negative.
DIRECT_SM_INTERACTION_TYPES = frozenset(
    {
        "inhibitor",
        "antagonist",
        "blocker",
        "binder",
        "agonist",
        "partial agonist",
        "inverse agonist",
        "modulator",
        "negative modulator",
        "positive modulator",
        "allosteric modulator",
        "inhibitory allosteric modulator",
        "activator",
        "suppressor",
        "cleavage",
    }
)
# The count of DIRECT typed interactions at/above which the approved-drug signal is credited as DIRECT
# engagement (approved_direct); below it, an approved drug rests on an indirect-inclusive roster
# (approved_indirect_only). Calibrated LIVE on the reference panel (2026-09-04): the natural gap sits
# between TP53 (6) and SMARCA4 (2) — 5 keeps every genuine druggable (BRAF 44, KRAS 43, EGFR 157, BTK 64,
# IDH1 10, MAP2K1 31, MET 65, STAT3 11, and TP53 6 via mutant-p53 reactivators) and demotes the
# undruggable-TF/scaffold inflation (CTNNB1 1, MYC 0, MYCN 0, GATA3 0, MECOM 0, SMARCA4 2, WRN 0).
DIRECT_ENGAGEMENT_MIN = 5


@lru_cache(maxsize=1)
def _load_biologics_precedent(target_contracts_dir: str = None) -> dict:
    """Curated biologics-precedent crosswalk (entries keyed by HGNC symbol; each value carries
    `modality` + optional `biologics_only`). {} on any failure — an unreadable vocab must never break the
    DGIdb read (fail toward prior modality-blind behaviour)."""
    import yaml

    path = Path(target_contracts_dir or DEFAULT_TARGET_CONTRACTS) / BIOLOGICS_PRECEDENT_VOCAB_RELPATH
    try:
        return (yaml.safe_load(path.read_text()) or {}).get("entries", {}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _biologic_precedent_for(sym: str, target_contracts_dir: str = None) -> Optional[dict]:
    """Crosswalk entry for one gene ({modality, biologics_only, ...}) or None if the target is not a
    curated biologics-precedent antigen (or the vocab is unreadable)."""
    entry = _load_biologics_precedent(target_contracts_dir).get((sym or "").strip().upper())
    return entry if isinstance(entry, dict) else None


def _approved_drug_modality(has_approved: bool, precedent: Optional[dict]) -> tuple[str, Optional[str]]:
    """(approved_drug_modality, biologic_modality_tag). Characterises the MODALITY of the approved drug
    behind DGIdb's has_approved_drug flag using the curated crosswalk:
      not_applicable            — no approved-drug flag (nothing to characterise)
      biologic                  — has_approved AND the target is a BIOLOGICS-ONLY antigen (in the
                                  crosswalk with biologics_only: true) — the DRUG flag is a biologic
      small_molecule_or_unknown — has_approved but NOT biologics-only (a genuine/dual SM target, or a
                                  target absent from the crosswalk — DGIdb cannot tell, assume SM/unknown)
    The second element is the raw modality tag (adc/tce/...) when biologic, else None."""
    if not has_approved:
        return "not_applicable", None
    if precedent is not None and bool(precedent.get("biologics_only", False)):
        return "biologic", (precedent.get("modality") or "biologic")
    return "small_molecule_or_unknown", None


def _read_dgidb_row(target: str) -> Optional[dict]:
    """Pushdown-read the per-gene DGIdb rollup for one gene symbol. None if unresolvable/absent."""
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

        # A GENUINELY absent object (NoSuchKey/404, or pyarrow/s3fs FileNotFoundError) means the
        # DGIdb product truly has no row for this gene -> None -> _classify(None) ->
        # no_known_drug_evidence, the honest coverage-gap class (unchanged semantics; a gene absent
        # from DGIdb legitimately has no known drug). A transient/creds/broken-env failure (throttle,
        # expired token, missing pyarrow) is NOT absence -> re-raise so the live-read seam surfaces an
        # honest _live_read_error, never a false "no_known_drug_evidence" for a live gene.
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return None
        raise
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def _read_directional_rows(target: str) -> Optional[list]:
    """Pushdown-read the per-(gene,drug) directional interaction rows for one gene. Returns a list of
    {drug_name_norm, interaction_types, is_approved, is_antineoplastic} rows; [] if the gene is genuinely
    absent from the directional product (has no TYPED interaction — the honest MYC/GATA3 case); None on a
    transient/creds/broken-env failure so the caller leaves directness UNMEASURED rather than falsely 0."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(DIRECTIONAL_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[("gene_symbol", "=", (target or "").strip().upper())],
        )
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return []
        raise
    return tbl.to_pylist()


def _count_direct(rows: Optional[list]) -> Optional[int]:
    """Count directional rows carrying at least one DIRECT small-molecule interaction_type. None when
    directness is unmeasured (transient read failure); 0 when genuinely no typed-direct interaction."""
    if rows is None:
        return None
    n = 0
    for r in rows:
        raw = str((r or {}).get("interaction_types") or "")
        toks = {t.strip().lower() for part in raw.split("|") for t in part.split(",") if t.strip()}
        if toks & DIRECT_SM_INTERACTION_TYPES:
            n += 1
    return n


def _direct_engagement_class(n_direct: Optional[int]) -> str:
    """direct_engagement_class from the typed-direct count. UNMEASURED preserves the coverage gap."""
    if n_direct is None:
        return "unmeasured"
    if n_direct >= DIRECT_ENGAGEMENT_MIN:
        return "direct_typed"
    if n_direct >= 1:
        return "sparse_direct"  # 1-4 typed-direct interactions — a weak/uncorroborated direct hit
    return "indirect_or_untyped_only"  # zero typed-direct — interactions (if any) are indirect/untyped


def _approved_drug_engagement_class(has_approved: bool, direct_class: str, is_biologics_only: bool = False) -> str:
    """The RESOLVER-KEYED field (Design B2): fuse the approved-drug flag with directness + MODALITY so the
    resolver can gate the approved rung WITHOUT the reader touching known_drug_tractability_class.
      approved_biologic_only — has_approved AND the target is a BIOLOGICS-ONLY antigen (CASE-008): the
                               approved drug is a biologic (ADC/TCE/CAR), NOT a small molecule, so it must
                               not credit SM tractability. Takes PRECEDENCE over direct/indirect — a
                               biologics antigen with false-direct DGIdb records (CEACAM5, 8 mistyped
                               interactions) is still biologics-only. Dual-modality SM targets
                               (EGFR/ERBB2/MET; no biologics_only flag) are NOT biologics-only → unaffected.
      approved_direct        — approved drug + DIRECT engagement (>=5 typed) or directness unmeasured
                               (fail toward the prior behaviour on a transient read failure).
      approved_indirect_only — approved drug catalogued, but the roster is indirect/sparse.
    Non-approved genes → not_approved (the approved rung never fired for them anyway)."""
    if not has_approved:
        return "not_approved"
    if is_biologics_only:
        return "approved_biologic_only"
    if direct_class in ("direct_typed", "unmeasured"):
        return "approved_direct"
    return "approved_indirect_only"  # approved drug catalogued, but the roster is indirect/sparse


def _classify(row: Optional[dict]) -> str:
    """Map a DGIdb rollup row -> known_drug_tractability_class (approved hoisted above clinical)."""
    if row is None:
        return "no_known_drug_evidence"
    if bool(row.get("has_approved_drug")):
        return "approved_drug_tractable"
    if bool(row.get("is_clinically_actionable")):
        return "clinically_actionable"
    if bool(row.get("is_druggable_genome")):
        return "druggable_genome"
    if int(row.get("n_drug_interactions") or 0) >= 1:
        return "interaction_only"
    if int(row.get("n_categories") or 0) >= 1:
        return "category_only"
    return "no_known_drug_evidence"


_UNSET = object()


def known_drug_tractability_for_gene(
    target: str,
    dgidb_row: Optional[dict] = None,
    directional_rows: Optional[list] = None,
    biologic_precedent=_UNSET,
    target_contracts_dir: Optional[str] = None,
) -> dict:
    """Per-target known-drug / druggable-category tractability. dgidb_row / directional_rows may be
    injected for tests (directional_rows=None triggers a live directional read unless dgidb_row is
    injected, in which case the live read is skipped and directness is left UNMEASURED for unit tests
    that only exercise the rollup).

    biologic_precedent (CASE-008): the curated crosswalk entry ({modality, biologics_only} | None). Pass it
    to inject the modality signal in tests; leave UNSET for a live crosswalk read (skipped when dgidb_row
    was injected, matching the directional-read convention → modality unread for pure-rollup unit tests)."""
    sym = (target or "").strip().upper()
    row = dgidb_row if dgidb_row is not None else _read_dgidb_row(sym)
    klass = _classify(row)
    # DIRECTNESS (2026-09-04): count TYPED direct-SM interactions from the directional product. Skip the
    # live directional read when dgidb_row was injected (unit-test path) → directness unmeasured. Additive
    # fields only; known_drug_tractability_class above is UNCHANGED.
    if directional_rows is None and dgidb_row is None:
        directional_rows = _read_directional_rows(sym)
    n_direct = _count_direct(directional_rows)
    direct_class = _direct_engagement_class(n_direct)
    has_approved = bool((row or {}).get("has_approved_drug", False))
    # MODALITY (CASE-008): resolve the curated biologics-precedent crosswalk. Skip the live read when
    # dgidb_row was injected (pure-rollup unit-test path) unless the caller injected biologic_precedent.
    if biologic_precedent is _UNSET:
        precedent = _biologic_precedent_for(sym, target_contracts_dir) if dgidb_row is None else None
    else:
        precedent = biologic_precedent
    approved_modality, biologic_modality_tag = _approved_drug_modality(has_approved, precedent)
    is_biologics_only = approved_modality == "biologic"
    approved_engagement = _approved_drug_engagement_class(has_approved, direct_class, is_biologics_only)
    return {
        "known_drug_tractability_class": klass,
        "druggability_tier": (row or {}).get("druggability_tier"),  # DGIdb-native tier (passthrough)
        "is_druggable_genome": bool((row or {}).get("is_druggable_genome", False)),
        "is_clinically_actionable": bool((row or {}).get("is_clinically_actionable", False)),
        "has_approved_drug": has_approved,
        "n_drug_interactions": int((row or {}).get("n_drug_interactions") or 0),
        "n_approved_drug_interactions": int((row or {}).get("n_approved_drug_interactions") or 0),
        "n_antineoplastic_interactions": int((row or {}).get("n_antineoplastic_interactions") or 0),
        "gene_categories": (row or {}).get("gene_categories"),
        # ── DIRECTNESS metadata (additive; drives the resolver directness gate in target-contracts) ──
        "n_direct_interactions": n_direct,  # typed DIRECT-SM interactions (None=unmeasured)
        "direct_engagement_class": direct_class,  # direct_typed / sparse_direct / indirect_or_untyped_only / unmeasured
        "approved_drug_engagement_class": approved_engagement,  # RESOLVER-KEYED: approved_biologic_only / approved_direct / approved_indirect_only / not_approved
        # ── MODALITY metadata (CASE-008; drives the resolver modality gate in target-contracts) ──
        "approved_drug_modality": approved_modality,  # biologic / small_molecule_or_unknown / not_applicable
        "approved_drug_modality_tag": biologic_modality_tag,  # raw crosswalk tag (adc/tce/...) when biologic, else None
        "known_drug_context": _context(sym, klass, row),
        "directness_context": _directness_context(sym, klass, n_direct, approved_engagement),
        "modality_context": _modality_context(sym, approved_modality, biologic_modality_tag),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }


def _modality_context(sym, approved_modality, tag) -> Optional[str]:
    """Human line explaining the MODALITY read — surfaces WHY a biologics-only antigen's approved-drug
    flag is NOT small-molecule tractability evidence (the CASE-008 modality mismatch)."""
    if approved_modality == "biologic":
        return (
            f"{sym}: the approved/precedented agent is a BIOLOGIC (modality={tag} — antibody-drug "
            "conjugate / T-cell engager / CAR), NOT a small molecule. DGIdb's has_approved_drug is "
            "modality-blind, so this DRUG-axis signal is biologics-precedent, NOT evidence of "
            "small-molecule druggability (biologics_precedent_targets.yaml, curated)."
        )
    return None


def _directness_context(sym, klass, n_direct, approved_engagement) -> Optional[str]:
    """Human line explaining the directness read — surfaces WHY an approved-drug target may be
    indirect-only (the CTNNB1/MYC undruggable-TF inflation)."""
    if n_direct is None:
        return f"{sym}: DGIdb directional product unread — directness UNMEASURED (not demoting)."
    if approved_engagement == "approved_indirect_only":
        return (
            f"{sym}: an approved drug is catalogued, but only {n_direct} DIRECT typed small-molecule "
            f"interaction(s) (< {DIRECT_ENGAGEMENT_MIN}) — the roster is dominated by INDIRECT / "
            "pathway / untyped records, so approved-drug tractability is annotation-driven, not a "
            "demonstrated direct binder. Confirm target-directness from the literature."
        )
    if approved_engagement == "approved_direct":
        return (
            f"{sym}: {n_direct} DIRECT typed small-molecule interaction(s) (>= {DIRECT_ENGAGEMENT_MIN}) "
            "— an approved drug rests on demonstrated direct engagement."
        )
    return f"{sym}: {n_direct} DIRECT typed small-molecule interaction(s); no approved-drug flag."


def _context(sym: str, klass: str, row: Optional[dict]) -> Optional[str]:
    if klass == "no_known_drug_evidence":
        return (
            f"{sym}: absent from DGIdb (no catalogued drug-gene interaction or druggable "
            f"category). A coverage gap — NOT evidence of undruggability."
        )
    n_int = int((row or {}).get("n_drug_interactions") or 0)
    n_appr = int((row or {}).get("n_approved_drug_interactions") or 0)
    n_antineo = int((row or {}).get("n_antineoplastic_interactions") or 0)
    cats = (row or {}).get("gene_categories") or ""
    if klass == "approved_drug_tractable":
        return (
            f"{sym}: {n_appr} approved-drug interaction(s) of {n_int} total "
            f"({n_antineo} antineoplastic) in DGIdb — a drug against this target is approved "
            f"(known-drug tractability demonstrated). Categories: {cats}."
        )
    if klass == "clinically_actionable":
        return (
            f"{sym}: DGIdb CLINICALLY ACTIONABLE ({n_int} drug interactions, {n_antineo} "
            f"antineoplastic) — a clinically-relevant drug exists. Categories: {cats}."
        )
    if klass == "druggable_genome":
        return (
            f"{sym}: in the DGIdb DRUGGABLE GENOME category ({n_int} interactions) — a "
            f"recognized druggable family, no approved/clinically-actionable flag yet. Categories: {cats}."
        )
    if klass == "interaction_only":
        return f"{sym}: {n_int} catalogued drug interaction(s) but no druggable-category membership."
    if klass == "category_only":
        return f"{sym}: in a DGIdb family category ({cats}) but no catalogued drug interactions."
    return None
