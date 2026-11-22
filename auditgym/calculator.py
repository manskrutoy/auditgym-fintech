"""Arithmetic-only calculator (no names, calls, attributes, code or files)."""

import ast
from decimal import ROUND_FLOOR, Decimal, DecimalException, DivisionByZero, InvalidOperation, localcontext

from .constants import MAX_CALC_LEN


class CalcError(ValueError):
    pass


_BIN = {ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow}
_UN = {ast.UAdd, ast.USub}


def evaluate(expr: str) -> str:
    if not isinstance(expr, str):
        raise CalcError("expression must be a string")
    if len(expr) > MAX_CALC_LEN:
        raise CalcError("expression too long")
    allowed = set("0123456789.+-*/%() eE\t")
    if any(ch not in allowed for ch in expr):
        raise CalcError("only digits, decimal point, + - * / // % ** and parentheses are allowed")
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise CalcError("syntax error")
    with localcontext() as ctx:
        ctx.prec = 50
        ctx.traps[DivisionByZero] = True
        ctx.traps[InvalidOperation] = True
        try:
            val = _eval(tree.body, expr)
        except (DivisionByZero, InvalidOperation, ZeroDivisionError):
            raise CalcError("invalid operation (e.g. division by zero)")
        except (OverflowError, DecimalException, ArithmeticError, ValueError, RecursionError):
            raise CalcError("result out of range")
        if not val.is_finite():
            raise CalcError("result not finite")
        if abs(val) > Decimal(10) ** 30:
            raise CalcError("result too large")
        out = format(val.normalize(), "f")
        return out


LIMIT = Decimal(10) ** 30


def _bounded(v):
    if not v.is_finite() or abs(v) > LIMIT:
        raise CalcError("numbers must stay within ±1e30")
    return v


def _eval(node, src):
    return _bounded(_eval_raw(node, src))


def _eval_raw(node, src):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        seg = ast.get_source_segment(src, node)
        return Decimal(seg)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        v = _eval(node.operand, src)
        return v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        a, b = _eval(node.left, src), _eval(node.right, src)
        op = type(node.op)
        if op is ast.Add:
            return a + b
        if op is ast.Sub:
            return a - b
        if op is ast.Mult:
            return a * b
        if op is ast.Div:
            return a / b
        if op is ast.FloorDiv:                 # Python semantics: floor, not truncation
            return (a / b).to_integral_value(rounding=ROUND_FLOOR)
        if op is ast.Mod:
            return a - b * (a / b).to_integral_value(rounding=ROUND_FLOOR)
        if op is ast.Pow:
            if b != b.to_integral_value() or abs(b) > 64:
                raise CalcError("exponent must be an integer with |exp| <= 64")
            return a ** int(b)
    raise CalcError("unsupported expression element")
