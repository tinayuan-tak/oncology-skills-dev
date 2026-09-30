"""Contract-driven evaluator for ``dataset_fitness_resolution.yaml``.

THE GRAMMAR THIS EXECUTES
-------------------------
``resolve:`` is an ordered list of rungs. Each carries a ``class``, a ``priority``, a
``reason_code``, optionally a ``reason_detail_from``, and exactly one of ``when_any`` /
``when_all``. A clause is either ``{signal, op, value}`` or ``{threshold: <id>}``, where the
threshold is looked up in ``thresholds:`` and supplies its own ``signal``/``op``/``value``.
Evaluation is ``first_match_wins``; a product matching nothing lands on ``default:``.

THREE THINGS THIS ENFORCES RATHER THAN ASSUMES
---------------------------------------------
1. **An absent value never satisfies a bound.** ``gt/gte/lt/lte`` against ``None`` is False,
   in BOTH directions -- no unfit-by-silence and no fit-by-silence. The contract's ``fit``
   rung is an explicit positive conjunction for exactly this reason, and an executor that let
   a missing value pass a bound would hand back the promotion the contract refuses.

2. **Document order must equal priority order.** ``first_match_wins`` over a list makes
   document order the operative ordering, while every human reads the ``priority:`` numbers.
   If those two disagree the contract means one thing and does another, so a non-monotonic
   ladder is a ``ContractInvalid`` rather than a silently different verdict. This matters
   concretely: the contract's own rationale says the shape rungs (15 and 30) being ABOVE the
   reliability rung (40) is what makes the discordance read a within-shape comparison, and
   that guarantee is carried by ordering alone.

3. **A non-finite number is treated as ABSENT, and said so out loud.** ``float('inf')`` is a
   number: it satisfies ``gt``, and ``pd.isna`` returns False for it, so an inf missingness
   fraction would be scored as "91% missing" and a NaN would quietly fail every bound in
   whichever direction happened to be safe. Both are corrupt values, not measurements, so
   they are normalised to ``None`` and reported in ``anomalies`` -- an abstention the consumer
   can see, never a silent score. Inert on the first roster (all 36 rows are finite), which
   is pinned by a test so the guard is known to be forward-looking rather than load-bearing.

ABSENCE DISCIPLINE ON THE CONTRACT READ ITSELF
----------------------------------------------
The repo's reader-absence lint exists because ``except Exception: return <empty>`` turns a
broken environment into an honest-looking "no data". The same distinction applies to reading a
contract, so this module separates the two cases: a contract that is not on disk raises
``ContractUnavailable`` (the sibling repo is genuinely absent -- a clone without it beside),
and a contract that IS on disk but does not satisfy the grammar raises ``ContractInvalid``.
Neither degrades to a default class, because "we could not read the rules" and "the rules say
not_measured" are different facts and only one of them is about the data.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

import yaml

from onc_methods.roots import contracts_root

CONTRACT_REL = "vocabularies/dataset_fitness_resolution.yaml"


def _default_target_contracts() -> Path:
    """Resolve TARGET_CONTRACTS_ROOT, else the sibling checkout -- read at CALL time (delegates
    to ``methods.roots.contracts_root``, itself resolved fresh on every call).

    ``methods/dge_deseq2/figures.py`` caches this at import time; that is a latent bug rather
    than a convention to copy. A consumer that sets the env var after importing us (a CLI that
    parses its own args first, a notebook, a test) would silently keep the stale path, and the
    failure mode is a contract read against the wrong checkout -- which looks like a stale
    contract, not like a misconfiguration.
    """
    return contracts_root()


_REQUIRED_KEYS = ("resolution_id", "emits", "keyed_by", "evaluation", "reads", "thresholds", "resolve", "default")
_BOUND_OPS = ("gt", "gte", "lt", "lte")


class ContractUnavailable(FileNotFoundError):
    """The resolution contract is not on disk (sibling target-contracts absent)."""


class ContractInvalid(ValueError):
    """The contract is on disk but does not satisfy the grammar this executor implements."""


def contract_path(target_contracts_root: str | Path | None = None) -> Path:
    """Where the resolution contract is expected to live.

    Resolution order is arg > ``TARGET_CONTRACTS_ROOT`` > sibling checkout. Returned whether
    or not it exists, so a caller can report the path it looked at.
    """
    root = Path(target_contracts_root) if target_contracts_root else _default_target_contracts()
    return root / CONTRACT_REL


def load_contract(target_contracts_root: str | Path | None = None) -> dict:
    """Load and structurally validate the resolution contract.

    Raises ``ContractUnavailable`` if the file is absent and ``ContractInvalid`` if it is
    present but violates the grammar. The ``never_gates`` check is deliberate: this executor
    is written for a DIMENSION axis that reports and never vetoes, so a contract that flipped
    to gating must not silently acquire an engine -- it should red here and get reviewed.
    """
    path = contract_path(target_contracts_root)
    if not path.exists():
        raise ContractUnavailable(
            f"dataset-fitness resolution contract not found at {path}. It ships in the sibling "
            "target-contracts repo; set TARGET_CONTRACTS_ROOT or clone it beside this one."
        )
    with open(path) as fh:
        contract = yaml.safe_load(fh)
    if not isinstance(contract, dict):
        raise ContractInvalid(f"{path}: top level is {type(contract).__name__}, expected a mapping")

    missing = [k for k in _REQUIRED_KEYS if k not in contract]
    if missing:
        raise ContractInvalid(f"{path}: missing required keys {missing}")
    if contract["evaluation"] != "first_match_wins":
        raise ContractInvalid(
            f"{path}: evaluation is {contract['evaluation']!r}; this executor implements first_match_wins only"
        )
    if contract.get("never_gates") is not True:
        raise ContractInvalid(
            f"{path}: never_gates is {contract.get('never_gates')!r}. This executor is written "
            "for a report-only dimension; a gating fitness axis needs a reviewed gate path, not "
            "an engine it inherited by accident."
        )
    _validate_ladder(contract, path)
    return contract


def _validate_ladder(contract: Mapping[str, Any], path: Path | str) -> None:
    """Check the ladder's shape, including the document-order/priority-order agreement."""
    rungs = contract["resolve"]
    if not isinstance(rungs, list) or not rungs:
        raise ContractInvalid(f"{path}: resolve must be a non-empty list")

    priorities = []
    for i, rung in enumerate(rungs):
        if not isinstance(rung, dict):
            raise ContractInvalid(f"{path}: resolve[{i}] is not a mapping")
        for key in ("class", "priority", "reason_code"):
            if key not in rung:
                raise ContractInvalid(f"{path}: resolve[{i}] missing {key!r}")
        has_any, has_all = "when_any" in rung, "when_all" in rung
        if has_any == has_all:  # neither, or both
            raise ContractInvalid(
                f"{path}: resolve[{i}] (priority {rung.get('priority')}) must carry exactly one of when_any / when_all"
            )
        clauses = rung["when_any"] if has_any else rung["when_all"]
        if not isinstance(clauses, list) or not clauses:
            raise ContractInvalid(f"{path}: resolve[{i}] has an empty clause list")
        priorities.append(rung["priority"])

    if priorities != sorted(priorities):
        raise ContractInvalid(
            f"{path}: resolve priorities {priorities} are not ascending in document order. "
            "first_match_wins makes DOCUMENT order operative while every reader reasons about "
            "the priority numbers, so the two disagreeing means the ladder means one thing and "
            "does another -- reorder the blocks and the numbers together."
        )
    if len(set(priorities)) != len(priorities):
        raise ContractInvalid(f"{path}: duplicate priorities {priorities} -- first-match becomes position-dependent")

    for key in ("class", "reason_code"):
        if key not in contract["default"]:
            raise ContractInvalid(f"{path}: default missing {key!r}")

    known = {t["id"] for t in contract["thresholds"] if isinstance(t, dict) and "id" in t}
    for i, rung in enumerate(rungs):
        for clause in rung.get("when_any", []) + rung.get("when_all", []):
            tid = clause.get("threshold")
            if tid is not None and tid not in known:
                raise ContractInvalid(
                    f"{path}: resolve[{i}] references threshold {tid!r}, which is not declared. "
                    f"Declared: {sorted(known)}"
                )


