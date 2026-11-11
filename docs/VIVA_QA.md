# Viva preparation — Lumen (every question the professor can ask)

How to use this: read the **one-minute story** first, then the questions by topic. Every answer is short
enough to say aloud. Where a question is a trap, the answer starts with **TRAP**. Everything here matches
the code in this repository; the commands in `[brackets]` let you *show* the answer live.

---

## 0. The one-minute story (memorise this)

"Software keeps losing money and lives because numbers lose their meaning. In 1999 NASA's Mars Climate Orbiter
burned up because one program gave thruster impulse in pound-force seconds and another read it as newton seconds —
a factor of 4.45, $327.6 million. In 1983 an Air Canada 767 ran out of fuel because pounds-per-litre was used as
kilograms-per-litre. Lumen is a language where a number carries its unit in its **type**. The compiler does
dimensional analysis on every expression: it adds exponents when you multiply, subtracts when you divide,
refuses to add metres to seconds, and converts kilometres to metres exactly when the dimension agrees. Then it
**erases** the units, so the program that runs is plain arithmetic with no runtime cost. It is a full compiler:
lexer, recursive-descent parser, unit/type checker, three-address code, optimizer, stack bytecode and a VM, with
187 tests and 34 example programs."

---

## 1. Motivation and idea

**Q1. What problem does Lumen solve?**
Unit mistakes: values that are numerically fine but physically meaningless (m + s) or silently wrong by a scale factor
(lbf·s read as N·s, mg vs mcg, lb/L vs kg/L). Normal languages see only `float`, so they cannot notice. [`run examples/mars_bug.lum`]

**Q2. Explain the Mars Climate Orbiter failure.**
Lockheed's ground software file (`SM_FORCES`) gave thruster impulse in lbf·s; NASA's navigation software expected N·s.
Nobody converted (×4.45). The orbiter's trajectory error accumulated; it was planned to pass Mars at about 226 km but
reached about 57 km (minimum survivable ≈ 80 km) on 23 Sep 1999. Total cost $327.6M. NASA's investigation named
the root cause as failure to use metric units in the coding of a ground software file; two navigators' doubts were dismissed over paperwork form.

**Q3. Explain the Gimli Glider.**
23 July 1983, Air Canada Boeing 767, Montreal–Ottawa–Edmonton, 69 people aboard. The fuel gauges were out, so fuel was measured by dipstick in litres (7,682 L aboard) and converted to mass.
The crew used 1.77 — pounds per litre — as if it were kilograms per litre. They believed 7,682 × 1.77 ≈ 13,600 kg was aboard, needed 22,300 kg, and added only 4,917 L. With the correct 0.803 kg/L the aircraft had ≈ 10,100 kg:
less than half. Both engines quit at 41,000 ft; the crew glided about 17 minutes to Gimli, Manitoba; nobody died.
[`run examples/gimli_bug.lum` is rejected; `gimli_fixed.lum` converts 1.77 lb/L to 0.803 kg/L automatically]

**Q4. TRAP — "Would Lumen really have caught Mars? The bug was between two programs."**
Honest answer: partly. A checker only sees one program. Lumen catches it **where data enters with a declared type**: if the navigation
function takes `N*s`, a bare number from a file is rejected, and the only way through is to write the unit
(`x * 1 N*s` or `12.5 lbf*s`) — which makes the assumption visible in the code and reviewable. If a human *writes the wrong unit*
claiming lbf data is N·s, no compiler can know. We state this limit openly.

