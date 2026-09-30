#!/usr/bin/env python3
"""subgroup_assigner_maf_filter CLI — generate per-sample subgroup assignments
from MAF (mutation annotation format) predicates.

Invocation:
    subgroup-assigner-maf-filter \
      --subgroup-catalog /path/to/coadread-subgroups-2026-q2.yaml \
      --data-source tcga \
      --release-pin 2026-Q2 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

The CLI:
  1. Loads the subgroup_catalog YAML; filters to atomic_strata with
     derivation_source == maf_filter_per_rule.
  2. Resolves the MAF manifest per data-source
     (gdc-pancohort-somatic-dr45-0 for TCGA; OmicsSomaticMutations.csv for DepMap).
  3. For each stratum: applies the AND/OR/negation predicate against MAF rows;
     aggregates to sample-level (any-hit-per-sample); emits tri-valued
     is_member per resolver-product design.
  4. Emits assignments.parquet + manifest.yaml conforming to
     subgroup_assignment.schema.json.

Iter-1b implementation — Phase 2a.2 of iDAS Subtype Pipeline. See
target-contracts docs/design/SAMPLE_ANNOTATION_PLAN.md for Modality B design.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click
import pandas as pd
import yaml

from onc_methods.roots import data_catalog_root
from onc_methods.subgroup_common import maf_vocab
from onc_methods.subgroup_common.manifest import emit_assignment_manifest
from onc_methods.subgroup_common.paths import cache_root

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.3.0"  # tri-valued sample aggregation + declared source capability

SUPPORTED_DERIVATION_SOURCES = {"maf_filter_per_rule"}


# ---------- MAF-predicate parser -------------------------------------------
#
# MAF rules in the 8 Phase-1 catalogs come in these forms (from grep):
#
#   `gene_symbol == 'X' && protein_change == 'p.YnnnZ'`        # exact hotspot
#   `gene_symbol == 'X' && protein_change in ['p.Y', ...]`     # any-of hotspots
#   `gene_symbol == 'X' && effect == 'in_frame_deletion' && exon == 19`
#   `gene_symbol == 'X' && effect in ['nonsense', 'frameshift', ...]`
#   `!(gene_symbol == 'KRAS' && protein_change in [...])`       # KRAS-WT (negation)
#   `sample.tmb >= 10`                                           # TMB threshold
#   `fusion_gene == 'ALK'`                                       # fusion (Modality A, but sometimes B)
#   `copy_number.ERBB2 == 'amplified'`                           # copy-number (Modality A)
#
# The parser produces a callable predicate: (row) → bool | None.
# Predicate returns None when a required field is NaN (tri-value:
# insufficient upstream).

_ATOMIC_EQ = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*==\s*'([^']*)'$")
_ATOMIC_IN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s+in\s+\[([^\]]+)\]$")
_ATOMIC_INT_EQ = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*==\s*(\d+)$")
_ATOMIC_GTE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*>=\s*(\d+\.?\d*)$")
_ATOMIC_LTE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_.]*)\s*<=\s*(\d+\.?\d*)$")


def _extract_column_name(lhs: str) -> str:
    """Strip a `namespace.field` prefix down to `field` for DataFrame lookup."""
    if "." in lhs:
        return lhs.split(".", 1)[1]
    return lhs


class RuleContext:
    """Per-source capability context threaded into a compiled predicate.

    `unavailable_effect_tokens` maps a token the SOURCE CANNOT PRODUCE to the parent
    token it refines (or None when there is no parent). It comes from the capability
    sidecar the prefetch step writes next to each MAF parquet
    (methods/subgroup_common/maf_vocab.py).

    This exists because a rule that references something the source cannot supply
    otherwise evaluates to False on every row and the pipeline emits a CONFIDENT
    NEGATIVE. `missense_damaging` on DepMap is the live case: DepMap's MAF has no
    PolyPhen column, so a damaging-missense variant is indistinguishable from a benign
    one. Answering False for `TP53 && effect in [nonsense, frameshift, splice_site,
    missense_damaging]` on a TP53-missense model claims the model is TP53-wild-type. It
    is not; we simply cannot tell. So we abstain on exactly those rows and keep the
    evaluable legs (a nonsense hit is still a True; no TP53 hit at all is still a False).
    """

    __slots__ = ("unavailable_effect_tokens",)

    def __init__(self, unavailable_effect_tokens: dict[str, str | None] | None = None):
        self.unavailable_effect_tokens = dict(unavailable_effect_tokens or {})

    def partition(self, values: list[str]) -> tuple[list[str], set[str], list[str]]:
        """Split a rule's target values into (producible, abstain_on_parents, orphaned).

        - `producible`: values the source can actually emit → a match is a real True.
        - `abstain_on_parents`: parent tokens whose rows have UNKNOWN refinement status
          → return None for those rows rather than False.
        - `orphaned`: unproducible values with no declared parent → nothing in the frame
          can confirm or deny them, so the atom is unevaluable outright.
        """
        producible, parents, orphaned = [], set(), []
        for v in values:
            if v in self.unavailable_effect_tokens:
                parent = self.unavailable_effect_tokens[v]
                if parent:
                    parents.add(parent)
                else:
                    orphaned.append(v)
            else:
                producible.append(v)
        return producible, parents, orphaned


_NO_CONTEXT = RuleContext()


def _atomic_predicate(atom: str, ctx: RuleContext = _NO_CONTEXT):
    """Return a row-level callable for a single atomic predicate.

    The callable returns True/False/None. None = "cannot be evaluated on this row":
    either the source value is NaN, or the atom targets a value this source cannot
    produce and the row might have been it (see RuleContext).
    """
    atom = atom.strip()
    m = _ATOMIC_EQ.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        target = m.group(2)
        producible, parents, orphaned = ctx.partition([target])

        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            if orphaned:
                # The one target value is unproducible with no parent to key on: this
                # atom can never be answered against this source.
                return None
            if v in producible:
                return True
            if v in parents:
                return None
            return False

        return _pred
    m = _ATOMIC_IN.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        values = [v.strip().strip("'\"") for v in m.group(2).split(",")]
        producible, parents, orphaned = ctx.partition(values)

        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            if v in producible:
                return True
            if v in parents:
                return None
            # An orphaned unproducible value means we cannot rule the row OUT either:
            # abstain rather than claim a negative on a partially-answerable set.
            return None if orphaned else False

        return _pred
    m = _ATOMIC_INT_EQ.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        target = int(m.group(2))

        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            try:
                return int(v) == target
            except (ValueError, TypeError):
                return False

        return _pred
    m = _ATOMIC_GTE.match(atom)
    if m:
        col = _extract_column_name(m.group(1))
        target = float(m.group(2))

        def _pred(row):
            v = row.get(col)
            if pd.isna(v):
                return None
            try:
                return float(v) >= target
            except (ValueError, TypeError):
                return False

        return _pred
    raise ValueError(f"Unsupported atomic predicate: {atom!r}")


def _split_top_level(expr: str, sep: str) -> list[str]:
    """Split `expr` on `sep` at bracket-depth 0."""
    parts, depth, cur = [], 0, []
    i = 0
    while i < len(expr):
        c = expr[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
        elif depth == 0 and expr[i : i + len(sep)] == sep:
            parts.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(c)
        i += 1
    parts.append("".join(cur).strip())
    return parts


def compile_rule(rule: str, ctx: RuleContext = _NO_CONTEXT):
    """Compile a MAF-filter rule string into a row-level callable predicate.

    Returns a function (row) → bool | None. None represents "evaluated but not
    answerable on this row" — the resolver-product null semantic. `ctx` carries the
    source's declared capability gaps; the default context assumes nothing is missing.
    """
    rule = rule.strip()

    # Negation wrapper: `!(...)`
    if rule.startswith("!(") and rule.endswith(")"):
        inner = compile_rule(rule[2:-1], ctx)

        def _neg(row):
            r = inner(row)
            return None if r is None else (not r)

        return _neg

    # Conjunction: `a && b && c`
    if "&&" in rule and not (rule.startswith("(") and rule.endswith(")")):
        parts = _split_top_level(rule, "&&")
        if len(parts) > 1:
            compiled = [compile_rule(p, ctx) for p in parts]

            # FULL three-valued AND: a definitive False from ANY conjunct wins over a
            # None from another, and we only return None when nothing settled it. The
            # earlier version returned None on the first None it met, which made the
            # result depend on the ORDER the catalog author happened to write the
            # conjuncts in: `gene_symbol == 'EGFR' && exon == 19` correctly answered
            # False for a TP53 row (gene mismatch settles it) while the equivalent
            # `exon == 19 && gene_symbol == 'EGFR'` nulled EVERY row on a source with no
            # exon column. Same rule, same data, different answer. Order-independence is
            # the point: False-dominance also keeps irrelevant rows from poisoning a
            # sample — a TP53 row with a NaN protein_change must not make a KRAS_WT
            # sample unevaluable.
            def _conj(row):
                any_none = False
                for p in compiled:
                    r = p(row)
                    if r is None:
                        any_none = True
                    elif not r:
                        return False
                return None if any_none else True

            return _conj

    # Disjunction: `a || b` — three-valued OR (True dominates, then None, else False).
    if "||" in rule:
        parts = _split_top_level(rule, "||")
        if len(parts) > 1:
            compiled = [compile_rule(p, ctx) for p in parts]

            def _disj(row):
                any_none = False
                for p in compiled:
                    r = p(row)
                    if r is None:
                        any_none = True
                        continue
                    if r:
                        return True
                return None if any_none else False

            return _disj

    # Fallback: atomic predicate
    return _atomic_predicate(rule, ctx)


# ---------- Source-data loaders --------------------------------------------

# The prefetched-parquet path per (data_source, indication). ONE definition, used both
# by the loaders and by the capability-sidecar read, so the two can never disagree about
# which file is being described.
_PREFETCH_LAYOUT = {
    "tcga": ("framework-gdc-pancohort-somatic", "mc3"),
    "genie": ("framework-genie-public-v19", "genie-maf"),
    "depmap": ("framework-depmap-26q3", "depmap-maf"),
}


def _prefetched_maf_path(data_source: str, indication: str) -> Path | None:
    """Expected prefetched-parquet path, or None for an unknown data source."""
    layout = _PREFETCH_LAYOUT.get(data_source)
    if not layout:
        return None
    dir_slug, tag = layout
    return cache_root() / dir_slug / f"{indication.lower()}-{tag}.parquet"


def _rule_context_for(data_source: str, indication: str, maf: pd.DataFrame) -> tuple[RuleContext, dict | None]:
    """Build the RuleContext from the capability sidecar next to the prefetched MAF.

    An ABSENT sidecar means "undeclared", not "everything available": we return an empty
    context and the caller warns. The independent `_effect_vocabulary_guard` still runs
    on the data itself, so an undeclared source cannot silently reproduce the
    raw-vocabulary defect — it can only under-declare the derived-token gaps.
    """
    path = _prefetched_maf_path(data_source, indication)
    fields = maf_vocab.read_source_fields(path) if path else None
    unavailable = maf_vocab.unavailable_tokens_from_fields(fields)
    if fields is None:
        # No sidecar (a parquet predating it). Fall back to what the FRAME shows: a
        # derived token absent from the emitted `effect` values was not produced.
        #
        # Note this must key on the emitted TOKEN, not on the evidence column: the
        # prefetch consumes PolyPhen to derive `missense_damaging` rows and does not
        # carry PolyPhen into the output parquet, so an evidence-column check would
        # declare the token unproducible for TCGA MC3 too and start abstaining on 181
        # of 277 real HNSC TP53 calls — trading a false-negative defect for a
        # false-abstention one.
        present = set(maf["effect"].dropna().unique()) if "effect" in maf.columns else set()
        for tok, spec in maf_vocab.DERIVED_EFFECT_TOKENS.items():
            if tok not in present and tok not in unavailable:
                unavailable[tok] = spec.refines
    return RuleContext(unavailable), fields


def _load_tcga_maf(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load TCGA MAF for the indication.

    Returns DataFrame with normalized columns: Tumor_Sample_Barcode
    (aliquot) mapped to sample_id (truncated to sample level), plus
    gene_symbol, protein_change, effect, exon (from Consequence/HGVSp fields),
    Variant_Classification.

    Iter-1b: reads from cache fallback pending Phase 2a.4's canonical loader.
    Expected canonical source: s3://onc-compbio/data-catalog/sources/gdc-pancohort-somatic/dr45-0/
    """
    fallback = _prefetched_maf_path("tcga", indication)
    if fallback.exists():
        return pd.read_parquet(fallback)
    csv_fallback = fallback.with_suffix(".csv")
    if csv_fallback.exists():
        return pd.read_csv(csv_fallback)
    raise FileNotFoundError(
        f"TCGA MAF for {indication} not found at {fallback} or {csv_fallback}. "
        f"Phase 2a.4 provides the canonical loader with S3-plus-local-cache. "
        f"For immediate execution: place a MAF-shaped parquet/csv with columns "
        f"(Tumor_Sample_Barcode, gene_symbol, protein_change, effect, exon, ...) "
        f"at the fallback path."
    )


