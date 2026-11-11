# Lumen: a language where every number knows its unit

**Compiler Design (BCSE307L) project — VIT**
Sanjay Suresh (24BCE2685) · Sugesh Kumar (24BCE2687) · Noel Ninan (24BCE2737)
Advaith Sivakumar (24BCE2715) · Ajay Kumar (24BCE2721)

Lumen is a small statically-typed language in which a number carries its unit.
`9.8 m/s^2`, `12.5 lbf*s`, `250 USD` are values of different *types*. The compiler
checks the units of every expression, converts between compatible units exactly,
rejects incompatible ones (metres + seconds, mg vs mcg, lbf·s vs N·s) with a precise
message, and then **erases the units**, so the running program is plain arithmetic.

> NASA lost the $327.6M Mars Climate Orbiter (1999) because one program produced
> impulse in lbf·s and another read it as N·s (a ×4.45 error). An Air Canada Boeing 767
> ran out of fuel in 1983 because 1.77 lb/L was used as kg/L. Both bugs are
> compile-time errors in Lumen (`examples/mars_bug.lum`, `examples/gimli_bug.lum`).

## Run it

Python 3.10+ is the only requirement (pytest for the tests).

```bash
cd lumen-compiler
export PYTHONPATH=src                      # or: pip install -e .
python -m lumen run examples/travel_time.lum
python -m lumen run examples/mars_bug.lum        # compile error, exit code 1
python -m lumen run examples/mars_fixed.lum
python -m pytest                                 # 187 tests
python playground/server.py                      # web front end at http://localhost:8765
```

