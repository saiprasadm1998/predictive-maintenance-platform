"""Operating-mode filter expressions (FR-MOD-03): parsing, evaluation and safety."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from pmp.modelling import ExpressionError, parse_expression
from pmp.modelling.expressions import MAX_DEPTH, MAX_LENGTH

CURRENT = "K101.II1001.PV"


def test_the_spec_example_parses_and_evaluates() -> None:
    expression = parse_expression(f"{CURRENT} > 120")
    assert expression.names == {CURRENT}
    assert expression.evaluate({CURRENT: 121.0})
    assert not expression.evaluate({CURRENT: 120.0})
    assert str(expression) == f"{CURRENT} > 120"


@pytest.mark.parametrize(
    ("text", "values", "expected"),
    [
        ("a > 1 or b > 1 and c > 1", {"a": 2, "b": 0, "c": 0}, True),  # and binds tighter
        ("(a > 1 or b > 1) and c > 1", {"a": 2, "b": 0, "c": 0}, False),
        ("120 < a", {"a": 130}, True),  # number on the left is flipped
        ("NOT a <= 5 AND b != 3", {"a": 6, "b": 4}, True),  # keywords in any case
        ("a == 0.5e1", {"a": 5}, True),
        ("a >= -2.5", {"a": -2.5}, True),
        ("TI-1012 < 80", {"TI-1012": 79}, True),  # hyphens inside names
        ("not (a > 1 and b > 1)", {"a": 2, "b": 0}, True),
    ],
)
def test_evaluation(text: str, values: dict[str, float], expected: bool) -> None:
    assert parse_expression(text).evaluate(values) is expected


def test_a_missing_value_makes_the_expression_false_even_under_not() -> None:
    expression = parse_expression("not a > 1")
    assert expression.evaluate({"a": 0.0})
    assert not expression.evaluate({"a": None})
    assert not expression.evaluate({"a": float("nan")})
    assert not expression.evaluate({})


def test_frames_evaluate_row_by_row_with_the_same_rules() -> None:
    expression = parse_expression("a > 1 and not b > 5")
    frame = pd.DataFrame({"a": [2.0, 2.0, 0.0, np.nan], "b": [1.0, 9.0, 1.0, 1.0]})
    assert expression.evaluate_frame(frame).tolist() == [True, False, False, False]
    assert expression.evaluate_frame(frame[["a"]]).tolist() == [False] * 4  # b missing


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("__import__('os')", "Unexpected character"),
        ('os.system("rm")', "Unexpected character"),
        ("a > 1; b > 2", "Unexpected character ';'"),
        ("a + 1 > 2", "Unexpected character '\\+'"),
        ("a > b", "expected number"),
        ("1 > 2", "expected name"),
        ("a >", "ends early"),
        ("a > 1 b > 2", "Unexpected 'b'"),
        ("(a > 1", "Missing '\\)'"),
        ("a > 1)", "Unexpected '\\)'"),
        ("a > inf", "expected number"),
        ("a > 1e999", "finite"),
        ("a and b", "expected op"),
    ],
)
def test_bad_and_unsafe_input_is_refused(text: str, message: str) -> None:
    with pytest.raises(ExpressionError, match=message):
        parse_expression(text)


def test_size_limits() -> None:
    with pytest.raises(ExpressionError, match="longer than"):
        parse_expression("a > 1 or " * (MAX_LENGTH // 9 + 1) + "a > 1")
    with pytest.raises(ExpressionError, match="nested"):
        parse_expression("(" * (MAX_DEPTH + 1) + "a > 1" + ")" * (MAX_DEPTH + 1))
    with pytest.raises(ExpressionError, match="nested"):
        parse_expression("not " * (MAX_DEPTH + 1) + "a > 1")


names = st.sampled_from(["a", "K101.II1001.PV", "TI-1012", "x_1"])
ops = st.sampled_from(["<", "<=", ">", ">=", "==", "!="])
numbers = st.integers(min_value=-1000, max_value=1000)
comparisons = st.builds(lambda n, o, v: f"{n} {o} {v}", names, ops, numbers)
expressions = st.recursive(
    comparisons,
    lambda inner: st.one_of(
        st.builds(lambda e: f"not ({e})", inner),
        st.builds(lambda a, b: f"({a}) and ({b})", inner, inner),
        st.builds(lambda a, b: f"({a}) or ({b})", inner, inner),
    ),
    max_leaves=8,
)


TAG_NAMES = ["a", "K101.II1001.PV", "TI-1012", "x_1"]


@given(text=expressions, values=st.fixed_dictionaries(dict.fromkeys(TAG_NAMES, numbers)))
def test_printing_keeps_the_meaning(text: str, values: dict[str, int]) -> None:
    """The canonical text re-parses to an expression with the same meaning and text."""
    parsed = parse_expression(text)
    again = parse_expression(str(parsed))
    assert str(again) == str(parsed)
    floats = {k: float(v) for k, v in values.items()}
    assert again.evaluate(floats) == parsed.evaluate(floats)
    frame = pd.DataFrame({k: [v] for k, v in floats.items()})
    assert bool(parsed.evaluate_frame(frame)[0]) == parsed.evaluate(floats)
