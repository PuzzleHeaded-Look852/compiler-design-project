# Lumen: five parts, five people

The compiler is a pipeline, so it splits cleanly by phase. Each person owns one part, can run it on its
own with a flag, and should be able to answer questions on it. Everyone should still know the one-minute
story (docs/VIVA_QA.md, section 0) and the pipeline picture.

Run everything from `lumen-compiler/` with `export PYTHONPATH=src`.
Lines are approximate (`wc -l`).

| # | Person | Part | Files | Lines |
|---|---|---|---|---|
| 1 | Sanjay Suresh (24BCE2685) | Lexer, diagnostics, CLI, driver | lexer.py, tokens.py, errors.py, cli.py, compiler.py | ~590 |
| 2 | Advaith Sivakumar (24BCE2715) | Parser and syntax tree | parser.py, ast_nodes.py | ~700 |
| 3 | Sugesh Kumar (24BCE2687) | Unit system and type checker | units.py, semantic.py | ~1150 |
| 4 | Noel Ninan (24BCE2737) | Intermediate code and optimizer | ir.py, irgen.py, optimizer.py | ~680 |
| 5 | Ajay Kumar (24BCE2721) | Bytecode, VM, tests, playground | codegen.py, vm.py, tests/, playground/ | ~310 + tests |

Part 3 is the biggest because the unit checker is the heart of the project. If that feels unfair, Sugesh can hand
`units.py` (the unit table and dimension arithmetic, ~210 lines) to Ajay, whose part is the lightest.

---

## 1. Sanjay: lexer, diagnostics, CLI

**Explain:** how characters become tokens (longest match, so `<=` is one token), exact number handling (0.1 is 1/10),
why the lexer does not decide what a unit is (`m/s^2` is just IDENT / IDENT ^ INT), how errors are collected rather than
thrown, the caret-and-help error format, what stops after which phase, exit codes 0/1/2/3.

**Demo:**
```
python -m lumen run examples/phases_demo.lum --tokens
python -m lumen run examples/err_lexical.lum
```
**Likely questions:** Why are lexical errors reported alone? (A damaged token stream only produces confusing follow-on errors.)
What is the exit code for a compile error? (1.)

## 2. Advaith: parser and syntax tree

**Explain:** recursive descent, one function per grammar rule, the precedence ladder (expr, or, and, equality, comparison,
term, factor, unary, power, primary), the two unit rules (a name right after a number is a unit; a unit continues over `*` and `/`
only if the next name is a known unit, so `10 m / t` is `(10 m) / t`), panic-mode recovery (skip to the next `;` or `}`).

**Demo:**
```
python -m lumen run examples/err_syntax.lum
python -m lumen run examples/phases_demo.lum --ast
```
**Likely questions:** Is the grammar LL(1)? (Yes, plus a 2-token peek for `IDENT =` and the two unit rules.)
Why can `10 m / t` not be a unit? (`t` is a variable, not a known unit.)

## 3. Sugesh: unit system and type checker

**Explain:** every type is (kind, dimension, scale); multiplying adds dimension exponents, dividing subtracts them, `+` needs
equal dimensions; implicit conversion changes scale only, never dimension; a plain number never becomes a quantity
(except literal 0); the checker inserts `Convert` nodes; one bad expression gets an error type so it does not cascade;
help text and did-you-mean (edit distance on unit names).

**Demo:**
```
python -m lumen run examples/err_units.lum
python -m lumen run examples/mars_bug.lum
python -m lumen run examples/unit_algebra.lum --units
```
**Likely questions:** Would Lumen really have caught Mars? (Where data enters with a declared type, yes: a bare number is rejected.
Not if a human writes the wrong unit.) Why no degrees Celsius? (Offset units need point-vs-difference types: future work.)

## 4. Noel: intermediate code and optimizer

**Explain:** three-address code (one operation per line, temporaries t1, t2...), how `&&` becomes jumps, units are already gone
at this point (a conversion is just `x * 0.2777...`), the optimizer passes (fold, propagate, fuse conversions, simplify, prune
branches and dead code), why optimized and unoptimized programs always print the same (they share one arithmetic function),
why division that might trap is never folded.

**Demo:**
```
python -m lumen run examples/optimizer_demo.lum --ir
python -m lumen run examples/optimizer_demo.lum --ir-opt
python -m lumen run examples/optimizer_demo.lum --stats
```
**Likely questions:** Is fusing conversions exact? (The factor is an exact fraction, rounded once; km to m to km folds to exactly 1.)

## 5. Ajay: bytecode, VM, tests, playground

**Explain:** the stack machine (LOAD, PUSH, STORE, arithmetic, JZ, CALL, RET), frames for calls, own frame list so deep
recursion is a Lumen error and not a Python crash, step limit for infinite loops, runtime errors carry the source line,
zero runtime cost (no unit logic in codegen.py or vm.py; a test checks the opcode set), the 187 tests and golden outputs,
and the web playground.

**Demo:**
```
python -m lumen run examples/fib.lum --bytecode
python -m lumen run examples/err_runtime.lum
python -m pytest -q
python playground/server.py
```
**Likely questions:** Are units free at run time? (Yes: the bytecode has only ordinary opcodes, tested on every example.)
How do you know the optimizer is safe? (A differential test runs 21 programs with and without it and compares output.)
