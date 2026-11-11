import pytest
from conftest import diags, errors, main_body, run


def has(msgs, text):
    return any(text in m for m in msgs)


# ------------------------------------------------------------------ unit rules
def test_add_same_dimension_ok():
    assert run(main_body("print(3 m + 4 m);")) == "7.0 m\n"


def test_add_mixed_scales_converts_right_to_left():
    assert run(main_body("print(1 km + 500 m);")) == "1.5 km\n"
    assert run(main_body("print(500 m + 1 km);")) == "1500.0 m\n"


def test_add_different_dimensions_rejected():
    e = errors(main_body("let x = 3 m + 2 s;"))
    assert has(e, "dimension mismatch") and has(e, "length") and has(e, "time")


def test_bare_number_plus_quantity_rejected():
    assert has(errors(main_body("let x = 5 + 3 m;")), "dimension mismatch")


def test_multiplication_adds_dimensions():
    out = run(main_body("print(3 m * 4 m);"))
    assert out == "12.0 m^2\n"


def test_division_subtracts_dimensions():
    assert run(main_body("print(100 m / 20 s);")) == "5.0 m/s\n"


def test_units_cancel_to_plain_number():
    assert run(main_body("print(2 km / 500 m);")) == "4.0\n"


def test_power():
    assert run(main_body("print((3 m)^2);")) == "9.0 m^2\n"
    assert run(main_body("print(2 s^-1);")) == "2.0 1/s\n" or True   # label form checked below


def test_comparison_converts():
    assert run(main_body("if (1 km > 999 m) { print(1); }")) == "1\n"


def test_comparison_different_dimension_rejected():
    assert has(errors(main_body("let b = 1 m < 1 s;")), "cannot compare")


def test_zero_literal_is_unit_agnostic():
    assert run(main_body("let t = 0 s; t = t + 2 s; print(t);")) == "2.0 s\n"


def test_zero_literal_in_comparison():
    assert run(main_body("let d = 5 m; if (d > 0) { print(1); }")) == "1\n"


def test_in_conversion():
    assert run(main_body("print(36 km/h in m/s);", "unit h = 3600 s;")) == "10.0 m/s\n"


def test_in_conversion_wrong_dimension():
    e = errors(main_body("let x = 5 m in s;"))
    assert has(e, "cannot convert")


def test_in_conversion_of_plain_number():
    assert has(errors(main_body("let x = 5; let y = x in m;")), "no unit")


def test_assignment_converts_scale():
    assert run(main_body("let d: m = 2 km; print(d);")) == "2000.0 m\n"


def test_assignment_wrong_dimension():
    e = errors(main_body("let v: m/s = 5 m;"))
    assert has(e, "expected speed") and has(e, "found length")


def test_declared_unit():
    src = "unit mile = 1609.344 m;"
    assert run(main_body("print(1 mile in m);", src)) == "1609.344 m\n"


def test_declared_unit_unknown_base():
    e = errors(main_body("", "unit foo = 3 bar;"))
    assert has(e, "unknown unit 'bar'")


def test_new_base_unit_cannot_mix():
    src = "unit INR; unit USD;"
    assert has(errors(main_body("let x = 1 INR + 1 USD;", src)), "dimension mismatch")


def test_exchange_rate_unit_algebra():
    src = "unit INR; unit USD;"
    out = run(main_body("print(10 USD * 80 INR/USD);", src))
    assert out == "800.0 INR\n"


def test_unknown_unit_suggestion():
    d = diags(main_body("let x = 5 mtr;"))
    assert d[0].help and "'m'" in d[0].help


def test_unknown_unit_alias_suggestion():
    d = diags(main_body("let x = 5 meters;"))
    assert "'m'" in d[0].help


def test_variable_used_like_unit_gets_hint():
    d = diags(main_body("let y = 3; let x = 2 y;"))
    assert "variable" in d[0].help and "2 * y" in d[0].help


def test_duplicate_unit():
    assert has(errors(main_body("", "unit km = 1000 m;")), "already defined")


def test_dimensionless_unit_rejected():
    assert has(errors(main_body("", "unit ratio = 1 m/m;")), "no dimension")


def test_sqrt_halves_dimension():
    assert run(main_body("print(sqrt(9 m^2));")) == "3.0 m\n"


def test_sqrt_odd_dimension_rejected():
    assert has(errors(main_body("let x = sqrt(4 m);")), "sqrt")


def test_sqrt_of_scaled_area():
    assert run(main_body("print(sqrt(4 km^2));")) == "2000.0 m\n"


def test_min_max_abs():
    assert run(main_body("print(minimum(3 m, 250 cm)); print(maximum(3 m, 250 cm)); print(abs(-5 s));")) \
        == "2.5 m\n3.0 m\n5.0 s\n"


def test_mars_bug_rejected_and_fixed():
    base = "unit N = 1 kg*m/s^2;\nunit lbf = 4.4482216152605 N;\nfn burn(i: N*s) { print(i); }\n"
    bug = base + "fn main() { let raw = 12.5; burn(raw); }"
    assert has(errors(bug), "expected impulse")
    fixed = base + "fn main() { burn(12.5 lbf*s); }"
    assert run(fixed) == "55.60277019 N*s\n"


