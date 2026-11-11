"""Phase 7: the virtual machine (runs the stack bytecode).

A classic fetch-decode-execute loop. Each function call gets a FRAME holding
its local slots, its operand stack, and an instruction pointer. CALL pushes a
frame, RET pops it and hands the result to the caller's stack. Recursion uses
this explicit frame list rather than Python's own call stack, so deep Lumen
recursion is reported as a clean Lumen error, never a Python crash.

There is NO unit logic here at all: units were erased by the compiler. The
VM only knows ints, floats, bools and strings.

Runtime errors carry the source line: division by zero, sqrt of a negative,
call stack too deep, and a step limit that catches infinite loops.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field

from .codegen import Bytecode, Code
from .errors import LumenRuntimeError
from .ir import BINOPS, eval_binop, eval_unop


def fmt_value(v) -> str:
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = f"{v:.10g}"
        if s.lstrip("-").isdigit():
            s += ".0"
        return s
    return str(v)


@dataclass
class Frame:
    code: Code
    ip: int = 0
    locals: list = field(default_factory=list)
    stack: list = field(default_factory=list)


@dataclass
class RunStats:
    steps: int = 0
    calls: int = 0
    max_depth: int = 0
    prints: int = 0


class VM:
    def __init__(self, bc: Bytecode, out=None, max_steps: int = 10_000_000, max_depth: int = 5000):
        self.bc = bc
        self.out = out or sys.stdout.write
        self.max_steps = max_steps
        self.max_depth = max_depth
        self.stats = RunStats()

    def run(self) -> RunStats:
        main = self.bc.funcs["main"]
        frames = [Frame(main, 0, [0] * len(main.slots))]
        st = self.stats
        st.calls = 1
        st.max_depth = 1
        while frames:
            fr = frames[-1]
            ins = fr.code.instrs[fr.ip]
            fr.ip += 1
            st.steps += 1
            if st.steps > self.max_steps:
                raise LumenRuntimeError(
                    f"step limit of {self.max_steps} exceeded (infinite loop?)", ins.line)
            op = ins.op
            stack = fr.stack
            try:
                if op == "PUSH":
                    stack.append(ins.arg)
                elif op == "LOAD":
                    stack.append(fr.locals[ins.arg])
                elif op == "STORE":
                    fr.locals[ins.arg] = stack.pop()
                elif op in BINOPS:
                    b = stack.pop()
                    a = stack.pop()
                    stack.append(eval_binop(op, a, b))
                elif op in ("NEG", "NOT", "I2F"):
                    stack.append(eval_unop(op, stack.pop()))
                elif op == "JMP":
                    fr.ip = ins.arg
                elif op == "JZ":
                    if not stack.pop():
                        fr.ip = ins.arg
                elif op == "JNZ":
                    if stack.pop():
                        fr.ip = ins.arg
                elif op == "POP":
                    stack.pop()
                elif op == "CALL":
                    n = ins.arg2
                    args = stack[len(stack) - n:] if n else []
                    del stack[len(stack) - n:]
                    callee = self.bc.funcs[ins.arg]
                    if len(frames) >= self.max_depth:
                        raise LumenRuntimeError(
                            f"call stack too deep (more than {self.max_depth} nested calls)",
                            ins.line)
                    loc = list(args) + [0] * (len(callee.slots) - n)
                    frames.append(Frame(callee, 0, loc))
                    st.calls += 1
                    st.max_depth = max(st.max_depth, len(frames))
                elif op == "CALLB":
                    n = ins.arg2
                    args = stack[len(stack) - n:]
                    del stack[len(stack) - n:]
                    stack.append(self.builtin(ins.arg, args, ins.line))
                elif op == "RET":
                    val = stack.pop() if ins.arg else None
                    frames.pop()
                    if frames and ins.arg:
                        frames[-1].stack.append(val)
                elif op == "PRINT":
                    v = stack.pop()
                    text = fmt_value(v) + (" " + ins.arg if ins.arg else "")
                    self.out(text + "\n")
                    st.prints += 1
                else:
                    raise LumenRuntimeError(f"unknown instruction {op}", ins.line)
            except ZeroDivisionError:
                raise LumenRuntimeError("division by zero", ins.line) from None
            except OverflowError:
                raise LumenRuntimeError("numeric overflow", ins.line) from None
        return st

    def builtin(self, name: str, args: list, line: int):
        if name == "sqrt":
            if args[0] < 0:
                raise LumenRuntimeError("sqrt of a negative number", line)
            return math.sqrt(args[0])
        if name == "abs":
            return abs(args[0])
        if name == "minimum":
            return min(args)
        if name == "maximum":
            return max(args)
        if name == "float":
            return float(args[0])
        if name == "int":
            return int(args[0])
        raise LumenRuntimeError(f"unknown builtin {name}", line)