def _load_genie_maf(catalog_repo: Path, indication: str) -> pd.DataFrame:
    """Load GENIE public v19-0 MAF pre-filtered to indication-relevant samples.

    Returns DataFrame with columns already normalized to resolver-product
    convention: sample_id (GENIE-{CENTER}-{PATIENT}-{SAMPLE}), gene_symbol,
    protein_change, effect, plus source_native_id (= sample_id since GENIE
    doesn't have a distinct aliquot-level ID).

    GENIE public v19 covers ~271K samples across ~30 sequencing centers; per
    indication the pre-filter step (via data_clinical_sample.txt CANCER_TYPE)
    reduces this substantially (e.g. Colorectal Cancer = 23,312 samples,
    22,642 with MAF rows). This method reads the pre-filtered per-indication
    parquet from cache; a Phase-2b/c prefetch step is responsible for pulling
    the 1.12 GB MAF from S3 + slicing to the indication.

    Iter-1b: reads from cache fallback pending Phase 2a.4's canonical loader.
    Expected canonical source: s3://onc-compbio/data-catalog/sources/synapse/
    genie-public-v19-0/data_mutations_extended.txt (1.12 GB) filtered via
    data_clinical_sample.txt to the target indication's CANCER_TYPE.
    """
    fallback = _prefetched_maf_path("genie", indication)
    if fallback.exists():
        return pd.read_parquet(fallback)
    raise FileNotFoundError(
        f"GENIE MAF for {indication} not found at {fallback}. "
        f"For immediate execution: pull s3://onc-compbio/data-catalog/sources/"
        f"synapse/genie-public-v19-0/data_mutations_extended.txt (1.12 GB) + "
        f"data_clinical_sample.txt, filter to CANCER_TYPE == '{indication} '"
        f"target, save as {fallback}."
    )