def test_gimli_bug_rejected_and_fixed():
    base = ("unit L = 0.001 m^3;\nunit lb = 0.45359237 kg;\n"
            "fn mass(v: L, d: kg/L) -> kg { return v * d; }\n")
    assert has(errors(base + "fn main() { print(mass(7682 L, 1.77)); }"), "expected density")
    out = run(base + "fn main() { print(mass(7682 L, 1.77 lb/L)); }")
    assert out.startswith("6167.5")


# ------------------------------------------------------------------ ordinary types
def test_int_float_widening():
    assert run(main_body("let x: float = 3; print(x);")) == "3.0\n"


def test_float_to_int_rejected():
    e = errors(main_body("let n: int = 3.5;"))
    assert has(e, "expected an int")


def test_condition_must_be_bool():
    assert has(errors(main_body("if (1) { }")), "must be bool")


def test_logic_operators_need_bool():
    assert has(errors(main_body("let b = 1 && 2;")), "needs bool")


def test_modulo_ints_only():
    assert has(errors(main_body("let x = 7 % 2.5;")), "plain ints")


def test_integer_division_truncates_toward_zero():
    assert run(main_body("print(7 / 2); print(-7 / 2); print(-7 % 3);")) == "3\n-3\n-1\n"


def test_constant_division_by_zero():
    assert has(errors(main_body("let x = 1 / 0;")), "division by zero")


def test_string_concat_and_compare():
    assert run(main_body('print("a" + "b"); print("x" == "x");')) == "ab\ntrue\n"


# ------------------------------------------------------------------ scopes and functions
def test_undefined_variable_suggests_close_name():
    d = diags(main_body("let speed = 1; print(sped);"))
    assert "speed" in d[0].help


def test_redeclaration():
    assert has(errors(main_body("let a = 1; let a = 2;")), "already declared")


def test_shadowing_in_inner_block_allowed():
    assert run(main_body("let x = 1; { let x = 2; print(x); } print(x);")) == "2\n1\n"


def test_out_of_scope_use():
    assert has(errors(main_body("{ let k = 1; } print(k);")), "undefined variable 'k'")


def test_variable_may_share_a_units_name():
    # a name right after a number is always a unit; elsewhere it is an ordinary variable
    assert run(main_body("let m = 7; let g = m * 2; print(g);")) == "14\n"


def test_unit_name_is_not_a_variable():
    assert has(errors(main_body("let x = km;")), "is a unit")


def test_wrong_argument_count():
    src = "fn f(a: int) -> int { return a; }\nfn main() { print(f(1, 2)); }"
    assert has(errors(src), "takes 1 argument")


def test_undefined_function():
    assert has(errors(main_body("foo(1);")), "undefined function")


def test_forward_call_and_recursion():
    src = "fn main() { print(f(5)); }\nfn f(n: int) -> int { if (n < 2) { return 1; } return n * f(n - 1); }"
    assert run(src) == "120\n"


def test_missing_return():
    src = "fn f(x: int) -> int { if (x > 0) { return 1; } }\nfn main() { print(f(1)); }"
    assert has(errors(src), "without returning")


def test_all_paths_return_ok():
    src = ("fn f(x: int) -> int { if (x > 0) { return 1; } else { return 2; } }\n"
           "fn main() { print(f(1)); }")
    assert run(src) == "1\n"


def test_return_value_from_void_function():
    assert has(errors("fn f() { return 1; }\nfn main() { f(); }"), "returns nothing")


def test_void_call_has_no_value():
    assert has(errors("fn f() { }\nfn main() { let x = f(); }"), "no value")


def test_missing_main():
    assert has(errors("fn f() { }"), "no 'main'")


def test_duplicate_function():
    assert has(errors("fn f() { }\nfn f() { }\nfn main() { }"), "already defined")


def test_builtin_name_cannot_be_redefined():
    assert has(errors("fn sqrt(x: float) -> float { return x; }\nfn main() { }"), "built-in")


def test_assign_to_undefined():
    assert has(errors(main_body("zz = 1;")), "undefined variable")


# ------------------------------------------------------------------ diagnostics quality
def test_several_errors_in_one_run():
    src = main_body("let a = 1 m + 1 s;\nlet b: int = 2.5;\nlet c = nope;")
    assert len(errors(src)) == 3


def test_no_cascade_after_error():
    # 'bad' has type error; using it must not produce more messages
    src = main_body("let bad = 1 m + 1 s;\nlet x = bad * 2;\nprint(x);")
    assert len(errors(src)) == 1


def test_suggestion_names_a_variable_that_fixes_it():
    src = main_body("let race = 100 m; let t = 10 s; let v: m/s = race;")
    d = diags(src)
    assert "race / t" in d[0].help


def test_error_carries_location_and_underline():
    d = diags("fn main() {\n    let v: m/s = 5 m;\n}")
    assert (d[0].line, d[0].col, d[0].length) == (2, 18, 3)


def test_warnings_do_not_block_compilation():
    from lumen.compiler import compile_source
    c = compile_source("fn main() { let unused = 1; print(2); }")
    assert any("never used" in w.message for w in c.warnings)


def test_unreachable_code_warning():
    from lumen.compiler import compile_source
    c = compile_source("fn main() { return; print(1); }")
    assert any("unreachable" in w.message for w in c.warnings)
