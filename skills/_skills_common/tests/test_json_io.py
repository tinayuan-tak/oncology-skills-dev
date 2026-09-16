"""json_io.dump_json — the non-finite-fatal emission boundary (Track C Stage 2 helper)."""

from __future__ import annotations

import json

import pytest
from _skills_common.json_io import NonFiniteEmissionError, dump_json


def test_clean_object_round_trips():
    obj = {"target": "KRAS", "n": 1538, "median_chronos": -1.18, "flags": [True, None, "x"]}
    assert json.loads(dump_json(obj)) == obj


def test_nan_raises_located_named_error():
    with pytest.raises(NonFiniteEmissionError) as e:
        dump_json({"summary": {"q_value": float("nan")}})
    assert e.value.path == "summary.q_value"
    assert e.value.value != e.value.value  # NaN


def test_infinity_in_a_list_reports_the_index_path():
    with pytest.raises(NonFiniteEmissionError) as e:
        dump_json({"cards": [{"summary": {"x": 1.0}}, {"summary": {"x": float("inf")}}]})
    assert e.value.path == "cards[1].summary.x"


def test_error_is_a_valueerror_subclass():
    # an existing `except ValueError` around a write still catches the located error
    with pytest.raises(ValueError):
        dump_json({"x": float("-inf")})


def test_allow_nan_cannot_be_overridden():
    with pytest.raises(NonFiniteEmissionError):
        dump_json({"x": float("nan")}, allow_nan=True)  # ignored — the guard holds


def test_kwargs_pass_through():
    assert dump_json({"b": 1, "a": 2}, sort_keys=True) == '{"a": 2, "b": 1}'