def _load_depmap_somatic_mutations(catalog_repo: Path, indication: str | None = None) -> pd.DataFrame:
    """Load DepMap somatic mutations, normalized to MAF-like shape.

    Prefers the per-indication prefetched parquet produced by
    scripts/prefetch_source_maf.py --source depmap_somatic (already
    lineage-filtered + column-normalized: sample_id / gene_symbol /
    protein_change / effect). Falls back to the raw
    OmicsSomaticMutations.csv only if the prefetched parquet is absent.

    DepMap MAF uses Hugo_Symbol / Protein_Change / Variant_Classification /
    ModelID; the prefetch step already renames these to the resolver
    convention. DepMap Protein_Change is in `p.G12C` HGVS form — identical
    to the catalog rule syntax, no value normalization needed.
    """
    # Prefer prefetched, lineage-filtered, column-normalized parquet
    if indication:
        prefetched = _prefetched_maf_path("depmap", indication)
        if prefetched.exists():
            return pd.read_parquet(prefetched)

    fallback = cache_root() / "framework-depmap-26q3" / "OmicsSomaticMutations.csv"
    if fallback.exists():
        df = pd.read_csv(fallback)
        # Raw CSV needs column normalization (prefetch parquet already has it)
        rename = {
            "Hugo_Symbol": "gene_symbol",
            "Protein_Change": "protein_change",
            "Variant_Classification": "effect",
            "ModelID": "sample_id",
        }
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        # ★ Renaming Variant_Classification to `effect` is NOT normalizing it. This
        # fallback path used to hand raw `Nonsense_Mutation` to rules that test
        # `nonsense` — the same vocabulary mismatch as the prefetch path, in a second
        # place. Map through the canonical vocabulary here too; unmapped classes
        # lowercase so they stay recognizable tokens rather than raw MAF classes.
        if "effect" in df.columns:
            raw = df["effect"]
            df["effect"] = raw.map(maf_vocab.VARIANT_CLASSIFICATION_TO_EFFECT).fillna(raw.astype(str).str.lower())
        if "sample_id" in df.columns:
            df["source_native_id"] = df["sample_id"]
        return df
    raise FileNotFoundError(
        f"No DepMap somatic MAF found for {indication}. Run "
        f"scripts/prefetch_source_maf.py --source depmap_somatic "
        f"--indication {indication or '<IND>'} to produce the prefetched parquet, "
        f"or place OmicsSomaticMutations.csv at {fallback}."
    )


