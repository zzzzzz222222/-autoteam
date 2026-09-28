"""Safe arithmetic evaluation (v0.5.0).

Parses and evaluates basic arithmetic via the ``ast`` module — ``eval`` is never
used. Allowed: numbers, ``+ - * / %``, unary ``-/+`` and parentheses. Anything
else (names, calls, attributes, …) is rejected.
"""

from __future__ import annotations

import ast
import operator

from pydantic import BaseModel

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}


class CalculatorResult(BaseModel):
    expression: str
    value: float | None = None
    error: str | None = None


def _eval_node(node: ast.expr) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


def safe_calculate(expression: str) -> CalculatorResult:
    expression = expression.strip()
    try:
        tree = ast.parse(expression, mode="eval")
        value = _eval_node(tree)
        rounded = round(value, 10)
        return CalculatorResult(expression=expression, value=rounded)
    except ZeroDivisionError:
        return CalculatorResult(expression=expression, error="division by zero")
    except Exception as exc:
        return CalculatorResult(expression=expression, error=f"invalid expression: {exc}")
