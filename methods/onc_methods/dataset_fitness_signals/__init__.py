"""dataset_fitness_signals — the executor for the declared dataset-fitness resolution.

WHAT THIS IS FOR
----------------
target-contracts ships ``vocabularies/dataset_fitness_resolution.yaml`` (PR #832): a
product-grain ladder that maps the measured quality signals of a data PRODUCT onto a
``dataset_fitness_class``. That contract is deliberately NOT a ``resolvers/*.resolver.yaml``
-- ``validate_resolvers.py`` globs that directory and requires every ``when_fired`` token to
be a ``rule_id`` from ``interpretation-rules/``, which key on ``card_id``, which requires a
per-TARGET ``measurement_type``. A product-grain resolution is unreachable there, and
keeping it out is what makes the contract's ``never_gates: true`` a REACHABILITY guarantee
rather than a convention.

The consequence is that **no existing engine walks that ladder**. Until this method, its only
interpreter was its own test. Any consumer wanting a fitness class -- a skill, a dashboard, a
dataset report -- had to re-derive one, and the whole point of the axis is that a naive
re-derivation gets it WRONG in a specific, measured way: it reads comparator SHAPE as data
quality.

So: the YAML stays the single source of ladder truth, and this method is its one executor.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not produce the signals. ``data-catalog``'s ``characterization/dge_characterize.py``
and the dataset-profile sidecars are their sole producer; a second producer would be drift.
This method consumes a signal mapping and applies the declared rules to it.

THE TWO PIECES
--------------
``resolve``      -- the contract-driven ladder evaluator. First-match-wins over the rungs in
                    document order (which it VERIFIES equals priority order), with the
                    absence semantics the contract's own tests pin: an absent value never
                    satisfies a bound, so there is no unfit-by-silence and no fit-by-silence.

``distribution`` -- the shape-CONDITIONED roster-relative cut. ``discordance_high`` is
                    declared ``basis: roster_relative`` with its distribution frozen as of
                    2026-09-19 over the ``both_comparators`` partition ONLY (n=21), and the
                    contract states it "must be re-anchored when a second family lands".
                    Re-anchoring by pooling the whole roster reproduces the very confound the
                    axis exists to prevent, so the conditioning is enforced in code rather
                    than left to the caller's memory. See that module for the measurement.

Modeled on ``percentile_null`` (pure computation, ``None`` for unmeasurable, a categorical
companion because the rules engine cannot threshold a float) and on
``dge_deseq2/figures.py`` for the ``TARGET_CONTRACTS_ROOT``-or-sibling contract resolution.
"""

from __future__ import annotations

from .distribution import (
    conditioned_values,
    percentile_cut,
    reanchor,
    roster_relative_cut,
)
from .resolve import (
    CONTRACT_REL,
    ContractInvalid,
    ContractUnavailable,
    contract_path,
    load_contract,
    resolve_fitness,
)

__all__ = [
    "CONTRACT_REL",
    "ContractInvalid",
    "ContractUnavailable",
    "conditioned_values",
    "contract_path",
    "load_contract",
    "percentile_cut",
    "reanchor",
    "resolve_fitness",
    "roster_relative_cut",
]
