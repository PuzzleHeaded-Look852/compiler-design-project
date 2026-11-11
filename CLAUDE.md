# CLAUDE.md — Lumen compiler

Lumen is a small language where every number knows its unit (`9.8 m/s^2`, `12.5 lbf*s`). The compiler checks
dimensions at compile time, converts compatible units exactly, rejects incompatible ones, then erases units so
the VM runs plain arithmetic. Course project (VIT BCSE307L, Compiler Design) by Sanjay Suresh (24BCE2685),
Sugesh Kumar (24BCE2687), Noel Ninan (24BCE2737), Advaith Sivakumar (24BCE2715) and Ajay Kumar (24BCE2721). **The project is complete (Reviews 1–3).** Keep changes small and
explainable: every student must be able to defend every line in a viva.

## Commands

```bash
export PYTHONPATH=src                       # or pip install -e .
python -m lumen run  examples/travel_time.lum [--tokens|--ast|--ir|--ir-opt|--bytecode|--units|--stats|--no-opt]
python -m lumen check examples/fact.lum
python -m pytest -q                         # all tests; golden outputs in tests/golden
python tests/make_golden.py                 # regenerate golden outputs (REVIEW THE DIFF)
python tools/make_phases_doc.py             # regenerate docs/PHASES.md from real output
```

Exit codes: 0 ok, 1 compile error, 2 unreadable file, 3 runtime error.

## Pipeline and files (`src/lumen/`)

`lexer.py` → `parser.py` → `semantic.py` (+ `units.py`) → `irgen.py` (+ `ir.py`) → `optimizer.py` → `codegen.py` → `vm.py`.
`compiler.py` is the driver, `cli.py` the interface, `errors.py` renders `file:line:col: error: msg` with a caret and `= help:`.

## Invariants (do not break)

1. **Units never reach run time.** `vm.py` and `codegen.py` contain no unit logic; a test checks the opcode set.
2. **Scales are exact `Fraction`s** until `float(...)` at IR/codegen time. Do not introduce floats earlier.
3. **The optimizer and the VM share arithmetic** (`ir.eval_binop`); never fold with different semantics than the VM.
   Never fold or delete an operation that can trap (division by zero). Reset knowledge at every label.
4. **Errors are collected, not raised one at a time.** An erroneous expression gets `ERR` type and stays silent afterwards
   (no cascades). Lexical errors stop before parsing; syntax errors stop before checking; warnings are hidden when errors exist.
5. Implicit conversion changes **scale only**, never dimension; a plain number never becomes a quantity (except literal `0`).
6. A name directly after a number is always a unit; a unit literal continues over `*` `/` only if the next name is a known unit.

## Conventions

* Pure Python 3.10+, no dependencies except pytest. No parser generators.
* One class/function per grammar rule in `parser.py`; comment the *why* at the top of each module.
* Every new language rule needs: a test in `tests/test_semantic.py` or `tests/test_parser.py`, an example in `examples/`
  (then regenerate goldens), and a line in `docs/LANGUAGE.md`.
* Every new error message must carry a location and, if possible, a `help:` line.

## Documentation map

`README.md` overview · `docs/LANGUAGE.md` reference + grammar + typing rules · `docs/PHASES.md` real output of every phase ·
`docs/VIVA_QA.md` viva preparation (74 questions, demo script).

## Known limits (state them honestly)

Single-program checking only (Mars crossed two programs); no offset units (°C), no quantity kinds (torque vs energy), no
fractional exponents, no unit-polymorphic functions, Python VM speed. See README "Honest limits".
