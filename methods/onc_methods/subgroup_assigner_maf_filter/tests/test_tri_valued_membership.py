"""Tri-valued membership + source-capability tests for subgroup_assigner_maf_filter.

These cover the defect measured 2026-09-13: on the DepMap cohort, all 13 strata whose
rule references `effect` reported `is_member=False` for every sample — a confident zero
over a full evaluable denominator — because (a) DepMap's `effect` column held raw MAF
Variant_Classification while the rules test the normalized vocabulary, and (b) the
sample-level aggregation computed `is_member = sid in hit_set`, a plain bool, so the
method could not emit null at all.

Deliberately DATA-FREE: every frame is built inline. The cross-source discriminator that
makes the vocabulary defect undeniable (same rule, two sources, 0/95 vs 181/277) is
reproduced here as two frames differing ONLY in effect vocabulary — a within-source test
passes vacuously, which is exactly why the defect survived.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

from onc_methods.subgroup_assigner_maf_filter import cli
from onc_methods.subgroup_common import maf_vocab

TP53_RULE = "gene_symbol == 'TP53' && effect in ['nonsense', 'frameshift', 'splice_site', 'missense_damaging']"
EX19DEL_RULE = "gene_symbol == 'EGFR' && effect == 'in_frame_deletion' && exon == 19"
KRAS_WT_RULE = "!(gene_symbol == 'KRAS' && protein_change in ['p.G12C', 'p.G12D'])"


def _load_ops_script(name: str):
    """Load ``methods/scripts/<name>.py`` by file location.

    ``methods/scripts/`` holds operational drivers, NOT package modules: pyproject's
    ``packages.find.include`` is ``onc_methods*``, so the scripts dir is not installed and
    there is no import path to it. These tests used to reach it as a bare top-level
    ``scripts`` namespace package, which resolved ONLY because a ``sys.path.insert`` had put
    the distribution root on ``sys.path`` (deleted in skills#2237). Load by location instead
    — the same idiom the ``steps/*.py`` tests use. The script's OWN
    ``from onc_methods... import`` lines still resolve through the editable install, so
    identity assertions against reader-module objects hold.
    """
    import importlib.util

    path = _OPS_SCRIPTS / f"{name}.py"
    assert path.is_file(), f"ops script not found: {path}"
    spec = importlib.util.spec_from_file_location(f"_ops_script_{name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_OPS_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
_OPS_PREFETCH_SOURCE_MAF = _load_ops_script("prefetch_source_maf")


def _stratum(sid: str, rule: str) -> dict:
    return {"id": sid, "rule": rule, "derivation_source": "maf_filter_per_rule"}


def _maf(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["source_native_id"] = df["sample_id"]
    return df


def _cohort(sample_ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"sample_id": sample_ids, "source_native_id": sample_ids})


def _evaluate(stratum, maf, cohort, ctx=cli._NO_CONTEXT) -> dict[str, object]:
    """Run one stratum and return {sample_id: is_member} for easy assertion."""
    out = cli._evaluate_stratum_maf(stratum, maf, "sample_id", None, "source_native_id", cohort, ctx)
    return {r.sample_id: (None if pd.isna(r.is_member) else r.is_member) for r in out.itertuples()}


# ---------- the vocabulary defect, both directions --------------------------


def test_raw_vocabulary_makes_the_rule_match_nothing():
    """The falsification: the SAME rule and the SAME variants, two vocabularies.

    This is the shape of the shipped defect. Nothing here is null — every sample gets a
    confident False — which is why a 0-count read as biology rather than as a bug.
    """
    raw = _maf(
        [
            {"sample_id": "ACH-1", "gene_symbol": "TP53", "protein_change": "p.R213*", "effect": "Nonsense_Mutation"},
            {"sample_id": "ACH-2", "gene_symbol": "TP53", "protein_change": "p.K132fs", "effect": "Frame_Shift_Del"},
        ]
    )
    got = _evaluate(_stratum("TP53_mut", TP53_RULE), raw, _cohort(["ACH-1", "ACH-2"]))
    assert got == {"ACH-1": False, "ACH-2": False}, "raw vocabulary must match nothing — that was the defect"

    normalized = raw.copy()
    normalized["effect"] = normalized["effect"].map(maf_vocab.VARIANT_CLASSIFICATION_TO_EFFECT)
    got = _evaluate(_stratum("TP53_mut", TP53_RULE), normalized, _cohort(["ACH-1", "ACH-2"]))
    assert got == {"ACH-1": True, "ACH-2": True}, "normalizing the vocabulary recovers both real calls"


def test_effect_vocabulary_guard_refuses_a_raw_frame():
    """The run-time guard: a raw `effect` column plus an effect-referencing rule must
    RAISE, not emit. Independent of the capability sidecar — it reads the data."""
    raw = _maf([{"sample_id": "ACH-1", "gene_symbol": "TP53", "protein_change": "p.R213*", "effect": "Splice_Site"}])
    with pytest.raises(RuntimeError, match="RAW MAF Variant_Classification"):
        cli._effect_vocabulary_guard(raw, [_stratum("TP53_mut", TP53_RULE)], "depmap", "HNSC")


def test_effect_vocabulary_guard_is_silent_when_no_rule_reads_effect():
    """GENIE stays raw-passthrough and its COADREAD strata are all protein_change-based.
    The guard must not break that working lane — it fires on the RULE, not the column."""
    raw = _maf([{"sample_id": "S1", "gene_symbol": "KRAS", "protein_change": "p.G12C", "effect": "Missense_Mutation"}])
    protein_only = _stratum("KRAS_G12C", "gene_symbol == 'KRAS' && protein_change == 'p.G12C'")
    cli._effect_vocabulary_guard(raw, [protein_only], "genie", "COADREAD")  # must not raise


def test_effect_vocabulary_guard_is_silent_on_a_normalized_frame():
    ok = _maf([{"sample_id": "ACH-1", "gene_symbol": "TP53", "protein_change": "p.R213*", "effect": "nonsense"}])
    cli._effect_vocabulary_guard(ok, [_stratum("TP53_mut", TP53_RULE)], "depmap", "HNSC")  # must not raise


# ---------- abstention: unevaluable must be null, not False ------------------


def test_missing_column_abstains_only_for_samples_the_gap_can_reach():
    """An `exon` rule against a source with no exon column (DepMap).

    The precision that matters: the EGFR-mutant sample abstains because its exon is
    unknowable, while the sample with no EGFR mutation at all stays a real False — it
    cannot be ex19del regardless of exon. Blanket-nulling the stratum would be honest but
    would throw that negative away; blanket-False is the shipped defect.
    """
    maf = _maf(
        [
            {
                "sample_id": "ACH-1",
                "gene_symbol": "EGFR",
                "protein_change": "p.E746_A750del",
                "effect": "in_frame_deletion",
            },
            {"sample_id": "ACH-2", "gene_symbol": "KRAS", "protein_change": "p.G12C", "effect": "missense"},
        ]
    )
    got = _evaluate(_stratum("EGFR_mut_ex19del", EX19DEL_RULE), maf, _cohort(["ACH-1", "ACH-2", "ACH-3"]))
    assert got["ACH-1"] is None, "EGFR in-frame-del with unknowable exon must ABSTAIN"
    assert got["ACH-2"] is False, "a KRAS-only sample is definitively not ex19del"
    assert got["ACH-3"] is False, "an assayed sample with no MAF rows is a real negative"


def test_unproducible_token_abstains_on_parent_rows_only():
    """`missense_damaging` needs PolyPhen, which DepMap lacks.

    Three outcomes from one rule, which is the whole point of declaring capability
    narrowly: the nonsense leg still answers True, a missense-only TP53 sample abstains
    (damaging status unknown), and a sample with no TP53 hit is still a real False.
    """
    ctx = cli.RuleContext({"missense_damaging": "missense"})
    maf = _maf(
        [
            {"sample_id": "ACH-1", "gene_symbol": "TP53", "protein_change": "p.R213*", "effect": "nonsense"},
            {"sample_id": "ACH-2", "gene_symbol": "TP53", "protein_change": "p.R175H", "effect": "missense"},
            {"sample_id": "ACH-3", "gene_symbol": "KRAS", "protein_change": "p.G12C", "effect": "missense"},
        ]
    )
    got = _evaluate(_stratum("TP53_mut", TP53_RULE), maf, _cohort(["ACH-1", "ACH-2", "ACH-3"]), ctx)
    assert got["ACH-1"] is True, "the nonsense leg is producible and must still fire"
    assert got["ACH-2"] is None, "a TP53 missense of unknown damaging status must abstain"
    assert got["ACH-3"] is False, "no TP53 hit at all is a real negative"


def test_a_token_with_no_parent_makes_the_atom_unevaluable():
    """A whole raw-vocabulary source declares every normalized token unproducible with no
    parent to key on, so the atom cannot be answered at all — null, never False."""
    ctx = cli.RuleContext(dict.fromkeys(maf_vocab.NORMALIZED_EFFECT_TOKENS, None))
    maf = _maf([{"sample_id": "S1", "gene_symbol": "TP53", "protein_change": "p.R213*", "effect": "whatever"}])
    got = _evaluate(_stratum("TP53_mut", TP53_RULE), maf, _cohort(["S1"]), ctx)
    assert got["S1"] is None


def test_sample_absent_from_the_maf_stays_a_real_negative():
    """Guards the opposite failure. Over-abstention is a different defect, not a safer
    one: the cohort file means ASSAYED, so zero mutation rows is a measured negative."""
    maf = _maf([{"sample_id": "ACH-1", "gene_symbol": "TP53", "protein_change": "p.R213*", "effect": "nonsense"}])
    got = _evaluate(_stratum("TP53_mut", TP53_RULE), maf, _cohort(["ACH-1", "ACH-9"]))
    assert got == {"ACH-1": True, "ACH-9": False}


# ---------- three-valued logic ---------------------------------------------


def test_conjunction_is_order_independent():
    """Same rule, conjuncts swapped, source with no exon column → same answer.

    The old `_conj` returned None at the FIRST None it met, so the answer depended on the
    order the catalog author happened to write the conjuncts in: gene-first correctly
    answered False for a KRAS row, exon-first nulled every row in the frame.
    """
    maf = _maf([{"sample_id": "S1", "gene_symbol": "KRAS", "protein_change": "p.G12C", "effect": "missense"}])
    gene_first = cli.compile_rule("gene_symbol == 'EGFR' && exon == 19")
    exon_first = cli.compile_rule("exon == 19 && gene_symbol == 'EGFR'")
    row = maf.iloc[0]
    assert gene_first(row) is False
    assert exon_first(row) is False, "a definitive False from any conjunct must win over a None"


def test_conjunction_truth_table():
    """False dominates None; None dominates True."""
    row = pd.Series({"a": "x", "missing": None})
    assert cli.compile_rule("a == 'x'")(row) is True
    assert cli.compile_rule("a == 'y'")(row) is False
    assert cli.compile_rule("missing == 'x'")(row) is None
    assert cli.compile_rule("a == 'x' && missing == 'x'")(row) is None  # True ∧ None → None
    assert cli.compile_rule("a == 'y' && missing == 'x'")(row) is False  # False ∧ None → False
    assert cli.compile_rule("a == 'x' && a == 'x'")(row) is True


def test_disjunction_truth_table():
    """True dominates None; None dominates False."""
    row = pd.Series({"a": "x", "missing": None})
    assert cli.compile_rule("a == 'x' || missing == 'x'")(row) is True  # True ∨ None → True
    assert cli.compile_rule("a == 'y' || missing == 'x'")(row) is None  # False ∨ None → None
    assert cli.compile_rule("a == 'y' || a == 'z'")(row) is False


def test_negation_propagates_null_rather_than_asserting_wild_type():
    """A KRAS row whose protein_change is unknown must NOT make the sample KRAS-WT.

    S1 has an unresolved KRAS row → null. S2's TP53 row settles to False at the
    gene_symbol conjunct (so a NaN protein_change on an irrelevant row cannot poison the
    sample) → S2 is genuinely WT. S3 carries the hotspot → not WT.
    """
    maf = _maf(
        [
            {"sample_id": "S1", "gene_symbol": "KRAS", "protein_change": None, "effect": "missense"},
            {"sample_id": "S2", "gene_symbol": "TP53", "protein_change": None, "effect": "nonsense"},
            {"sample_id": "S3", "gene_symbol": "KRAS", "protein_change": "p.G12D", "effect": "missense"},
        ]
    )
    got = _evaluate(_stratum("KRAS_WT", KRAS_WT_RULE), maf, _cohort(["S1", "S2", "S3"]))
    assert got["S1"] is None, "an unresolved KRAS row must not be reported as wild-type"
    assert got["S2"] is True
    assert got["S3"] is False


# ---------- capability declaration ----------------------------------------


def test_source_fields_sidecar_round_trips(tmp_path):
    parquet = tmp_path / "hnsc-depmap-maf.parquet"
    maf_vocab.write_source_fields(
        parquet,
        source="depmap_somatic",
        indication="HNSC",
        columns=["sample_id", "gene_symbol", "effect"],
        effect_vocabulary=maf_vocab.EFFECT_VOCAB_NORMALIZED,
        unavailable_effect_tokens=["missense_damaging"],
    )
    assert maf_vocab.source_fields_path(parquet).exists()
    fields = maf_vocab.read_source_fields(parquet)
    assert fields["effect_vocabulary"] == "normalized"
    assert maf_vocab.unavailable_tokens_from_fields(fields) == {"missense_damaging": "missense"}


def test_absent_sidecar_means_undeclared_not_available(tmp_path):
    """None must not be read as 'everything available' — that assumption is how the
    original mismatch went unnoticed on the reading side."""
    assert maf_vocab.read_source_fields(tmp_path / "nope.parquet") is None
    assert maf_vocab.unavailable_tokens_from_fields(None) == {}


def test_vocabulary_map_is_the_canonical_object_not_a_fork():
    """The producer must re-export maf_vocab's map, not carry its own copy. The two sides
    holding separate copies is how the producer could opt DepMap out with nothing on the
    consumer side able to notice."""
    prefetch_source_maf = _OPS_PREFETCH_SOURCE_MAF

    assert prefetch_source_maf.VARIANT_CLASSIFICATION_TO_EFFECT is maf_vocab.VARIANT_CLASSIFICATION_TO_EFFECT


def test_capability_report_names_the_blocker():
    """A null count must be attributable to a NAMED cause, not left looking like a data
    gap — Stage 3b writes these reasons into the catalogs as denominator notes."""
    ctx = cli.RuleContext({"missense_damaging": "missense"})
    columns = {"sample_id", "gene_symbol", "protein_change", "effect"}
    reasons = cli._rule_capability_report(EX19DEL_RULE, columns, ctx)
    assert any("exon" in r for r in reasons), reasons
    reasons = cli._rule_capability_report(TP53_RULE, columns, ctx)
    assert any("missense_damaging" in r and "missense" in r for r in reasons), reasons
    assert cli._rule_capability_report("gene_symbol == 'KRAS'", columns, ctx) == []
