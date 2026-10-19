"""Operating-mode filter expressions (FR-MOD-03, UC-05 step 4), e.g. `K101.II1001.PV > 120`.

A small hand-written parser: nothing is ever passed to Python's eval, so an expression can
only compare tag values with numbers. Grammar (keywords are case-insensitive):

    expression := term ("or" term)*
    term       := factor ("and" factor)*
    factor     := "not" factor | "(" expression ")" | comparison
    comparison := NAME OP NUMBER | NUMBER OP NAME        OP: < <= > >= == !=

NAME is a tag's source name (letters, digits, '.', '_', '-'; implementation plan, decision
for 3.1). If any tag the expression names has no usable value, the expression is false,
so the cycle counts as "Not in operating mode" rather than being guessed.
"""

from __future__ import annotations

import math
import operator
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

MAX_LENGTH = 500
MAX_DEPTH = 20

_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<number>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?(?![A-Za-z0-9_.\-]))"
    r"|(?P<op><=|>=|==|!=|<|>)"
    r"|(?P<paren>[()])"
    r"|(?P<name>[A-Za-z0-9_][A-Za-z0-9_.\-]*)"
    r")"
)
_KEYWORDS = {"and", "or", "not"}
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<=", "==": "==", "!=": "!="}
_COMPARE: Mapping[str, Callable[[Any, Any], Any]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


class ExpressionError(ValueError):
    """An expression that cannot be parsed, with the position of the problem."""


# ------------------------------------------------------------------ syntax tree


@dataclass(frozen=True)
class Compare:
    name: str
    op: str
    value: float

    def __str__(self) -> str:
        return f"{self.name} {self.op} {self.value:g}"


@dataclass(frozen=True)
class Not:
    operand: Node

    def __str__(self) -> str:
        return f"not {_wrap(self.operand)}"


@dataclass(frozen=True)
class And:
    operands: tuple[Node, ...]

    def __str__(self) -> str:
        return " and ".join(_wrap(o, Or) for o in self.operands)


@dataclass(frozen=True)
class Or:
    operands: tuple[Node, ...]

    def __str__(self) -> str:
        return " or ".join(str(o) for o in self.operands)


Node = Compare | Not | And | Or


def _wrap(node: Node, *types: type) -> str:
    needs = isinstance(node, types or (And, Or))
    return f"({node})" if needs else str(node)


# ------------------------------------------------------------------ parser


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    pos: int


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(text):
        if text[pos:].strip() == "":
            break
        match = _TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            start = len(text) - len(text[pos:].lstrip())
            raise ExpressionError(f"Unexpected character {text[start]!r} at position {start + 1}")
        kind = match.lastgroup or ""
        value = match.group(kind)
        start = match.start(kind)
        if kind == "name" and value.lower() in _KEYWORDS:
            kind = value.lower()
        tokens.append(_Token(kind, value, start))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.tokens = _tokenize(text)
        self.i = 0
        self.depth = 0

    def _peek(self) -> _Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _take(self, *kinds: str) -> _Token:
        token = self._peek()
        if token is None:
            raise ExpressionError(f"Expression ends early; expected {' or '.join(kinds)}")
        if token.kind not in kinds:
            raise ExpressionError(
                f"Unexpected {token.text!r} at position {token.pos + 1}; "
                f"expected {' or '.join(kinds)}"
            )
        self.i += 1
        return token

    def parse(self) -> Node:
        if not self.tokens:
            raise ExpressionError("Expression is empty")
        node = self._expression()
        extra = self._peek()
        if extra is not None:
            raise ExpressionError(f"Unexpected {extra.text!r} at position {extra.pos + 1}")
        return node

    def _expression(self) -> Node:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExpressionError(f"Expression is nested more than {MAX_DEPTH} levels deep")
        operands = [self._term()]
        while (token := self._peek()) is not None and token.kind == "or":
            self.i += 1
            operands.append(self._term())
        self.depth -= 1
        return operands[0] if len(operands) == 1 else Or(tuple(operands))

    def _term(self) -> Node:
        operands = [self._factor()]
        while (token := self._peek()) is not None and token.kind == "and":
            self.i += 1
            operands.append(self._factor())
        return operands[0] if len(operands) == 1 else And(tuple(operands))

    def _factor(self) -> Node:
        token = self._peek()
        if token is not None and token.kind == "not":
            self.i += 1
            self.depth += 1
            if self.depth > MAX_DEPTH:
                raise ExpressionError(f"Expression is nested more than {MAX_DEPTH} levels deep")
            negated = Not(self._factor())
            self.depth -= 1
            return negated
        if token is not None and token.text == "(":
            self.i += 1
            inner = self._expression()
            closing = self._peek()
            if closing is None or closing.text != ")":
                where = f"at position {closing.pos + 1}" if closing else "at the end"
                raise ExpressionError(f"Missing ')' {where}")
            self.i += 1
            return inner
        return self._comparison()

    def _comparison(self) -> Node:
        left = self._take("name", "number")
        op = self._take("op").text
        right = self._take("number" if left.kind == "name" else "name")
        if left.kind == "name":
            name, number = left.text, right.text
        else:
            name, number, op = right.text, left.text, _FLIP[op]
        value = float(number)
        if not math.isfinite(value):
            raise ExpressionError(f"{number} is not a finite number")
        return Compare(name, op, value)


# ------------------------------------------------------------------ public interface


@dataclass(frozen=True)
class Expression:
    """A parsed filter expression: a condition on tag values."""

    text: str
    root: Node

    def __str__(self) -> str:
        return str(self.root)

    @property
    def names(self) -> frozenset[str]:
        return frozenset(_names(self.root))

    def evaluate(self, values: Mapping[str, float | None]) -> bool:
        """One cycle: tag source name to its usable value (None or NaN: not usable)."""
        for name in self.names:
            value = values.get(name)
            if value is None or not math.isfinite(value):
                return False
        return bool(_evaluate(self.root, {n: values[n] for n in self.names}))

    def evaluate_frame(self, frame: pd.DataFrame) -> npt.NDArray[np.bool_]:
        """Many cycles at once: one column per tag (source name), NaN where not usable."""
        missing = [n for n in self.names if n not in frame.columns]
        if missing:
            return np.zeros(len(frame), dtype=bool)
        columns = {n: frame[n].to_numpy(dtype=np.float64) for n in self.names}
        complete = np.logical_and.reduce([np.isfinite(c) for c in columns.values()])
        result = np.asarray(_evaluate(self.root, columns), dtype=bool)
        return np.asarray(result & complete, dtype=bool)


def parse_expression(text: str) -> Expression:
    if len(text) > MAX_LENGTH:
        raise ExpressionError(f"Expression is longer than {MAX_LENGTH} characters")
    return Expression(text.strip(), _Parser(text).parse())


def _names(node: Node) -> set[str]:
    if isinstance(node, Compare):
        return {node.name}
    if isinstance(node, Not):
        return _names(node.operand)
    return set().union(*(_names(o) for o in node.operands))


def _evaluate(node: Node, values: Mapping[str, Any]) -> Any:
    if isinstance(node, Compare):
        return _COMPARE[node.op](values[node.name], node.value)
    if isinstance(node, Not):
        return np.logical_not(_evaluate(node.operand, values))
    combine = np.logical_and if isinstance(node, And) else np.logical_or
    result: Any = _evaluate(node.operands[0], values)
    for operand in node.operands[1:]:
        result = combine(result, _evaluate(operand, values))
    return result