Look inside every phase (each flag prints that phase's output and stops):

| flag | shows |
|---|---|
| `--tokens` | lexer output (type, text, line:col) |
| `--ast` | type- and unit-annotated syntax tree (after conversions are inserted) |
| `--ir` / `--ir-opt` | three-address code before / after the optimizer |
| `--bytecode` | stack-machine code the VM runs |
| `--units` | the unit table (built-in + declared) |
| `--stats` | optimizer counters + VM step count (after the run) |
| `--no-opt` | skip the optimizer |

Exit codes: `0` ok · `1` compile error · `2` cannot read file · `3` runtime error.

## The language in one page

```
unit min = 60 s;                      // declare a unit: a number of another unit
unit h   = 3600 s;
unit N   = 1 kg*m/s^2;                // derived unit
unit INR;                             // a brand-new base dimension (money)

fn pace(d: km, t: min) -> km/h {      // types may be units
    return d / t;                     // km/min is converted to km/h by the compiler
}

fn main() {
    let d = 42.195 km;                // a number followed by a unit is a quantity
    let t = 3 h + 30 min;             // mixed scales: right side converted, t is in h
    print(pace(d, t));                // 12.055714286 km/h
    print(d in m);                    // explicit conversion: 42195.0 m
    let x = d + 5 s;                  // ERROR: cannot add time (s) to length (km)
}
```

Types: `int`, `float`, `bool`, `string`, and any unit expression (`m`, `km/h`, `kg*m/s^2`, `N*s`, ...).
Built-in units: `m kg s bit g` with SI prefixes `n u m c k M G` (`km`, `mg`, `ms`, `Mbit` ...).
Operators: `+ - * / % ^ == != < <= > >= && || ! in`. Statements: `let`, assignment, `if/else`, `while`,
`return`, `print`, blocks. Functions may recurse. Builtins: `sqrt abs minimum maximum float int`.

**Unit rules** (the heart of the checker):

| expression | rule |
|---|---|
| `a + b`, `a - b`, `a < b`, `a == b` | dimensions must be equal; if scales differ the right side is converted to the left's unit |
| `a * b` / `a / b` | dimensions add / subtract; if everything cancels the result is a plain number |
| `a ^ n` | `n` is an integer literal; dimension and scale are raised to `n` |
| `x in U` | explicit conversion; error unless `x` and `U` have the same dimension |
| assignment, argument, `return` | same dimension required, scale differences converted automatically; **a plain number never becomes a quantity** (except literal `0`) |
| `sqrt(q)` | all exponents of `q`'s dimension must be even |

Full reference: `docs/LANGUAGE.md`. Exam preparation: `docs/VIVA_QA.md`.

## Architecture

```
source.lum
  │  lexer.py      hand-written scanner; exact Fraction numbers; errors collected
  ▼
tokens
  │  parser.py     recursive descent, one method per grammar rule; panic-mode recovery
  ▼
AST
  │  semantic.py   unit + type checker (S-attributed); inserts Convert / Cast nodes
  │  units.py      dimension algebra, unit table, SI prefixes, "did you mean"
  ▼
annotated AST
  │  irgen.py      three-address code, short-circuit &&/||, labels and jumps
  ▼
TAC ──optimizer.py──▶ optimized TAC   (folding, propagation, conversion fusion, DCE, branch folding)
  │  codegen.py    stack bytecode, local slots, absolute jump targets
  ▼
bytecode ──vm.py──▶ output          (explicit frames; step limit; runtime errors with line numbers)
```

Support modules: `errors.py` (diagnostics + caret rendering), `tokens.py`, `ast_nodes.py`,
`ir.py` (instruction set + the arithmetic shared by VM and optimizer), `compiler.py` (driver), `cli.py`.

## Why "zero runtime cost" is true, and how we checked it

* `tests/test_backend.py::test_bytecode_has_no_unit_instructions`: the bytecode of a unit program
  contains only ordinary stack operations.
* `examples/zero_cost.lum`: `let v: km/h = 10 m/s; print(v);` optimizes to the single instruction
  `print 36.0 "km/h"`.
* Conversions are exact `Fraction`s until the last step, and chained conversions are fused:
  `x in m in mile` becomes one multiply; a km → m → km round trip disappears completely
  (factor exactly 1).
* Differential test: 21 example programs print identical output with and without the optimizer.

## Error handling

All phases collect errors instead of stopping at the first one. Output looks like:

```
examples/err_units.lum:9:18: error: cannot initialize 'v': expected speed (m/s), found length (m)
    9 |     let v: m/s = race;
      |                  ^~~~
      = help: a speed is a length / time: try `race / t`
```

* Lexical errors: illegal character, unterminated string / comment, malformed number, bad escape.
* Syntax errors: expected-token messages positioned after the previous token, `=` vs `==` hint,
  panic-mode recovery that skips whole `{ }` groups, so one run lists several real errors.
* Unit/type errors: dimension mismatch in `+ - <`, bad assignment / argument / return, bare number
  where a quantity is needed, impossible `in` conversion, unknown unit (typo and spelling suggestions),
  wrong argument count, undefined names (did-you-mean), redeclaration, missing return on some path,
  missing `main`, constant division by zero, non-bool conditions.
* Warnings: unused variable, unreachable code, unused expression value.
* Run time: division by zero, sqrt of a negative, runaway recursion, step limit (infinite loop) — each with a line number.
* An erroneous expression gets the type `error`, so one mistake produces one message, never a cascade.

## Honest limits (and the ideas for future work)

1. The checker protects a single Lumen program. Mars crossed two programs through a file; Lumen catches
   that bug where the data enters with a declared type (a bare number into an `N*s` parameter is rejected),
   but cannot see a wrong unit claimed by a human (`12.5 N*s` when the file really held lbf·s).
2. Dimensions, not *kinds*: torque and energy are both `kg*m^2/s^2`; `mcg/kg` (drug per body weight) is
   dimensionless. We reject unit expressions that cancel to a plain number.
3. No offset units (°C, °F): `20 °C + 20 °C` is meaningless, and a correct model needs affine types.
4. Integer exponents only (no `Hz^(1/2)`); `^` needs a literal exponent.
5. No unit-polymorphic functions (`fn square<U>(x: U)`) and no unit inference across calls.
6. Ints are arbitrary precision (Python); floats are IEEE doubles. The optimizer may change the last bit of
   a chain of conversions (it uses one exact factor instead of two rounded ones).
7. Back end is a stack VM written in Python; an LLVM / x86 back end is the natural next step.

## Repository layout

```
src/lumen/    the compiler (3.4k lines, no third-party dependencies)
examples/     34 Lumen programs: working, bug-and-fix pairs, and one per error class
tests/        187 pytest tests + golden outputs for every example (tests/golden)
docs/         LANGUAGE.md (reference + grammar), VIVA_QA.md, PHASES.md (what each phase does, with real output)
CLAUDE.md     guide for working on the repo with Claude Code
```

## Team

| member | owned (and can defend) |
|---|---|
| Sanjay Suresh | lexer, parser, grammar, error recovery, diagnostics rendering, CLI |
| Sugesh Kumar | unit algebra, unit table, unit/type checker, error catalogue |
| Noel Ninan | IR generation, optimizer, bytecode generator, VM, test suite |

Every member has read every phase and answers questions on all of them (see `docs/VIVA_QA.md`).
