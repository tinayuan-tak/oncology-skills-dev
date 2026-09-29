"""maf_vocab — the ONE canonical MAF `effect` vocabulary, plus the
source-capability sidecar that says which of its tokens a given prefetched MAF
can actually produce.

Why this module exists (measured 2026-09-13, analysis-methods):

The subgroup catalogs author MAF rules against a NORMALIZED lowercase effect
vocabulary (`effect in ['nonsense', 'frameshift', 'splice_site',
'missense_damaging']`). Raw MAFs carry MAF v2.4 title-case classes
(`Nonsense_Mutation`, `Frame_Shift_Del`, …). `scripts/prefetch_source_maf.py`
normalized for `tcga_mc3` but opted DepMap out, so DepMap's `effect` column held
the RAW vocabulary while the rules tested the normalized one. Nothing matched —
and because the assigner collapsed "no matching row" to `is_member=False`, all
13 effect-referencing strata reported a CONFIDENT ZERO on the DepMap cohort
(HNSC TP53_mut: 0 of 95, against 181 of 277 for the SAME rule on TCGA MC3, with
86 of those 95 DepMap models plainly carrying a TP53 hit).

A vocabulary mismatch is the worst kind of defect because it does not look like
one: a 0-count over a FULL evaluable denominator reads as biology, not as a
build error. So this module is deliberately blunt about two things:

1. **One map, one owner.** `VARIANT_CLASSIFICATION_TO_EFFECT` lives here and is
   imported by both the producer (scripts/prefetch_source_maf.py) and the
   consumer (methods/subgroup_assigner_maf_filter). A forked copy is how the
   two sides drifted in the first place.
2. **Capability is DECLARED, not guessed.** A source that lacks the evidence
   column behind a DERIVED token cannot produce that token, and a rule testing
   it must ABSTAIN (`is_member=null`) rather than answer False. DepMap's MAF has
   18 columns — no `Exon_Number`, no `PolyPhen` — so `missense_damaging` is
   unproducible there by construction. That fact is written next to the parquet
   (see `write_source_fields`) instead of being re-inferred by every reader.

Deliberately stdlib+yaml only (no pandas) so it stays a LEAF: `prefetch_source_maf.py`
keeps its heavy imports inside functions to keep `--help` fast, and this module
has to be importable at module scope on both sides.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml

# MAF v2.4 Variant_Classification → catalog `effect` vocabulary. The subgroup
# catalogs (NSCLC/HNSC/ESCA/PAAD/AML) author rules against this normalized
# lowercase vocabulary; raw MC3/DepMap/GENIE MAFs carry title-case MAF classes.
# Both frameshift dels/ins collapse to a single `frameshift` token (the catalogs
# don't distinguish direction). `missense_damaging` is NOT a raw class — it is a
# DERIVED refinement; see DERIVED_EFFECT_TOKENS.
VARIANT_CLASSIFICATION_TO_EFFECT = {
    "In_Frame_Del": "in_frame_deletion",
    "In_Frame_Ins": "in_frame_insertion",
    "Splice_Site": "splice_site",
    "Missense_Mutation": "missense",
    "Nonsense_Mutation": "nonsense",
    "Nonstop_Mutation": "nonstop",
    "Frame_Shift_Del": "frameshift",
    "Frame_Shift_Ins": "frameshift",
    "Translation_Start_Site": "translation_start_site",
    "Silent": "silent",
    "Intron": "intron",
    "RNA": "rna",
    "3'UTR": "three_prime_utr",
    "5'UTR": "five_prime_utr",
    "3'Flank": "three_prime_flank",
    "5'Flank": "five_prime_flank",
}

#: Tokens the normalized `effect` column can hold directly from the map above.
NORMALIZED_EFFECT_TOKENS = frozenset(VARIANT_CLASSIFICATION_TO_EFFECT.values())

#: Raw MAF classes — used by `raw_effect_tokens_present` to detect an
#: un-normalized column before it can silently answer False everywhere.
RAW_VARIANT_CLASSIFICATIONS = frozenset(VARIANT_CLASSIFICATION_TO_EFFECT)


@dataclass(frozen=True)
class DerivedEffectToken:
    """An effect token that is not a raw MAF class but a REFINEMENT of one.

    `refines` is the parent token a row carries when the refinement cannot be
    evaluated. That parent is what makes honest abstention possible: a rule
    testing `missense_damaging` against a source with no PolyPhen column must
    return null for `missense` rows (unknown refinement) and False for rows that
    are not missense at all (definitively outside the rule). Blanket-nulling the
    whole stratum would throw away the nonsense/frameshift/splice_site legs that
    ARE evaluable; blanket-False is the defect this module exists to prevent.
    """

    token: str
    refines: str
    evidence_column: str
    reason_when_absent: str


DERIVED_EFFECT_TOKENS: dict[str, DerivedEffectToken] = {
    "missense_damaging": DerivedEffectToken(
        token="missense_damaging",
        refines="missense",
        evidence_column="PolyPhen",
        reason_when_absent=(
            "source MAF carries no PolyPhen column, so a missense variant's damaging "
            "status is unknown; rules testing missense_damaging abstain on missense rows"
        ),
    ),
}

#: Suffix of the capability sidecar written next to each prefetched MAF parquet.
SOURCE_FIELDS_SUFFIX = ".source-fields.yaml"

EFFECT_VOCAB_NORMALIZED = "normalized"
EFFECT_VOCAB_RAW = "raw_variant_classification"


def source_fields_path(parquet_path: Path | str) -> Path:
    """Path of the capability sidecar for a prefetched MAF parquet."""
    p = Path(parquet_path)
    return p.with_name(p.stem + SOURCE_FIELDS_SUFFIX)


def write_source_fields(
    parquet_path: Path | str,
    *,
    source: str,
    indication: str,
    columns: Iterable[str],
    effect_vocabulary: str,
    unavailable_effect_tokens: Iterable[str],
) -> Path:
    """Declare, next to the parquet, what the emitted MAF can and cannot answer.

    Written by the PRODUCER (scripts/prefetch_source_maf.py) on every run, so the
    declaration can never be staler than the parquet it describes.
    """
    unavailable = sorted(set(unavailable_effect_tokens))
    doc = {
        "source": source,
        "indication": indication,
        "columns": sorted(set(columns)),
        "effect_vocabulary": effect_vocabulary,
        "unavailable_effect_tokens": {
            tok: {
                "refines": DERIVED_EFFECT_TOKENS[tok].refines if tok in DERIVED_EFFECT_TOKENS else None,
                "reason": (
                    DERIVED_EFFECT_TOKENS[tok].reason_when_absent
                    if tok in DERIVED_EFFECT_TOKENS
                    else "not producible from this source"
                ),
            }
            for tok in unavailable
        },
    }
    path = source_fields_path(parquet_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        yaml.safe_dump(doc, fh, sort_keys=True)
    return path


def read_source_fields(parquet_path: Path | str) -> dict | None:
    """Read the capability sidecar, or None when the parquet predates it.

    None means "undeclared", NOT "everything available" — callers must fall back
    to what they can verify from the frame itself (column presence, effect-token
    shape) rather than assuming capability. See
    `subgroup_assigner_maf_filter.cli._effect_vocabulary_guard`.
    """
    path = source_fields_path(parquet_path)
    if not path.exists():
        return None
    with path.open() as fh:
        doc = yaml.safe_load(fh)
    return doc if isinstance(doc, dict) else None


def unavailable_tokens_from_fields(fields: dict | None) -> dict[str, str | None]:
    """`{token: parent_token_or_None}` for tokens the source cannot produce."""
    if not fields:
        return {}
    raw = fields.get("unavailable_effect_tokens") or {}
    out: dict[str, str | None] = {}
    for tok, meta in raw.items():
        out[tok] = (meta or {}).get("refines") if isinstance(meta, dict) else None
    return out


def raw_effect_tokens_present(values: Iterable) -> set[str]:
    """Raw MAF classes found among `values` — non-empty means NOT normalized.

    The tell for the DepMap defect: the `effect` column exists and is fully
    populated, but holds `Nonsense_Mutation` where the rules test `nonsense`.
    Column-present is not field-evaluable.
    """
    return {str(v) for v in values if str(v) in RAW_VARIANT_CLASSIFICATIONS}
