"""LIVE coverage guard — card `outputs.summary_fields` vs. what the live reader EMITS.

The dominant defect found in the card-review sweep: a card's `outputs.summary_fields`
declares a key its live reader never emits, OR the reader emits a value OUTSIDE the
field's declared `summary_fields_vocabulary`. This test dispatches every WIRED card on
one representative fixture target and asserts, per card:

  1. every declared (non-conditional) `summary_fields` key is present in the emitted dict, and
  2. every emitted value for a field carrying a declared vocabulary is IN that vocabulary.

It doubles as a per-card COVERAGE REPORT: run `-v` and each card_id shows PASS / FAIL /
SKIP; a FAIL's assertion message names the exact missing field(s) or out-of-vocab value(s).

WIRED = the card has a live reader: a bespoke `CARD_DISPATCHERS` entry OR a `methods[].entrypoint`
routed by `_generic_dispatch`. We SKIP cleanly:
  - `placeholder_not_wired` cards and cards with no dispatcher (never enumerated);
  - the subgroup PANORAMA cards (they need a resolved-strata scope, not a scalar target);
  - any card whose live read is unavailable in this environment — an S3 access/credential
    failure, a structured `_live_read_error`, or a degenerate no-data `_data_note`
    (via `conftest.skip_if_no_data`). So this NEVER false-fails in credless CI: with no S3
    creds every card read degrades and the test skips with a clear message.

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
import sys
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR.parent))  # skills/ — _live_readers lives in _skills_common

from _skills_common._live_readers import (  # noqa: E402
    CARD_DISPATCHERS,
    PANORAMA_DISPATCHERS,
    read_live_summary,
)
from conftest import skip_if_no_data  # noqa: E402 — shared live-S3 skip guard

_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
))
_CARDS_DIR = _CONTRACTS / "cards"


# --- documented data-unavailable / abstain vocab values -----------------------------------------
# When a card emits one of these for a vocab-bearing field, the reader is on a degenerate / abstain
# branch and legitimately emits fewer summary_fields — the MISSING-field check is relaxed. These are
# ALSO always-allowed vocab values (a card need not re-declare `data_unavailable` in every vocab).
DATA_UNAVAILABLE_MARKERS = {
    "data_unavailable", "no_match", "no_data", "not_applicable", "not_evaluated",
    "not_measured", "unmeasured", "insufficient", "unavailable", "absent",
    # card-specific abstain classes (documented in the card vocab as honest no-signal states):
    "no_partner_mapped", "no_target_event",
    "not_surface_density_whole_cell_estimate",
    "not_phosphoprotein",   # phospho-pathway-activity abstains here (target has no CPTAC phosphosites)
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
    # KRAS is not a phosphoprotein (→ not_phosphoprotein abstain, minimal dict); EGFR/LUAD is a
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
# The guard now asserts full emission with NO tracked debt — any new gap FAILS.
KNOWN_EMISSION_DEBT: dict[str, set[str]] = {}


# --- fields emitted only on a NON-primary dispatch branch (exempt from the presence check) -------
# tumor-vs-normal-selectivity is a DUAL-GRAIN card: the per-subgroup panorama fields below are emitted
# by the SEPARATE subgroup reader (DUAL_GRAIN_SUBGROUP_DISPATCHERS), which only runs when a resolved
# subgroup scope is in play. The pooled scalar reader we call here does not — and should not — emit them.
CONDITIONAL_FIELDS: dict[str, set[str]] = {
    "tumor-vs-normal-selectivity": {
        "per_subgroup_metrics", "subgroup_axis", "n_subgroups_with_data",
        "max_subgroup_log2fc", "min_subgroup_log2fc", "cross_subgroup_delta_log2fc",
        "selectivity_class_by_subgroup", "cross_subgroup_selectivity_divergence",
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
        has_entrypoint = any(
            isinstance(m, dict) and m.get("entrypoint") for m in (spec.get("methods") or [])
        )
        if cid in CARD_DISPATCHERS or has_entrypoint:
            ids.append(cid)
    return ids


WIRED_CARD_IDS = _wired_card_ids() if _CARDS_DIR.is_dir() else []


def _target_for(card_id: str) -> tuple[str, str]:
    return TARGET_OVERRIDES.get(card_id, DEFAULT_TARGET)


def _emission_problems(card_id: str, target: str, indication: str, result: dict) -> list[str]:
    """Compute the (missing-field, out-of-vocab) findings for one live read. Empty list == clean."""
    spec = _load_card(card_id)
    out = spec.get("outputs") or {}
    summary_fields = _normalize_summary_fields(out.get("summary_fields") or [])
    vocab = {k: v for k, v in (out.get("summary_fields_vocabulary") or {}).items()
             if isinstance(v, list)}

    # DEGENERATE / ABSTAIN branch: a vocab field emitting a documented no-data/abstain value means the
    # reader legitimately emits fewer fields — relax the presence check for this read (task §3).
    on_degenerate_branch = any(
        isinstance(result.get(f), str) and result[f].lower() in DATA_UNAVAILABLE_MARKERS
        for f in vocab
    )
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
        for v in (value if isinstance(value, list) else [value]):
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
        f"{card_id} ({target}/{indication}) card-contract gap:\n  " + "\n  ".join(novel)
        + "\n(fix in target-contracts: align outputs.summary_fields / summary_fields_vocabulary with "
        "the live reader, OR make the reader emit the declared field. If genuinely deferred, add to "
        "KNOWN_EMISSION_DEBT with a rationale.)"
    )