def _finite(value: Any) -> Any:
    """Return ``value``, or ``None`` if it is a non-finite number.

    NaN and +/-inf are numbers, not measurements: NaN fails every comparison (so it escapes a
    demote-only floor) and inf satisfies every upper bound (so it would be scored as a
    catastrophic missingness fraction). Both become absence, which the ladder handles.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else None
    return value


def _normalise(signals: Mapping[str, Any]) -> tuple[dict, list[str]]:
    """Copy the signal mapping with non-finite numbers demoted to absence, recording each."""
    out, anomalies = {}, []
    for key, value in signals.items():
        clean = _finite(value)
        if clean is None and value is not None:
            anomalies.append(f"{key}={value!r} is non-finite; treated as absent, not as a measurement")
        out[key] = clean
    return out, anomalies


def _apply_op(op: str, actual: Any, expected: Any) -> bool:
    """Evaluate one comparison with the contract's absence semantics."""
    if op == "is_true":
        return actual is True
    if op == "is_false":
        return actual is False
    if op == "eq":
        return actual == expected
    if op == "in":
        if not isinstance(expected, (list, tuple, set)):
            raise ContractInvalid(f"op 'in' needs a list value, got {expected!r}")
        return actual in expected
    if op in _BOUND_OPS:
        # THE LOAD-BEARING LINE: an absent value never satisfies a bound, so silence can
        # neither demote a product nor promote it.
        if actual is None:
            return False
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        return actual <= expected
    raise ContractInvalid(f"unknown op {op!r}; this executor implements is_true/is_false/eq/in/gt/gte/lt/lte")


