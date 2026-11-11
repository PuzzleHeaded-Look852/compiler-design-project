"""Phase 2: syntax analysis (a hand-written recursive-descent parser).

Each grammar rule is one method. The grammar (EBNF; { } repeat, [ ] optional):

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

Precedence comes from the layering: rules lower in the list bind tighter.
Binary operators are left-associative, written as loops (not left recursion),
which keeps the grammar LL(1): one token of lookahead picks the rule.

The two places that need more than a plain grammar (the "unit problem"):
  1. IS A NAME A UNIT?  In `9.8 m/s^2` the name `m` directly after a number is
     read as a unit. No other construct puts a name right after a number.
  2. IS `/` DIVIDE OR UNIT-PER?  In `12 km/h` the parser keeps extending the
     unit only if the name after `/` (or `*`) is a KNOWN unit. To divide a
     literal by a variable, use parentheses: `(12 km) / h`.

Error recovery: a syntax error is recorded, then the parser skips ahead to the
next `;` or `}` (panic mode) and continues, so one run reports several errors.
"""

from __future__ import annotations

from fractions import Fraction

from . import ast_nodes as A
from .errors import Diagnostic
from .tokens import T, Token, describe
from .units import UnitTable, closest


class ParseError(Exception):
    def __init__(self, diag: Diagnostic):
        super().__init__(diag.message)
        self.diag = diag


TYPE_KEYWORDS = {T.KW_INT: "int", T.KW_FLOAT: "float", T.KW_BOOL: "bool",
                 T.KW_STRING: "string"}
STATEMENT_STARTS = {T.LET, T.IF, T.WHILE, T.RETURN, T.PRINT, T.FN, T.UNIT}