**Q5. Why not just a library (F#, Frink, Rust `uom`, C++ Boost.Units)?**
Those exist and are good; Lumen's point is to *build the compiler* that does it. In a library, units are encoded
in the host language's generic types (hard error messages, compile-time cost). In Lumen units are first-class syntax
(`9.8 m/s^2`, `x in km`), the error messages speak physics ("expected speed (m/s), found length (m); try `race / t`"), and the
design is small enough to explain end to end.

**Q6. Why is this a *compiler* project and not just a calculator?**
Because every phase has real work: units force context-sensitive lexing/parsing decisions, the checker is an
attribute-grammar evaluator over a new type system, the optimizer has a unit-specific pass (conversion fusion), and the
back end is a real code generator and VM.

---

## 2. Overall architecture

**Q7. Name the phases and their input/output.**
Lexer (text→tokens) → Parser (tokens→AST) → Unit/type checker (AST→annotated AST) → IR generator (→three-address code) →
Optimizer (TAC→TAC) → Code generator (→stack bytecode) → VM (executes). Front end = first three; back end = rest.
[`--tokens`, `--ast`, `--ir`, `--ir-opt`, `--bytecode`]

**Q8. Which parts are analysis and which are synthesis?**
Analysis: lexer, parser, checker. Synthesis: IR, optimizer, codegen (and the VM runs the result).

**Q9. Why an intermediate representation at all?**
It separates what the program means from how a machine runs it. The optimizer works on TAC without caring about source syntax
or target machine; a different back end (LLVM, x86) could be attached to the same IR.

**Q10. Why Python? Why no lex/yacc/ANTLR?**
We wanted every line to be explainable. Python lets us write the lexer, parser and VM in a few hundred readable lines, and exact
`fractions.Fraction` arithmetic is built in, which we need for conversion factors. No parser generators so we can defend every rule.
Cost: the VM is slow compared to native code (future work: LLVM).

**Q11. How big is it?**
About 3.4k lines in `src/lumen`, 187 pytest tests, 34 example programs (each with a golden output), no dependencies besides pytest.

---

## 3. Lexer

**Q12. How does the lexer work?**
Hand-written scanner: look at the current character and dispatch — whitespace/comments skipped, digit → number, letter/_ → word
(keyword table lookup), quote → string, else operator. It is effectively a hand-coded DFA. [`lexer.py`]

**Q13. What is "longest match" and where do you use it?**
Take the longest string that forms a valid token. `<=` is one token, not `<` then `=`. We try the two-character operator table first.

**Q14. Why store numbers as `Fraction`?**
So `0.1` is exactly 1/10 and unit scales like `4.4482216152605` stay exact until the very last step. If we used binary floats the conversion
factors would already carry rounding error before any computation.

**Q15. Does the lexer know about units?**
No. `m/s^2` is `IDENT SLASH IDENT CARET INT`. Deciding that `m` is a unit is the parser's job (needs context) and checking it is the checker's job.

**Q16. Which lexical errors are reported?**
Illegal character (with hint for lone `&`/`|`), unterminated string, unterminated block comment, malformed number (`3.`), unknown escape.
All are collected in one run with line:column. [`run examples/err_lexical.lum`]

**Q17. Why do you stop after lexical errors instead of parsing?**
A damaged token stream only creates confusing follow-on syntax errors. Report the lexical ones alone.

---

## 4. Parser

**Q18. What parsing technique and why?**
Recursive descent (top-down, predictive): one method per grammar rule. Easy to read, easy to produce good error messages, and our grammar is LL(1)
plus two small context rules.

**Q19. How do you get operator precedence and associativity?**
Precedence comes from layering: `expr → logicOr → logicAnd → equality → comparison → term → factor → unary → power → primary`; tighter operators are lower
in the chain. Left associativity comes from writing each level as a loop (`while next is + or -`), not as left recursion, which a top-down parser cannot handle.

**Q20. Is the grammar LL(1)?**
Almost. One token of lookahead decides every rule except the statement starting with IDENT, where we peek a second token (`=` means assignment).
The unit syntax adds two context rules (below).

**Q21. TRAP — "`12 km/h`: is `/` division or a unit?" How do you decide?**
Rule 1: a name directly after a number starts a unit literal (no other construct puts a name there). Rule 2: inside a unit literal, `*` or `/` continues
the unit only if the next name is a **known unit**. So `10 m / t` with variable `t` is `(10 m) / t`, and `9.8 m/s^2` is one literal. To divide by a variable that has a unit's name: `(10 m) / s`.

**Q22. Left recursion — what is it and how did you avoid it?**
`term → term + factor` would make a recursive-descent function call itself forever. We rewrite as `term → factor { (+|-) factor }` and build the left-leaning tree in the loop.

**Q23. How does error recovery work?**
Panic mode: after a syntax error record it, then skip tokens to a safe point — just after a `;` at brace depth 0, a `}` that closes the current block, or the start of the next statement.
Braces opened while skipping are skipped whole, so a bad `if (...) { ... }` header does not make us lose the enclosing function. [`run examples/err_syntax.lum` reports 5 errors]

**Q24. Where is a "missing `;`" error reported?**
Right after the previous token (where you would type it), not at the next token on the following line. That is where editors expect the cursor.

**Q25. What does the AST contain versus the parse tree?**
Only meaning: `(2+3)*4` is `Binary(*, Binary(+,2,3), 4)`; parentheses and semicolons are gone. Each node records line, column and end column for underlining errors.

**Q26. FIRST and FOLLOW — give an example.**
FIRST(statement) = {let, if, while, return, print, `{`, IDENT, literals, `(`, `-`, `!`}. Because `let`, `if`, … are distinct keywords the parser chooses a statement rule by looking at one token.
FOLLOW(expr) contains `;`, `)`, `,` — that is why the parser stops an expression at those tokens.

---

## 5. Unit system and checker (the core)

**Q27. Define dimension, unit and scale.**
Dimension: what kind of quantity — a sparse vector of integer exponents over base units, e.g. speed = (m¹, s⁻¹). Unit: a dimension plus an exact scale to the base units: km = (length, 1000), h = (time, 3600).
Same dimension = convertible; different dimension = never.

**Q28. State the typing rules.**
`+ - < <= > >= == !=`: dimensions equal (scales may differ — the right operand is converted). `*`: dimensions add, scales multiply. `/`: subtract, divide. `^n`: multiply by n, scale to the n.
`x in U`: dimensions equal. Assignment/argument/return: dimension equal, scale auto-converted. See `docs/LANGUAGE.md` §4.

**Q29. Is the checker S-attributed or L-attributed?**
The type of a node is a synthesized attribute computed from its children's types bottom-up (post-order), so it is S-attributed. The symbol table (scopes) supplies the types of variables, which is the usual environment carried alongside.

**Q30. What is the "type" of an expression exactly?**
`(kind, dimension, scale)`: kind ∈ int, float, bool, string, void, error. Quantities are floats with a non-empty dimension. `factors` (a printable form like `km/h`) rides along only for messages.

**Q31. Why exact fractions for scale?**
Conversions must not drift. `unit lbf = 4.4482216152605 N` is stored exactly; km→m→km is exactly ×1. Rounding happens once, at the end, when we make the double used at run time.

**Q32. When are conversions inserted?**
Only where a type is *required*: `let`, assignment, function argument, `return`, and the operands of `+ - comparison`. We insert a `Convert(from_scale, to_scale)` node. It changes scale only, never dimension.

**Q33. What is the result unit of `1 km + 500 m`?**
The unit of the left operand: `1.5 km`. (`500 m + 1 km` is `1500.0 m`.) A documented, deterministic choice.

**Q34. Why can't I write `5 + 3 m`?**
A bare number has no unit, and Lumen refuses to guess one — guessing is exactly the Mars bug. Write `5 m + 3 m`. The only unit-less value accepted where a quantity is expected is the literal `0`.

**Q35. Why is literal `0` special?**
Zero of any unit is the same physical amount, and loops need `let t = 0 s;`, `if (d > 0)`. It cannot hide a conversion error because 0 × any factor is 0.

**Q36. What if units cancel? `2 km / 500 m`?**
Dimension becomes empty (a plain number) but the scale is 1000/1; the checker inserts a conversion by that scale so the result is the plain number `4`, not `0.004`.

**Q37. How do you handle `unit INR;` and money?**
A declaration with no value creates a new base dimension. INR and USD are different base dimensions, so `INR + USD` is a dimension error; you must multiply by a rate whose unit is `INR/USD`, which algebraically yields INR. [`run examples/currency.lum`]

**Q38. What does `sqrt` do with units?**
Halves every exponent; all must be even, otherwise a compile error. The argument is first converted to scale 1 (`sqrt(4 km^2) = 2000 m`).

**Q39. TRAP — "`^` with a variable exponent?"**
Not allowed: the unit of `x^n` depends on `n`, so `n` must be a compile-time integer literal. We say so in the error message.

**Q40. Why do dimensions "multiply by adding exponents"? Prove `N = kg·m/s²`.**
Exponent vector of kg·m/s² is (kg¹, m¹, s⁻²), which equals force from F = ma: mass¹ × acceleration (m¹s⁻²). `unit N = 1 kg*m/s^2` just names that vector with scale 1.

**Q41. What can't the checker catch? (Say this proactively.)**
(1) A human claiming the wrong unit. (2) Quantities of the same dimension but different meaning (torque vs energy, body-weight kg vs drug kg). (3) Offset units like °C. (4) Fractional exponents. (5) Unit-polymorphic functions.
We reject unit expressions that cancel to a plain number (like `mcg/kg`) and use `mcg/kg/min` in the dosing example.

**Q42. Why no temperature (°C, °F)?**
They are *affine* (have an offset): 20 °C + 20 °C ≠ 40 °C in any physical sense. A correct treatment needs affine types distinguishing points from differences — a planned extension, not a quick hack.

**Q43. How are error cascades prevented?**
A failed expression gets the special type `error`; any operation with an `error` operand returns `error` silently. One mistake, one message. [`test_no_cascade_after_error`]

**Q44. How do the helpful suggestions work?**
For a dimension mismatch the checker looks through variables in scope for one whose dimension combined with the offending expression gives the wanted dimension (a/b, a·b or b/a) and prints
"a speed is a length / time: try `race / t`". Unknown units use edit distance ("did you mean 'm'?") plus a spelling table (`meters`→`m`).

**Q45. What is the complexity of checking?**
Linear in the size of the program: one post-order walk; every unit lookup, dimension operation and scope lookup is O(1) (dimensions are tiny dictionaries; scope chain is shallow).

**Q46. What other semantic errors exist?**
Undefined/redeclared names, wrong argument count/type, missing return on some path (control-flow check), missing `main`, return value from void function, void call used as a value, constant division by zero,
non-bool condition, builtin redefinition. Warnings: unused variable, unreachable code, unused value.

**Q47. How do you check "every path returns"?**
`always_returns(stmt)`: a `return` does; a block does if any statement does; an `if` does if it has an `else` and both branches do; loops don't count. The function body must satisfy it.

---

## 6. Intermediate code

**Q48. What is three-address code?**
Each instruction has at most one operator and two operands plus a result: `t3 = t1 * t2`. Control flow uses labels and jumps. It is easy to optimize and to translate.

**Q49. How do you generate code for `&&` and `||`?**
Short-circuit with jumps: evaluate left into `t`; for `&&` `ifFalse t goto end`; else evaluate right into `t`. So `loud(0) && loud(1)` never calls the second function. [`examples/logic.lum`]

**Q50. How is `while` lowered?**
`L_top: cond; ifFalse cond goto L_end; body; goto L_top; L_end:`.

**Q51. Where do the units go in the IR?**
They are gone. A conversion is `t = a * 3.6` marked CONV with an exact Fraction factor; every other quantity is just a float. [`--ir`]

---

## 7. Optimizer

**Q52. Which optimizations do you implement?**
Constant folding, constant propagation, copy propagation, algebraic simplification (x+0, x*1), branch folding, unreachable-code removal, jump clean-up, dead-code elimination, and a unit-specific one:
**conversion fusion** (`x*a*b` → `x*(a·b)` using exact fractions). All run in rounds until nothing changes (fixed point). [`run examples/optimizer_demo.lum --stats`: 20 → 6 instructions]

**Q53. Show that units cost nothing at run time.**
`let v: km/h = 10 m/s; print(v);` becomes the single instruction `print 36.0 "km/h"`. The bytecode of unit programs contains no unit operations (a test checks the opcode set). [`run examples/zero_cost.lum --ir-opt`]

**Q54. How can you be sure the optimizer doesn't change behaviour?**
(1) The folder uses the same arithmetic functions as the VM (`ir.eval_binop`). (2) Knowledge is thrown away at every label (join point) and after jumps. (3) We never fold or delete an operation that can trap (division by zero).
(4) A differential test runs 21 example programs with and without the optimizer and requires identical output.

**Q55. TRAP — "Is conversion fusion exact? Floating point!"**
The fused factor is computed exactly (Fractions) and rounded once, so it is *more* accurate than two rounded multiplies. The result can differ in the last bit from the unfused code; we print 10 significant digits. A km→m→km round trip fuses to factor exactly 1 and disappears completely. [`tests::test_roundtrip_conversion_cancels`]

**Q56. What is a basic block? Why does it matter?**
A straight-line run of instructions with one entry (a label) and one exit (a jump). Local optimizations are safe inside it because we know exactly what runs in order. Our propagation environment is reset at every label.

**Q57. What is dead-code elimination here?**
Compute every name that is read anywhere in the function; delete pure instructions whose result is never read, repeat until stable (deleting one can make another dead).

**Q58. What would global optimization (dataflow) add?**
Propagating constants across branches and loops via iterative dataflow on the CFG, common-subexpression elimination, loop-invariant motion. Not needed for the demonstrated claims; listed as future work.

---

## 8. Code generation and VM

**Q59. Why a stack machine?**
Simplest to generate and explain: each operation pops its operands and pushes its result. `t3 = t1 * t2` → `LOAD t1; LOAD t2; MUL; STORE t3`.

**Q60. How do function calls work?**
`CALL name argc` pops the arguments, creates a **frame** (local slots, operand stack, instruction pointer) and pushes it on the VM's own frame list. `RET` pops the frame and pushes the result onto the caller's stack.
We do not use Python's call stack, so runaway recursion becomes a clean Lumen error ("call stack too deep") instead of a crash. [`examples/err_recursion.lum`]

**Q61. How are locals stored?**
Every variable and temporary is mapped to a numbered slot in the frame; parameters take the first slots.

**Q62. What runtime errors exist and how are they reported?**
Division by zero, sqrt of a negative, numeric overflow, call stack too deep, step limit exceeded (catches infinite loops). Each carries the source line: `file:3: runtime error: division by zero` plus the line text. Exit code 3.

**Q63. Is there any unit logic in the VM?**
None. Not one instruction. That is the "units are erased" guarantee.

**Q64. Integer semantics?**
`int/int` truncates toward zero and `%` takes the dividend's sign (like C). Python ints are unbounded, so there is no overflow. Floats are IEEE doubles.

---

## 9. Testing and quality

**Q65. How did you test?**
187 pytest tests: lexer (positions, errors), parser (precedence, associativity, unit literals, recovery), units, checker (every rule and every error class), optimizer, VM runtime errors, plus golden-output tests for all 34 examples
and a differential test (optimized vs unoptimized). [`python -m pytest`]

**Q66. What is a golden test?**
Run a program, compare stdout/stderr/exit code with a stored expected file. Any change in behaviour or message wording shows up as a failing test.

**Q67. Show me the error messages.**
[`run examples/err_units.lum` — six different unit errors with carets and help]

---

## 10. Design decisions the professor may challenge

**Q68. Why implicit conversion on assignment? Isn't that dangerous?**
It only ever changes *scale* between units of the *same dimension*, exactly, so it cannot hide a physical error — the Mars error was the *absence* of conversion. Dimension changes are never implicit.

**Q69. Why can a variable be named `m` or `g`?**
Physicists name variables `m`, `g`, `t`. A name is a unit only directly after a number or in a type/`in` position, so there's no ambiguity. The one pitfall (`10 m / s` with a variable `s`) is documented, and parentheses resolve it.

**Q70. Why integer-only exponents?**
The checker's dimension vectors are integer vectors; fractional ones would complicate scale arithmetic (irrational scales) for little gain. `sqrt` covers the common half-exponent case.

**Q71. Why are units declared with `unit` and not built in (`h`, `min`, `lbf`)?**
Only SI base units, grams and prefixes are built in. Everything else is in the program, explicit and auditable: you can see that `lbf = 4.4482216152605 N`. It also shows the compiler supports user-defined units.

**Q72. What would you add with more time?**
Offset units (°C), quantity *kinds*, unit-polymorphic functions, a typed file/JSON boundary (to fix the Mars gap), LLVM/x86 back end, a REPL, global dataflow optimizations, an IDE plugin showing inferred units.

**Q73. How is Lumen different from just writing comments like `// metres`?**
Comments are not checked. Lumen's units are part of the type: wrong units don't compile.

**Q74. Does the optimizer matter for correctness?**
No: `--no-opt` gives identical output; the optimizer is purely about speed and demonstrating the zero-cost claim.

---

## 11. Who did what (each of us also knows the rest)

* **Sanjay Suresh** — lexer, grammar, recursive-descent parser, error recovery, diagnostics rendering, CLI.
* **Sugesh Kumar** — unit algebra and unit table, unit/type checker, error catalogue and suggestions.
* **Noel Ninan** — IR generation, optimizer, bytecode generator, VM, test suite.

---

## 12. Live demo script (3 minutes)

1. `python -m lumen run examples/mars_bug.lum` → compile error with help text.
2. `python -m lumen run examples/mars_fixed.lum` → `55.60277019 N*s`.
3. `python -m lumen run examples/gimli_bug.lum` then `gimli_fixed.lum`.
4. `python -m lumen run examples/err_units.lum` → six unit errors at once.
5. `python -m lumen run examples/zero_cost.lum --ir` then `--ir-opt` → conversion folded to `36.0`.
6. `python -m lumen run examples/optimizer_demo.lum --stats` → 20 → 6 instructions.
7. `python -m lumen run examples/fib.lum --bytecode` → show the VM code; then `python -m pytest -q` → all green.

## 13. Numbers to remember

7 phases · ~3.4k lines · 187 tests · 34 examples · 21 differential tests · optimizer demo 20→6 instructions ·
Mars: ×4.45, $327.6M, 226 km planned vs ~57 km actual · Gimli: 1.77 lb/L vs 0.803 kg/L, 41,000 ft, ~17 min glide, 0 deaths.
