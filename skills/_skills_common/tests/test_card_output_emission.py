"""LIVE coverage guard — card `outputs.summary_fields` vs. what the live reader EMITS.

The dominant defect found in the card-review sweep: a card's `outputs.summary_fields`
declares a key its live reader never emits, OR the reader emits a value OUTSIDE the
field's declared `summary_fields_vocabulary`. This test dispatches every WIRED card on
one representative fixture target and asserts, per card:

  1. every declared (non-conditional) `summary_fields` key is present in the emitted dict, and
  2. every emitted value for a field carrying a declared vocabulary is IN that vocabulary.

TWO THIRD DIRECTIONS WERE BUILT, MEASURED AND REFUTED on 2026-09-14. Both are recorded here with their
numbers so they are not re-proposed, because both look fail-safe and neither is.

(A) THE REVERSE OF (1), i.e.
"every EMITTED key must be DECLARED". It was measured (135 wired cards, live, 0 skips) and REFUTED as a
gate. `target-contracts/validators/gen_summary_schemas.py` sets `additionalProperties: true` as
MANDATORY v1 with the written reason that real summaries carry undeclared internal keys, retired-but-
emitted fields and computed extras, and that a strict schema "would break every wired card" — measured,
that is 97 of 135 cards, 141 distinct keys, 292 instances, of which 127 are one framework-level echo
envelope (`method_version` 50 cards, `target` 40, `indication` 37) that the card schema never modelled.
So an emitted-but-undeclared summary key is LEGAL BY CONTRACT and a hard assert here would put this
test in direct conflict with a documented sibling-repo ruling. The narrow slice that IS a genuine
defect is static and needs no credentials, so it belongs in target-contracts rather than here, and it
LANDED there as contracts #776 (validator layer 2i, `_summary_vocabulary_declaration_check`). MIND THE
COUNT, because the number measured here was one too high: 5 cards declare a `summary_fields_vocabulary`
key that is absent from `summary_fields`, but only 4 are defects (functional-gene-state `sample_state`,
normal-tissue-protein-abundance-tphp `tissue_category`, prism-compound-activity `metric_source`,
variant-level-interpretation `resistance_class`). The 5th is CORRECT and must not be re-filed:
tumor-vs-normal-percentile-crossing-by-subtype declares `percentile_crossing_class` as a key of its own
`per_subgroup_metrics` RECORD SCHEMA, and a per-record class needs a vocabulary too. So the legal
targets are `summary_fields` OR a declared record-schema key, and the one-sided invariant this file
originally measured would have shipped a 20% false-positive rate. It composes with (B), because the
degenerate predicate iterates the VOCABULARY keys, so an undeclared field's abstain value can switch
off the presence check for a card's declared ones.

(B) PINNING THE REACH OF THE DEGENERATE OFF-SWITCH BY NAME. `_emission_problems` relaxes the
missing-field check for the WHOLE card when any vocab field emits a documented no-data marker
(`on_degenerate_branch`, via `_degenerate_vocab_fields`). The relaxation is correct per contract — 128
of the 133 cards carrying a list-valued vocabulary DECLARE a data-unavailable marker as a legal enum
value (207 of 283 vocab fields), so "this field may be unavailable" is something cards actually say.
What no card says is "…and therefore my OTHER fields may vanish too", which is what a whole-card
relaxation grants. Measured reach, live S3, all 135 wired cards, 0 skips: 11 cards land on the
degenerate branch, 6 are forgiven a declared field, 21 fields total, and ZERO non-degenerate cards have
a missing declared field — so every gap direction (1) could find today sits behind this switch, and
`KNOWN_EMISSION_DEBT` is empty partly for that reason rather than because the debt was paid.

An exact by-name pin of the forgiven set was built and then REFUTED by re-measuring WITHOUT S3
credentials, which is the environment CI actually has. The two populations are DISJOINT, not nested:
credless, `adc-tce-modality-fit` errors outright (so `skip_if_no_data` skips it) and the other 5 pinned
cards forgive exactly their pinned fields, but 5 ENTIRELY DIFFERENT cards degrade instead and are
forgiven 35 further fields (alteration-clinical-association 10, subtype-survival-association 8,
surface-abundance-density 8, cellline-protein-abundance-procan 5, cellline-rna-protein-concordance 4).
Membership is decided by which data source answers in this environment, so the pin reds in CI in the
"newly forgiven" direction and reds on a well-credentialed laptop in the "stale waiver" direction; the
forgiven set is monotone in data availability, so NEITHER one-sided half is safe either. The shape of
the read does not separate the populations and cannot rescue the pin: unpinned
`cellline-protein-abundance-procan` arrives with 13 of 18 required fields present while pinned
`ici-response-imvigor210` arrives with 2 of 16. A LOCAL DISK CACHE is part of the environment too
(`~/.cache/framework-depmap-26q1`, the cached TCGA subgroup assignments), so even a credless run here
is not cold CI.

The real remedy is therefore NOT a test-side waiver list and NOT tightening the relaxation (which would
red on the same data-dependent set): it is for a card to declare WHICH fields depend on WHICH
degradable source, so the relaxation can be scoped to them. That is a card-schema design question,
owned by target-contracts, and is filed as a finding rather than fixed here.

It doubles as a per-card COVERAGE REPORT: run `-v` and each card_id shows PASS / FAIL /
SKIP; a FAIL's assertion message names the exact missing field(s) or out-of-vocab value(s).

WIRED = the card has a live reader: a bespoke `CARD_DISPATCHERS` entry OR a `methods[].entrypoint`
routed by `_generic_dispatch`. We SKIP cleanly:
  - `placeholder_not_wired` cards and cards with no dispatcher (never enumerated);
  - the subgroup PANORAMA cards (they need a resolved-strata scope, not a scalar target);
  - any card whose live read is unavailable in this environment — an S3 access/credential
    failure, a structured `_live_read_error`, or a degenerate no-data `_data_note`
    (via `conftest.skip_if_no_data`). This never false-FAILS in credless CI, but do not read that
    as "credless CI exercises nothing": measured 2026-09-14 with no cbg profile, the file is
    28 passed / 108 skipped, because some readers answer from a local disk cache or a non-S3
    source. 5 of those 28 pass with direction (1) switched off — see (B) above.

EXEMPTIONS (so a FAIL is always a genuine card-contract gap, not a fixture artifact):
  - DEGENERATE PATH: if the card emits a documented data-unavailable / abstain value for a
    vocab field (e.g. `no_partner_mapped`, `data_unavailable`), the MISSING-field check is
    relaxed for that read — the card legitimately emits fewer fields on that branch (task §3).
  - CONDITIONAL FIELDS: a few fields are emitted only by a NON-primary dispatch branch
    (the dual-grain per-subgroup panorama reader, not the pooled scalar reader we call here).
    Those are listed in CONDITIONAL_FIELDS with a reason and exempted from the presence check.

Determinism / speed: ONE representative target per card (KRAS/COADREAD workhorse; MSLN/PAAD
for surface antigens; WRN/COADREAD for the partner-conditional SL card). No fan-out over
multiple targets.

This is a LIVE test — not a CI-required gate (CI has no S3 creds). Run it with:
    export PATH="$HOME/.pixi/bin:$PATH"; AWS_PROFILE=cbg \
      PYTHONPATH=<skills-repo>/skills python -m pytest \
      skills/_skills_common/tests/test_card_output_emission.py -v
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from _skills_common._live_readers import (
    CARD_DISPATCHERS,
    PANORAMA_DISPATCHERS,
    read_live_summary,
)
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT
from conftest import skip_if_no_data  # shared live-S3 skip guard

_CONTRACTS = Path(
    os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        TARGET_CONTRACTS_ROOT_DEFAULT,
    )
)
_CARDS_DIR = _CONTRACTS / "cards"


# --- documented data-unavailable / abstain vocab values -----------------------------------------
# When a card emits one of these for a vocab-bearing field, the reader is on a degenerate / abstain
# branch and legitimately emits fewer summary_fields — the MISSING-field check is relaxed. These are
# ALSO always-allowed vocab values (a card need not re-declare `data_unavailable` in every vocab).
DATA_UNAVAILABLE_MARKERS = {
    "data_unavailable",
    "no_match",
    "no_data",
    "not_applicable",
    "not_evaluated",
    "not_measured",
    "unmeasured",
    "insufficient",
    "unavailable",
    "absent",
    # card-specific abstain classes (documented in the card vocab as honest no-signal states):
    "no_partner_mapped",
    "no_target_event",
    "not_surface_density_whole_cell_estimate",
    "phospho_not_detected",  # phospho-pathway-activity abstains here (no phosphosites detected for the target)
}


# --- one representative fixture target per card -------------------------------------------------
# KRAS/COADREAD is the workhorse: COADREAD has the richest landed product coverage, so KRAS exercises
# the fullest emission path for almost every card (best gap detection). Only two cards need a bespoke
# target because KRAS lands on a degenerate branch that hides real fields:
#   - surface-abundance-density: KRAS is intracellular → the reader emits a not-a-surface-protein
#     whole-cell-estimate class; a surface antigen (MSLN, high in PAAD) exercises the real density path.
#   - partner-conditional-dependency: KRAS has no curated SL partner (→ no_partner_mapped abstain);
#     WRN×MSI is the live exemplar that exercises the partner-stratification fields.
# NB: a BLANKET "surface antigen for every surface card" override is deliberately NOT used — PAAD has
# thinner product coverage than COADREAD, so it degrades otherwise-clean surface cards (adc-tce-modality-fit,
# surfaceome-cohort-ranking) into FALSE missing-field gaps. Narrow, evidence-based overrides only.
DEFAULT_TARGET = ("KRAS", "COADREAD")

TARGET_OVERRIDES: dict[str, tuple[str, str]] = {
    "surface-abundance-density": ("MSLN", "PAAD"),
    "partner-conditional-dependency": ("WRN", "COADREAD"),
    # KRAS has no detected phosphosites in coad (→ phospho_not_detected abstain, minimal dict); EGFR/LUAD is a
    # CPTAC phosphoprotein that exercises the real emission path (all phospho summary_fields).
    "phospho-pathway-activity": ("EGFR", "LUAD"),
}


# --- KNOWN EMISSION DEBT (ratchet allowlist; mirrors target-contracts KNOWN_FIGURE_DEBT) ----------
# Genuine card-contract gaps the sweep found but has not yet resolved: a declared summary_field the
# live reader never emits ("MISSING <field>"), or an emitted class value outside the declared vocab
# ("OUT_OF_VOCAB <field>=<value>"). Each is TRACKED here so the guard lands GREEN and RATCHETS — a NEW
# (unlisted) gap FAILS; a listed one xfails as tracked debt. Work an item down, then delete its line.
# NB: the four *-stratified-dependency entries are one coherent naming inconsistency — cn/amp/fusion
# readers emit `pan_lineage_RAW_*_class` while the cards declare `pan_lineage_*_class` (no "raw"), and
# the mutation sibling omits the declared `indication_lineage`. Resolve by aligning the 4 sibling
# reader/card names together (deferred: touches 3 AM readers + 4 cards).
# EMPTY — every gap this guard found has been resolved (card-review sweep, 2026-09-01):
#   - the 7 code-fixable gaps: AM #545 (lineage_ladder pan_lineage audit-field, subtype
#     dropped_underpowered_strata, tcga_gtex purity_source, mutation indication_lineage) + skills
#     #891 (topology vocabulary_version_isoform);
#   - ddr median_mutsig3: AM #546 carried it through the multi-cohort _combine_rows (not a product gap);
#   - cptac 'ns' + pooled_sd: data-catalog cptac per-cohort rebuild to v1.2.0 ('ns' -> not_significant,
#     + protein_effect_size_se) and target-contracts #600 (trim the legacy pooled_sd field).
# The guard asserts full emission with NO tracked debt — any new gap FAILS, EXCEPT on a card whose
# read lands on the degenerate branch, where the presence check is relaxed WHOLESALE. That carve-out is
# not hypothetical, and this dict is empty partly BECAUSE of it: measured live, all 21 currently-
# unchecked declared fields (6 cards) sit behind that switch and no non-degenerate card has a missing
# declared field. So an empty ledger here means "nothing is owed among the cards still being CHECKED",
# not "nothing is owed". Docstring §(B) records why the switch's reach cannot be pinned by name.
KNOWN_EMISSION_DEBT: dict[str, set[str]] = {}


# --- fields emitted only on a NON-primary dispatch branch (exempt from the presence check) -------
# tumor-vs-normal-selectivity is a DUAL-GRAIN card: the per-subgroup panorama fields below are emitted
# by the SEPARATE subgroup reader (DUAL_GRAIN_SUBGROUP_DISPATCHERS), which only runs when a resolved
# subgroup scope is in play. The pooled scalar reader we call here does not — and should not — emit them.
CONDITIONAL_FIELDS: dict[str, set[str]] = {
    "tumor-vs-normal-selectivity": {
        "per_subgroup_metrics",
        "subgroup_axis",
        "n_subgroups_with_data",
        "max_subgroup_log2fc",
        "min_subgroup_log2fc",
        "cross_subgroup_delta_log2fc",
        "selectivity_class_by_subgroup",
        "cross_subgroup_selectivity_divergence",
        "any_subgroup_strong_selective",
    },
    # A boolean flag the reader sets ONLY on the pan-lineage-fallback CAP branch
    # (methods/depmap_mutation_dependency/cli.py: set True only when a STRONG pan call is capped to
    # moderate). KRAS/COADREAD is powered within-lineage, so this branch is not taken — the flag's
    # absence is correct, not a never-emitted defect.
    "mutation-stratified-dependency": {"pan_fallback_strong_capped_to_moderate"},
}


def _normalize_summary_fields(sf) -> list[tuple[str, bool]]:
    """Return [(field_name, is_lens_conditional)]. `summary_fields` is normally a list of str, but a
    card may declare a dict entry {name, lens_conditional_on, description} for a field emitted only
    when a display lens (e.g. --modality) is invoked. Those are conditional → exempt from the base
    presence check (we dispatch without a lens)."""
    out: list[tuple[str, bool]] = []
    for x in sf or []:
        if isinstance(x, str):
            out.append((x, False))
        elif isinstance(x, dict) and x.get("name"):
            out.append((x["name"], bool(x.get("lens_conditional_on"))))
    return out


def _load_card(card_id: str) -> dict:
    p = _CARDS_DIR / f"{card_id}.card.yaml"
    return yaml.safe_load(p.read_text()) or {}


def _wired_card_ids() -> list[str]:
    """Enumerate WIRED cards: a bespoke CARD_DISPATCHERS entry OR a methods[].entrypoint (generic
    dispatch). Skip placeholder_not_wired, the subgroup PANORAMA cards, and cards with no dispatcher."""
    ids: list[str] = []
    for p in sorted(_CARDS_DIR.glob("*.card.yaml")):
        spec = yaml.safe_load(p.read_text()) or {}
        cid = spec.get("card_id") or p.name[: -len(".card.yaml")]
        if cid in PANORAMA_DISPATCHERS:
            continue
        if "placeholder_not_wired" in (spec.get("status") or ""):
            continue
        has_entrypoint = any(isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or []))
        if cid in CARD_DISPATCHERS or has_entrypoint:
            ids.append(cid)
    return ids


WIRED_CARD_IDS = _wired_card_ids() if _CARDS_DIR.is_dir() else []


def _target_for(card_id: str) -> tuple[str, str]:
    return TARGET_OVERRIDES.get(card_id, DEFAULT_TARGET)


def _degenerate_vocab_fields(vocab: dict, result: dict) -> list[str]:
    """The vocab fields whose emitted value is a documented no-data/abstain marker. Non-empty == this
    read is on the DEGENERATE branch. NB it iterates the VOCABULARY keys, not the declared field names,
    so a card declaring a vocabulary for a field it never declares in `summary_fields` can trip the
    relaxation from an UNDECLARED field (5 cards carry such a key; 4 are genuine contract defects,
    the 5th declares it in a record schema — see the module docstring and contracts #776)."""
    return sorted(f for f in vocab if isinstance(result.get(f), str) and result[f].lower() in DATA_UNAVAILABLE_MARKERS)


def _emission_problems(card_id: str, target: str, indication: str, result: dict) -> list[str]:
    """Compute the (missing-field, out-of-vocab) findings for one live read. Empty list == clean."""
    spec = _load_card(card_id)
    out = spec.get("outputs") or {}
    summary_fields = _normalize_summary_fields(out.get("summary_fields") or [])
    vocab = {k: v for k, v in (out.get("summary_fields_vocabulary") or {}).items() if isinstance(v, list)}

    # DEGENERATE / ABSTAIN branch: a vocab field emitting a documented no-data/abstain value means the
    # reader legitimately emits fewer fields — relax the presence check for this read (task §3). The
    # predicate lives in ONE named place (`_degenerate_vocab_fields`) rather than inline here, because
    # this switch is what the docstring's §(B) measurement is ABOUT: an inline copy would let the thing
    # that fires and the thing that was measured drift apart silently, and the reach of a relaxation is
    # exactly the property nothing else in this file records.
    on_degenerate_branch = bool(_degenerate_vocab_fields(vocab, result))
    conditional = CONDITIONAL_FIELDS.get(card_id, set())

    problems: list[str] = []

    # Granular, canonical problem strings ("MISSING <field>" / "OUT_OF_VOCAB <field>=<value>") so they
    # match KNOWN_EMISSION_DEBT entries exactly (task: ratchet allowlist).
    if not on_degenerate_branch:
        for f, is_cond in summary_fields:
            if (not is_cond) and f not in conditional and f not in result:
                problems.append(f"MISSING {f}")

    for field, allowed in vocab.items():
        if field not in result:
            continue
        allowed_lc = {str(a).lower() for a in allowed} | DATA_UNAVAILABLE_MARKERS
        value = result[field]
        for v in value if isinstance(value, list) else [value]:
            if isinstance(v, str) and v.lower() not in allowed_lc:
                problems.append(f"OUT_OF_VOCAB {field}={v!r}")
    return problems


def test_wired_card_enumeration_is_populated():
    """Sanity: the guard must be checking a substantial slice of the card corpus. A near-empty
    enumeration means the target-contracts checkout is missing or the wiring probe broke."""
    assert _CARDS_DIR.is_dir(), f"target-contracts cards dir not found: {_CARDS_DIR}"
    assert len(WIRED_CARD_IDS) >= 100, (
        f"expected >=100 wired cards, enumerated {len(WIRED_CARD_IDS)} — wiring probe likely broken"
    )


@pytest.mark.parametrize("card_id", WIRED_CARD_IDS)
def test_card_emits_declared_summary_fields(card_id):
    """Every declared (non-conditional) summary_fields key must be EMITTED by the live reader, and
    every emitted vocab-field value must be WITHIN its declared vocabulary. See module docstring for
    the skip/exemption contract. A FAIL names the exact card-contract gap to fix in target-contracts."""
    target, indication = _target_for(card_id)

    # skip_if_no_data converts an S3-access / credential failure, a structured _live_read_error, OR a
    # degenerate all-None _data_note into a clean SKIP (env limitation, not a regression).
    result = skip_if_no_data(lambda: read_live_summary(card_id, target, indication))

    if result is None:
        pytest.skip(f"{card_id}: reader returned None (not exercised for {target}/{indication})")
    assert isinstance(result, dict), f"{card_id}: reader returned {type(result).__name__}, expected dict"

    problems = _emission_problems(card_id, target, indication, result)

    known = KNOWN_EMISSION_DEBT.get(card_id, set())
    novel = [p for p in problems if p not in known]
    # A resolved-but-still-listed debt entry (card now clean) should be pruned from the allowlist.
    stale_debt = known - set(problems)
    assert not stale_debt, (
        f"{card_id}: KNOWN_EMISSION_DEBT lists {sorted(stale_debt)} but the reader now emits them — "
        "delete these from KNOWN_EMISSION_DEBT (debt paid, keep the ratchet tight)."
    )
    if not novel and problems:
        pytest.xfail(f"{card_id}: tracked emission debt (KNOWN_EMISSION_DEBT): {sorted(problems)}")
    assert not novel, (
        f"{card_id} ({target}/{indication}) card-contract gap:\n  "
        + "\n  ".join(novel)
        + "\n(fix in target-contracts: align outputs.summary_fields / summary_fields_vocabulary with "
        "the live reader, OR make the reader emit the declared field. If genuinely deferred, add to "
        "KNOWN_EMISSION_DEBT with a rationale.)"
    )