class Parser:
    def __init__(self, tokens: list[Token]):
        self.toks = tokens
        self.i = 0
        self.diags: list[Diagnostic] = []
        self.builtin_units = UnitTable()
        self.declared_units: set[str] = set()

    # ---- token helpers ---------------------------------------------------
    @property
    def cur(self) -> Token:
        return self.toks[self.i]

    def peek(self, n: int = 1) -> Token:
        return self.toks[min(self.i + n, len(self.toks) - 1)]

    def prev(self) -> Token:
        return self.toks[max(self.i - 1, 0)]

    def next(self) -> Token:
        tok = self.toks[self.i]
        if tok.type != T.EOF:
            self.i += 1
        return tok

    def at(self, *types: T) -> bool:
        return self.cur.type in types

    def match(self, *types: T) -> Token | None:
        if self.cur.type in types:
            return self.next()
        return None

    def fin(self, node):
        """Record where `node` ends (the end of the token just consumed)."""
        p = self.prev()
        node.end_line, node.end_col = p.line, p.end_col
        return node

    def cond_close(self, what: str):
        """`)` after an if/while condition, with a friendly hint for `if (x = 5)`."""
        if self.at(T.ASSIGN):
            raise self.error_at(self.cur, "'=' is assignment, not comparison",
                                "use '==' to test for equality")
        self.expect(T.RPAREN, ")", f"after the {what} condition")

    def error_at(self, tok: Token, msg: str, help: str | None = None) -> ParseError:
        return ParseError(Diagnostic("error", msg, tok.line, tok.col,
                                     max(len(tok.lexeme), 1), help, "parser"))

    def error_after_prev(self, msg: str, help: str | None = None) -> ParseError:
        p = self.prev()
        return ParseError(Diagnostic("error", msg, p.line, p.end_col, 1, help, "parser"))

    def expect(self, tt: T, text: str, after: str = "", help: str | None = None) -> Token:
        """Consume a token of type `tt` or raise a located ParseError."""
        if self.cur.type == tt:
            return self.next()
        msg = f"expected '{text}'" + (f" {after}" if after else "")
        if tt in (T.SEMI, T.RPAREN, T.RBRACE, T.RBRACE):
            # the missing token belongs right after the previous one
            if self.cur.type != T.EOF or tt != T.RBRACE:
                raise self.error_after_prev(msg + f", found {describe(self.cur)}", help)
        raise self.error_at(self.cur, msg + f", found {describe(self.cur)}", help)

    def is_known_unit(self, name: str) -> bool:
        return name in self.declared_units or self.builtin_units.lookup(name) is not None

    # ---- error recovery ----------------------------------------------------
    def sync_statement(self):
        """Panic mode: skip tokens until a safe place to resume.

        Safe = just after a ';' at brace depth 0, or at a '}' that closes the
        current block, or at the start of the next statement. Braces opened
        while skipping are skipped as a whole, so one bad `if (...) { ... }`
        header does not make the parser lose track of the enclosing function."""
        depth = 0
        while not self.at(T.EOF):
            t = self.cur.type
            if t == T.LBRACE:
                depth += 1
            elif t == T.RBRACE:
                if depth == 0:
                    return
                depth -= 1
            elif depth == 0 and t == T.SEMI:
                self.next()
                return
            elif depth == 0 and t in STATEMENT_STARTS:
                return
            self.next()

    def sync_toplevel(self):
        while not self.at(T.EOF) and not self.at(T.FN, T.UNIT):
            self.next()

    # ---- program and declarations -----------------------------------------
    def parse_program(self) -> A.Program:
        first = self.cur
        items: list[A.Node] = []
        while not self.at(T.EOF):
            start = self.i
            try:
                if self.at(T.UNIT):
                    items.append(self.unit_decl())
                elif self.at(T.FN):
                    items.append(self.function())
                else:
                    raise self.error_at(
                        self.cur,
                        f"expected 'fn' or 'unit' at the top level, found {describe(self.cur)}",
                        "a Lumen program is a list of unit declarations and functions")
            except ParseError as e:
                self.diags.append(e.diag)
                if self.i == start:
                    self.next()
                self.sync_toplevel()
        return A.Program(items, line=first.line, col=first.col)

    def unit_decl(self) -> A.UnitDecl:
        kw = self.next()
        name_tok = self.expect(T.IDENT, "unit name", "after 'unit'")
        if self.match(T.SEMI):
            self.declared_units.add(name_tok.lexeme)
            return A.UnitDecl(name_tok.lexeme, None, [], line=name_tok.line, col=name_tok.col)
        self.expect(T.ASSIGN, "=", "or ';' after the unit name",
                    "write `unit km = 1000 m;` or `unit INR;` for a new base unit")
        if not self.at(T.INT, T.FLOAT):
            raise self.error_at(self.cur, f"expected a number after '=', found {describe(self.cur)}",
                                "a unit is defined as a number of another unit: `unit km = 1000 m;`")
        num = self.next()
        factors = self.unit_expr()
        self.expect(T.SEMI, ";", "after the unit declaration")
        self.declared_units.add(name_tok.lexeme)
        return A.UnitDecl(name_tok.lexeme, num.value, factors, line=name_tok.line, col=name_tok.col)

    def function(self) -> A.FuncDecl:
        self.next()  # fn
        name = self.expect(T.IDENT, "function name", "after 'fn'")
        self.expect(T.LPAREN, "(", "after the function name")
        params: list[A.Param] = []
        if not self.at(T.RPAREN):
            while True:
                p = self.expect(T.IDENT, "parameter name")
                self.expect(T.COLON, ":", "after the parameter name",
                            "every parameter needs a type, e.g. `d: m`")
                params.append(A.Param(p.lexeme, self.parse_type(), line=p.line, col=p.col))
                if not self.match(T.COMMA):
                    break
        self.expect(T.RPAREN, ")", "after the parameters")
        ret = None
        if self.match(T.ARROW):
            ret = self.parse_type()
        body = self.block()
        return A.FuncDecl(name.lexeme, params, ret, body, line=name.line, col=name.col)

    # ---- types and unit expressions ----------------------------------------
    def parse_type(self) -> A.TypeRef:
        tok = self.cur
        if tok.type in TYPE_KEYWORDS:
            self.next()
            return A.TypeRef(TYPE_KEYWORDS[tok.type], [], line=tok.line, col=tok.col)
        if tok.type in (T.IDENT, T.LPAREN):
            return A.TypeRef("unit", self.unit_expr(), line=tok.line, col=tok.col)
        raise self.error_at(tok, f"expected a type, found {describe(tok)}",
                            "a type is int, float, bool, string, or a unit such as m or km/h")

    def unit_expr(self) -> list[A.UnitFactor]:
        """unitFactor { ('*' | '/') unitFactor }, used in types, `unit` and `in`."""
        factors = self.unit_factor(1)
        while self.at(T.STAR, T.SLASH):
            sign = 1 if self.next().type == T.STAR else -1
            factors += self.unit_factor(sign)
        return factors

    def unit_factor(self, sign: int) -> list[A.UnitFactor]:
        tok = self.cur
        if self.match(T.LPAREN):
            inner = self.unit_expr()
            self.expect(T.RPAREN, ")", "to close the unit group")
            exp = self.unit_exponent()
            return [A.UnitFactor(f.name, f.exp * exp * sign, line=f.line, col=f.col)
                    for f in inner]
        if tok.type != T.IDENT:
            raise self.error_at(tok, f"expected a unit name, found {describe(tok)}")
        self.next()
        exp = self.unit_exponent()
        return [A.UnitFactor(tok.lexeme, exp * sign, line=tok.line, col=tok.col)]

    def unit_exponent(self) -> int:
        if not self.match(T.CARET):
            return 1
        neg = self.match(T.MINUS) is not None
        if not self.at(T.INT):
            raise self.error_at(self.cur, f"expected an integer exponent, found {describe(self.cur)}",
                                "Lumen exponents are whole numbers, e.g. s^2 or s^-1")
        n = int(self.next().value)
        return -n if neg else n

    def unit_literal(self) -> list[A.UnitFactor]:
        """The unit right after a number: `m`, `km/h`, `m/s^2`, `kg*m/s^2`."""
        factors = self.unit_factor_simple(1)
        while (self.at(T.STAR, T.SLASH) and self.peek().type == T.IDENT
               and self.is_known_unit(self.peek().lexeme)):
            sign = 1 if self.next().type == T.STAR else -1
            factors += self.unit_factor_simple(sign)
        return factors

    def unit_factor_simple(self, sign: int) -> list[A.UnitFactor]:
        tok = self.next()          # an IDENT
        exp = self.unit_exponent()
        return [A.UnitFactor(tok.lexeme, exp * sign, line=tok.line, col=tok.col)]

    # ---- statements ---------------------------------------------------------
    def block(self) -> A.Block:
        lb = self.expect(T.LBRACE, "{", "to start the block")
        stmts: list[A.Stmt] = []
        while not self.at(T.RBRACE, T.EOF):
            start = self.i
            try:
                stmts.append(self.statement())
            except ParseError as e:
                self.diags.append(e.diag)
                if self.i == start:
                    self.next()
                self.sync_statement()
        if self.at(T.EOF):
            raise ParseError(Diagnostic("error", "missing '}' before end of file",
                                        lb.line, lb.col, 1,
                                        "this '{' is never closed", "parser"))
        self.next()
        return A.Block(stmts, line=lb.line, col=lb.col)

    def statement(self) -> A.Stmt:
        t = self.cur
        if t.type == T.LET:
            return self.let_stmt()
        if t.type == T.IF:
            return self.if_stmt()
        if t.type == T.WHILE:
            return self.while_stmt()
        if t.type == T.RETURN:
            self.next()
            value = None if self.at(T.SEMI) else self.expr()
            self.expect(T.SEMI, ";", "after 'return'")
            return A.Return(value, line=t.line, col=t.col)
        if t.type == T.PRINT:
            self.next()
            self.expect(T.LPAREN, "(", "after 'print'")
            value = self.expr()
            self.expect(T.RPAREN, ")", "after the printed value")
            self.expect(T.SEMI, ";", "after print(...)")
            return A.Print(value, line=t.line, col=t.col)
        if t.type == T.LBRACE:
            return self.block()
        if t.type == T.IDENT and self.peek().type == T.ASSIGN:
            self.next()
            self.next()
            value = self.expr()
            self.expect(T.SEMI, ";", "after the assignment")
            return A.Assign(t.lexeme, value, line=t.line, col=t.col)
        if t.type in (T.FN, T.UNIT):
            raise self.error_at(t, f"'{t.lexeme}' declarations must be at the top level, "
                                   "not inside a function",
                                "move it outside the function braces")
        e = self.expr()
        self.expect(T.SEMI, ";", "after the expression")
        return A.ExprStmt(e, line=t.line, col=t.col)

    def let_stmt(self) -> A.Let:
        kw = self.next()
        name = self.expect(T.IDENT, "variable name", "after 'let'")
        tyref = None
        if self.match(T.COLON):
            tyref = self.parse_type()
        init = None
        if self.match(T.ASSIGN):
            init = self.expr()
        self.expect(T.SEMI, ";", "after the declaration")
        return A.Let(name.lexeme, tyref, init, line=name.line, col=name.col)

    def if_stmt(self) -> A.If:
        kw = self.next()
        self.expect(T.LPAREN, "(", "after 'if'")
        cond = self.expr()
        self.cond_close("if")
        then = self.block()
        other = None
        if self.match(T.ELSE):
            other = self.if_stmt() if self.at(T.IF) else self.block()
        return A.If(cond, then, other, line=kw.line, col=kw.col)

    def while_stmt(self) -> A.While:
        kw = self.next()
        self.expect(T.LPAREN, "(", "after 'while'")
        cond = self.expr()
        self.cond_close("while")
        return A.While(cond, self.block(), line=kw.line, col=kw.col)

    # ---- expressions (one method per precedence level) ---------------------
    def expr(self) -> A.Expr:
        e = self.logic_or()
        if self.at(T.IN):
            kw = self.next()
            e = self.fin(A.InConv(e, self.unit_expr(), line=kw.line, col=kw.col))
        return e

    def binary_level(self, sub, *ops: T) -> A.Expr:
        left = sub()
        while self.cur.type in ops:
            op = self.next()
            right = sub()
            left = self.fin(A.Binary(op.lexeme, left, right, line=op.line, col=op.col))
        return left

    def logic_or(self):
        return self.binary_level(self.logic_and, T.OR)

    def logic_and(self):
        return self.binary_level(self.equality, T.AND)

    def equality(self):
        return self.binary_level(self.comparison, T.EQ, T.NE)

    def comparison(self):
        return self.binary_level(self.term, T.LT, T.LE, T.GT, T.GE)

    def term(self):
        return self.binary_level(self.factor, T.PLUS, T.MINUS)

    def factor(self):
        return self.binary_level(self.unary, T.STAR, T.SLASH, T.PERCENT)

    def unary(self) -> A.Expr:
        if self.at(T.MINUS, T.NOT):
            op = self.next()
            return self.fin(A.Unary(op.lexeme, self.unary(), line=op.line, col=op.col))
        return self.power()

    def power(self) -> A.Expr:
        base = self.primary()
        if self.at(T.CARET):
            op = self.next()
            neg = self.match(T.MINUS) is not None
            if not self.at(T.INT):
                raise self.error_at(self.cur, "the exponent after '^' must be a whole-number literal",
                                    "write x^2 or x^-1; Lumen cannot raise to a variable power "
                                    "because the unit of the result would be unknown")
            n = int(self.next().value)
            exp = A.Num(Fraction(-n if neg else n), False, None, line=op.line, col=op.col)
            return self.fin(A.Binary("^", base, exp, line=op.line, col=op.col))
        return base

    def primary(self) -> A.Expr:
        t = self.cur
        if t.type in (T.INT, T.FLOAT):
            self.next()
            units = None
            if self.at(T.IDENT):                    # a name right after a number is a unit
                units = self.unit_literal()
            return self.fin(A.Num(t.value, t.type == T.FLOAT, units, line=t.line, col=t.col))
        if t.type == T.STRING:
            self.next()
            return self.fin(A.StrLit(t.value, line=t.line, col=t.col))
        if t.type in (T.TRUE, T.FALSE):
            self.next()
            return self.fin(A.BoolLit(t.type == T.TRUE, line=t.line, col=t.col))
        if t.type in (T.KW_INT, T.KW_FLOAT) and self.peek().type == T.LPAREN:
            self.next()                 # the conversion functions int(x) / float(x)
            self.next()
            arg = self.expr()
            self.expect(T.RPAREN, ")", "after the argument")
            return self.fin(A.Call(t.lexeme, [arg], line=t.line, col=t.col))
        if t.type == T.IDENT:
            self.next()
            if self.match(T.LPAREN):
                args: list[A.Expr] = []
                if not self.at(T.RPAREN):
                    while True:
                        args.append(self.expr())
                        if not self.match(T.COMMA):
                            break
                self.expect(T.RPAREN, ")", "after the arguments")
                return self.fin(A.Call(t.lexeme, args, line=t.line, col=t.col))
            return self.fin(A.Var(t.lexeme, line=t.line, col=t.col))
        if t.type == T.LPAREN:
            self.next()
            e = self.expr()
            self.expect(T.RPAREN, ")", "to close the parenthesis")
            return e
        raise self.error_at(t, f"expected an expression, found {describe(t)}")


def parse(tokens: list[Token]) -> tuple[A.Program, list[Diagnostic]]:
    p = Parser(tokens)
    prog = p.parse_program()
    return prog, p.diags
