"""Regenerates docs/PHASES.md from the real compiler output (run from the project root)."""
import os
import subprocess
import sys

env = dict(os.environ, PYTHONPATH="src")


def sh(*a):
    r = subprocess.run([sys.executable, "-m", "lumen", *a], capture_output=True, text=True, env=env)
    return (r.stdout + r.stderr).rstrip()


f = "examples/phases_demo.lum"
src = open(f).read().rstrip()
toks = sh("run", f, "--tokens").splitlines()
doc = f"""# What each phase does (with real output)

Everything below is real compiler output for `examples/phases_demo.lum`
(regenerate with `python tools/make_phases_doc.py`):

```
{src}
```

## Phase 1 — Lexer (`lexer.py`)
Reads characters, produces tokens with line:column. Longest match wins (`<=` is one token). Numbers keep
an exact `Fraction` value. The lexer does **not** decide what a unit is: `m/s^2` is just
`IDENT SLASH IDENT CARET INT`. First 16 of {len(toks)} tokens (`--tokens`):

```
{chr(10).join(toks[:16])}
```

## Phase 2 — Parser (`parser.py`)
Recursive descent, one method per grammar rule, precedence from rule layering, left-associative loops.
Two context rules handle units: an identifier directly after a number starts a unit, and `/` or `*` keeps
extending the unit only if the next name is a *known* unit. `--ast` prints the tree **after** checking,
so each node shows its type (`: km/h`):

```
{sh("run", f, "--ast")}
```

## Phase 3 — Unit and type checker (`semantic.py`, `units.py`)
Bottom-up, computes a type (kind, dimension, scale) for every node. `Binary(op='/') : km/h` is the dimension
algebra at work. Where scales differ the checker inserts `Convert` nodes (see the last `Print`); the factors
are exact fractions. The unit table (`--units`):

```
{sh("run", f, "--units")}
```

## Phase 4 — Three-address code (`irgen.py`)
Flat, one operation per line, temporaries `t1, t2...`. Units are gone; a conversion is a multiply (marked `; convert`).

```
{sh("run", f, "--ir")}
```

## Phase 5 — Optimizer (`optimizer.py`)
Folding, propagation, conversion fusion, dead-code and branch elimination, repeated to a fixed point.

```
{sh("run", f, "--ir-opt")}
```

## Phase 6 — Bytecode (`codegen.py`)
Stack machine; each variable/temporary gets a numbered local slot; jump targets are absolute addresses.
(Shown for the *optimized* program: two PUSH/PRINT pairs.)

```
{sh("run", f, "--bytecode")}
```

## Phase 7 — VM (`vm.py`) and result

```
{sh("run", f, "--stats")}
```
"""
open("docs/PHASES.md", "w", encoding="utf-8").write(doc + "\n")
print("wrote docs/PHASES.md")