def _cohort_samples_path(data_source: str, indication: str) -> Path | None:
    """Companion FULL-cohort sample list produced alongside the prefetched MAF.

    The prefetch step (scripts/prefetch_source_maf.py) computes the indication cohort
    (`keep_samples` from data_clinical_sample.txt CANCER_TYPE / lineage) but historically
    wrote only the mutation-bearing MAF rows. When it ALSO emits this companion parquet
    (a `sample_id` column, optionally source_native_id / patient_id for the full cohort
    INCLUDING fully-WT tumors), we use it as the WT/negation-stratum denominator. Convention:
    `{indication}-cohort-samples.parquet` in the same cache dir as the MAF."""
    layout = _PREFETCH_LAYOUT.get(data_source)
    if not layout:
        return None
    dir_slug, _tag = layout
    p = cache_root() / dir_slug / f"{indication.lower()}-cohort-samples.parquet"
    return p if p.exists() else None


def _load_cohort_samples(
    data_source: str, indication: str, sample_id_col: str, native_id_col: str, patient_id_col: str | None
):
    """Full-cohort sample frame (INCLUDING zero-mutation tumors) from the companion file, or None.

    Returns a DataFrame with [sample_id_col, native_id_col, (patient_id_col)] deduped on
    sample_id_col, normalizing whatever id columns the companion file carries. None when the
    companion file is absent (caller then falls back to MAF-present samples + a WARNING)."""
    path = _cohort_samples_path(data_source, indication)
    if path is None:
        return None
    df = pd.read_parquet(path)
    # normalize to the id columns the stratum evaluator expects.
    if sample_id_col not in df.columns:
        for alt in ("sample_id", "SAMPLE_ID", "ModelID", "Tumor_Sample_Barcode"):
            if alt in df.columns:
                df = df.rename(columns={alt: sample_id_col})
                break
    if sample_id_col not in df.columns:
        return None  # companion file lacks a usable sample id — ignore it (fall back + WARN)
    if native_id_col not in df.columns:
        df[native_id_col] = df[sample_id_col]
    cols = [sample_id_col, native_id_col]
    if patient_id_col:
        if patient_id_col not in df.columns:
            df[patient_id_col] = None
        cols = [sample_id_col, patient_id_col, native_id_col]
    return df[cols].drop_duplicates(subset=[sample_id_col])


