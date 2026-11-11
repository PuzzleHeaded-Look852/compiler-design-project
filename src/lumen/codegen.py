"""Phase 6: code generation (three-address code -> stack bytecode).

The target is a small STACK machine. Each TAC instruction becomes a few
bytecode instructions: push the inputs, do the operation, store the result.
For example  `t3 = t1 * t2`  becomes  LOAD t1 / LOAD t2 / MUL / STORE t3.

Every variable and temporary gets a numbered local SLOT in its function's
frame. Labels become absolute instruction addresses in a second pass.

A unit conversion is just  PUSH factor / MUL : by now a unit is nothing more
than an ordinary multiplication (and usually the optimizer already folded it).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .ir import BINOPS, IRFunc, IRProgram, fmt_const


@dataclass
class BC:
    op: str
    arg: object = None
    arg2: object = None
    line: int = 0


@dataclass
class Code:
    name: str
    nparams: int
    slots: list[str]
    instrs: list[BC]
    returns_value: bool = False


@dataclass
class Bytecode:
    funcs: dict[str, Code] = field(default_factory=dict)


def gen_function(f: IRFunc, returns: dict[str, bool]) -> Code:
    slots: dict[str, int] = {p: n for n, p in enumerate(f.params)}

    def slot(name: str) -> int:
        if name not in slots:
            slots[name] = len(slots)
        return slots[name]

    code: list[BC] = []
    patches: list[tuple[int, str]] = []
    labels: dict[str, int] = {}

    def load(x, line):
        if isinstance(x, str):
            code.append(BC("LOAD", slot(x), x, line))
        else:
            code.append(BC("PUSH", x.value, None, line))

    for i in f.instrs:
        op, ln = i.op, i.line
        if op == "LABEL":
            labels[i.a] = len(code)
        elif op == "COPY":
            load(i.a, ln)
            code.append(BC("STORE", slot(i.dst), i.dst, ln))
        elif op in BINOPS:
            load(i.a, ln)
            load(i.b, ln)
            code.append(BC(op, None, None, ln))
            code.append(BC("STORE", slot(i.dst), i.dst, ln))
        elif op in ("NEG", "NOT", "I2F"):
            load(i.a, ln)
            code.append(BC(op, None, None, ln))
            code.append(BC("STORE", slot(i.dst), i.dst, ln))
        elif op == "CONV":
            load(i.a, ln)
            code.append(BC("PUSH", float(i.b.value), None, ln))
            code.append(BC("MUL", None, None, ln))
            code.append(BC("STORE", slot(i.dst), i.dst, ln))
        elif op == "JUMP":
            patches.append((len(code), i.a))
            code.append(BC("JMP", None, None, ln))
        elif op in ("JZ", "JNZ"):
            load(i.a, ln)
            patches.append((len(code), i.b))
            code.append(BC(op, None, None, ln))
        elif op in ("CALL", "CALLB"):
            for a in i.args:
                load(a, ln)
            code.append(BC(op, i.a, len(i.args), ln))
            returns_val = True if op == "CALLB" else returns.get(i.a, False)
            if i.dst is not None:
                code.append(BC("STORE", slot(i.dst), i.dst, ln))
            elif returns_val:
                code.append(BC("POP", None, None, ln))
        elif op == "RET":
            if i.a is not None:
                load(i.a, ln)
                code.append(BC("RET", 1, None, ln))
            else:
                code.append(BC("RET", 0, None, ln))
        elif op == "PRINT":
            load(i.a, ln)
            code.append(BC("PRINT", i.b.value if i.b is not None else "", None, ln))
        else:
            raise ValueError(f"codegen: unknown IR op {op}")

    for at, label in patches:
        code[at].arg = labels[label]
        code[at].arg2 = label
    names = [""] * len(slots)
    for n, k in slots.items():
        names[k] = n
    return Code(f.name, len(f.params), names, code, f.returns_value)


def generate(prog: IRProgram) -> Bytecode:
    returns = {f.name: f.returns_value for f in prog.funcs}
    bc = Bytecode()
    for f in prog.funcs:
        bc.funcs[f.name] = gen_function(f, returns)
    return bc


def format_bytecode(bc: Bytecode) -> str:
    out = []
    for c in bc.funcs.values():
        out.append(f"== {c.name}  ({c.nparams} param{'s' if c.nparams != 1 else ''}, "
                   f"{len(c.slots)} local slots)")
        for n, ins in enumerate(c.instrs):
            note = ""
            if ins.op in ("LOAD", "STORE"):
                arg = f"{ins.arg}"
                note = f"; {ins.arg2}"
            elif ins.op == "PUSH":
                arg, note = "", ""
                arg = fmt_const(ins.arg)
            elif ins.op in ("JMP", "JZ", "JNZ"):
                arg = f"{ins.arg:04d}"
                note = f"; {ins.arg2}"
            elif ins.op in ("CALL", "CALLB"):
                arg = f"{ins.arg}"
                note = f"; {ins.arg2} arg(s)"
            elif ins.op == "PRINT":
                arg = f'"{ins.arg}"' if ins.arg else ""
            elif ins.op == "RET":
                arg = "value" if ins.arg else ""
            else:
                arg = ""
            out.append(f"  {n:04d}  {ins.op:<6} {arg:<12} {note}".rstrip())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def count_bytecode(bc: Bytecode) -> int:
    return sum(len(c.instrs) for c in bc.funcs.values())
