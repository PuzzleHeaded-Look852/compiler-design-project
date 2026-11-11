"""Tokens: the "words" of the Lumen language.

The lexer turns source text into a list of Token objects. Each token records
its kind, the exact text (lexeme), a value for literals, and where it was
found (line and column, both starting at 1) so later phases can point at it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from fractions import Fraction
from typing import Any


class T(Enum):
    # literals and names
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    IDENT = auto()
    # keywords
    FN = auto()
    LET = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    RETURN = auto()
    PRINT = auto()
    TRUE = auto()
    FALSE = auto()
    UNIT = auto()
    IN = auto()
    KW_INT = auto()
    KW_FLOAT = auto()
    KW_BOOL = auto()
    KW_STRING = auto()
    # operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    CARET = auto()
    EQ = auto()          # ==
    NE = auto()          # !=
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    AND = auto()         # &&
    OR = auto()          # ||
    NOT = auto()         # !
    ASSIGN = auto()      # =
    # delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    SEMI = auto()
    COLON = auto()
    ARROW = auto()       # ->
    EOF = auto()


KEYWORDS = {
    "fn": T.FN, "let": T.LET, "if": T.IF, "else": T.ELSE, "while": T.WHILE,
    "return": T.RETURN, "print": T.PRINT, "true": T.TRUE, "false": T.FALSE,
    "unit": T.UNIT, "in": T.IN,
    "int": T.KW_INT, "float": T.KW_FLOAT, "bool": T.KW_BOOL, "string": T.KW_STRING,
}

# Two-character operators are tried before one-character ones (longest match).
TWO_CHAR = {
    "==": T.EQ, "!=": T.NE, "<=": T.LE, ">=": T.GE,
    "&&": T.AND, "||": T.OR, "->": T.ARROW,
}
ONE_CHAR = {
    "+": T.PLUS, "-": T.MINUS, "*": T.STAR, "/": T.SLASH, "%": T.PERCENT,
    "^": T.CARET, "<": T.LT, ">": T.GT, "!": T.NOT, "=": T.ASSIGN,
    "(": T.LPAREN, ")": T.RPAREN, "{": T.LBRACE, "}": T.RBRACE,
    ",": T.COMMA, ";": T.SEMI, ":": T.COLON,
}


@dataclass
class Token:
    type: T
    lexeme: str
    line: int
    col: int
    value: Any = None     # Fraction for numbers, str for strings

    @property
    def end_col(self) -> int:
        return self.col + max(len(self.lexeme), 1)

    def __str__(self) -> str:
        if self.type in (T.INT, T.FLOAT):
            return f"{self.type.name}({self.lexeme})"
        if self.type in (T.IDENT, T.STRING):
            return f"{self.type.name}({self.lexeme})"
        return self.type.name


def describe(tok: Token) -> str:
    """Human wording for a token in error messages."""
    if tok.type == T.EOF:
        return "end of file"
    return f"'{tok.lexeme}'"


__all__ = ["T", "Token", "KEYWORDS", "TWO_CHAR", "ONE_CHAR", "describe", "Fraction"]
