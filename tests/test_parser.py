from lumen import ast_nodes as A
from lumen.lexer import tokenize
from lumen.parser import parse


def parse_src(src):
    toks, d = tokenize(src)
    assert not d
    return parse(toks)


def expr(src):
    prog, d = parse_src("fn f() { let x = " + src + "; }")
    assert not d, d
    return prog.items[0].body.stmts[0].init


def test_precedence_mul_over_add():
    e = expr("1 + 2 * 3")
    assert e.op == "+" and e.right.op == "*"


def test_left_associativity():
    e = expr("10 - 4 - 3")
    assert e.op == "-" and e.left.op == "-"          # (10-4)-3


def test_parentheses():
    e = expr("(1 + 2) * 3")
    assert e.op == "*" and e.left.op == "+"


def test_logic_precedence():
    e = expr("a || b && c")
    assert e.op == "||" and e.right.op == "&&"


def test_unary_binds_tighter_than_binary():
    e = expr("-a * b")
    assert e.op == "*" and isinstance(e.left, A.Unary)


def test_power_with_integer_exponent():
    e = expr("t^2")
    assert e.op == "^" and e.right.value == 2
    e = expr("t^-1")
    assert e.right.value == -1


def test_unit_literal_simple():
    e = expr("5 km")
    assert isinstance(e, A.Num) and A.unit_text(e.units) == "km"


def test_unit_literal_compound():
    e = expr("9.8 m/s^2")
    assert [(f.name, f.exp) for f in e.units] == [("m", 1), ("s", -2)]


def test_unit_literal_product_and_quotient():
    e = expr("2 kg*m/s^2")
    assert [(f.name, f.exp) for f in e.units] == [("kg", 1), ("m", 1), ("s", -2)]


def test_division_by_variable_is_not_a_unit():
    e = expr("10 m / t")
    assert isinstance(e, A.Binary) and e.op == "/" and isinstance(e.right, A.Var)


def test_division_by_number_is_not_a_unit():
    e = expr("10 m / 2")
    assert isinstance(e, A.Binary) and e.op == "/"


def test_in_conversion_lowest_precedence():
    e = expr("d / t in km/h")
    assert isinstance(e, A.InConv) and isinstance(e.expr, A.Binary)


def test_unit_declaration():
    prog, d = parse_src("unit N = 1 kg*m/s^2; unit INR;")
    assert not d
    assert prog.items[0].value == 1 and prog.items[1].value is None


def test_type_with_units():
    prog, _ = parse_src("fn f(v: m/s, n: int) -> km { return 1 km; }")
    f = prog.items[0]
    assert f.params[0].tyref.kind == "unit" and f.params[1].tyref.kind == "int"
    assert A.unit_text(f.ret.units) == "km"


def test_else_if_chain():
    prog, d = parse_src("fn f() { if (a) { } else if (b) { } else { } }")
    assert not d
    s = prog.items[0].body.stmts[0]
    assert isinstance(s.other, A.If) and isinstance(s.other.other, A.Block)


def test_missing_semicolon_points_after_previous_token():
    toks, _ = tokenize("fn f() {\n let a = 5\n let b = 6; }")
    _, d = parse(toks)
    assert d[0].line == 2 and "expected ';'" in d[0].message


def test_recovery_reports_several_errors():
    src = "fn f() {\n let a = ;\n let b = (1;\n print(1);\n}"
    toks, _ = tokenize(src)
    _, d = parse(toks)
    assert len(d) == 2 and d[0].line == 2 and d[1].line == 3


def test_assignment_in_condition_hint():
    toks, _ = tokenize("fn f() { if (a = 1) { } }")
    _, d = parse(toks)
    assert "==" in d[0].help


def test_unclosed_brace():
    toks, _ = tokenize("fn f() { let a = 1;")
    _, d = parse(toks)
    assert any("missing '}'" in x.message for x in d)


def test_nested_declaration_rejected():
    toks, _ = tokenize("fn f() { fn g() { } }")
    _, d = parse(toks)
    assert "top level" in d[0].message
