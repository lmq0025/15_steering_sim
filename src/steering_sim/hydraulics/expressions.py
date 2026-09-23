"""A deliberately small AST interpreter for the frozen AMESim expressions."""

from __future__ import annotations

import ast
import math
import operator
from dataclasses import dataclass, field
from typing import Callable, Mapping


class UnsafeExpressionError(ValueError):
    """Expression contains syntax outside the evidence-backed subset."""


_BINARY: Mapping[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_UNARY: Mapping[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_COMPARE: Mapping[type[ast.cmpop], Callable[[float, float], bool]] = {
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_FUNCTIONS: Mapping[str, Callable[[float], float]] = {"sqrt": math.sqrt, "fabs": math.fabs}


@dataclass(frozen=True, slots=True)
class SafeExpression:
    """Parsed scalar expression with no Python ``eval`` or builtins access."""

    raw: str
    variables: tuple[str, ...] = ("x", "area")
    _tree: ast.Expression = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        try:
            tree = ast.parse(self.raw.replace("^", "**"), mode="eval")
        except SyntaxError as exc:
            raise UnsafeExpressionError(f"Invalid expression: {self.raw!r}") from exc
        object.__setattr__(self, "_tree", tree)
        self._validate(tree)

    def evaluate(self, **values: float) -> float:
        unknown = set(values) - set(self.variables)
        if unknown:
            raise UnsafeExpressionError(f"Unknown variables: {sorted(unknown)}")
        result = float(self._evaluate_node(self._tree.body, values))
        if not math.isfinite(result):
            raise ValueError(f"Expression produced a non-finite result: {self.raw!r}")
        return result

    def _validate(self, node: ast.AST) -> None:
        allowed = (
            ast.Expression,
            ast.Constant,
            ast.Name,
            ast.BinOp,
            ast.UnaryOp,
            ast.Compare,
            ast.Call,
            *tuple(_BINARY),
            *tuple(_UNARY),
            *tuple(_COMPARE),
            ast.Load,
        )
        if not isinstance(node, allowed):
            raise UnsafeExpressionError(f"Forbidden syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in {*self.variables, "pi", *_FUNCTIONS}:
            raise UnsafeExpressionError(f"Forbidden name: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise UnsafeExpressionError("Only sqrt() and fabs() are permitted")
            if len(node.args) != 1 or node.keywords:
                raise UnsafeExpressionError("Permitted functions take one positional argument")
        if isinstance(node, ast.Compare) and (len(node.ops) != 1 or len(node.comparators) != 1):
            raise UnsafeExpressionError("Chained comparisons are not supported")
        for child in ast.iter_child_nodes(node):
            self._validate(child)

    def _evaluate_node(self, node: ast.AST, values: Mapping[str, float]) -> float | bool:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise UnsafeExpressionError("Only numeric constants are permitted")
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id == "pi":
                return math.pi
            if node.id in values:
                return float(values[node.id])
            raise UnsafeExpressionError(f"No value supplied for {node.id!r}")
        if isinstance(node, ast.BinOp):
            function = _BINARY.get(type(node.op))
            if function is None:
                raise UnsafeExpressionError(f"Forbidden operator: {type(node.op).__name__}")
            return function(float(self._evaluate_node(node.left, values)), float(self._evaluate_node(node.right, values)))
        if isinstance(node, ast.UnaryOp):
            function = _UNARY.get(type(node.op))
            if function is None:
                raise UnsafeExpressionError(f"Forbidden unary operator: {type(node.op).__name__}")
            return function(float(self._evaluate_node(node.operand, values)))
        if isinstance(node, ast.Compare):
            function = _COMPARE.get(type(node.ops[0]))
            if function is None:
                raise UnsafeExpressionError("Forbidden comparison")
            return function(float(self._evaluate_node(node.left, values)), float(self._evaluate_node(node.comparators[0], values)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            return _FUNCTIONS[node.func.id](float(self._evaluate_node(node.args[0], values)))
        raise UnsafeExpressionError(f"Forbidden syntax: {type(node).__name__}")

