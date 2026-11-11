"""Command-line interface.

  python -m lumen run   prog.lum            compile and run
  python -m lumen check prog.lum            compile only (report errors and warnings)

Flags (stop after showing that phase):
  --tokens     the token stream                 --ast        the type-annotated AST
  --ir         three-address code               --ir-opt     optimized three-address code
  --bytecode   the stack bytecode               --units      the unit table
Other:
  --no-opt     skip the optimizer               --stats      optimizer + run statistics
  --max-steps N   VM step limit (default 10,000,000)
"""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .ast_nodes import dump_ast
from .codegen import count_bytecode, format_bytecode
from .compiler import compile_source
from .errors import CompileError, LumenRuntimeError, render_all
from .ir import format_program
from .vm import VM


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lumen",
                                 description="Lumen: a language where every number knows its unit.")
    ap.add_argument("--version", action="version", version=f"lumen {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("run", "check"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--tokens", action="store_true")
        p.add_argument("--ast", action="store_true")
        p.add_argument("--ir", action="store_true")
        p.add_argument("--ir-opt", action="store_true")
        p.add_argument("--bytecode", action="store_true")
        p.add_argument("--units", action="store_true")
        p.add_argument("--no-opt", action="store_true")
        p.add_argument("--stats", action="store_true")
        p.add_argument("--max-steps", type=int, default=10_000_000)
    args = ap.parse_args(argv)

    try:
        with open(args.file, encoding="utf-8") as fh:
            source = fh.read()
    except OSError as e:
        print(f"lumen: cannot read '{args.file}': {e.strerror}", file=sys.stderr)
        return 2

    try:
        c = compile_source(source, optimize=not args.no_opt)
    except CompileError as e:
        print(render_all(e.diagnostics, source, args.file), file=sys.stderr)
        return 1

    if c.warnings:
        print(render_all(c.warnings, source, args.file), file=sys.stderr)
        print(file=sys.stderr)

    if args.tokens:
        for t in c.tokens:
            print(f"{t.line:>3}:{t.col:<3} {t}")
        return 0
    if args.units:
        for n in c.units.order:
            u = c.units.units[n]
            print(f"{n:<8} {c.units.dim_name(u.dim):<22} = {float(u.scale):g} x {c.units.si_label(u.dim)}")
        return 0
    if args.ast:
        print(dump_ast(c.ast, show_types=True))
        return 0
    if args.ir:
        print(format_program(c.ir), end="")
        return 0
    if args.ir_opt:
        if c.ir_opt is None:
            print("lumen: --ir-opt cannot be combined with --no-opt", file=sys.stderr)
            return 2
        print(format_program(c.ir_opt), end="")
        return 0
    if args.bytecode:
        print(format_bytecode(c.bytecode), end="")
        return 0
    if args.cmd == "check":
        print(f"{args.file}: OK ({len([i for i in c.ast.items])} declarations)")
        return 0

    vm = VM(c.bytecode, max_steps=args.max_steps)
    try:
        stats = vm.run()
    except LumenRuntimeError as e:
        sys.stdout.flush()
        where = f"{args.file}:{e.line}: " if e.line else ""
        print(f"{where}runtime error: {e.message}", file=sys.stderr)
        if e.line and 1 <= e.line <= len(source.splitlines()):
            print(f"{e.line:>5} | {source.splitlines()[e.line - 1]}", file=sys.stderr)
        return 3

    if args.stats:
        print("\n--- statistics ---")
        if c.opt_stats:
            print("\n".join(c.opt_stats.lines()))
        print(f"bytecode instructions            : {count_bytecode(c.bytecode)}")
        print(f"VM steps executed                : {stats.steps}")
        print(f"function calls                   : {stats.calls}")
        print(f"max call depth                   : {stats.max_depth}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
