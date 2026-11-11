"""Three-address code (TAC): the compiler's intermediate representation.

Every instruction does ONE small thing and names at most two inputs and one
output, e.g. `t3 = t1 * t2`. Complex expressions are broken into steps using
temporaries (t1, t2, ...). Control flow is flat: labels and jumps only.
Because it has no source syntax and no machine detail, the optimizer works
here, and a different back end could be attached later.

Operands are either a NAME (a source variable's unique id or a temporary), or
a constant K(value).

  COPY  dst = a                   ADD SUB MUL DIV IDIV MOD POW  dst = a op b
  NEG NOT I2F  dst = op a         LT LE GT GE EQ NE            dst = a op b
  CONV  dst = a * factor          (a unit conversion: factor is an exact Fraction)
  LABEL L        JUMP L        JZ a, L (jump if false)        JNZ a, L
  CALL dst = f(args)    CALLB dst = builtin(args)    RET [a]    PRINT a, "label"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

BINOPS = {"ADD", "SUB", "MUL", "DIV", "IDIV", "MOD", "POW",
          "LT", "LE", "GT", "GE", "EQ", "NE"}
UNOPS = {"NEG", "NOT", "I2F"}
SYMBOL = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "IDIV": "/", "MOD": "%",
          "POW": "^", "LT": "<", "LE": "<=", "GT": ">", "GE": ">=", "EQ": "==", "NE": "!="}


@dataclass(frozen=True)
class K:
    """A constant operand."""
    value: object

    def __str__(self) -> str:
        return fmt_const(self.value)


def fmt_const(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return '"' + v.replace("\n", "\\n") + '"'
    if isinstance(v, Fraction):
        return str(float(v)) if v.denominator != 1 else str(v.numerator)
    return repr(v)


@dataclass
class Instr:
    op: str
    dst: str | None = None
    a: object = None
    b: object = None
    args: list = field(default_factory=list)
    line: int = 0


@dataclass
class IRFunc:
    name: str
    params: list[str]
    instrs: list[Instr]
    returns_value: bool = False


@dataclass
class IRProgram:
    funcs: list[IRFunc]


# ---------------------------------------------------------------- uses / defs
def uses(i: Instr) -> list[str]:
    """Names (variables / temporaries) that the instruction READS."""
    if i.op in ("LABEL", "JUMP"):
        return []
    if i.op in ("JZ", "JNZ", "RET", "PRINT"):
        return [i.a] if isinstance(i.a, str) else []
    if i.op in ("CALL", "CALLB"):
        return [x for x in i.args if isinstance(x, str)]
    out = []
    for x in (i.a, i.b):
        if isinstance(x, str):
            out.append(x)
    return out


def defines(i: Instr) -> str | None:
    return i.dst


# ---------------------------------------------------------------- shared arithmetic
def trunc_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def eval_binop(op: str, a, b):
    """The meaning of every binary IR op. Used by the VM AND by the optimizer's
    constant folder, so folded and unfolded code can never disagree."""
    if op == "ADD":
        return a + b
    if op == "SUB":
        return a - b
    if op == "MUL":
        return a * b
    if op == "DIV":
        return a / b                      # ZeroDivisionError if b == 0
    if op == "IDIV":
        return trunc_div(a, b)            # truncates toward zero, like C
    if op == "MOD":
        return a - b * trunc_div(a, b)    # sign follows the dividend, like C
    if op == "POW":
        return a ** b
    if op == "LT":
        return a < b
    if op == "LE":
        return a <= b
    if op == "GT":
        return a > b
    if op == "GE":
        return a >= b
    if op == "EQ":
        return a == b
    if op == "NE":
        return a != b
    raise ValueError(op)


def eval_unop(op: str, a):
    if op == "NEG":
        return -a
    if op == "NOT":
        return not a
    if op == "I2F":
        return float(a)
    raise ValueError(op)


def eval_conv(a, factor: Fraction):
    return a * float(factor)


# ---------------------------------------------------------------- printing
def fmt_instr(i: Instr) -> str:
    op = i.op
    if op == "LABEL":
        return f"{i.a}:"
    if op == "COPY":
        return f"    {i.dst} = {i.a}"
    if op in BINOPS:
        return f"    {i.dst} = {i.a} {SYMBOL[op]} {i.b}" + ("   ; int division" if op == "IDIV" else "")
    if op == "NEG":
        return f"    {i.dst} = -{i.a}"
    if op == "NOT":
        return f"    {i.dst} = !{i.a}"
    if op == "I2F":
        return f"    {i.dst} = float({i.a})"
    if op == "CONV":
        return f"    {i.dst} = {i.a} * {fmt_const(i.b.value)}   ; convert"
    if op == "JUMP":
        return f"    goto {i.a}"
    if op == "JZ":
        return f"    ifFalse {i.a} goto {i.b}"
    if op == "JNZ":
        return f"    if {i.a} goto {i.b}"
    if op in ("CALL", "CALLB"):
        call = f"{i.a}({', '.join(str(x) for x in i.args)})"
        return f"    {i.dst} = {call}" if i.dst else f"    {call}"
    if op == "RET":
        return "    return" + (f" {i.a}" if i.a is not None else "")
    if op == "PRINT":
        return f"    print {i.a}" + (f" {i.b}" if i.b is not None and i.b.value else "")
    return f"    ?{op}"


def format_program(p: IRProgram) -> str:
    out = []
    for f in p.funcs:
        out.append(f"func {f.name}({', '.join(f.params)}):")
        out.extend(fmt_instr(i) for i in f.instrs)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def count_instrs(p: IRProgram) -> int:
    return sum(1 for f in p.funcs for i in f.instrs if i.op != "LABEL")