# ---------- Stratum evaluation ---------------------------------------------


def _evaluate_stratum_maf(
    stratum: dict,
    maf_df: pd.DataFrame,
    sample_id_col: str,
    patient_id_col: str | None,
    native_id_col: str,
    all_samples: pd.DataFrame,
    ctx: RuleContext = _NO_CONTEXT,
) -> pd.DataFrame:
    """Evaluate a single MAF-filter stratum with TRUE tri-valued aggregation.

    A stratum is a row-level predicate on MAF rows, aggregated to the sample. Both
    levels are three-valued:

    - per-MAF-row: True / False / None, where None = "not answerable on this row"
      (source value NaN, or the atom targets a value this source cannot produce).
    - per-sample, three-valued OR over that sample's rows:
        * ≥1 row True                     → True  (member; one hit is enough)
        * else ≥1 row None                → None  (ABSTAIN; a hit cannot be excluded)
        * else (all rows False, or the sample has no MAF rows at all
          while being present in the assayed cohort)
                                          → False (genuinely not a member)

    ★ The third bullet used to be the only outcome besides True. `is_member` was
    computed as `sid in hit_set` — a plain Python bool — so this method could NOT emit
    null at all, and every unanswerable row was reported as a confident NEGATIVE. That
    is how 13 effect-referencing strata came to report clean zeros over full
    denominators on the DepMap cohort: a 0-of-95 reads as biology, and is therefore far
    more likely to be believed than an all-null. Measured + fixed 2026-09-13.

    A sample absent from the MAF but present in `all_samples` stays False on purpose:
    the cohort file means ASSAYED, so zero mutation rows is a real negative, not a gap.
    That distinction is what keeps this from degenerating into blanket abstention — an
    over-broad null is a different failure, not a safer one.

    SAMPLE-LEVEL NEGATION (`!(...)`): a wild-type stratum like KRAS-WT means the
    SAMPLE carries no matching mutation — NOT that some row fails to match. A
    row-level `!(...)` predicate is True for every non-KRAS row (a TP53 row is
    "not a KRAS hotspot"), so any-hit aggregation would mark every mutated sample
    a member. We instead detect the top-level negation, evaluate the INNER
    predicate, and take the sample-level complement: member iff the sample has
    ZERO inner-hit rows (across the assayed cohort). The complement is taken over the
    tri-value, so an unresolved inner state stays unresolved rather than becoming WT.
    """
    rule = stratum["rule"].strip()
    is_sample_negation = rule.startswith("!(") and rule.endswith(")")
    predicate = compile_rule(rule[2:-1], ctx) if is_sample_negation else compile_rule(rule, ctx)

    # Apply the (possibly inner) per-MAF-row predicate.
    maf_df = maf_df.copy()
    maf_df["_hit"] = maf_df.apply(predicate, axis=1)

    hits = maf_df[maf_df["_hit"] == True]  # noqa: E712 — object column: `is True` won't vectorize
    # Rows the predicate could not answer. Tracked separately so a sample with no hit
    # but an unanswerable row abstains instead of being called a negative.
    unresolved = maf_df[maf_df["_hit"].isna()]
    hit_samples = (
        hits.groupby(sample_id_col)
        .agg(
            _first_native=(native_id_col, "first"),
            _first_hit=("protein_change", "first") if "protein_change" in maf_df.columns else (sample_id_col, "first"),
        )
        .reset_index()
        if len(hits) > 0
        else pd.DataFrame(columns=[sample_id_col, "_first_native", "_first_hit"])
    )

    # For every sample in `all_samples`, produce an assignment row
    out_rows = []
    hit_set = set(hit_samples[sample_id_col]) if len(hit_samples) > 0 else set()
    unresolved_set = set(unresolved[sample_id_col]) if len(unresolved) > 0 else set()
    hit_lookup = hit_samples.set_index(sample_id_col).to_dict("index") if len(hit_samples) > 0 else {}

    for _, sample_row in all_samples.iterrows():
        sid = sample_row[sample_id_col]
        pid = sample_row.get(patient_id_col) if patient_id_col else None
        native = sample_row[native_id_col]
        # Three-valued OR over this sample's rows: True dominates, then None, else False.
        if sid in hit_set:
            inner_state = True
        elif sid in unresolved_set:
            inner_state = None
        else:
            inner_state = False
        # Sample-level negation inverts membership: WT = no inner-hit. None stays None.
        if is_sample_negation:
            is_member = None if inner_state is None else (not inner_state)
        else:
            is_member = inner_state
        # derivation_value only carries the matched variant for positive (hit)
        # strata; a WT member has no matching variant to report.
        deriv_value = (
            hit_lookup.get(sid, {}).get("_first_hit", "") if (is_member is True and not is_sample_negation) else ""
        )
        out_rows.append(
            {
                "sample_id": sid,
                "patient_id": pid,
                "source_native_id": native,
                "stratum_id": stratum["id"],
                "is_member": is_member,
                "derivation_source": stratum["derivation_source"],
                "derivation_value": deriv_value,
            }
        )
    return pd.DataFrame(out_rows)