def _clause_holds(clause: Mapping[str, Any], contract: Mapping[str, Any], signals: Mapping[str, Any]) -> bool:
    """Evaluate a ``{signal, op, value}`` clause or a ``{threshold: id}`` indirection."""
    if "threshold" in clause:
        tid = clause["threshold"]
        spec = next((t for t in contract["thresholds"] if t.get("id") == tid), None)
        if spec is None:  # unreachable via load_contract, reachable via a hand-built contract
            raise ContractInvalid(f"threshold {tid!r} is not declared")
        return _apply_op(spec["op"], signals.get(spec["signal"]), spec.get("value"))
    if "signal" not in clause or "op" not in clause:
        raise ContractInvalid(f"clause {dict(clause)!r} is neither a threshold nor a signal comparison")
    return _apply_op(clause["op"], signals.get(clause["signal"]), clause.get("value"))


def resolve_fitness(signals: Mapping[str, Any], contract: Mapping[str, Any]) -> dict:
    """Apply the declared ladder to one product's signals.

    ``signals`` is a mapping of the contract's ``reads`` signal ids to measured values; a
    signal that was never measured should be absent or ``None`` rather than zero-filled --
    "unmeasured" and "measured as zero" are different facts and the ladder distinguishes them.

    Returns a dict with:

    ``dataset_fitness_class``  the emitted class
    ``reason_code``            the firing rung's reason code
    ``priority``               the firing rung's priority, or ``None`` for the default
    ``resolved_by``            ``"priority_<n>"`` or ``"default"`` -- rung attribution, so a
                               consumer can report WHICH rule decided rather than just the
                               verdict, and so an unexpectedly-firing default is visible
    ``reason_detail``          the value of the rung's ``reason_detail_from`` signal, if any
    ``matched``                the clause(s) that fired -- one for ``when_any``, all for
                               ``when_all``
    ``anomalies``              non-finite inputs demoted to absence; empty in the normal case
    """
    clean, anomalies = _normalise(signals)

    for rung in contract["resolve"]:
        if "when_any" in rung:
            matched = next((c for c in rung["when_any"] if _clause_holds(c, contract, clean)), None)
            hit = matched is not None
            matched_list = [dict(matched)] if hit else []
        else:
            clauses = rung["when_all"]
            hit = all(_clause_holds(c, contract, clean) for c in clauses)
            matched_list = [dict(c) for c in clauses] if hit else []
        if not hit:
            continue
        detail_signal = rung.get("reason_detail_from")
        return {
            "dataset_fitness_class": rung["class"],
            "reason_code": rung["reason_code"],
            "priority": rung["priority"],
            "resolved_by": f"priority_{rung['priority']}",
            "reason_detail": clean.get(detail_signal) if detail_signal else None,
            "matched": matched_list,
            "anomalies": anomalies,
        }

    default = contract["default"]
    return {
        "dataset_fitness_class": default["class"],
        "reason_code": default["reason_code"],
        "priority": None,
        "resolved_by": "default",
        "reason_detail": None,
        "matched": [],
        "anomalies": anomalies,
    }
