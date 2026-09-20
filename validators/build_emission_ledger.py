#!/usr/bin/env python3
"""build_emission_ledger.py — T1 reachability: which (card_id, field, value) triples exist?

Every interpretation rule is pure config keyed on a `(card_id, field, value)` triple:

    when: {card_id: combo-chemical-synergy, field: synergy_opportunity_class,
           equals: strong_synergy_opportunity}

A rule can only be as right as the triple it keys on, and until this file existed nothing
enumerated the triples the corpus actually produces. `gen_summary_schemas.py:155` looks like it
does, but it copies each field's `enum` straight from the card's DECLARED
`outputs.summary_fields_vocabulary` and consults the corpus only to widen JSON types — so it
restates the declaration rather than measuring the emission, and all 46 generated schemas carry
`required: []` + `additionalProperties: true` and cannot fail.

This walks the emitted corpus and records, per (card_id, field), the OBSERVED value distribution,
then derives three findings:

    out_of_vocab   observed token NOT in the card's declared vocabulary   -> GATE
    never_emitted  declared token the corpus emits 0x                     -> dimension
    saturation     top value / non-null instances                         -> dimension

`out_of_vocab` gates because it is a flat contradiction between two committed files: the card
declares `surface_density_class: [high, moderate, low, very_low, unmeasured]` while
methods/cptac_protein_deg/read.py:1249 emits `not_surface_density_whole_cell_estimate` — and a
test ASSERTS the out-of-vocabulary value. Two repos contradict each other in writing and nothing
reds today.

`never_emitted` and `saturation` are DIMENSIONS, NOT GATES. Saturation is sometimes legitimate by
design (an existential coverage flag is supposed to be ~always true), and gating drift on a
measured distribution recreates a vacuity this repo has already learned the hard way.

GRAIN, load-bearing: everything is keyed per (card_id, field) and NEVER aggregated across cards by
field name alone. Rules key per-card, so a field name shared by several cards has several
independent distributions; pooling them produced a materially wrong saturation figure (86.3%
pooled vs 97.8% at the declaring-card grain) on the very field that motivated a 21-PR arc.

WHAT EACH HALF OF --self-check CAN AND CANNOT SEE (state this plainly; an unstated limitation is
how a gate becomes a green for the wrong reason):

  HERMETIC half  — runs in CI on every PR, no corpus, no credentials. Re-reads today's cards and
                   re-derives the findings from the committed `observed` counts. Catches
                   DECLARATION-side regressions: a vocabulary narrowed while a value is still
                   emitted, a field renamed or deleted out from under a rule, a stale ledger entry.
  CORPUS half    — needs the corpus, so it runs locally and in the nightly that already checks out
                   siblings; skipped (announced, never silent) when the corpus is absent. Catches
                   EMISSION-side regressions: a method starting to emit a new token.

So a PR that changes a method's emitted values is NOT caught by CI here. It is caught at corpus
regeneration. That is a real hole, named on purpose rather than papered over.

Usage:
    python validators/build_emission_ledger.py                  # regenerate the snapshot
    python validators/build_emission_ledger.py --self-check     # CI: hermetic drift gate
    python validators/build_emission_ledger.py --self-check --corpus <dir>   # + verify counts

Modelled on build_rule_role_partition.py (committed snapshot + --self-check, a pattern CI already
gates), including its central rule: the generator writes its inputs into the snapshot for diff
visibility but NEVER reads them back. `declared` is re-read from cards/ at check time, because
deriving a guard's scope from the artifact it is checking is how the guard goes vacuous.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CARDS = ROOT / "cards"
LEDGER_PATH = ROOT / "coverage" / "emission_ledger.yaml"

DEFAULT_CORPUS = Path(os.environ.get("EMISSION_CORPUS", Path.home() / "dev" / "target-archetype-corpus-20260920"))

# Anti-vacuity floors. A ledger that silently finds nothing is indistinguishable from a clean
# repo, which is the exact failure this file exists to remove.
MIN_PACKAGES = 100
MIN_CARDS_WITH_OBSERVATIONS = 40


# ---------------------------------------------------------------------------
# declared side (hermetic: committed cards only)
# ---------------------------------------------------------------------------
def load_declared() -> dict[str, dict[str, dict]]:
    """{card_id -> {field -> {"tokens": [...], "grain": <grain>}}}.

    GRAIN IS LOAD-BEARING AND MUST BE RESOLVED BEFORE ANYTHING IS ACCUSED. A vocabulary key can
    target four different things, and a walk that assumes `summary[field]` is a scalar string
    mis-accuses three of them. Measured on this repo: 5 of an initial 18 `never_observed` findings
    (28%) were grain errors, not defects — the same false-positive class
    `test_card_vocabulary_declaration` documents at ~20%.

      scalar          the field is in `outputs.summary_fields`. Arity (one token vs a list of
                      tokens) is NOT declared anywhere, so the walker observes it; four fields
                      here emit ARRAYS of tokens (`protein_class` 102/120, `moa_classes_present`
                      114/120) and were invisible to a scalar-only read.
      record:<field>  the key lives inside `summary_fields_record_schemas[<field>]`, i.e. inside
                      the items of a record array. Censusable, but only by descending.
      lens:<axis>     the field carries `lens_conditional_on` — "emitted only when the --modality
                      lens is invoked". The deterministic corpus is built WITHOUT a lens, so its
                      absence is EXPECTED, not a defect. Never gated.
      orphan          declared on no field at all. A real defect, but one this repo ALREADY gates
                      in `validate_cards._summary_vocabulary_declaration_check`; re-gating it here
                      would double-report the same 4 keys and make two gates move together.
    """
    declared: dict[str, dict[str, dict]] = {}
    for path in sorted(CARDS.glob("*.card.yaml")):
        spec = yaml.safe_load(path.read_text()) or {}
        outputs = spec.get("outputs") or {}
        card_id = spec.get("card_id") or path.name.removesuffix(".card.yaml")

        scalars: set[str] = set()
        lens: dict[str, str] = {}
        for entry in outputs.get("summary_fields") or []:
            if isinstance(entry, str):
                scalars.add(entry)
            elif isinstance(entry, dict) and entry.get("name"):
                scalars.add(entry["name"])
                if entry.get("lens_conditional_on"):
                    lens[entry["name"]] = entry["lens_conditional_on"]

        records = outputs.get("summary_fields_record_schemas") or {}
        in_record = {
            key: rec_field for rec_field, schema in records.items() if isinstance(schema, dict) for key in schema
        }

        fields: dict[str, dict] = {}
        for field, tokens in (outputs.get("summary_fields_vocabulary") or {}).items():
            if not isinstance(tokens, list):
                continue
            if field in lens:
                grain = f"lens:{lens[field]}"
            elif field in scalars:
                grain = "scalar"
            elif field in in_record:
                grain = f"record:{in_record[field]}"
            else:
                grain = "orphan"
            fields[field] = {"tokens": list(tokens), "grain": grain}
        if fields:
            declared[card_id] = fields
    return declared


def gated_grain(grain: str) -> bool:
    """Only scalar and record grains can be accused of never being observed."""
    return grain == "scalar" or grain.startswith("record:")


def normalize(value) -> str | None:
    """Emitted value -> the token form a declared vocabulary can be compared against.

    The card schema mandates string-only vocabulary lists (no `null`, no bools), so a method
    emitting Python True against a declared ['true', 'false'] is a TYPE mismatch, not a
    vocabulary violation. Normalizing here and reporting the type separately is what keeps five
    dead-by-construction declarations out of the gate; a naive comparison shipped them as five
    false positives.
    """
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return None
    return value


# ---------------------------------------------------------------------------
# observed side (corpus)
# ---------------------------------------------------------------------------
def _new_bucket() -> dict:
    return {
        "tokens": Counter(),  # normalized token -> count
        "types": Counter(),  # python type name of the emitted value -> count
        "n_scalar": 0,  # emissions where the value was a scalar
        "n_array": 0,  # emissions where the value was a list of tokens
        "n_empty_array": 0,  # ... of which were []
        "n_absent": 0,  # card present, key absent from its summary
    }


def _census(bucket: dict, value) -> None:
    """Count one emitted value, tracking ARITY separately from token counts.

    Arity is not declared on the card, so it is observed here. It matters because saturation
    (top / non-null) is only meaningful for a scalar field: in an array field a package
    contributes several tokens at once, so top/total is a share of TOKENS, not of packages, and
    reading it as "this field is degenerate" would be wrong.
    """
    bucket["types"][type(value).__name__] += 1
    if isinstance(value, list):
        bucket["n_array"] += 1
        if not value:
            bucket["n_empty_array"] += 1
        for item in value:
            if isinstance(item, (str, bool)) or item is None:
                bucket["tokens"][normalize(item)] += 1
    elif isinstance(value, (str, bool)) or value is None:
        bucket["n_scalar"] += 1
        bucket["tokens"][normalize(value)] += 1


def walk_corpus(corpus: Path, declared: dict) -> tuple[dict, dict[str, int], dict]:
    """Walk <corpus>/<TARGET-INDICATION>/evidence_package.json -> cards[].summary.

    Censuses exactly the declared vocabulary keys, at each key's declared GRAIN — scalar/array
    fields from the summary itself, record-grain keys by descending into the record array. Walking
    only `summary[field]` as a scalar is what produced a 28% false-positive rate.
    """
    observed: dict[str, dict[str, dict]] = defaultdict(dict)
    with_card: Counter = Counter()
    n_pkg = n_bad = 0
    build_shas: Counter = Counter()

    for pkg in sorted(corpus.glob("*/evidence_package.json")):
        try:
            doc = json.loads(pkg.read_text())
        except Exception:
            n_bad += 1
            continue
        n_pkg += 1
        sha_file = pkg.parent / "build_sha.json"
        if sha_file.exists():
            try:
                build_shas[json.loads(sha_file.read_text()).get("claude-oncology-skills", "?")] += 1
            except Exception:
                build_shas["unparseable"] += 1

        for card in doc.get("cards") or []:
            card_id = card.get("card_id")
            summary = card.get("summary")
            if not card_id or not isinstance(summary, dict):
                continue
            with_card[card_id] += 1
            for field, spec in (declared.get(card_id) or {}).items():
                grain = spec["grain"]
                bucket = observed[card_id].setdefault(field, _new_bucket())
                if grain.startswith("record:"):
                    rec_field = grain.split(":", 1)[1]
                    rows = summary.get(rec_field)
                    if not isinstance(rows, list):
                        bucket["n_absent"] += 1
                        continue
                    for row in rows:
                        if isinstance(row, dict) and field in row:
                            _census(bucket, row[field])
                        else:
                            bucket["n_absent"] += 1
                elif field in summary:
                    _census(bucket, summary[field])
                else:
                    # ABSENT KEY is not the same fact as an emitted null: one means the method
                    # never wrote the field, the other means it wrote "no value". Rules key on the
                    # value, so conflating them hides which of the two is happening.
                    bucket["n_absent"] += 1

    meta = {
        "n_packages": n_pkg,
        "n_unparseable": n_bad,
        # A shared checkout is not a pinned input over a multi-hour build. Stamping the producing
        # SHA makes a heterogeneous corpus detectable instead of assumed.
        "build_shas": dict(build_shas.most_common()),
    }
    return dict(observed), dict(with_card), meta


# ---------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------
def declared_pairs(declared) -> set[str]:
    return {f"{c}::{f}" for c, fs in declared.items() for f in fs}


def derive(declared, observed, with_card) -> dict:
    """Per (card_id, field) the corpus emitted at least one value for.

    Pairs the corpus never emits are NOT dropped silently — see `never_observed_pairs`. Dropping
    them is a fail-open, and the strongest form of the failure this file exists to catch: not a
    rare token, but a rule keying on a field no package contains.
    """
    by_card: dict[str, dict] = {}
    for card_id, fields in sorted(declared.items()):
        for field, spec in sorted(fields.items()):
            bucket = observed.get(card_id, {}).get(field)
            if not bucket:
                # The CARD never appeared in any package. Distinct from every status below, and
                # reported by its absence from by_card.
                continue
            declared_set = {t for t in spec["tokens"] if t is not None}
            non_null = {k: v for k, v in bucket["tokens"].items() if k is not None}
            total = sum(non_null.values())
            top, top_n = max(sorted(non_null.items()), key=lambda kv: kv[1]) if non_null else (None, 0)
            arity = (
                "array"
                if bucket["n_array"] and not bucket["n_scalar"]
                else "scalar"
                if bucket["n_scalar"] and not bucket["n_array"]
                else "mixed"
                if bucket["n_array"] and bucket["n_scalar"]
                else "none"
            )
            # "No value observed" has FOUR distinct causes with four different fixes, and a check
            # that collapses them reports the wrong defect. Naming the status is what separates
            # "the method never writes this field" from "the method always writes []" — the second
            # kills every rule keyed on the field while the field itself looks healthy.
            if total:
                status = "observed"
            elif bucket["n_empty_array"] and bucket["n_empty_array"] == bucket["n_array"]:
                status = "always_empty_array"
            elif bucket["n_scalar"] or bucket["n_array"]:
                status = "always_null"
            else:
                status = "field_absent"

            row = {
                "grain": spec["grain"],
                "arity": arity,
                "status": status,
                "declared": sorted(declared_set),
                "observed": dict(sorted(non_null.items(), key=lambda kv: (-kv[1], kv[0]))),
                "n_non_null": total,
                "n_null": bucket["tokens"].get(None, 0),
                "n_absent": bucket["n_absent"],
                "n_packages_with_card": with_card.get(card_id, 0),
                "out_of_vocab": sorted(set(non_null) - declared_set),
                "never_emitted": sorted(declared_set - set(non_null)),
                "top": top,
            }
            # Saturation is a per-PACKAGE degeneracy claim, so it is only meaningful where one
            # package contributes one token. An array field contributes several at once, so
            # top/total there is a share of tokens and reading it as "degenerate" would be wrong.
            if arity == "scalar":
                row["saturation"] = round(top_n / total, 4) if total else None
            else:
                row["saturation"] = None
                row["saturation_na"] = f"arity={arity}: top/total is a token share, not a package share"
                row["n_emissions"] = bucket["n_array"] + bucket["n_scalar"]
                row["n_empty_array"] = bucket["n_empty_array"]
            # Reported, never gated: the card schema forbids non-string vocabulary entries, so a
            # bool emission against a ['true','false'] declaration is dead by construction.
            if set(bucket["types"]) - {"str", "NoneType", "list"}:
                row["emitted_types"] = dict(sorted(bucket["types"].items()))
            by_card.setdefault(card_id, {})[field] = row
    return by_card


def violations(by_card) -> list[str]:
    """Flat `card_id::field::token` keys for every out_of_vocab observation."""
    return sorted(
        f"{card_id}::{field}::{token}"
        for card_id, fields in by_card.items()
        for field, row in fields.items()
        for token in row["out_of_vocab"]
    )


def never_observed_pairs(declared, by_card) -> list[str]:
    """Declared (card, field) pairs the corpus emits 0x — GATED GRAINS ONLY.

    A lens-conditional field is expected-absent in a lens-free corpus, and an orphan vocabulary is
    already gated by validate_cards. Accusing either here would be a false positive, and would make
    two gates move together on the same 4 keys.
    """
    return sorted(never_observed_reasons(declared, by_card))


def never_observed_reasons(declared, by_card) -> dict[str, str]:
    """{`card::field` -> why no token was ever observed}, gated grains only.

    Keyed the same as the gate list so the two cannot disagree, but carrying the cause, because
    `card_never_emitted` (wire the card), `field_absent` (wire the field), `always_empty_array`
    (the producer computes nothing) and `always_null` (the producer declines to answer) are four
    different repairs.
    """
    out: dict[str, str] = {}
    for card_id, fields in declared.items():
        for field, spec in fields.items():
            if not gated_grain(spec["grain"]):
                continue
            row = (by_card.get(card_id) or {}).get(field)
            if row is None:
                out[f"{card_id}::{field}"] = "card_never_emitted"
            elif row["status"] != "observed":
                out[f"{card_id}::{field}"] = row["status"]
    return out


def ungated_absences(declared, by_card) -> dict[str, list[str]]:
    """Declared-but-unobserved pairs whose grain makes the absence expected. Reported, not gated.

    The test is "does this key have OBSERVATIONS?", never "does it have a row?". walk_corpus writes
    a row for every declared pair it looked for, absent ones included, so keying off row presence
    made this entire report vacuous — it published `{}` while 4 orphans and every lens field sat in
    NEITHER summary list. An exclusion filter that swallows its own subject is the failure this
    report exists to prevent, so the partition is asserted in self_check_hermetic.
    """
    has_observations = {
        f"{c}::{f}" for c, fs in by_card.items() for f, r in fs.items() if r.get("status") == "observed"
    }
    out: dict[str, list[str]] = defaultdict(list)
    for card_id, fields in declared.items():
        for field, spec in fields.items():
            key = f"{card_id}::{field}"
            if key in has_observations or gated_grain(spec["grain"]):
                continue
            reason = (
                "lens_conditional: corpus is built without --modality"
                if spec["grain"].startswith("lens:")
                else "orphan: declared on no field — already gated by validate_cards"
            )
            out[reason].append(key)
    return {k: sorted(v) for k, v in sorted(out.items())}


def dead_token_count(by_card) -> int:
    return sum(len(r["never_emitted"]) for fs in by_card.values() for r in fs.values())


def compute_ledger(corpus: Path) -> dict:
    declared = load_declared()
    observed, with_card, meta = walk_corpus(corpus, declared)
    by_card = derive(declared, observed, with_card)
    never_observed = never_observed_pairs(declared, by_card)
    return {
        "_doc": (
            "T1 emission ledger: the (card_id, field, value) triples the corpus actually emits, "
            "per declaring card. out_of_vocab GATES (a contradiction between two committed "
            "files); never_emitted and saturation are DIMENSIONS, not gates. Regenerate with "
            "validators/build_emission_ledger.py; --self-check gates declaration-side drift. "
            "Grain is per (card_id, field) and is never pooled by field name."
        ),
        "corpus_vintage": corpus.name,
        "n_packages": meta["n_packages"],
        "n_unparseable": meta["n_unparseable"],
        "producing_shas": meta["build_shas"],
        # UNKNOWN IS NOT HOMOGENEOUS. An empty producing_shas map means the corpus carries no
        # build_sha.json stamps at all (every vintage before 20260919), so the counts cannot be
        # attributed to any code state — yet `{}` reads exactly like a clean single-SHA build, and a
        # warning keyed on `len > 1` stays silent for it. Name the three states so a reviewer cannot
        # mistake absent provenance for verified provenance.
        "provenance": (
            "unknown: corpus carries no build_sha.json stamps"
            if not meta["build_shas"]
            else "homogeneous"
            if len(meta["build_shas"]) == 1
            else "heterogeneous: packages were produced by different code"
        ),
        "counts": {
            "cards_declaring_vocabulary": len(declared),
            "cards_with_observations": len(by_card),
            "declared_pairs": len(declared_pairs(declared)),
            "pairs": sum(len(v) for v in by_card.values()),
            "out_of_vocab": len(violations(by_card)),
            "never_observed_pairs": len(never_observed),
            "dead_tokens": dead_token_count(by_card),
        },
        # Absences whose GRAIN makes them expected. Written out so the exclusion is auditable
        # rather than an invisible filter — an unexplained exclusion is how a gate quietly narrows.
        "ungated_absences": ungated_absences(declared, by_card),
        # Both lists are dated so each removal is a one-line PR and trunk lands green.
        # `contracts-validate` is not a branch-protection-required check, so a red trunk silently
        # taints every open PR.
        "known_out_of_vocab": {
            "as_of": date.today().isoformat(),
            "keys": violations(by_card),
        },
        # A declared vocabulary nothing emits. Listed today, GATED on new additions: that is what
        # makes it impossible to declare a key space no method produces — the failure that cost a
        # 21-PR arc whose binding conjunct fired ~0x.
        "known_never_observed": {
            "as_of": date.today().isoformat(),
            "keys": never_observed,
            "reasons": never_observed_reasons(declared, by_card),
        },
        "by_card": by_card,
    }


# ---------------------------------------------------------------------------
# self-check
# ---------------------------------------------------------------------------
def _floors(ledger: dict) -> list[str]:
    n_pkg = ledger.get("n_packages") or 0
    n_cards = (ledger.get("counts") or {}).get("cards_with_observations") or 0
    errs = []
    if n_pkg < MIN_PACKAGES:
        errs.append(f"vacuous: n_packages={n_pkg} < {MIN_PACKAGES} — the census saw ~no corpus")
    if n_cards < MIN_CARDS_WITH_OBSERVATIONS:
        errs.append(
            f"vacuous: cards_with_observations={n_cards} < {MIN_CARDS_WITH_OBSERVATIONS} — the "
            f"walk found ~no cards, which reads identically to a clean repo"
        )
    return errs


def _row_integrity(card_id: str, field: str, row: dict) -> list[str]:
    """Each row's own arithmetic must agree with its own `observed` map.

    The hermetic half necessarily TRUSTS the committed counts — only the corpus half can prove
    them. But it need not trust them to be self-consistent: a hand-edited count breaks
    n_non_null, saturation and top simultaneously, so checking a row against itself catches
    fabrication without pretending to re-measure. Bounded, honest, and cheap.
    """
    errs: list[str] = []
    observed = row.get("observed") or {}
    total = sum(observed.values())
    if total != row.get("n_non_null"):
        errs.append(
            f"internally inconsistent {card_id}::{field}: n_non_null={row.get('n_non_null')} but "
            f"observed sums to {total} — the row was hand-edited or partially regenerated"
        )
        return errs  # every derived field below is now meaningless
    if observed:
        top, top_n = max(sorted(observed.items()), key=lambda kv: kv[1])
        if row.get("top") != top:
            errs.append(
                f"internally inconsistent {card_id}::{field}: top={row.get('top')!r} is not the argmax ({top!r})"
            )
        # Saturation is defined ONLY for scalar arity — see derive(). Recomputing it for an array
        # row would demand a number the generator deliberately withholds, and this check would
        # then red on every correct array row.
        if row.get("arity") == "scalar":
            want = round(top_n / total, 4) if total else None
            if row.get("saturation") != want:
                errs.append(
                    f"internally inconsistent {card_id}::{field}: saturation={row.get('saturation')} "
                    f"but top/non-null = {want}"
                )
        elif row.get("saturation") is not None:
            errs.append(
                f"internally inconsistent {card_id}::{field}: arity={row.get('arity')} must carry "
                f"saturation: null (top/total would be a token share, not a package share)"
            )
    return errs


def self_check_hermetic(ledger: dict) -> list[str]:
    """Re-derive the findings from committed `observed` counts + TODAY's cards. No corpus.

    LIMITATION, stated so it cannot become a green for the wrong reason: this half cannot know
    whether the committed counts match the corpus. It proves they are internally consistent and
    that they agree with today's declarations. Only `--corpus` proves the counts themselves.
    """
    declared = load_declared()
    errs = _floors(ledger)
    known = set((ledger.get("known_out_of_vocab") or {}).get("keys") or [])
    live: set[str] = set()

    for card_id, fields in sorted((ledger.get("by_card") or {}).items()):
        card_vocab = declared.get(card_id)
        if card_vocab is None:
            errs.append(
                f"stale entry {card_id!r} — the ledger names a card that declares no vocabulary; "
                f"it was deleted, renamed, or lost its summary_fields_vocabulary without "
                f"regenerating"
            )
            continue
        for field, row in sorted(fields.items()):
            spec = card_vocab.get(field)
            if spec is None:
                errs.append(
                    f"stale entry {card_id}::{field} — no such field in the card's vocabulary; a "
                    f"rename or deletion landed without regenerating the ledger"
                )
                continue
            if row.get("grain") != spec["grain"]:
                errs.append(
                    f"grain drift {card_id}::{field}: ledger says {row.get('grain')!r}, card now "
                    f"implies {spec['grain']!r} — the field moved between scalar/record/lens/orphan "
                    f"and the census read it at the wrong grain"
                )
            errs += _row_integrity(card_id, field, row)
            declared_set = {t for t in spec["tokens"] if t is not None}
            observed_set = set((row.get("observed") or {}).keys())
            fresh = sorted(observed_set - declared_set)
            live.update(f"{card_id}::{field}::{t}" for t in fresh)

            # Direction matters. A snapshot that UNDER-reports is safety-adverse: it means the
            # card narrowed its vocabulary while the corpus still emits the value, so a rule keyed
            # on it now references a token the contract no longer admits.
            for token in sorted(set(fresh) - set(row.get("out_of_vocab") or [])):
                errs.append(
                    f"NEW out_of_vocab {card_id}::{field}::{token} (emitted "
                    f"{row['observed'][token]}x) — the card's declared vocabulary no longer admits "
                    f"a value the corpus emits; SAFETY-ADVERSE"
                )
            for token in sorted(set(row.get("out_of_vocab") or []) - set(fresh)):
                errs.append(
                    f"RESOLVED out_of_vocab {card_id}::{field}::{token} — the declaration now "
                    f"admits it; regenerate the ledger to bank the fix"
                )

    for key in sorted(live - known):
        errs.append(f"unlisted violation {key} — add it to known_out_of_vocab or fix the contract")
    for key in sorted(known - live):
        errs.append(
            f"known_out_of_vocab lists {key} but it is no longer a violation — regenerate so the "
            f"list cannot accumulate fixed entries and go vacuous"
        )

    # NEVER-OBSERVED pairs. This is the gate that makes the subset_high failure class impossible:
    # a newly declared vocabulary that no package emits reds until it is either produced or
    # consciously listed. Hermetic because `declared` is today's cards and `by_card` is the
    # committed census.
    listed = set((ledger.get("known_never_observed") or {}).get("keys") or [])
    fresh_never = set(never_observed_reasons(declared, ledger.get("by_card") or {}))
    observed_now = {
        f"{c}::{f}"
        for c, fs in (ledger.get("by_card") or {}).items()
        for f, r in fs.items()
        if r.get("status") == "observed"
    }
    for key in sorted(fresh_never - listed):
        errs.append(
            f"NEW never_observed {key} — the card declares a vocabulary the corpus emits 0x. Do "
            f"not build a rule on it: either make a method emit it, or list it in "
            f"known_never_observed with today's date"
        )
    for key in sorted(listed - fresh_never):
        card_field = key.split("::")
        if len(card_field) == 2 and card_field[0] not in declared:
            errs.append(f"stale known_never_observed {key} — no card declares that vocabulary")
        elif key in observed_now:
            errs.append(f"known_never_observed lists {key} but the corpus now emits it — regenerate to bank the fix")
        else:
            errs.append(f"stale known_never_observed {key} — no longer a declared pair")

    # PARTITION. Every declared pair with no observations is either GATED (known_never_observed) or
    # EXCUSED BY GRAIN (ungated_absences) — exactly one, never neither. Without this, an absence can
    # go missing from both summaries and the artifact reads clean while a field is dead: the first
    # version of ungated_absences published `{}` for precisely this reason. An exclusion is only
    # honest if it is written down, so the check is that the excusing list is non-empty where
    # exclusions exist, not merely that the gate stayed quiet.
    excused = {k for v in (ledger.get("ungated_absences") or {}).values() for k in v}
    for card_id, fields in sorted(declared.items()):
        for field, spec in sorted(fields.items()):
            key = f"{card_id}::{field}"
            if key in observed_now:
                continue
            in_gated, in_excused = key in listed, key in excused
            if in_gated and in_excused:
                errs.append(
                    f"double-reported {key} — an absence counted as both a defect and an expected "
                    f"exclusion; the grain partition is broken"
                )
            elif not in_gated and not in_excused:
                errs.append(
                    f"unreported absence {key} (grain={spec['grain']}) — the corpus emits no value "
                    f"and NEITHER summary list names it, so the ledger reads clean while the field "
                    f"is dead. Gate it in known_never_observed or excuse it in ungated_absences"
                )
    return errs


def self_check_corpus(ledger: dict, corpus: Path) -> tuple[list[str], str | None]:
    """Re-walk the corpus and confirm the committed counts. Returns (errors, skip_reason).

    A VINTAGE MISMATCH IS A SKIP, NOT A FAILURE, and the distinction is the whole point. Counts
    from two different corpora are not comparable, so this half is simply INAPPLICABLE — the same
    epistemic position as a missing corpus. Failing instead would red preland for every developer
    whose corpus is newer than the committed ledger, for a reason unrelated to their change; the
    predictable response is to silence the step, and then the half is lost for real cases too.

    What stays fatal is the case this half exists for: same vintage, different counts.
    """
    fresh = compute_ledger(corpus)
    errs: list[str] = []
    if fresh["corpus_vintage"] != ledger.get("corpus_vintage"):
        return errs, (
            f"vintage mismatch — ledger was built from {ledger.get('corpus_vintage')!r}, on disk is "
            f"{fresh['corpus_vintage']!r}; counts are not comparable. To verify, point "
            f"EMISSION_CORPUS at {ledger.get('corpus_vintage')!r}, or regenerate the ledger"
        )
    cf, cl = fresh["by_card"], ledger.get("by_card") or {}
    for card_id in sorted(set(cf) | set(cl)):
        ff, fl = cf.get(card_id, {}), cl.get(card_id, {})
        for field in sorted(set(ff) | set(fl)):
            a, b = ff.get(field, {}).get("observed"), fl.get(field, {}).get("observed")
            if a != b:
                errs.append(f"count drift {card_id}::{field}: walked {a} vs committed {b}")
    return errs, None


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="CI-safe: fail if the committed ledger drifted from today's cards",
    )
    ap.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS,
        help=f"emitted-package corpus root (default: {DEFAULT_CORPUS})",
    )
    args = ap.parse_args(argv)

    if args.self_check:
        if not LEDGER_PATH.exists():
            print(f"missing {LEDGER_PATH.name} — run without --self-check to generate it")
            return 1
        ledger = yaml.safe_load(LEDGER_PATH.read_text()) or {}
        errs = self_check_hermetic(ledger)
        print("build_emission_ledger.py --self-check (hermetic: cards vs committed counts)")
        # Announced either way, never silent: a skipped half that prints nothing reads as a pass.
        if args.corpus.is_dir():
            corpus_errs, skipped = self_check_corpus(ledger, args.corpus)
            errs += corpus_errs
            if skipped:
                print(f"  ~ corpus half SKIPPED: {skipped}")
            else:
                print(f"  + corpus half: re-walked {args.corpus}")
        else:
            print(f"  ~ corpus half SKIPPED: {args.corpus} absent (emission-side drift unchecked)")
        for e in errs:
            print(f"  [DRIFT] {e}")
        print("  OK" if not errs else "  FAILED")
        return 0 if not errs else 1

    if not args.corpus.is_dir():
        print(f"cannot regenerate: corpus {args.corpus} not found")
        return 1

    ledger = compute_ledger(args.corpus)
    # A regenerate that quietly writes a vacuous ledger is the failure this file is about, so the
    # floors are fatal here too, not only under --self-check.
    fatal = _floors(ledger)
    if fatal:
        print("build_emission_ledger.py: REFUSING to write — fix these first:")
        for e in fatal:
            print(f"  [ERROR] {e}")
        return 1

    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(yaml.safe_dump(ledger, sort_keys=False, width=100))
    c = ledger["counts"]
    print(
        f"wrote {LEDGER_PATH.relative_to(ROOT)} — {ledger['n_packages']} packages, "
        f"{c['pairs']} (card, field) pairs over {c['cards_with_observations']} cards, "
        f"{c['out_of_vocab']} out_of_vocab."
    )
    if not ledger["producing_shas"]:
        print(
            "  NOTE provenance UNKNOWN — no build_sha.json stamps in this corpus, so these counts "
            "cannot be attributed to a code state. Resolved by regenerating on a stamped vintage."
        )
    elif len(ledger["producing_shas"]) > 1:
        print(f"  NOTE heterogeneous corpus — producing skills SHAs: {ledger['producing_shas']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