def _rule_capability_report(rule: str, maf_columns: set[str], ctx: RuleContext) -> list[str]:
    """Human-readable reasons this rule is not fully evaluable against this source.

    Reported per stratum so a null count is attributable to a NAMED blocker rather than
    left looking like a data gap. Recorded for the record, not used to skip the stratum:
    the partially-evaluable legs still produce real Trues and Falses.
    """
    reasons = []
    fields = set(re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:==|>=|<=|\bin\b)", rule))
    # `sample.tmb` / `copy_number.X` namespaced fields resolve to their bare tail.
    referenced = {_extract_column_name(f) for f in fields}
    missing = sorted(f for f in referenced if f not in maf_columns)
    if missing:
        reasons.append(f"columns absent from source MAF: {missing}")
    for tok, parent in sorted(ctx.unavailable_effect_tokens.items()):
        if re.search(rf"'{re.escape(tok)}'", rule):
            where = f"abstains on `{parent}` rows" if parent else "unevaluable outright"
            reasons.append(f"effect token {tok!r} not producible by this source → {where}")
    return reasons


def _effect_vocabulary_guard(maf: pd.DataFrame, applicable: list[dict], data_source: str, indication: str) -> None:
    """Refuse to run when the rules test the normalized effect vocabulary and the
    source column holds RAW MAF Variant_Classification.

    This is the guard that would have caught the original defect at run time, and it is
    deliberately independent of the capability sidecar: an OLD parquet with no sidecar
    still gets checked, because the check reads the DATA rather than a declaration about
    it. Fires only when a rule actually references `effect`, so raw-passthrough sources
    (GENIE, whose COADREAD strata are all protein_change-based) keep working untouched.
    """
    if "effect" not in maf.columns:
        return
    if not any(re.search(r"\beffect\b", s.get("rule", "") or "") for s in applicable):
        return
    raw = maf_vocab.raw_effect_tokens_present(maf["effect"].dropna().unique())
    if not raw:
        return
    raise RuntimeError(
        f"{data_source} × {indication}: catalog rules reference the NORMALIZED `effect` "
        f"vocabulary but the source column holds RAW MAF Variant_Classification "
        f"{sorted(raw)[:5]}. Nothing would match and every sample would be emitted as "
        f"is_member=False — a fabricated measured negative over a full denominator. "
        f"Re-run scripts/prefetch_source_maf.py for this source with normalize_effect=True "
        f"(see methods/subgroup_common/maf_vocab.py)."
    )


