"""The abstract syntax tree (AST): the program as a tree of Python objects.

The parser builds it; the checker walks it, adds a `ty` (type = kind + unit)
to every expression and inserts Convert / Cast nodes where a conversion is
needed; the IR generator walks it again to produce three-address code.

A parse tree would keep every token (parentheses, semicolons). The AST keeps
only the meaning: `(2 + 3) * 4` becomes Binary('*', Binary('+', 2, 3), 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from fractions import Fraction
from typing import Any


@dataclass(kw_only=True)
class Node:
    line: int = 0
    col: int = 0
    end_line: int = 0           # where the node ends (set by the parser, used for ~~~ underlines)
    end_col: int = 0


# ---------------------------------------------------------------- units and types
@dataclass
class UnitFactor(Node):
    """One factor of a unit expression: `s^-2` is UnitFactor('s', -2)."""
    name: str
    exp: int = 1


@dataclass
class TypeRef(Node):
    """A type written in the source: int, float, bool, string, or a unit like m/s."""
    kind: str                                   # int float bool string unit
    units: list[UnitFactor] = field(default_factory=list)


# ---------------------------------------------------------------- expressions
@dataclass
class Expr(Node):
    ty: Any = field(default=None, kw_only=True, repr=False, compare=False)


@dataclass
class Num(Expr):
    value: Fraction
    is_float: bool
    units: list[UnitFactor] | None = None       # `42.195 km` carries a unit


@dataclass
class BoolLit(Expr):
    value: bool


@dataclass
class StrLit(Expr):
    value: str


@dataclass
class Var(Expr):
    name: str
    uid: str = ""                               # unique id (set by the checker; handles shadowing)


@dataclass
class Unary(Expr):
    op: str                                     # '-' or '!'
    operand: Expr


@dataclass
class Binary(Expr):                             # line/col = the operator's position
    op: str
    left: Expr
    right: Expr


@dataclass
class Call(Expr):
    name: str
    args: list[Expr]


@dataclass
class InConv(Expr):
    """`expr in km`: explicit conversion to another unit of the same dimension."""
    expr: Expr
    units: list[UnitFactor]


@dataclass
class Convert(Expr):
    """Inserted by the checker: multiply by (from_scale / to_scale)."""
    expr: Expr
    from_scale: Fraction
    to_scale: Fraction


@dataclass
class Cast(Expr):
    """Inserted by the checker: widen an int to a float."""
    expr: Expr
    to: str = "float"


# ---------------------------------------------------------------- statements
@dataclass
class Stmt(Node):
    pass


@dataclass
class Block(Stmt):
    stmts: list[Stmt]


@dataclass
class Let(Stmt):
    name: str
    tyref: TypeRef | None
    init: Expr | None
    uid: str = ""


@dataclass
class Assign(Stmt):
    name: str
    value: Expr
    uid: str = ""


@dataclass
class If(Stmt):
    cond: Expr
    then: Block
    other: Stmt | None                          # Block, If (else if) or None


@dataclass
class While(Stmt):
    cond: Expr
    body: Block


@dataclass
class Return(Stmt):
    value: Expr | None


@dataclass
class Print(Stmt):
    value: Expr
    label: str = ""                             # unit text printed after the value (compile-time)


@dataclass
class ExprStmt(Stmt):
    expr: Expr


# ---------------------------------------------------------------- declarations
@dataclass
class UnitDecl(Node):
    name: str
    value: Fraction | None                      # None for `unit INR;` (new base unit)
    units: list[UnitFactor]


@dataclass
class Param(Node):
    name: str
    tyref: TypeRef
    ty: Any = None
    uid: str = ""


@dataclass
class FuncDecl(Node):
    name: str
    params: list[Param]
    ret: TypeRef | None
    body: Block
    ret_ty: Any = None


@dataclass
class Program(Node):
    items: list[Node]                           # UnitDecl and FuncDecl in source order


# ---------------------------------------------------------------- pretty printer
def unit_text(factors: list[UnitFactor] | None) -> str:
    if not factors:
        return ""
    return "*".join(f.name if f.exp == 1 else f"{f.name}^{f.exp}" for f in factors)


def _short(v: Any) -> str:
    if isinstance(v, Fraction):
        return str(float(v)) if v.denominator != 1 else str(v.numerator)
    if isinstance(v, list) and v and isinstance(v[0], UnitFactor):
        return unit_text(v)
    return repr(v)


def dump_ast(node: Any, show_types: bool = False, indent: int = 0) -> str:
    """Indented text rendering of the tree (used by `--ast`)."""
    pad = "  " * indent
    if isinstance(node, list):
        return "\n".join(dump_ast(n, show_types, indent) for n in node)
    if not isinstance(node, Node):
        return pad + repr(node)
    simple, children = [], []
    for f in fields(node):
        if f.name in ("line", "col", "ty", "end_line", "end_col", "uid", "ret_ty"):
            continue
        v = getattr(node, f.name)
        if isinstance(v, Node) or (isinstance(v, list) and v and isinstance(v[0], Node)
                                   and not isinstance(v[0], UnitFactor)):
            children.append((f.name, v))
        elif v is not None and v != []:
            simple.append(f"{f.name}={_short(v)}")
    head = f"{pad}{type(node).__name__}({', '.join(simple)})"
    ty = getattr(node, "ty", None)
    if show_types and ty is not None:
        head += f"  : {ty}"
    lines = [head]
    for name, child in children:
        if isinstance(child, list):
            for c in child:
                lines.append(dump_ast(c, show_types, indent + 1))
        else:
            lines.append(dump_ast(child, show_types, indent + 1))
    return "\n".join(lines)
