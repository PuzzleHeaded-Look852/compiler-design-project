"""Phase 1: lexical analysis.

Reads the source one character at a time and groups characters into tokens.
It is a hand-written scanner (effectively a hand-coded finite automaton):

  * whitespace and comments (// and /* */) are skipped,
  * the LONGEST valid token wins, so `<=` is one token, not `<` then `=`,
  * identifiers are looked up in the keyword table,
  * numbers keep their exact value as a Fraction (so 0.1 is exactly 1/10),
  * every token remembers its line and column.

Lexical errors (illegal character, unterminated string, ...) do not stop the
scan: they are recorded and the lexer carries on, so one run reports them all.

Note that the lexer does NOT decide whether a name is a unit. In `9.8 m/s^2`
it just produces FLOAT, IDENT(m), SLASH, IDENT(s), CARET, INT. The parser
decides that a name right after a number starts a unit.
"""

from __future__ import annotations

from fractions import Fraction

from .errors import Diagnostic
from .tokens import KEYWORDS, ONE_CHAR, T, TWO_CHAR, Token

ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}


class Lexer:
    def __init__(self, source: str):
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []
        self.diags: list[Diagnostic] = []

    # ---- low-level helpers -------------------------------------------------
    def peek(self, offset: int = 0) -> str:
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def error(self, msg: str, line: int, col: int, length: int = 1, help: str | None = None):
        self.diags.append(Diagnostic("error", msg, line, col, length, help, "lexer"))

    # ---- main loop ---------------------------------------------------------
    def tokenize(self) -> tuple[list[Token], list[Diagnostic]]:
        while self.pos < len(self.src):
            ch = self.peek()
            if ch in " \t\r\n":
                self.advance()
            elif ch == "/" and self.peek(1) == "/":
                self.skip_line_comment()
            elif ch == "/" and self.peek(1) == "*":
                self.skip_block_comment()
            elif ch.isdigit():
                self.read_number()
            elif ch.isalpha() or ch == "_":
                self.read_word()
            elif ch == '"':
                self.read_string()
            else:
                self.read_operator()
        self.tokens.append(Token(T.EOF, "", self.line, self.col))
        return self.tokens, self.diags

    # ---- comments ----------------------------------------------------------
    def skip_line_comment(self):
        while self.pos < len(self.src) and self.peek() != "\n":
            self.advance()

    def skip_block_comment(self):
        line, col = self.line, self.col
        self.advance()
        self.advance()
        while self.pos < len(self.src):
            if self.peek() == "*" and self.peek(1) == "/":
                self.advance()
                self.advance()
                return
            self.advance()
        self.error("unterminated block comment", line, col, 2,
                   "close the comment with */")

    # ---- words and numbers -------------------------------------------------
    def read_word(self):
        line, col = self.line, self.col
        start = self.pos
        while self.peek().isalnum() or self.peek() == "_":
            self.advance()
        text = self.src[start:self.pos]
        self.tokens.append(Token(KEYWORDS.get(text, T.IDENT), text, line, col))

    def read_number(self):
        line, col = self.line, self.col
        start = self.pos
        is_float = False
        while self.peek().isdigit():
            self.advance()
        if self.peek() == ".":
            if self.peek(1).isdigit():
                is_float = True
                self.advance()
                while self.peek().isdigit():
                    self.advance()
            else:
                # `5.` or `5.x`: a float needs digits on both sides of the dot
                self.advance()
                text = self.src[start:self.pos]
                self.error(f"malformed number '{text}'", line, col, len(text),
                           "write digits after the decimal point, e.g. 5.0")
                return
        # optional exponent, e.g. 1e-6 (only if digits really follow)
        if self.peek() in ("e", "E"):
            k = 1
            if self.peek(1) in ("+", "-"):
                k = 2
            if self.peek(k).isdigit():
                is_float = True
                for _ in range(k):
                    self.advance()
                while self.peek().isdigit():
                    self.advance()
        text = self.src[start:self.pos]
        self.tokens.append(Token(T.FLOAT if is_float else T.INT, text, line, col,
                                 Fraction(text)))

    # ---- strings -----------------------------------------------------------
    def read_string(self):
        line, col = self.line, self.col
        self.advance()  # opening quote
        chars: list[str] = []
        while True:
            ch = self.peek()
            if ch == "" or ch == "\n":
                self.error("unterminated string", line, col, 1,
                           'add a closing " before the end of the line')
                return
            if ch == '"':
                self.advance()
                break
            if ch == "\\":
                e_line, e_col = self.line, self.col
                self.advance()
                esc = self.peek()
                if esc in ESCAPES:
                    chars.append(ESCAPES[esc])
                    self.advance()
                else:
                    self.error(f"unknown escape '\\{esc}'", e_line, e_col, 2,
                               "valid escapes are \\n \\t \\\" \\\\")
                    if esc and esc != "\n":
                        self.advance()
                continue
            chars.append(self.advance())
        text = "".join(chars)
        self.tokens.append(Token(T.STRING, '"' + text + '"', line, col, text))

    # ---- operators and delimiters -----------------------------------------
    def read_operator(self):
        line, col = self.line, self.col
        two = self.peek() + self.peek(1)
        if two in TWO_CHAR:
            self.advance()
            self.advance()
            self.tokens.append(Token(TWO_CHAR[two], two, line, col))
            return
        ch = self.peek()
        if ch in ONE_CHAR:
            self.advance()
            self.tokens.append(Token(ONE_CHAR[ch], ch, line, col))
            return
        self.advance()
        help = None
        if ch == "&":
            help = "did you mean '&&' (logical and)?"
        elif ch == "|":
            help = "did you mean '||' (logical or)?"
        self.error(f"unexpected character '{ch}'", line, col, 1, help)


def tokenize(source: str) -> tuple[list[Token], list[Diagnostic]]:
    return Lexer(source).tokenize()