# ---------- Output emission ------------------------------------------------

# The schema-valid subgroup_assignment_product manifest is emitted via the
# shared subgroup_common.manifest.emit_assignment_manifest. The maf_filter
# product uses variant="maf" so its product id doesn't collide with the
# directly_tagged product on the same (source × indication).


# ---------- CLI ------------------------------------------------------------


@click.command()
@click.option(
    "--subgroup-catalog",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the subgroup_catalog YAML.",
)
@click.option(
    "--data-source",
    required=True,
    type=click.Choice(["tcga", "depmap", "genie"]),
    help="Which data source's MAF to assign against.",
)
@click.option("--release-pin", required=True, help="Catalog release_pin identifier (e.g., 2026-Q2).")
# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
@click.option(
    "--catalog-repo",
    type=click.Path(file_okay=False, path_type=Path),
    default=data_catalog_root(),
    help="Path to the data-catalog repo for input-manifest resolution.",
)
@click.option(
    "--out",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory; assignments.parquet + manifest.yaml land here.",
)
@click.option("--dry-run", is_flag=True, help="Parse the catalog, print the plan, do not produce assignments.")
def main(
    subgroup_catalog: Path, data_source: str, release_pin: str, catalog_repo: Path, out: Path, dry_run: bool
) -> int:
    """Generate per-sample subgroup assignments from MAF-filter predicates."""
    with subgroup_catalog.open() as f:
        catalog = yaml.safe_load(f)

    indication = catalog.get("indication")
    catalog_id = catalog.get("id")
    atomic = catalog.get("atomic_strata", [])

    applicable = []
    for s in atomic:
        if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES:
            continue
        applicable_sources = s.get("applicable_data_sources", [])
        if data_source not in applicable_sources:
            continue
        applicable.append(s)

    click.echo(f"=== subgroup_assigner_maf_filter v{METHOD_VERSION} ===")
    click.echo(f"  catalog:       {catalog_id} (indication={indication})")
    click.echo(f"  data_source:   {data_source}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  out:           {out}")
    click.echo(f"  applicable MAF-filter strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        rule = s.get("rule", "")
        m = re.search(r"gene_symbol\s*==\s*['\"]([A-Z0-9]+)['\"]", rule)
        gene_hint = f"  [gene={m.group(1)}]" if m else ""
        click.echo(f"    - {s['id']:<20}{gene_hint}")
        click.echo(f"      rule: {rule}")

    skipped = [s["id"] for s in atomic if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES]
    if skipped:
        click.echo(f"  skipped strata (non-MAF derivation): {skipped}")
        click.echo("  → dispatch to subgroup_assigner_directly_tagged or subgroup_assigner_classifier")

    if not applicable:
        click.echo(f"WARNING: no applicable MAF-filter strata for data_source={data_source}", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual assignment generation)")
        return 0

    # ============ Load MAF + cohort samples ============
    if data_source == "tcga":
        maf = _load_tcga_maf(catalog_repo, indication)
        sample_id_col = "sample_id"
        patient_id_col = "patient_id"
        native_id_col = "source_native_id"
    elif data_source == "genie":
        maf = _load_genie_maf(catalog_repo, indication)
        sample_id_col = "sample_id"  # already normalized in the prefetch step
        patient_id_col = None  # GENIE has PATIENT_ID but is not carried in the CRC-scoped subset
        native_id_col = "source_native_id"
    else:
        maf = _load_depmap_somatic_mutations(catalog_repo, indication)
        # Prefetched parquet normalizes to sample_id/source_native_id; the raw-CSV
        # fallback also renames ModelID→sample_id. Prefer sample_id when present.
        sample_id_col = "sample_id" if "sample_id" in maf.columns else "ModelID"
        patient_id_col = None
        native_id_col = "source_native_id" if "source_native_id" in maf.columns else sample_id_col

    click.echo(f"  loaded {len(maf):,} MAF rows")

    # ============ Capability checks BEFORE any stratum is evaluated ============
    # Order matters: the vocabulary guard reads the DATA and fails loudly, so a
    # raw-vocabulary source can never proceed to emit confident zeros. The sidecar only
    # refines WHICH derived tokens are unproducible.
    _effect_vocabulary_guard(maf, applicable, data_source, indication)
    ctx, source_fields = _rule_context_for(data_source, indication, maf)
    if source_fields is None:
        click.echo(
            f"  WARNING: no capability sidecar beside the {data_source} MAF for {indication} "
            f"(expected {maf_vocab.source_fields_path(_prefetched_maf_path(data_source, indication))}). "
            f"Derived-token availability was inferred from the emitted `effect` values instead. "
            f"Re-run scripts/prefetch_source_maf.py to write the declaration.",
            err=True,
        )
    if ctx.unavailable_effect_tokens:
        click.echo(f"  effect tokens NOT producible by {data_source}: {sorted(ctx.unavailable_effect_tokens)}")

    # Derive the cohort (all_samples) — the WT/negation-stratum DENOMINATOR. Prefer the FULL cohort
    # (companion cohort-samples file, which includes fully-WT tumors); else fall back to MAF-present
    # samples. The MAF-only denominator UNDER-COUNTS WT strata: a tumor with zero MAF rows (fully WT
    # for every gene in the panel) is absent from the MAF entirely, so it never contributes a WT-side
    # row — inflating mutant fractions in the verdict-inert panorama/subtype rules.
    cohort = _load_cohort_samples(data_source, indication, sample_id_col, native_id_col, patient_id_col)
    if cohort is not None:
        # union with any MAF-present samples not in the cohort file (belt-and-suspenders), so a
        # mutated sample is never dropped from the denominator.
        if patient_id_col and patient_id_col in maf.columns:
            maf_samples = maf[[sample_id_col, patient_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
        else:
            maf_samples = maf[[sample_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
            if patient_id_col:
                maf_samples[patient_id_col] = None
        extra = maf_samples[~maf_samples[sample_id_col].isin(set(cohort[sample_id_col]))]
        all_samples = pd.concat([cohort, extra], ignore_index=True).drop_duplicates(subset=[sample_id_col])
        click.echo(f"  cohort samples: {len(all_samples):,} (full cohort incl. WT tumors)")
    else:
        if patient_id_col and patient_id_col in maf.columns:
            all_samples = maf[[sample_id_col, patient_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
        else:
            all_samples = maf[[sample_id_col, native_id_col]].drop_duplicates(subset=[sample_id_col])
            if patient_id_col:
                all_samples[patient_id_col] = None
        click.echo(f"  cohort samples: {len(all_samples):,}")
        click.echo(
            "  WARNING: cohort denominator drawn from MAF-PRESENT samples only (no companion "
            f"{indication.lower()}-cohort-samples.parquet found). Fully-WT tumors (zero MAF rows) are "
            "under-counted in WT/negation strata → mutant fractions may be inflated. Emit the "
            "companion cohort-samples file from the prefetch step for an exact denominator.",
            err=True,
        )

    # ============ Evaluate strata ============
    per_stratum_dfs = []
    maf_columns = set(maf.columns)
    for stratum in applicable:
        try:
            rows = _evaluate_stratum_maf(stratum, maf, sample_id_col, patient_id_col, native_id_col, all_samples, ctx)
        except ValueError as e:
            click.echo(f"  SKIP {stratum['id']}: {e}", err=True)
            continue
        per_stratum_dfs.append(rows)
        n_hit = int((rows["is_member"] == True).sum())  # noqa: E712 — object column
        n_neg = int((rows["is_member"] == False).sum())  # noqa: E712 — object column
        n_null = int(rows["is_member"].isna().sum())
        # The EVALUABLE DENOMINATOR is true+false. Printed alongside the null count
        # because an expected_n measured against a denominator that silently included
        # unevaluable samples is not a measurement — it is the defect this fix removes.
        click.echo(
            f"    {stratum['id']:<25} is_member=true: {n_hit:>5}, false: {n_neg:>5}, "
            f"null: {n_null:>5}  (evaluable denominator {n_hit + n_neg:,} of {len(rows):,})"
        )
        for reason in _rule_capability_report(stratum.get("rule", "") or "", maf_columns, ctx):
            click.echo(f"      ↳ partially unevaluable on {data_source}: {reason}", err=True)

    if not per_stratum_dfs:
        click.echo("ERROR: no strata produced rows", err=True)
        return 1

    assignments = pd.concat(per_stratum_dfs, ignore_index=True)
    assignments["evaluated_at_release"] = release_pin

    # ============ Emit outputs ============
    out.mkdir(parents=True, exist_ok=True)
    parquet_path = out / "assignments.parquet"
    assignments.to_parquet(parquet_path, index=False)
    click.echo(f"  wrote {parquet_path} ({len(assignments):,} rows)")

    emit_assignment_manifest(
        out_dir=out,
        catalog=catalog,
        catalog_path=subgroup_catalog,
        data_source=data_source,
        release_pin=release_pin,
        assignments=assignments,
        assigner_method="subgroup_assigner_maf_filter",
        variant="maf",
    )
    click.echo(f"  wrote {out / 'manifest.yaml'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
