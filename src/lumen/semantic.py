"""Phase 3: semantic analysis, i.e. the TYPE and UNIT checker.

Input : the AST from the parser.
Output: the same AST, annotated and rewritten:
          * every expression gets `.ty`, a Type = (kind, dimension, scale),
          * implicit conversions become explicit nodes: Convert (km -> m, lbf*s -> N*s)
            and Cast (int -> float),
          * every variable gets a unique id (so shadowing is harmless later),
        plus a list of errors and warnings.

THE IDEA. The "type" of a number is more than int/float. It also records its
DIMENSION (an exponent vector over m, kg, s, bit, ...) and its SCALE (how many
base units one of its unit is). Each operator has a rule on those:

    a + b , a - b , a < b   dimensions must be EQUAL   (km + m is fine: scales differ,
                            the right side is converted; m + s is an error)
    a * b                   dimensions ADD,       scales multiply
    a / b                   dimensions SUBTRACT,  scales divide
    a ^ n                   dimension and scale raised to n
    x in U                  dimensions must be equal; inserts the conversion

This is an S-attributed definition: the attribute `ty` of a node is computed
from the `ty` of its children, bottom-up, in one post-order walk.

Errors never stop the walk. A bad expression gets the special type `error`,
and anything built from an `error` operand stays silent, so one mistake
produces one message, not a cascade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from . import ast_nodes as A
from .errors import Diagnostic
from .units import (ZERO, Unit, UnitTable, closest, dim_div, dim_mul, dim_pow)


# ====================================================================== types
@dataclass(frozen=True)
class Type:
    kind: str                                   # int float bool string void error
    dim: tuple = ()                             # () for anything that is not a quantity
    scale: Fraction = Fraction(1)
    factors: tuple = field(default=(), compare=False)   # ((name, exp), ...) for printing

    @property
    def is_num(self) -> bool:
        return self.kind in ("int", "float")

    @property
    def is_qty(self) -> bool:
        return self.kind == "float" and self.dim != ZERO

    def __str__(self) -> str:
        if self.is_qty:
            return fmt_factors(self.factors)
        return self.kind


INT = Type("int")
FLOAT = Type("float")
BOOL = Type("bool")
STRING = Type("string")
VOID = Type("void")
ERR = Type("error")

BUILTINS = {"sqrt", "abs", "minimum", "maximum", "float", "int"}


def fmt_factors(fs: tuple) -> str:
    def f(n, e):
        return n if e == 1 else f"{n}^{e}"
    pos = [f(n, e) for n, e in fs if e > 0]
    neg = [f(n, -e) for n, e in fs if e < 0]
    top = "*".join(pos) if pos else "1"
    if not neg:
        return top
    return f"{top}/{neg[0]}" if len(neg) == 1 else f"{top}/({'*'.join(neg)})"


def merge(fa: tuple, fb: tuple, sign: int = 1) -> tuple:
    d: dict[str, int] = {}
    for n, e in fa:
        d[n] = d.get(n, 0) + e
    for n, e in fb:
        d[n] = d.get(n, 0) + sign * e
    return tuple((n, e) for n, e in d.items() if e != 0)


def qty(dim, scale, factors) -> Type:
    return Type("float", dim, scale, factors)


@dataclass
class Sym:
    name: str
    ty: Type
    uid: str
    line: int
    col: int
    is_let: bool = False
    used: bool = False


@dataclass
class FuncSig:
    name: str
    params: list[Type]
    ret: Type
    node: A.FuncDecl


def is_zero(e: A.Expr) -> bool:
    """A bare literal 0 is the one unit-less number allowed to stand for zero of any unit."""
    return isinstance(e, A.Num) and e.units is None and e.value == 0


def start_of(e: A.Node) -> A.Node:
    while True:
        if isinstance(e, A.Binary):
            e = e.left
        elif isinstance(e, (A.InConv, A.Convert, A.Cast)):
            e = e.expr
        else:
            return e


def etext(e: A.Expr) -> str:
    """Short source-like text of an expression, for help messages."""
    if isinstance(e, A.Var):
        return e.name
    if isinstance(e, A.Num):
        v = e.value
        if v.denominator == 1:
            s = str(v.numerator) + (".0" if e.is_float else "")
        else:
            s = str(float(v))
        return s + (" " + A.unit_text(e.units) if e.units else "")
    if isinstance(e, A.BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, A.StrLit):
        return f'"{e.value}"'
    if isinstance(e, A.Call):
        return f"{e.name}({', '.join(etext(a) for a in e.args)})"
    if isinstance(e, A.Unary):
        return e.op + etext(e.operand)
    if isinstance(e, A.Binary):
        def side(x):
            return f"({etext(x)})" if isinstance(x, A.Binary) else etext(x)
        return f"{side(e.left)} {e.op} {side(e.right)}"
    if isinstance(e, A.InConv):
        return f"{etext(e.expr)} in {A.unit_text(e.units)}"
    if isinstance(e, (A.Convert, A.Cast)):
        return etext(e.expr)
    return "..."


def always_returns(s: A.Stmt) -> bool:
    """Does every path through this statement end in `return`? (simple control-flow check)"""
    if isinstance(s, A.Return):
        return True
    if isinstance(s, A.Block):
        return any(always_returns(x) for x in s.stmts)
    if isinstance(s, A.If):
        return s.other is not None and always_returns(s.then) and always_returns(s.other)
    return False


# ====================================================================== checker
class Checker:
    def __init__(self):
        self.units = UnitTable()
        self.diags: list[Diagnostic] = []
        self.funcs: dict[str, FuncSig] = {}
        self.scopes: list[dict[str, Sym]] = []
        self.uids: dict[str, int] = {}
        self.fn: FuncSig | None = None

    # ------------------------------------------------------------ reporting
    def error(self, line: int, col: int, length: int, msg: str, help: str | None = None):
        self.diags.append(Diagnostic("error", msg, line, col, max(length, 1), help, "semantic"))

    def warn(self, line: int, col: int, length: int, msg: str, help: str | None = None):
        self.diags.append(Diagnostic("warning", msg, line, col, max(length, 1), help, "semantic"))

    def span(self, e: A.Node) -> tuple[int, int, int]:
        s = start_of(e)
        length = 1
        if e.end_line == s.line and e.end_col > s.col:
            length = e.end_col - s.col
        return s.line, s.col, length

    def err_at(self, e: A.Node, msg: str, help: str | None = None):
        line, col, length = self.span(e)
        self.error(line, col, length, msg, help)

    def err_op(self, e: A.Binary, msg: str, help: str | None = None):
        self.error(e.line, e.col, len(e.op), msg, help)

    def bad(self, e: A.Expr) -> A.Expr:
        e.ty = ERR
        return e

    # ------------------------------------------------------------ describing types
    def describe(self, t: Type) -> str:
        if t.kind == "int":
            return "an int"
        if t.kind == "float" and t.dim == ZERO:
            return "a plain number (float)"
        if t.kind == "float":
            name = self.units.dim_name(t.dim)
            return name if str(t) == name else f"{name} ({t})"
        return f"a {t.kind}"

    def unit_label(self, t: Type) -> str:
        """Text printed after a value of this type (decided at compile time)."""
        if not t.is_qty:
            return ""
        if len(t.factors) == 1 and t.factors[0][1] == 1:
            return t.factors[0][0]
        return self.units.label_for(t.dim, t.scale) or fmt_factors(t.factors)

    # ------------------------------------------------------------ scopes
    def push(self):
        self.scopes.append({})

    def pop(self):
        for sym in self.scopes.pop().values():
            if sym.is_let and not sym.used and not sym.name.startswith("_"):
                self.warn(sym.line, sym.col, len(sym.name),
                          f"variable '{sym.name}' is never used",
                          "remove it, or start the name with '_' to silence this warning")

    def lookup(self, name: str) -> Sym | None:
        for sc in reversed(self.scopes):
            if name in sc:
                return sc[name]
        return None

    def visible_names(self) -> list[str]:
        out: list[str] = []
        for sc in self.scopes:
            out += list(sc)
        return out

    def check_name_free(self, name: str, line: int, col: int, what: str) -> bool:
        if name in BUILTINS:
            self.error(line, col, len(name), f"'{name}' is a built-in function and cannot be "
                                              f"used as a {what} name")
            return False
        return True

    def declare_var(self, name: str, ty: Type, line: int, col: int,
                    is_let: bool, node=None) -> str:
        scope = self.scopes[-1]
        if name in scope:
            old = scope[name]
            self.error(line, col, len(name), f"'{name}' is already declared in this scope",
                       f"first declared at line {old.line}")
        self.check_name_free(name, line, col, "variable")
        n = self.uids.get(name, 0)
        self.uids[name] = n + 1
        uid = name if n == 0 else f"{name}.{n}"
        scope[name] = Sym(name, ty, uid, line, col, is_let)
        return uid

    # ------------------------------------------------------------ units and types
    SPELLINGS = {"meter": "m", "meters": "m", "metre": "m", "metres": "m",
                 "sec": "s", "secs": "s", "second": "s", "seconds": "s",
                 "gram": "g", "grams": "g", "kilogram": "kg", "kilograms": "kg",
                 "kilometer": "km", "kilometers": "km", "kilometre": "km",
                 "kilometres": "km", "hour": "h", "hours": "h", "minute": "min",
                 "minutes": "min", "mins": "min", "hr": "h", "hrs": "h"}

    def unknown_unit(self, f: A.UnitFactor, lit: A.Num | None = None):
        c = closest(f.name, self.units.all_names())
        alias = self.SPELLINGS.get(f.name.lower())
        if alias and self.units.lookup(alias):
            c = alias
        elif alias:
            c = None
        if lit is not None and self.lookup(f.name):
            help = (f"'{f.name}' is a variable, not a unit. To multiply, write "
                    f"`{etext(A.Num(lit.value, lit.is_float, None))} * {f.name}`")
        elif c:
            help = f"did you mean '{c}'?"
        else:
            help = (f"declare it first: `unit {f.name} = <number> <known unit>;` "
                    f"(or `unit {f.name};` for a brand-new kind of quantity)")
        self.error(f.line, f.col, len(f.name), f"unknown unit '{f.name}'", help)

    def unit_type(self, factors: list[A.UnitFactor], lit: A.Num | None = None,
                  pos: A.Node | None = None) -> Type | None:
        dim, scale, fs = ZERO, Fraction(1), ()
        for f in factors:
            u = self.units.lookup(f.name)
            if u is None:
                self.unknown_unit(f, lit)
                return None
            dim = dim_mul(dim, dim_pow(u.dim, f.exp))
            scale *= u.scale ** f.exp
            fs = merge(fs, ((f.name, f.exp),))
        if dim == ZERO:
            where = pos or factors[0]
            self.error(where.line, where.col, 1,
                       f"the unit '{A.unit_text(factors)}' cancels out to a plain number",
                       "a unit must have a dimension; use a plain number instead")
            return None
        return qty(dim, scale, fs)

    def resolve_type(self, tr: A.TypeRef) -> Type:
        if tr.kind == "int":
            return INT
        if tr.kind == "float":
            return FLOAT
        if tr.kind == "bool":
            return BOOL
        if tr.kind == "string":
            return STRING
        t = self.unit_type(tr.units, pos=tr)
        return t if t is not None else ERR

    def declare_unit(self, d: A.UnitDecl):
        if self.units.lookup(d.name) is not None:
            self.error(d.line, d.col, len(d.name), f"unit '{d.name}' is already defined")
            return
        if d.name in BUILTINS or d.name in self.funcs:
            self.error(d.line, d.col, len(d.name), f"'{d.name}' cannot be used as a unit name")
            return
        if d.value is None:
            self.units.declare_base(d.name)
            return
        if d.value <= 0:
            self.error(d.line, d.col, len(d.name), f"unit '{d.name}' must be a positive multiple")
            return
        dim, scale = ZERO, Fraction(d.value)
        for f in d.units:
            u = self.units.lookup(f.name)
            if u is None:
                self.unknown_unit(f)
                return
            dim = dim_mul(dim, dim_pow(u.dim, f.exp))
            scale *= u.scale ** f.exp
        if dim == ZERO:
            self.error(d.line, d.col, len(d.name),
                       f"unit '{d.name}' would have no dimension",
                       "define it in terms of a unit with a dimension, e.g. `unit km = 1000 m;`")
            return
        self.units.declare(Unit(d.name, dim, scale, "user"))

    # ------------------------------------------------------------ program
    def check_program(self, prog: A.Program):
        # 1. unit declarations (in order) so every later use sees them
        for it in prog.items:
            if isinstance(it, A.UnitDecl):
                self.declare_unit(it)
        # 2. function signatures first, so calls may appear before definitions
        funcs = [it for it in prog.items if isinstance(it, A.FuncDecl)]
        for f in funcs:
            self.declare_func(f)
        # 3. bodies
        for f in funcs:
            self.check_func(f)
        if "main" not in self.funcs:
            self.error(1, 1, 1, "the program has no 'main' function",
                       "execution starts at `fn main() { ... }`")

    def declare_func(self, f: A.FuncDecl):
        if f.name in self.funcs:
            old = self.funcs[f.name].node
            self.error(f.line, f.col, len(f.name), f"function '{f.name}' is already defined",
                       f"first defined at line {old.line}")
            return
        if not self.check_name_free(f.name, f.line, f.col, "function"):
            return
        names = set()
        ptys = []
        for p in f.params:
            p.ty = self.resolve_type(p.tyref)
            if p.name in names:
                self.error(p.line, p.col, len(p.name),
                           f"duplicate parameter '{p.name}' in function '{f.name}'")
            names.add(p.name)
            ptys.append(p.ty)
        f.ret_ty = self.resolve_type(f.ret) if f.ret else VOID
        self.funcs[f.name] = FuncSig(f.name, ptys, f.ret_ty, f)
        if f.name == "main" and (f.params or f.ret):
            self.error(f.line, f.col, 4, "'main' must take no parameters and return nothing")

    def check_func(self, f: A.FuncDecl):
        sig = self.funcs.get(f.name)
        if sig is None or sig.node is not f:
            return                                   # duplicate definition, already reported
        self.fn = sig
        self.uids = {}
        self.push()
        for p in f.params:
            p.uid = self.declare_var(p.name, p.ty, p.line, p.col, False)
        self.stmts(f.body.stmts)
        if sig.ret != VOID and sig.ret != ERR and not always_returns(f.body):
            self.error(f.line, f.col, len(f.name),
                       f"function '{f.name}' may reach its end without returning "
                       f"{self.describe(sig.ret)}",
                       "make sure every path ends in a `return` statement")
        self.pop()
        self.fn = None

    # ------------------------------------------------------------ statements
    def stmts(self, stmts: list[A.Stmt]):
        warned = False
        for i, s in enumerate(stmts):
            self.stmt(s)
            if not warned and i + 1 < len(stmts) and always_returns(s):
                nxt = stmts[i + 1]
                self.warn(nxt.line, nxt.col, 1, "unreachable code",
                          "the statement before always returns")
                warned = True

    def block(self, b: A.Block):
        self.push()
        self.stmts(b.stmts)
        self.pop()

    def stmt(self, s: A.Stmt):
        getattr(self, "s_" + type(s).__name__)(s)

    def s_Block(self, s: A.Block):
        self.block(s)

    def zero_of(self, ty: Type, at: A.Node) -> A.Expr:
        if ty.kind == "bool":
            z: A.Expr = A.BoolLit(False, line=at.line, col=at.col)
        elif ty.kind == "string":
            z = A.StrLit("", line=at.line, col=at.col)
        else:
            z = A.Num(Fraction(0), ty.kind == "float", None, line=at.line, col=at.col)
        z.ty = ty
        return z

    def s_Let(self, s: A.Let):
        ty: Type | None = self.resolve_type(s.tyref) if s.tyref else None
        init = None
        if s.init is not None:
            init = self.value(s.init)
            if ty is None:
                ty = init.ty
            else:
                init = self.coerce(init, ty, f"cannot initialize '{s.name}'")
        elif ty is None:
            self.error(s.line, s.col, len(s.name), f"cannot infer the type of '{s.name}'",
                       "add a type (`let x: m;`) or an initial value (`let x = 5 m;`)")
            ty = ERR
        else:
            init = self.zero_of(ty, s) if ty != ERR else None
        s.init = init
        s.uid = self.declare_var(s.name, ty, s.line, s.col, True)

    def s_Assign(self, s: A.Assign):
        sym = self.lookup(s.name)
        val = self.value(s.value)
        if sym is None:
            self.undefined(s.name, s.line, s.col)
            return
        s.uid = sym.uid
        s.value = self.coerce(val, sym.ty, f"cannot assign to '{s.name}'")

    def condition(self, c: A.Expr, what: str) -> A.Expr:
        c = self.value(c)
        if c.ty not in (BOOL, ERR):
            help = None
            if c.ty.is_num:
                help = "compare explicitly, for example `x != 0` or `x > 0`"
            self.err_at(c, f"the {what} condition must be bool, found {self.describe(c.ty)}", help)
        return c

    def s_If(self, s: A.If):
        s.cond = self.condition(s.cond, "if")
        self.block(s.then)
        if isinstance(s.other, A.If):
            self.s_If(s.other)
        elif s.other is not None:
            self.block(s.other)

    def s_While(self, s: A.While):
        s.cond = self.condition(s.cond, "while")
        self.block(s.body)

    def s_Return(self, s: A.Return):
        fn = self.fn
        if s.value is None:
            if fn.ret not in (VOID, ERR):
                self.error(s.line, s.col, 6, f"function '{fn.name}' must return "
                                              f"{self.describe(fn.ret)}")
            return
        v = self.value(s.value)
        if fn.ret == VOID:
            self.err_at(v, f"function '{fn.name}' returns nothing, but this returns a value",
                        f"declare a return type: `fn {fn.name}(...) -> {v.ty} {{`"
                        if v.ty != ERR else None)
            s.value = v
            return
        s.value = self.coerce(v, fn.ret, f"return value of '{fn.name}'")

    def s_Print(self, s: A.Print):
        s.value = self.value(s.value)
        s.label = self.unit_label(s.value.ty)

    def s_ExprStmt(self, s: A.ExprStmt):
        s.expr = self.expr(s.expr)
        if not isinstance(s.expr, A.Call) and s.expr.ty != ERR:
            self.warn(*self.span(s.expr), "the value of this expression is not used")

    # ------------------------------------------------------------ expressions
    def expr(self, e: A.Expr) -> A.Expr:
        return getattr(self, "x_" + type(e).__name__)(e)

    def value(self, e: A.Expr) -> A.Expr:
        """An expression whose value is needed (so a void call is an error)."""
        e = self.expr(e)
        if e.ty == VOID:
            self.err_at(e, f"'{e.name}' returns nothing, so it has no value to use"
                        if isinstance(e, A.Call) else "this has no value")
            e.ty = ERR
        return e

    def x_Num(self, e: A.Num):
        if e.units is None:
            e.ty = FLOAT if e.is_float else INT
            return e
        t = self.unit_type(e.units, lit=e, pos=e)
        e.ty = t if t is not None else ERR
        return e

    def x_BoolLit(self, e):
        e.ty = BOOL
        return e

    def x_StrLit(self, e):
        e.ty = STRING
        return e

    def undefined(self, name: str, line: int, col: int):
        u = self.units.lookup(name)
        if u is not None:
            self.error(line, col, len(name), f"'{name}' is a unit, not a variable",
                       f"a quantity is a number followed by its unit, e.g. `5 {name}`")
            return
        if name in self.funcs:
            self.error(line, col, len(name), f"'{name}' is a function, not a variable",
                       f"call it: {name}(...)")
            return
        c = closest(name, self.visible_names())
        self.error(line, col, len(name), f"undefined variable '{name}'",
                   f"did you mean '{c}'?" if c else "declare it first with `let`")

    def x_Var(self, e: A.Var):
        sym = self.lookup(e.name)
        if sym is None:
            self.undefined(e.name, e.line, e.col)
            return self.bad(e)
        sym.used = True
        e.uid = sym.uid
        e.ty = sym.ty
        return e

    def x_Unary(self, e: A.Unary):
        e.operand = self.value(e.operand)
        t = e.operand.ty
        if t == ERR:
            return self.bad(e)
        if e.op == "!":
            if t != BOOL:
                self.error(e.line, e.col, 1, f"'!' needs a bool, found {self.describe(t)}")
                return self.bad(e)
            e.ty = BOOL
            return e
        if not t.is_num:
            self.error(e.line, e.col, 1, f"unary '-' needs a number, found {self.describe(t)}")
            return self.bad(e)
        e.ty = t
        return e

    def cast_float(self, x: A.Expr) -> A.Expr:
        c = A.Cast(x, "float", line=x.line, col=x.col)
        c.ty = FLOAT
        return c

    def convert(self, x: A.Expr, src: Type, dst: Type) -> A.Expr:
        c = A.Convert(x, src.scale, dst.scale, line=x.line, col=x.col)
        c.ty = qty(dst.dim, dst.scale, dst.factors) if dst.dim != ZERO else FLOAT
        return c

    # ---- dimension hints
    def suggest(self, e: A.Expr, src: Type, tgt: Type) -> str | None:
        """Help text for a unit mismatch between a value of type src and a wanted type tgt."""
        text = etext(e)
        if tgt.is_qty and src.dim == ZERO:
            return (f"if the number really is in {self.unit_label(tgt)}, say so: "
                    f"`{text} * 1 {self.unit_label(tgt)}`; or write the literal with its unit "
                    f"(e.g. `4 {self.unit_label(tgt)}`)")
        if src.is_qty and tgt.dim == ZERO and tgt.kind == "float":
            return f"to get the plain number, divide by the unit: `{text} / 1 {self.unit_label(src)}`"
        if src.is_qty and tgt.is_qty:
            tn, sn = self.units.dim_name(tgt.dim), self.units.dim_name(src.dim)
            # look for a variable that fixes the mismatch
            for name in reversed(self.visible_names()):
                sym = self.lookup(name)
                if sym is None or not sym.ty.is_qty or sym.ty.dim == ZERO:
                    continue
                d = sym.ty.dim
                if dim_div(src.dim, d) == tgt.dim:
                    return (f"a {tn} is a {sn} / {self.units.dim_name(d)}: "
                            f"try `{text} / {name}`")
                if dim_mul(src.dim, d) == tgt.dim:
                    return (f"a {tn} is a {sn} * {self.units.dim_name(d)}: "
                            f"try `{text} * {name}`")
                if dim_div(d, src.dim) == tgt.dim:
                    return (f"a {tn} is a {self.units.dim_name(d)} / {sn}: "
                            f"try `{name} / {text}`")
            need_div = self.units.dim_name(dim_div(src.dim, tgt.dim))
            return (f"to turn {sn} into {tn} you would divide by a {need_div} "
                    f"(or multiply by something that is {self.units.dim_name(dim_div(tgt.dim, src.dim))})")
        if tgt.kind == "int" and src.kind == "float" and src.dim == ZERO:
            return "use int(x) to truncate to a whole number"
        return None

    def mismatch(self, e: A.Expr, tgt: Type, src: Type, ctx: str):
        self.err_at(e, f"{ctx}: expected {self.describe(tgt)}, found {self.describe(src)}",
                    self.suggest(e, src, tgt))

    def coerce(self, e: A.Expr, tgt: Type, ctx: str) -> A.Expr:
        """Make `e` usable where a value of type `tgt` is required: insert a
        conversion if only the SCALE differs, report an error if the DIMENSION
        (or the basic kind) differs."""
        src = e.ty
        if src == ERR or tgt == ERR:
            return e
        if tgt.kind in ("bool", "string") or not src.is_num:
            if src.kind != tgt.kind:
                self.mismatch(e, tgt, src, ctx)
            return e
        if is_zero(e) and tgt.is_qty:                # zero of any unit
            e.ty = tgt
            return e
        if tgt.kind == "int":
            if src.kind != "int":
                self.mismatch(e, tgt, src, ctx)
            return e
        if src.dim != tgt.dim:
            self.mismatch(e, tgt, src, ctx)
            return e
        if src.kind == "int":
            return self.cast_float(e)
        if src.scale != tgt.scale:
            return self.convert(e, src, tgt)
        return e

    def unify(self, l: A.Expr, r: A.Expr, report) -> tuple[A.Expr, A.Expr, Type] | None:
        """Bring two numeric operands to a common type (used by + - comparisons min max)."""
        lt, rt = l.ty, r.ty
        if is_zero(r) and lt.is_qty:
            r.ty = rt = lt
        elif is_zero(l) and rt.is_qty:
            l.ty = lt = rt
        if lt.dim != rt.dim:
            report(lt, rt)
            return None
        any_float = lt.kind == "float" or rt.kind == "float"
        if any_float:
            if lt.kind == "int":
                l = self.cast_float(l)
            if rt.kind == "int":
                r = self.cast_float(r)
        if rt.scale != lt.scale:
            r = self.convert(r, rt, lt)
        return l, r, Type("float" if any_float else "int", lt.dim, lt.scale, lt.factors)

    def op_hint(self, e: A.Binary) -> str | None:
        lt, rt = e.left.ty, e.right.ty
        lt_q, rt_q = lt.is_qty, rt.is_qty
        if lt_q and rt.dim == ZERO and rt.is_num:
            return (f"write the number with its unit, e.g. `{etext(e.right)} {self.unit_label(lt)}`"
                    f" (or `{etext(e.right)} * 1 {self.unit_label(lt)}`)")
        if rt_q and lt.dim == ZERO and lt.is_num:
            return (f"write the number with its unit, e.g. `{etext(e.left)} {self.unit_label(rt)}`")
        if lt_q and rt_q:
            dn = self.units.dim_name(dim_div(lt.dim, rt.dim))
            mn = self.units.dim_name(dim_mul(lt.dim, rt.dim))
            return (f"'{e.op}' needs the same dimension on both sides. To combine different "
                    f"dimensions use `/` (would give {dn}) or `*` (would give {mn})")
        return None

    def x_Binary(self, e: A.Binary):
        e.left = self.value(e.left)
        e.right = self.value(e.right)
        lt, rt = e.left.ty, e.right.ty
        if lt == ERR or rt == ERR:
            return self.bad(e)
        op = e.op

        if op in ("&&", "||"):
            for t in (lt, rt):
                if t != BOOL:
                    self.err_op(e, f"'{op}' needs bool operands, found {self.describe(t)}")
                    return self.bad(e)
            e.ty = BOOL
            return e

        if op == "^":
            return self.power(e)

        if op in ("==", "!=") and lt.kind == rt.kind and lt.kind in ("bool", "string"):
            e.ty = BOOL
            return e

        if lt.kind == "string" and rt.kind == "string" and op == "+":
            e.ty = STRING
            return e

        if not (lt.is_num and rt.is_num):
            self.err_op(e, f"cannot apply '{op}' to {self.describe(lt)} and {self.describe(rt)}")
            return self.bad(e)

        if op in ("<", "<=", ">", ">=", "==", "!="):
            what = "compare" if op not in ("==", "!=") else "compare"

            def rep(a, b):
                self.err_op(e, f"cannot {what} {self.describe(a)} with {self.describe(b)}",
                            self.op_hint(e))
            u = self.unify(e.left, e.right, rep)
            if u is None:
                return self.bad(e)
            e.left, e.right, _ = u
            e.ty = BOOL
            return e

        if op in ("+", "-"):
            verb = "add" if op == "+" else "subtract"

            def rep2(a, b):
                self.err_op(e, f"dimension mismatch: cannot {verb} {self.describe(b)} "
                               f"{'to' if op == '+' else 'from'} {self.describe(a)}"
                            if op == "+" else
                            f"dimension mismatch: cannot subtract {self.describe(b)} "
                            f"from {self.describe(a)}", self.op_hint(e))
            u = self.unify(e.left, e.right, rep2)
            if u is None:
                return self.bad(e)
            e.left, e.right, e.ty = u
            return e

        if op == "%":
            if lt.kind != "int" or rt.kind != "int" or lt.dim or rt.dim:
                self.err_op(e, "'%' works on plain ints only",
                            "use it as in `n % 2` where both sides are int")
                return self.bad(e)
            self.check_div_zero(e)
            e.ty = INT
            return e

        return self.multiplicative(e)           # * /

    def check_div_zero(self, e: A.Binary):
        r = e.right
        if isinstance(r, A.Num) and r.value == 0:
            self.err_at(r, "division by zero", "the divisor is the constant 0")

    def multiplicative(self, e: A.Binary):
        lt, rt = e.left.ty, e.right.ty
        op = e.op
        if op == "/":
            self.check_div_zero(e)
        if lt.kind == "int" and rt.kind == "int":
            e.ty = INT
            return e
        if lt.kind == "int":
            e.left = self.cast_float(e.left)
        if rt.kind == "int":
            e.right = self.cast_float(e.right)
        if op == "*":
            dim, scale, fs = dim_mul(lt.dim, rt.dim), lt.scale * rt.scale, merge(lt.factors, rt.factors)
        else:
            dim, scale, fs = dim_div(lt.dim, rt.dim), lt.scale / rt.scale, merge(lt.factors, rt.factors, -1)
        return self.finish_float(e, dim, scale, fs)

    def finish_float(self, e: A.Expr, dim, scale, fs) -> A.Expr:
        """Give a float result its type. If the units cancelled to a plain number,
        convert it to scale 1 (so `2 km / 500 m` is 4, not 0.004)."""
        if dim == ZERO:
            e.ty = Type("float", ZERO, scale)
            if scale != 1:
                c = A.Convert(e, scale, Fraction(1), line=e.line, col=e.col)
                c.ty = FLOAT
                return c
            e.ty = FLOAT
            return e
        e.ty = qty(dim, scale, fs)
        return e

    def power(self, e: A.Binary):
        lt = e.left.ty
        n = int(e.right.value)
        e.right.ty = INT
        if not lt.is_num:
            self.err_op(e, f"'^' needs a number on the left, found {self.describe(lt)}")
            return self.bad(e)
        if lt.kind == "int":
            if n >= 0:
                e.ty = INT
                return e
            e.left = self.cast_float(e.left)
        dim, scale = dim_pow(lt.dim, n), lt.scale ** n
        fs = tuple((nm, ex * n) for nm, ex in lt.factors if ex * n != 0)
        return self.finish_float(e, dim, scale, fs)

    def x_InConv(self, e: A.InConv):
        e.expr = self.value(e.expr)
        t = e.expr.ty
        target = self.unit_type(e.units, pos=e)
        if t == ERR or target is None:
            return self.bad(e)
        if not t.is_qty:
            self.err_at(e.expr, f"cannot convert {self.describe(t)}: it has no unit",
                        f"give it one first, e.g. `{etext(e.expr)} * 1 {self.unit_label(target)}`"
                        if t.is_num else None)
            return self.bad(e)
        if t.dim != target.dim:
            others = [n for n in self.units.all_names()
                      if (u := self.units.lookup(n)) and u.dim == t.dim and u.kind != "base"][:6]
            help = (f"{self.units.dim_name(t.dim)} can be converted to: "
                    f"{', '.join(others)}" if others else None)
            self.error(e.line, e.col, 2,
                       f"cannot convert {self.describe(t)} to {self.describe(target)}", help)
            return self.bad(e)
        return self.convert(e.expr, t, target)

    # ---- calls
    def x_Call(self, e: A.Call):
        if e.name in BUILTINS:
            return self.builtin(e)
        e.args = [self.value(a) for a in e.args]
        sig = self.funcs.get(e.name)
        if sig is None:
            u = self.units.lookup(e.name)
            if e.name in self.visible_names():
                self.error(e.line, e.col, len(e.name), f"'{e.name}' is a variable, not a function")
            elif u is not None:
                self.error(e.line, e.col, len(e.name), f"'{e.name}' is a unit, not a function",
                           f"a quantity is a number followed by its unit, e.g. `5 {e.name}`")
            else:
                c = closest(e.name, list(self.funcs) + sorted(BUILTINS))
                self.error(e.line, e.col, len(e.name), f"undefined function '{e.name}'",
                           f"did you mean '{c}'?" if c else None)
            return self.bad(e)
        if len(e.args) != len(sig.params):
            plural = "" if len(sig.params) == 1 else "s"
            self.error(e.line, e.col, len(e.name),
                       f"function '{e.name}' takes {len(sig.params)} argument{plural} "
                       f"but {len(e.args)} {'was' if len(e.args) == 1 else 'were'} given",
                       "declared as `fn " + e.name + "(" + ", ".join(
                           f"{p.name}: {p.ty}" for p in sig.node.params) + ")`")
        else:
            e.args = [self.coerce(a, pt, f"argument {i} of '{e.name}'")
                      for i, (a, pt) in enumerate(zip(e.args, sig.params), 1)]
        e.ty = sig.ret
        return e

    def builtin(self, e: A.Call):
        name = e.name
        e.args = [self.value(a) for a in e.args]
        want = 2 if name in ("minimum", "maximum") else 1
        if len(e.args) != want:
            self.error(e.line, e.col, len(name),
                       f"'{name}' takes {want} argument{'s' if want > 1 else ''}, "
                       f"but {len(e.args)} given")
            return self.bad(e)
        if any(a.ty == ERR for a in e.args):
            return self.bad(e)
        a = e.args[0]
        t = a.ty
        if not t.is_num:
            self.err_at(a, f"'{name}' needs a number, found {self.describe(t)}")
            return self.bad(e)
        if name == "abs":
            e.ty = t
        elif name in ("minimum", "maximum"):
            def rep(x, y):
                self.error(e.line, e.col, len(name),
                           f"cannot compare {self.describe(x)} with {self.describe(y)} in '{name}'")
            u = self.unify(e.args[0], e.args[1], rep)
            if u is None:
                return self.bad(e)
            e.args = [u[0], u[1]]
            e.ty = u[2]
        elif name == "float":
            if t.dim != ZERO:
                self.err_at(a, "float() works on plain numbers",
                            f"to drop the unit divide by it: `{etext(a)} / 1 {self.unit_label(t)}`")
                return self.bad(e)
            e.ty = FLOAT
        elif name == "int":
            if t.dim != ZERO:
                self.err_at(a, "int() works on plain numbers",
                            f"divide by the unit first: `int({etext(a)} / 1 {self.unit_label(t)})`")
                return self.bad(e)
            e.ty = INT
        elif name == "sqrt":
            if t.kind == "int":
                e.args[0] = self.cast_float(a)
                e.ty = FLOAT
            elif t.dim == ZERO:
                e.ty = FLOAT
            else:
                if any(ex % 2 for _, ex in t.dim):
                    self.err_at(a, f"cannot take sqrt of {self.describe(t)}: the exponents "
                                   "of its dimension are not all even",
                                "sqrt of an area (m^2) is a length, but sqrt of a length is not "
                                "a Lumen unit")
                    return self.bad(e)
                if t.scale != 1:
                    e.args[0] = self.convert(a, t, qty(t.dim, Fraction(1), ()))
                dim = tuple((k, v // 2) for k, v in t.dim)
                e.ty = qty(dim, Fraction(1), tuple(dim))
        return e


# ====================================================================== entry point
def check(prog: A.Program) -> tuple[UnitTable, list[Diagnostic]]:
    c = Checker()
    c.check_program(prog)
    return c.units, c.diags
