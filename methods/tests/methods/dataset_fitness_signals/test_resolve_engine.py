"""Engine semantics for the dataset-fitness ladder executor.

Every test here builds its OWN contract on tmp_path and goes through the real
``load_contract`` seam, so the loader, the structural validator and the evaluator are all
exercised without needing the sibling target-contracts checkout. That matters for two reasons,
neither of them CI: CI *does* check the sibling out (see test_contract_conformance.py), but a
developer clone with no sibling beside it would otherwise have zero coverage of the grammar,
and -- the sharper reason -- a guard pinned to the frozen 36-product roster becomes hostage to
a corpus refresh. These tests assert what the LADDER means, so they must not move when the
corpus does.

Contract FIDELITY -- does the engine reproduce the 36-product roster the contract froze -- is a
separate file, and that one is legitimately sibling-gated.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from onc_methods.dataset_fitness_signals import (
    ContractInvalid,
    ContractUnavailable,
    contract_path,
    load_contract,
    resolve_fitness,
)

MINIMAL_DEFAULT = {"class": "not_measured", "reason_code": "shape_undecidable"}


def _write(tmp_path: Path, **overrides) -> Path:
    """Write a contract to tmp_path and return the ROOT to pass as target_contracts_root."""
    doc = {
        "resolution_id": "test_resolution",
        "emits": "dataset_fitness_class",
        "keyed_by": "product_id",
        "evaluation": "first_match_wins",
        "never_gates": True,
        "reads": [],
        "thresholds": [],
        "resolve": [
            {
                "class": "fit",
                "priority": 10,
                "reason_code": "ok",
                "when_all": [{"signal": "flag", "op": "is_true"}],
            }
        ],
        "default": dict(MINIMAL_DEFAULT),
    }
    doc.update(overrides)
    path = tmp_path / "vocabularies" / "dataset_fitness_resolution.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    return tmp_path


# ---------------------------------------------------------------- absence semantics


def test_an_absent_value_never_satisfies_a_bound_in_either_direction(tmp_path):
    """The load-bearing rule: silence can neither demote nor promote.

    Both rungs read the same signal -- one as a demoting floor, one as a promoting ceiling.
    With the signal absent, NEITHER may fire, so the product lands on the abstention. An
    executor that let ``None`` pass a comparison would produce `unfit`-by-silence or
    `fit`-by-silence depending only on which bound it evaluated first.
    """
    root = _write(
        tmp_path,
        thresholds=[{"id": "floor", "signal": "missingness", "op": "gt", "value": 0.9, "basis": "absolute"}],
        resolve=[
            {"class": "unfit", "priority": 10, "reason_code": "floor", "when_any": [{"threshold": "floor"}]},
            {
                "class": "fit",
                "priority": 20,
                "reason_code": "ok",
                "when_all": [{"signal": "missingness", "op": "lte", "value": 0.25}],
            },
        ],
    )
    contract = load_contract(root)

    absent = resolve_fitness({"missingness": None}, contract)
    assert absent["dataset_fitness_class"] == "not_measured", absent
    assert absent["resolved_by"] == "default"

    # ...and the same contract DOES decide when the value is present, so the test is not
    # vacuously passing on a ladder that can never fire.
    assert resolve_fitness({"missingness": 0.95}, contract)["dataset_fitness_class"] == "unfit"
    assert resolve_fitness({"missingness": 0.10}, contract)["dataset_fitness_class"] == "fit"


def test_a_signal_missing_from_the_mapping_behaves_as_absent(tmp_path):
    """Not the same code path as an explicit None: this exercises ``signals.get`` returning
    nothing at all, which is how a consumer that never collected a field will call us."""
    root = _write(
        tmp_path,
        resolve=[
            {
                "class": "fit",
                "priority": 10,
                "reason_code": "ok",
                "when_all": [{"signal": "missingness", "op": "lte", "value": 0.25}],
            }
        ],
    )
    out = resolve_fitness({}, load_contract(root))
    assert out["resolved_by"] == "default"


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_values_are_treated_as_absent_and_reported(tmp_path, bad):
    """+/-inf and NaN are numbers, and that is the trap.

    ``inf > 0.9`` is True, so an inf missingness fraction would be scored as a catastrophic
    measurement; ``nan > 0.9`` is False, so a NaN would escape the same floor. Both are corrupt
    values rather than measurements, so both become absence -- and the anomaly is REPORTED, so
    the consumer sees an abstention with a reason rather than a silent verdict.
    """
    root = _write(
        tmp_path,
        thresholds=[{"id": "floor", "signal": "missingness", "op": "gt", "value": 0.9, "basis": "absolute"}],
        resolve=[
            {"class": "unfit", "priority": 10, "reason_code": "floor", "when_any": [{"threshold": "floor"}]},
            {
                "class": "fit",
                "priority": 20,
                "reason_code": "ok",
                "when_all": [{"signal": "missingness", "op": "lte", "value": 0.25}],
            },
        ],
    )
    out = resolve_fitness({"missingness": bad}, load_contract(root))
    assert out["dataset_fitness_class"] == "not_measured", out
    assert out["resolved_by"] == "default"
    assert out["anomalies"] and "non-finite" in out["anomalies"][0], out["anomalies"]
    assert "missingness" in out["anomalies"][0]


def test_finite_values_produce_no_anomalies(tmp_path):
    """Control for the test above -- the anomaly channel must be quiet in the normal case,
    or 'no anomalies' on the real roster would prove nothing."""
    root = _write(tmp_path)
    out = resolve_fitness({"flag": True}, load_contract(root))
    assert out["anomalies"] == []
    assert out["dataset_fitness_class"] == "fit"


def test_is_true_is_identity_not_truthiness(tmp_path):
    """``1 == True`` in Python, so a producer emitting 1 instead of true must not satisfy
    ``is_true``. It falls through to the abstention, which is the conservative direction."""
    root = _write(tmp_path)
    contract = load_contract(root)
    assert resolve_fitness({"flag": True}, contract)["dataset_fitness_class"] == "fit"
    assert resolve_fitness({"flag": 1}, contract)["resolved_by"] == "default"
    assert resolve_fitness({"flag": "true"}, contract)["resolved_by"] == "default"


# ---------------------------------------------------------------- ordering


def test_first_match_wins_uses_document_order(tmp_path):
    """Two rungs that BOTH match: the earlier one decides."""
    root = _write(
        tmp_path,
        resolve=[
            {
                "class": "partially_fit",
                "priority": 10,
                "reason_code": "first",
                "when_any": [{"signal": "flag", "op": "is_true"}],
            },
            {
                "class": "fit",
                "priority": 20,
                "reason_code": "second",
                "when_any": [{"signal": "flag", "op": "is_true"}],
            },
        ],
    )
    out = resolve_fitness({"flag": True}, load_contract(root))
    assert (out["dataset_fitness_class"], out["reason_code"], out["resolved_by"]) == (
        "partially_fit",
        "first",
        "priority_10",
    )


def test_non_monotonic_priorities_are_rejected(tmp_path):
    """The ladder's conditioning guarantees are carried by ORDER, so document order and the
    priority numbers disagreeing is a defect, not a preference."""
    root = _write(
        tmp_path,
        resolve=[
            {
                "class": "fit_with_caveats",
                "priority": 40,
                "reason_code": "a",
                "when_any": [{"signal": "flag", "op": "is_true"}],
            },
            {
                "class": "partially_fit",
                "priority": 30,
                "reason_code": "b",
                "when_any": [{"signal": "flag", "op": "is_false"}],
            },
        ],
    )
    with pytest.raises(ContractInvalid, match="not ascending in document order"):
        load_contract(root)


def test_duplicate_priorities_are_rejected(tmp_path):
    root = _write(
        tmp_path,
        resolve=[
            {"class": "fit", "priority": 10, "reason_code": "a", "when_any": [{"signal": "flag", "op": "is_true"}]},
            {"class": "unfit", "priority": 10, "reason_code": "b", "when_any": [{"signal": "flag", "op": "is_false"}]},
        ],
    )
    with pytest.raises(ContractInvalid, match="duplicate priorities"):
        load_contract(root)


# ---------------------------------------------------------------- clause structure


def test_an_empty_when_all_would_fire_unconditionally_and_is_rejected(tmp_path):
    """``all([])`` is True, so an empty ``when_all`` is a rung that matches EVERY product --
    and because it is first-match-wins, it would swallow the entire ladder below it. The
    mirror case (``any([])`` is False) is a rung that can never fire, i.e. a silently dead
    rule. Both are rejected at load."""
    for clause_key in ("when_all", "when_any"):
        root = _write(
            tmp_path / clause_key,
            resolve=[{"class": "fit", "priority": 10, "reason_code": "a", clause_key: []}],
        )
        with pytest.raises(ContractInvalid, match="empty clause list"):
            load_contract(root)


def test_a_rung_must_carry_exactly_one_clause_list(tmp_path):
    both = _write(
        tmp_path / "both",
        resolve=[
            {
                "class": "fit",
                "priority": 10,
                "reason_code": "a",
                "when_any": [{"signal": "flag", "op": "is_true"}],
                "when_all": [{"signal": "flag", "op": "is_true"}],
            }
        ],
    )
    with pytest.raises(ContractInvalid, match="exactly one"):
        load_contract(both)

    neither = _write(tmp_path / "neither", resolve=[{"class": "fit", "priority": 10, "reason_code": "a"}])
    with pytest.raises(ContractInvalid, match="exactly one"):
        load_contract(neither)


def test_when_all_requires_every_clause(tmp_path):
    root = _write(
        tmp_path,
        resolve=[
            {
                "class": "fit",
                "priority": 10,
                "reason_code": "ok",
                "when_all": [
                    {"signal": "a", "op": "is_true"},
                    {"signal": "b", "op": "eq", "value": "full"},
                ],
            }
        ],
    )
    contract = load_contract(root)
    assert resolve_fitness({"a": True, "b": "full"}, contract)["dataset_fitness_class"] == "fit"
    assert resolve_fitness({"a": True, "b": "bounded"}, contract)["resolved_by"] == "default"
    assert resolve_fitness({"a": False, "b": "full"}, contract)["resolved_by"] == "default"


def test_a_reference_to_an_undeclared_threshold_is_rejected(tmp_path):
    root = _write(
        tmp_path,
        thresholds=[{"id": "declared", "signal": "x", "op": "gt", "value": 1, "basis": "absolute"}],
        resolve=[{"class": "unfit", "priority": 10, "reason_code": "a", "when_any": [{"threshold": "typo"}]}],
    )
    with pytest.raises(ContractInvalid, match="threshold 'typo'"):
        load_contract(root)


def test_an_unknown_op_is_rejected_at_evaluation(tmp_path):
    root = _write(
        tmp_path,
        resolve=[
            {
                "class": "fit",
                "priority": 10,
                "reason_code": "a",
                "when_any": [{"signal": "flag", "op": "approximately"}],
            }
        ],
    )
    with pytest.raises(ContractInvalid, match="unknown op"):
        resolve_fitness({"flag": True}, load_contract(root))


# ---------------------------------------------------------------- outputs


def test_the_default_is_attributed_as_the_default(tmp_path):
    """A default that quietly does real work is a rung nobody reviewed, so the output names
    it -- ``priority`` is None and ``resolved_by`` is the literal 'default'."""
    root = _write(tmp_path)
    out = resolve_fitness({"flag": False}, load_contract(root))
    assert out["resolved_by"] == "default"
    assert out["priority"] is None
    assert out["dataset_fitness_class"] == MINIMAL_DEFAULT["class"]
    assert out["reason_code"] == MINIMAL_DEFAULT["reason_code"]
    assert out["matched"] == []


def test_reason_detail_from_carries_the_named_signal(tmp_path):
    root = _write(
        tmp_path,
        resolve=[
            {
                "class": "partially_fit",
                "priority": 10,
                "reason_code": "collapsed",
                "reason_detail_from": "arm_below_floor",
                "when_any": [{"signal": "status", "op": "eq", "value": "degraded"}],
            }
        ],
    )
    out = resolve_fitness({"status": "degraded", "arm_below_floor": ["adjacent"]}, load_contract(root))
    assert out["reason_detail"] == ["adjacent"]
    assert out["matched"] == [{"signal": "status", "op": "eq", "value": "degraded"}]


def test_rung_attribution_names_the_firing_priority(tmp_path):
    root = _write(
        tmp_path,
        resolve=[
            {"class": "unfit", "priority": 20, "reason_code": "a", "when_any": [{"signal": "flag", "op": "is_false"}]},
            {"class": "fit", "priority": 50, "reason_code": "b", "when_any": [{"signal": "flag", "op": "is_true"}]},
        ],
    )
    contract = load_contract(root)
    assert resolve_fitness({"flag": False}, contract)["resolved_by"] == "priority_20"
    assert resolve_fitness({"flag": True}, contract)["resolved_by"] == "priority_50"


# ---------------------------------------------------------------- contract read discipline


def test_an_absent_contract_raises_unavailable_rather_than_returning_a_class(tmp_path):
    """ "We could not read the rules" and "the rules say not_measured" are different facts, and
    only one of them is about the data. A loader that degraded to the default class would make
    a missing sibling repo indistinguishable from a genuinely unprofiled product."""
    with pytest.raises(ContractUnavailable, match="not found"):
        load_contract(tmp_path / "nonexistent")


def test_the_env_override_is_honored_and_its_absence_also_raises(tmp_path, monkeypatch):
    """Defeat every supply mechanism, not just the argument: with no explicit root, the module
    resolves TARGET_CONTRACTS_ROOT and then the sibling checkout. Pointing the env var at a
    nonexistent tree must raise rather than silently falling through to a real sibling.

    Deliberately NOT via ``importlib.reload``: reloading the module rebinds ContractInvalid /
    ContractUnavailable to fresh class objects, so every later ``pytest.raises`` in this file
    would be catching a stale class and would fail while the code was correct. The module reads
    the env at call time precisely so this can be a plain monkeypatch.
    """
    monkeypatch.setenv("TARGET_CONTRACTS_ROOT", str(tmp_path / "nowhere"))
    assert str(tmp_path / "nowhere") in str(contract_path())
    with pytest.raises(ContractUnavailable):
        load_contract()


def test_the_env_override_loses_to_an_explicit_root(tmp_path, monkeypatch):
    """Precedence, pinned: an explicit argument outranks the env var. Otherwise a caller that
    passed a root would silently read whichever checkout the ambient environment named."""
    monkeypatch.setenv("TARGET_CONTRACTS_ROOT", str(tmp_path / "nowhere"))
    root = _write(tmp_path / "explicit")
    assert load_contract(root)["resolution_id"] == "test_resolution"


def test_contract_path_reports_where_it_looked(tmp_path):
    p = contract_path(tmp_path)
    assert p == tmp_path / "vocabularies" / "dataset_fitness_resolution.yaml"


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"evaluation": "last_match_wins"}, "first_match_wins only"),
        ({"never_gates": False}, "never_gates is False"),
        ({"never_gates": None}, "never_gates is None"),
        ({"resolve": []}, "non-empty list"),
    ],
)
def test_a_malformed_contract_raises_invalid_not_a_default_class(tmp_path, overrides, match):
    root = _write(tmp_path, **overrides)
    with pytest.raises(ContractInvalid, match=match):
        load_contract(root)


def test_a_missing_required_key_is_rejected(tmp_path):
    root = _write(tmp_path)
    path = root / "vocabularies" / "dataset_fitness_resolution.yaml"
    doc = yaml.safe_load(path.read_text())
    del doc["default"]
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    with pytest.raises(ContractInvalid, match="missing required keys"):
        load_contract(root)


def test_never_gates_is_enforced_because_this_executor_is_dimension_only(tmp_path):
    """Not a style check. The axis's report-only property is a REACHABILITY guarantee -- the
    contract is kept out of resolvers/ so no gate can consume it. If a future edit flipped the
    contract to gating, it must not silently acquire an execution path from here."""
    root = _write(tmp_path, never_gates=True)
    assert load_contract(root)["never_gates"] is True
    gating = _write(tmp_path / "gating", never_gates=False)
    with pytest.raises(ContractInvalid, match="reviewed gate path"):
        load_contract(gating)
