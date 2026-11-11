from lumen.lexer import tokenize
from lumen.tokens import T


def kinds(src):
    toks, d = tokenize(src)
    return [t.type for t in toks][:-1], d


def test_keywords_and_identifiers():
    k, d = kinds("fn let letter while")
    assert k == [T.FN, T.LET, T.IDENT, T.WHILE] and not d


def test_numbers_are_exact():
    toks, _ = tokenize("0.1 42 1e-3")
    assert [t.type for t in toks[:3]] == [T.FLOAT, T.INT, T.FLOAT]
    from fractions import Fraction
    assert toks[0].value == Fraction(1, 10) and toks[2].value == Fraction(1, 1000)


def test_longest_match_operators():
    k, _ = kinds("<= < == = != ! && || ->")
    assert k == [T.LE, T.LT, T.EQ, T.ASSIGN, T.NE, T.NOT, T.AND, T.OR, T.ARROW]


def test_unit_expression_tokens():
    k, _ = kinds("9.8 m/s^2")
    assert k == [T.FLOAT, T.IDENT, T.SLASH, T.IDENT, T.CARET, T.INT]


def test_comments_skipped():
    k, d = kinds("1 // line\n/* block\n over lines */ 2")
    assert k == [T.INT, T.INT] and not d


def test_positions():
    toks, _ = tokenize("let x\n  = 5;")
    assert (toks[0].line, toks[0].col) == (1, 1)
    assert (toks[2].line, toks[2].col) == (2, 3)


def test_string_escapes():
    toks, d = tokenize(r'"a\n\"b"')
    assert toks[0].value == 'a\n"b' and not d


def test_illegal_character():
    _, d = tokenize("let a = 5 @ 3;")
    assert len(d) == 1 and "unexpected character '@'" in d[0].message and d[0].col == 11


def test_single_ampersand_hint():
    _, d = tokenize("a & b")
    assert "&&" in d[0].help


def test_unterminated_string_and_comment_reported_together():
    _, d = tokenize('"abc\n/* open')
    msgs = [x.message for x in d]
    assert "unterminated string" in msgs and "unterminated block comment" in msgs


def test_malformed_number():
    _, d = tokenize("3.")
    assert "malformed number" in d[0].message


def test_unknown_escape():
    _, d = tokenize(r'"\q"')
    assert "unknown escape" in d[0].message
