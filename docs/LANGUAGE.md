# Lumen language reference

## 1. Lexical rules
* Identifiers `[A-Za-z_][A-Za-z0-9_]*`; keywords: `fn let if else while return print true false unit in int float bool string`.
* Numbers: `42` (int), `3.14` and `1e-6` (float). A float needs digits on both sides of the dot (`3.` is an error). The lexer keeps the exact value as a fraction, so `0.1` is exactly 1/10.
* Strings `"..."` with escapes `\n \t \" \\`. Comments `// ...` and `/* ... */`.
* Operators `+ - * / % ^ == != < <= > >= && || ! = ->`, punctuation `( ) { } , ; :`.

## 2. Grammar (EBNF; `{ }` repeat, `[ ]` optional)

```
  program    = { unitDecl | function } EOF
  unitDecl   = "unit" IDENT ( ";" | "=" NUMBER unitExpr ";" )
  function   = "fn" IDENT "(" [ param { "," param } ] ")" [ "->" type ] block
  param      = IDENT ":" type
  type       = "int" | "float" | "bool" | "string" | unitExpr
  unitExpr   = unitFactor { ( "*" | "/" ) unitFactor }
  unitFactor = ( IDENT | "(" unitExpr ")" ) [ "^" [ "-" ] INT ]

  block      = "{" { statement } "}"
  statement  = let | assign | if | while | return | print | block | exprStmt
  let        = "let" IDENT [ ":" type ] [ "=" expr ] ";"
  assign     = IDENT "=" expr ";"
  if         = "if" "(" expr ")" block [ "else" ( if | block ) ]
  while      = "while" "(" expr ")" block
  return     = "return" [ expr ] ";"          print = "print" "(" expr ")" ";"

  expr       = logicOr [ "in" unitExpr ]            (* explicit unit conversion *)
  logicOr    = logicAnd { "||" logicAnd }
  logicAnd   = equality { "&&" equality }
  equality   = comparison { ( "==" | "!=" ) comparison }
  comparison = term { ( "<" | "<=" | ">" | ">=" ) term }
  term       = factor { ( "+" | "-" ) factor }
  factor     = unary { ( "*" | "/" | "%" ) unary }
  unary      = ( "-" | "!" ) unary | power
  power      = primary [ "^" [ "-" ] INT ]
  primary    = NUMBER [ unitLiteral ] | STRING | "true" | "false"
             | IDENT [ "(" [ expr { "," expr } ] ")" ] | "(" expr ")"
```

Precedence, high to low: `^` (binds tighter than unary minus: `-x^2` is `-(x^2)`) · unary `- !` · `* / %` · `+ -` · `< <= > >=` · `== !=` · `&&` · `||` · `in`.
All binary operators are left-associative. The grammar is LL(1) with two *context rules* for units:

1. **A name directly after a number is a unit** (`5 km`). No other construct puts a name there.
2. **A unit literal continues over `*` or `/` only if the next name is a known unit**:
   `9.8 m/s^2` is one literal, `10 m / t` (t a variable) is `(10 m) / t`.
   To divide a literal by a variable that shares a unit's name, use parentheses: `(10 m) / s`.

The one place that needs two tokens of lookahead is the statement `IDENT = ...` (assignment) versus an expression statement.

## 3. Units

* **Dimension** = what kind of quantity: an exponent vector over base units, e.g. speed = m¹·s⁻¹.
* **Unit** = a dimension + an exact **scale** (how many base units it equals): `km` = length, 1000.
* Base units: `m` (length), `kg` (mass), `s` (time), `bit` (data). Built-in `g` = 1/1000 kg.
* SI prefixes `n u m c k M G` attach to `m s g bit` (`km`, `mg`, `ms`, `ug`, `Mbit`...). Prefixes do not attach to anything else.
* `unit NAME = NUMBER unitExpr;` declares a unit as a multiple of existing ones. `unit NAME;` declares a **new base dimension** (`INR`, `USD`): it can never be added to or converted into another base unit, so currencies need an explicit rate with its own unit (`83.5 INR/USD`).
* A unit expression must have a dimension: `unit r = 1 m/m;` and the type `mcg/kg` (mass over mass) are rejected because they cancel to a plain number.

## 4. Typing rules

Notation: `e : (K, d, s)` means expression `e` has kind `K`, dimension `d`, scale `s`.

```
e1 : (float, d, s1)   e2 : (float, d, s2)
------------------------------------------------   (+, -, comparison: same dimension)
e1 + e2 : (float, d, s1)        e2 is converted by s2/s1

e1 : (float, d1, s1)  e2 : (float, d2, s2)
------------------------------------------   (* : dimensions add, scales multiply)
e1 * e2 : (float, d1+d2, s1*s2)

e1 / e2 : (float, d1-d2, s1/s2)             e ^ n : (float, n*d, s^n)      n an integer literal
```

* When a product or quotient has dimension `0` (everything cancelled) but scale `s != 1`, the checker inserts a conversion by `s`, so `2 km / 500 m` is the plain number `4`.
* **Implicit conversion happens only where a type is *required***: `let`, assignment, function argument, `return`, and between the operands of `+ - < <= > >= == !=`. It only ever changes the **scale**, never the dimension.
* `int` widens to `float`. `float` never narrows to `int` implicitly (`int(x)` truncates toward zero).
* A plain number is never a quantity: `5 + 3 m` and passing `5` to an `m` parameter are errors. The one exception is the literal `0`, which stands for zero of any unit (`let t = 0 s;`, `if (d > 0)`).
* `a + b` where the units differ in scale (km + m) has the unit of the **left** operand.
* `int / int` truncates toward zero (like C); `%` follows the dividend's sign and works on ints only.
* `sqrt(q)` needs every exponent of `q`'s dimension to be even (`sqrt(9 m^2) = 3 m`).
* Built-in functions: `sqrt abs minimum maximum float int`.

## 5. Declarations and scope

* Program = unit declarations and functions. Units are declared before use; functions may call each other in any order.
* `fn main()` (no parameters, no result) starts execution.
* Block scoping; an inner block may shadow an outer name; redeclaring in the same scope is an error.
* A variable may share a name with a unit (`let g = 9.81 m/s^2;`); a name directly after a number is still the unit.
* Every function with a result type must return on every path (checked by a simple control-flow analysis).
* `let x: T;` without initializer starts at zero (`0`, `0.0`, `0 <unit>`, `false`, `""`).

## 6. Diagnostics

`file:line:col: error: message`, the source line, a caret/underline, and `= help:` text. Several errors are reported per run. Warnings: unused variable (silence with a leading `_`), unreachable code, unused expression value.
