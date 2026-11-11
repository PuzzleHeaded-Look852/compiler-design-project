# What each phase does (with real output)

Everything below is real compiler output for `examples/phases_demo.lum`
(regenerate with `python tools/make_phases_doc.py`):

```
// The program used in docs/PHASES.md to show every phase's output.
unit h = 3600 s;

fn main() {
    let d = 90 km;
    let t = 1.5 h;
    let v = d / t;
    print(v);
    print(v in m/s);
}
```

## Phase 1 — Lexer (`lexer.py`)
Reads characters, produces tokens with line:column. Longest match wins (`<=` is one token). Numbers keep
an exact `Fraction` value. The lexer does **not** decide what a unit is: `m/s^2` is just
`IDENT SLASH IDENT CARET INT`. First 16 of 46 tokens (`--tokens`):

```
  2:1   UNIT
  2:6   IDENT(h)
  2:8   ASSIGN
  2:10  INT(3600)
  2:15  IDENT(s)
  2:16  SEMI
  4:1   FN
  4:4   IDENT(main)
  4:8   LPAREN
  4:9   RPAREN
  4:11  LBRACE
  5:5   LET
  5:9   IDENT(d)
  5:11  ASSIGN
  5:13  INT(90)
  5:16  IDENT(km)
```

## Phase 2 — Parser (`parser.py`)
Recursive descent, one method per grammar rule, precedence from rule layering, left-associative loops.
Two context rules handle units: an identifier directly after a number starts a unit, and `/` or `*` keeps
extending the unit only if the next name is a *known* unit. `--ast` prints the tree **after** checking,
so each node shows its type (`: km/h`):

```
Program()
  UnitDecl(name='h', value=3600, units=s)
  FuncDecl(name='main')
    Block()
      Let(name='d')
        Num(value=90, is_float=False, units=km)  : km
      Let(name='t')
        Num(value=1.5, is_float=True, units=h)  : h
      Let(name='v')
        Binary(op='/')  : km/h
          Var(name='d')  : km
          Var(name='t')  : h
      Print(label='km/h')
        Var(name='v')  : km/h
      Print(label='m/s')
        Convert(from_scale=0.2777777777777778, to_scale=1)  : m/s
          Var(name='v')  : km/h
```

## Phase 3 — Unit and type checker (`semantic.py`, `units.py`)
Bottom-up, computes a type (kind, dimension, scale) for every node. `Binary(op='/') : km/h` is the dimension
algebra at work. Where scales differ the checker inserts `Convert` nodes (see the last `Print`); the factors
are exact fractions. The unit table (`--units`):

```
m        length                 = 1 x m
kg       mass                   = 1 x kg
s        time                   = 1 x s
bit      data                   = 1 x bit
g        mass                   = 0.001 x kg
h        time                   = 3600 x s
```

## Phase 4 — Three-address code (`irgen.py`)
Flat, one operation per line, temporaries `t1, t2...`. Units are gone; a conversion is a multiply (marked `; convert`).

```
func main():
    d = 90.0
    t = 1.5
    t1 = d / t
    v = t1
    print v "km/h"
    t2 = v * 0.2777777777777778   ; convert
    print t2 "m/s"
    return
```

## Phase 5 — Optimizer (`optimizer.py`)
Folding, propagation, conversion fusion, dead-code and branch elimination, repeated to a fixed point.

```
func main():
    print 60.0 "km/h"
    print 16.666666666666668 "m/s"
    return
```

## Phase 6 — Bytecode (`codegen.py`)
Stack machine; each variable/temporary gets a numbered local slot; jump targets are absolute addresses.
(Shown for the *optimized* program: two PUSH/PRINT pairs.)

```
== main  (0 params, 0 local slots)
  0000  PUSH   60.0
  0001  PRINT  "km/h"
  0002  PUSH   16.666666666666668
  0003  PRINT  "m/s"
  0004  RET
```

## Phase 7 — VM (`vm.py`) and result

```
60.0 km/h
16.66666667 m/s

--- statistics ---
instructions before optimization : 8
instructions after optimization  : 3
constants folded                 : 2
operands propagated              : 6
unit conversions fused           : 0
algebraic simplifications        : 0
branches folded                  : 0
unreachable instructions removed : 0
dead assignments removed         : 5
optimizer rounds                 : 2
bytecode instructions            : 5
VM steps executed                : 5
function calls                   : 1
max call depth                   : 1
```

