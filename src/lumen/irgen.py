"""Phase 4: intermediate code generation (checked AST -> three-address code).

Walks the type-annotated AST. Expressions return an OPERAND (a name or a
constant) after emitting the instructions that compute it; statements emit
control flow using labels. Units are already gone: the checker turned every
unit conversion into a CONV with an exact factor, and from here on a quantity
is just a number.

Short-circuit `&&` / `||` become jumps, so the right side is only evaluated
when needed. `while` becomes: label, test, conditional jump out, body, jump back.
"""

from __future__ import annotations

from fractions import Fraction

from . import ast_nodes as A
from .ir import K, Instr, IRFunc, IRProgram

OPS = {"+": "ADD", "-": "SUB", "*": "MUL", "%": "MOD", "^": "POW",
       "<": "LT", "<=": "LE", ">": "GT", ">=": "GE", "==": "EQ", "!=": "NE"}


class IRGen:
    def __init__(self):
        self.out: list[Instr] = []
        self.ntemp = 0
        self.nlabel = 0

    def temp(self) -> str:
        self.ntemp += 1
        return f"t{self.ntemp}"

    def label(self) -> str:
        self.nlabel += 1
        return f"L{self.nlabel}"

    def emit(self, op, dst=None, a=None, b=None, args=None, line=0) -> Instr:
        i = Instr(op, dst, a, b, args or [], line)
        self.out.append(i)
        return i

    # ---- program / functions
    def program(self, prog: A.Program) -> IRProgram:
        funcs = []
        for it in prog.items:
            if isinstance(it, A.FuncDecl):
                funcs.append(self.func(it))
        return IRProgram(funcs)

    def func(self, f: A.FuncDecl) -> IRFunc:
        self.out, self.ntemp, self.nlabel = [], 0, 0
        for s in f.body.stmts:
            self.stmt(s)
        if not self.out or self.out[-1].op != "RET":
            self.emit("RET", line=f.body.end_line or f.line)
        returns = f.ret_ty is not None and f.ret_ty.kind != "void"
        return IRFunc(f.name, [p.uid for p in f.params], self.out, returns)

    # ---- statements
    def stmt(self, s: A.Stmt):
        getattr(self, "s_" + type(s).__name__)(s)

    def s_Block(self, s):
        for x in s.stmts:
            self.stmt(x)

    def s_Let(self, s):
        r = self.expr(s.init)
        self.emit("COPY", s.uid, r, line=s.line)

    def s_Assign(self, s):
        r = self.expr(s.value)
        self.emit("COPY", s.uid, r, line=s.line)

    def s_ExprStmt(self, s):
        e = s.expr
        if isinstance(e, A.Call):
            self.call(e, want_value=False)
        else:
            self.expr(e)

    def s_Print(self, s):
        r = self.expr(s.value)
        self.emit("PRINT", None, r, K(s.label), line=s.line)

    def s_Return(self, s):
        r = self.expr(s.value) if s.value is not None else None
        self.emit("RET", None, r, line=s.line)

    def s_If(self, s):
        c = self.expr(s.cond)
        l_else = self.label()
        self.emit("JZ", None, c, l_else, line=s.line)
        self.stmt(s.then)
        if s.other is None:
            self.emit("LABEL", None, l_else)
            return
        l_end = self.label()
        self.emit("JUMP", None, l_end, line=s.line)
        self.emit("LABEL", None, l_else)
        self.stmt(s.other)
        self.emit("LABEL", None, l_end)

    def s_While(self, s):
        l_top, l_end = self.label(), self.label()
        self.emit("LABEL", None, l_top)
        c = self.expr(s.cond)
        self.emit("JZ", None, c, l_end, line=s.line)
        self.stmt(s.body)
        self.emit("JUMP", None, l_top, line=s.line)
        self.emit("LABEL", None, l_end)

    # ---- expressions
    def expr(self, e: A.Expr):
        return getattr(self, "x_" + type(e).__name__)(e)

    def x_Num(self, e):
        return K(float(e.value) if e.ty.kind == "float" else int(e.value))

    def x_BoolLit(self, e):
        return K(e.value)

    def x_StrLit(self, e):
        return K(e.value)

    def x_Var(self, e):
        return e.uid

    def x_Unary(self, e):
        r = self.expr(e.operand)
        t = self.temp()
        self.emit("NEG" if e.op == "-" else "NOT", t, r, line=e.line)
        return t

    def x_Cast(self, e):
        r = self.expr(e.expr)
        if isinstance(r, K):
            return K(float(r.value))
        t = self.temp()
        self.emit("I2F", t, r, line=e.line)
        return t

    def x_Convert(self, e):
        r = self.expr(e.expr)
        factor = Fraction(e.from_scale) / Fraction(e.to_scale)
        t = self.temp()
        self.emit("CONV", t, r, K(factor), line=e.line)
        return t

    def x_Binary(self, e):
        if e.op in ("&&", "||"):
            return self.short_circuit(e)
        l = self.expr(e.left)
        r = self.expr(e.right)
        if e.op == "/":
            op = "IDIV" if e.ty.kind == "int" else "DIV"
        else:
            op = OPS[e.op]
        if op == "POW":
            r = K(int(e.right.value))
        t = self.temp()
        self.emit(op, t, l, r, line=e.line)
        return t

    def short_circuit(self, e):
        t = self.temp()
        l_end = self.label()
        l = self.expr(e.left)
        self.emit("COPY", t, l, line=e.line)
        self.emit("JZ" if e.op == "&&" else "JNZ", None, t, l_end, line=e.line)
        r = self.expr(e.right)
        self.emit("COPY", t, r, line=e.line)
        self.emit("LABEL", None, l_end)
        return t

    def x_Call(self, e):
        return self.call(e, want_value=True)

    def call(self, e, want_value: bool):
        args = [self.expr(a) for a in e.args]
        from .semantic import BUILTINS
        op = "CALLB" if e.name in BUILTINS else "CALL"
        dst = self.temp() if want_value and e.ty.kind != "void" else None
        self.emit(op, dst, e.name, None, args, line=e.line)
        return dst


def generate(prog: A.Program) -> IRProgram:
    return IRGen().program(prog)
