"""Phase 5: optimization of the three-address code.

Several small passes, repeated until nothing changes (a fixed point):

  1. LOCAL PASS (inside one basic block, i.e. between labels/jumps)
       * constant folding            t = 2 + 3          -> t = 5
       * constant propagation        x = 5; y = x + 1   -> y = 6
       * copy propagation            t = x; y = t + 1   -> y = x + 1
       * CONVERSION FUSION           conv(conv(x,a),b)  -> conv(x, a*b)   (exact Fractions)
       * algebraic simplification    x + 0, x * 1, x / 1 -> x
  2. BRANCH FOLDING     ifFalse true goto L  -> (removed);  ifFalse false goto L -> goto L
  3. UNREACHABLE CODE   instructions after goto/return up to the next label
  4. JUMP CLEAN-UP      goto L directly before L: ; labels nobody jumps to
  5. DEAD-CODE ELIMINATION   an assignment whose result is never read (and has no side effect)

Why this matters for Lumen: a program like `let v: km/h = 10 m/s;` is checked
with units, becomes `t1 = 10.0 * 3.6` (a CONV), and the folder turns it into
the constant 36.0. After optimization no unit, and no conversion, is left at
run time: the "zero runtime cost" claim, measurable.

Safety rules: environments are discarded at every label (a join point) and
the folder uses the same arithmetic as the VM (ir.eval_binop), so optimized
and unoptimized programs always print the same thing. Division that might
trap (by a non-constant or zero) is never folded or deleted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from .ir import (BINOPS, K, UNOPS, Instr, IRFunc, IRProgram, count_instrs,
                 eval_binop, eval_conv, eval_unop, uses)

PURE = BINOPS | UNOPS | {"COPY", "CONV"}
MAY_TRAP = {"DIV", "IDIV", "MOD", "POW"}


@dataclass
class Stats:
    before: int = 0
    after: int = 0
    folded: int = 0            # constant folding (incl. folded conversions)
    propagated: int = 0        # constants / copies substituted into operands
    fused: int = 0             # conversion chains merged
    algebraic: int = 0
    branches: int = 0
    unreachable: int = 0
    dead: int = 0
    rounds: int = 0

    def lines(self) -> list[str]:
        return [
            f"instructions before optimization : {self.before}",
            f"instructions after optimization  : {self.after}",
            f"constants folded                 : {self.folded}",
            f"operands propagated              : {self.propagated}",
            f"unit conversions fused           : {self.fused}",
            f"algebraic simplifications        : {self.algebraic}",
            f"branches folded                  : {self.branches}",
            f"unreachable instructions removed : {self.unreachable}",
            f"dead assignments removed         : {self.dead}",
            f"optimizer rounds                 : {self.rounds}",
        ]


def is_int(k) -> bool:
    return isinstance(k, K) and type(k.value) is int


def is_const(x) -> bool:
    return isinstance(x, K)


# ---------------------------------------------------------------- local pass
def local_pass(f: IRFunc, st: Stats) -> bool:
    changed = False
    env: dict[str, tuple] = {}          # name -> ("const", K) | ("copy", name) | ("conv", name, Fraction)

    def forget(name: str):
        env.pop(name, None)
        for k in [k for k, v in env.items()
                  if v[0] in ("copy", "conv") and v[1] == name]:
            del env[k]

    def subst(x):
        """Replace an operand using what we know about it."""
        nonlocal changed
        if isinstance(x, str) and x in env:
            v = env[x]
            if v[0] == "const":
                st.propagated += 1
                changed = True
                return v[1]
            if v[0] == "copy":
                st.propagated += 1
                changed = True
                return v[1]
        return x

    out: list[Instr] = []
    for i in f.instrs:
        if i.op in ("LABEL",):
            env.clear()
            out.append(i)
            continue

        # substitute operands (not label names / function names)
        if i.op in BINOPS or i.op in ("COPY", "CONV", "NEG", "NOT", "I2F"):
            i.a = subst(i.a)
            if i.op in BINOPS and i.op != "POW":
                i.b = subst(i.b)
            elif i.op == "POW":
                pass
        elif i.op in ("JZ", "JNZ", "RET", "PRINT"):
            i.a = subst(i.a) if i.a is not None else None
        elif i.op in ("CALL", "CALLB"):
            i.args = [subst(x) for x in i.args]

        # fold / simplify
        i = simplify(i, env, st)
        if i is None:
            changed = True
            continue

        if i.dst is not None:
            forget(i.dst)
            if i.op == "COPY":
                if is_const(i.a):
                    env[i.dst] = ("const", i.a)
                elif isinstance(i.a, str) and i.a != i.dst:
                    env[i.dst] = ("copy", i.a)
            elif i.op == "CONV" and isinstance(i.a, str) and i.a != i.dst:
                env[i.dst] = ("conv", i.a, i.b.value)

        if i.op in ("JUMP", "JZ", "JNZ", "RET"):
            if i.op != "RET":
                pass
            # a jump ends the block; keep env only for fall-through of conditionals
            if i.op in ("JUMP", "RET"):
                env.clear()
        out.append(i)

    if len(out) != len(f.instrs) or any(a is not b for a, b in zip(out, f.instrs)):
        changed = changed or len(out) != len(f.instrs)
    f.instrs = out
    return changed


def simplify(i: Instr, env, st: Stats):
    """Constant folding and algebraic simplification of one instruction."""
    op = i.op
    # ---- folding
    if op in BINOPS and is_const(i.a) and is_const(i.b):
        try:
            v = eval_binop(op, i.a.value, i.b.value)
        except (ZeroDivisionError, OverflowError):
            return i                                  # leave it: it traps at run time
        st.folded += 1
        return Instr("COPY", i.dst, K(v), line=i.line)
    if op in UNOPS and is_const(i.a):
        st.folded += 1
        return Instr("COPY", i.dst, K(eval_unop(op, i.a.value)), line=i.line)
    if op == "CONV":
        factor: Fraction = i.b.value
        if is_const(i.a):
            st.folded += 1
            return Instr("COPY", i.dst, K(eval_conv(i.a.value, factor)), line=i.line)
        if factor == 1:
            st.algebraic += 1
            return Instr("COPY", i.dst, i.a, line=i.line)
        # conversion fusion: x --f1--> t --f2--> y   =>   x --f1*f2--> y
        known = env.get(i.a) if isinstance(i.a, str) else None
        if known and known[0] == "conv":
            st.fused += 1
            return simplify(Instr("CONV", i.dst, known[1], K(known[2] * factor), line=i.line),
                            env, st)
    # ---- algebra
    if op in ("ADD", "SUB") and is_const(i.b) and i.b.value == 0 and not isinstance(i.b.value, bool) \
            and isinstance(i.a, str):
        st.algebraic += 1
        return Instr("COPY", i.dst, i.a, line=i.line)
    if op == "ADD" and is_const(i.a) and i.a.value == 0 and not isinstance(i.a.value, bool) \
            and isinstance(i.b, str):
        st.algebraic += 1
        return Instr("COPY", i.dst, i.b, line=i.line)
    if op in ("MUL", "DIV", "IDIV") and is_const(i.b) and i.b.value == 1 \
            and not isinstance(i.b.value, bool) and isinstance(i.a, str):
        st.algebraic += 1
        return Instr("COPY", i.dst, i.a, line=i.line)
    if op == "MUL" and is_const(i.a) and i.a.value == 1 and not isinstance(i.a.value, bool) \
            and isinstance(i.b, str):
        st.algebraic += 1
        return Instr("COPY", i.dst, i.b, line=i.line)
    if op == "MUL" and (is_int(i.a) and i.a.value == 0 or is_int(i.b) and i.b.value == 0):
        st.algebraic += 1
        return Instr("COPY", i.dst, K(0), line=i.line)
    return i


# ---------------------------------------------------------------- control flow
def fold_branches(f: IRFunc, st: Stats) -> bool:
    out, changed = [], False
    for i in f.instrs:
        if i.op in ("JZ", "JNZ") and is_const(i.a):
            taken = (not i.a.value) if i.op == "JZ" else bool(i.a.value)
            st.branches += 1
            changed = True
            if taken:
                out.append(Instr("JUMP", None, i.b, line=i.line))
            continue
        out.append(i)
    f.instrs = out
    return changed


def remove_unreachable(f: IRFunc, st: Stats) -> bool:
    out, dead, changed = [], False, False
    for i in f.instrs:
        if i.op == "LABEL":
            dead = False
        if dead:
            st.unreachable += 1
            changed = True
            continue
        out.append(i)
        if i.op in ("JUMP", "RET"):
            dead = True
    f.instrs = out
    return changed


def clean_jumps(f: IRFunc, st: Stats) -> bool:
    changed = False
    ins = f.instrs
    out = []
    for n, i in enumerate(ins):
        # goto L immediately followed by L:
        if i.op == "JUMP":
            j = n + 1
            while j < len(ins) and ins[j].op == "LABEL":
                if ins[j].a == i.a:
                    break
                j += 1
            if j < len(ins) and ins[j].op == "LABEL" and ins[j].a == i.a:
                changed = True
                st.unreachable += 1
                continue
        out.append(i)
    targets = {i.b for i in out if i.op in ("JZ", "JNZ")} | {i.a for i in out if i.op == "JUMP"}
    final = []
    for i in out:
        if i.op == "LABEL" and i.a not in targets:
            changed = True
            continue
        final.append(i)
    f.instrs = final
    return changed


def eliminate_dead(f: IRFunc, st: Stats) -> bool:
    changed = False
    while True:
        used = set()
        for i in f.instrs:
            used.update(uses(i))
        keep = []
        removed = False
        for i in f.instrs:
            if i.dst is not None and i.dst not in used and i.op in PURE:
                if i.op in MAY_TRAP and not (is_const(i.b) and i.b.value != 0):
                    keep.append(i)
                    continue
                st.dead += 1
                removed = True
                continue
            keep.append(i)
        f.instrs = keep
        if not removed:
            return changed
        changed = True


# ---------------------------------------------------------------- driver
def optimize(prog: IRProgram, max_rounds: int = 20) -> tuple[IRProgram, Stats]:
    st = Stats(before=count_instrs(prog))
    for f in prog.funcs:
        for _ in range(max_rounds):
            st.rounds += 1
            c = local_pass(f, st)
            c |= fold_branches(f, st)
            c |= remove_unreachable(f, st)
            c |= clean_jumps(f, st)
            c |= eliminate_dead(f, st)
            if not c:
                break
    st.after = count_instrs(prog)
    return prog, st
