"""IR generation, optimizer, bytecode and VM."""
import pytest
from conftest import errors, main_body, run

from lumen.compiler import compile_source
from lumen.errors import LumenRuntimeError
from lumen.ir import format_program
from lumen.vm import VM


def ir_text(src, opt=True):
    c = compile_source(src)
    return format_program(c.ir_opt if opt else c.ir)


# ------------------------------------------------------------------ zero-cost units
def test_units_erased_conversion_folded_to_a_constant():
    src = "unit h = 3600 s;\nfn main() { let v: km/h = 10 m/s; print(v); }"
    text = ir_text(src)
    assert 'print 36.0 "km/h"' in text and "*" not in text


def test_unoptimized_ir_still_has_the_conversion():
    src = "unit h = 3600 s;\nfn main() { let v: km/h = 10 m/s; print(v); }"
    assert "; convert" in ir_text(src, opt=False)


def test_units_program_equals_plain_program():
    with_units = "unit h = 3600 s;\nfn main() { let v: km/h = 10 m/s; print(v); }"
    plain = "fn main() { let v = 36.0; print(v); }"
    a = compile_source(with_units).ir_opt
    b = compile_source(plain).ir_opt
    prints = lambda p: [str(i.a) for f in p.funcs for i in f.instrs if i.op == "PRINT"]
    assert prints(a) == prints(b) == ["36.0"]


def test_conversion_chain_fused_into_one_factor():
    # x (km) -> m -> mile : two conversions of a run-time value fuse into ONE multiply
    src = ("unit mile = 1609.344 m;\n"
           "fn conv(x: km) -> mile { let a = x in m; return a in mile; }\n"
           "fn main() { print(conv(3 km)); }")
    text = ir_text(src)
    assert text.count("; convert") == 1
    assert "; convert" in ir_text(src, opt=False) and ir_text(src, opt=False).count("; convert") == 2


def test_roundtrip_conversion_cancels():
    src = "fn f(x: km) -> km { return (x in m) in km; }\nfn main() { print(f(7 km)); }"
    text = ir_text(src)
    assert "; convert" not in text


# ------------------------------------------------------------------ optimizer behaviour
def test_constant_folding_and_propagation():
    src = "fn main() { let a = 2 + 3; let b = a * 4; print(b); }"
    assert "print 20" in ir_text(src)


def test_dead_assignment_removed():
    src = "fn main() { let unused = 5 * 5; print(1); }"
    assert "unused" not in ir_text(src)


def test_algebraic_identities():
    src = "fn f(x: int) -> int { return x * 1 + 0; }\nfn main() { print(f(3)); }"
    text = ir_text(src)
    assert "*" not in text and "+" not in text


def test_constant_branch_folded():
    src = "fn main() { if (1 < 2) { print(1); } else { print(2); } }"
    text = ir_text(src)
    assert "print 1" in text and "print 2" not in text and "goto" not in text


def test_while_false_removed():
    src = "fn main() { while (false) { print(1); } print(2); }"
    assert "print 1" not in ir_text(src)


def test_loop_variable_not_treated_as_constant():
    src = "fn main() { let i = 0; while (i < 3) { i = i + 1; } print(i); }"
    assert run(src) == "3\n"
    assert "while" not in ir_text(src)  # sanity: no stray text
    assert "i < 3" in ir_text(src) or "t" in ir_text(src)


def test_division_by_zero_not_folded_away():
    src = "fn main() { let z = 0; print(1 / z); }"
    with pytest.raises(LumenRuntimeError):
        run(src)


def test_trapping_division_not_deleted_as_dead():
    src = "fn main() { let z = 0; let dead = 1 / z; print(2); }"
    with pytest.raises(LumenRuntimeError):
        run(src)


@pytest.mark.parametrize("name", ["travel_time", "fact", "fib", "primes", "gcd", "force",
                                  "freefall", "energy", "orbit", "logic", "scopes",
                                  "unit_algebra", "gimli_fixed", "mars_fixed", "currency",
                                  "dosing", "data_rate", "chain", "zero_cost",
                                  "optimizer_demo", "phases_demo"])
