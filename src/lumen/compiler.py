"""The compiler driver: runs every phase in order and keeps each phase's output.

source -> tokens -> AST -> checked AST -> TAC -> optimized TAC -> bytecode
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from . import codegen, irgen, optimizer
from .codegen import Bytecode
from .errors import CompileError, Diagnostic
from .ir import IRProgram, format_program
from .lexer import tokenize
from .optimizer import Stats
from .parser import parse
from .semantic import check
from .units import UnitTable


@dataclass
class Compiled:
    source: str
    tokens: list
    ast: object
    units: UnitTable
    warnings: list[Diagnostic]
    ir: IRProgram
    ir_opt: IRProgram | None
    opt_stats: Stats | None
    bytecode: Bytecode


def tidy(diags: list[Diagnostic]) -> list[Diagnostic]:
    """Sort by position and drop exact duplicates."""
    seen, out = set(), []
    for d in sorted(diags, key=lambda d: (d.line, d.col, d.severity != "error")):
        key = (d.line, d.col, d.message)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def compile_source(source: str, optimize: bool = True) -> Compiled:
    """Run the whole pipeline. Raises CompileError carrying all errors found."""
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(max(old, 6000))
    try:
        return _compile(source, optimize)
    except RecursionError:
        # every phase walks the tree recursively; absurdly deep nesting is reported, not crashed on
        raise CompileError([Diagnostic(
            "error", "the program is nested too deeply to compile", 1, 1, 1,
            "split very long expressions or deeply nested blocks into smaller pieces", "driver")]) from None
    finally:
        sys.setrecursionlimit(old)


def _compile(source: str, optimize: bool) -> Compiled:
    tokens, diags = tokenize(source)
    if diags:
        # lexical errors first and alone: parsing a damaged token stream only
        # produces confusing follow-on errors
        raise CompileError(tidy(diags))
    prog, pdiags = parse(tokens)
    diags = diags + pdiags
    if any(d.severity == "error" for d in diags):
        # lexical / syntax errors: do not run the checker on a broken tree
        raise CompileError(tidy(diags))
    units, sdiags = check(prog)
    errors = [d for d in sdiags if d.severity == "error"]
    if errors:
        # warnings are noise while there are errors (a failed line makes variables look unused)
        raise CompileError(tidy(errors))
    warnings = tidy(sdiags)
    ir = irgen.generate(prog)
    ir_unopt_text = format_program(ir)
    ir_opt, stats = None, None
    final = ir
    if optimize:
        ir_for_opt = irgen.generate(prog)           # fresh copy; the optimizer edits in place
        ir_opt, stats = optimizer.optimize(ir_for_opt)
        final = ir_opt
    bc = codegen.generate(final)
    return Compiled(source, tokens, prog, units, warnings, ir, ir_opt, stats, bc)