def test_optimized_and_unoptimized_agree(name, example):
    src = example(name + ".lum")
    assert run(src, optimize=True) == run(src, optimize=False)


def test_optimizer_reduces_instruction_count():
    c = compile_source("unit h = 3600 s;\nfn main() { let v: km/h = 10 m/s; let w = v * 2; print(w); }")
    assert c.opt_stats.after < c.opt_stats.before


# ------------------------------------------------------------------ run time
def test_recursion():
    src = "fn fib(n: int) -> int { if (n < 2) { return n; } return fib(n-1) + fib(n-2); }\nfn main() { print(fib(15)); }"
    assert run(src) == "610\n"


def test_short_circuit_does_not_evaluate_right():
    src = ("fn loud() -> bool { print(99); return true; }\n"
           "fn main() { if (false && loud()) { } if (true || loud()) { print(1); } }")
    assert run(src) == "1\n"


def test_runtime_division_by_zero_reports_line():
    src = "fn d(a: int, b: int) -> int {\n return a / b;\n}\nfn main() { print(d(1, 0)); }"
    with pytest.raises(LumenRuntimeError) as e:
        run(src)
    assert e.value.line == 2 and "division by zero" in e.value.message


def test_float_division_by_zero():
    with pytest.raises(LumenRuntimeError):
        run("fn main() { let a = 1.0; let b = 0.0; print(a / b); }")


def test_infinite_loop_hits_step_limit():
    with pytest.raises(LumenRuntimeError) as e:
        run("fn main() { while (true) { } }", max_steps=10_000)
    assert "step limit" in e.value.message


def test_runaway_recursion_is_clean_error():
    with pytest.raises(LumenRuntimeError) as e:
        run("fn f(n: int) -> int { return f(n + 1); }\nfn main() { print(f(0)); }")
    assert "too deep" in e.value.message


def test_sqrt_of_negative():
    with pytest.raises(LumenRuntimeError):
        run("fn main() { let x = 0.0 - 4.0; print(sqrt(x)); }")


def test_discarded_return_value_is_popped():
    src = "fn f() -> int { return 5; }\nfn main() { f(); f(); print(1); }"
    assert run(src) == "1\n"


def test_print_formats():
    assert run('fn main() { print(true); print(3); print(2.5); print("hi"); print(10.0); }') \
        == "true\n3\n2.5\nhi\n10.0\n"


def test_int_to_float_builtin_and_int_truncation():
    assert run("fn main() { print(float(3)); print(int(3.9)); print(int(0.0 - 3.9)); }") == "3.0\n3\n-3\n"


def test_while_with_quantities():
    src = "fn main() { let t = 0 s; let n = 0; while (t < 5 s) { t = t + 2 s; n = n + 1; } print(n); print(t); }"
    assert run(src) == "3\n6.0 s\n"


def test_bytecode_has_no_unit_instructions():
    c = compile_source("unit h = 3600 s;\nfn main() { let v: km/h = 10 m/s; print(v); }")
    ops = {i.op for code in c.bytecode.funcs.values() for i in code.instrs}
    assert ops <= {"PUSH", "LOAD", "STORE", "PRINT", "RET", "MUL", "ADD", "SUB", "DIV", "IDIV",
                   "MOD", "POW", "LT", "LE", "GT", "GE", "EQ", "NE", "NEG", "NOT", "I2F",
                   "JMP", "JZ", "JNZ", "CALL", "CALLB", "POP"}


def test_absurdly_deep_nesting_is_a_clean_error():
    from lumen.errors import CompileError
    src = "fn main() { print(" + "(" * 4000 + "1" + ")" * 4000 + "); }"
    with pytest.raises(CompileError) as e:
        compile_source(src)
    assert "nested too deeply" in e.value.diagnostics[0].message
