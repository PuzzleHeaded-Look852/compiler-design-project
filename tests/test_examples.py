"""Golden tests: every program in examples/ must produce exactly the recorded output."""
import io
import os
import contextlib

import pytest

from lumen.cli import main

HERE = os.path.dirname(__file__)
EXAMPLES = os.path.join(HERE, "..", "examples")
GOLDEN = os.path.join(HERE, "golden")


def run_cli(path, *flags):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(["run", path, *flags])
    return code, out.getvalue(), err.getvalue()


def snapshot(name):
    path = os.path.join("examples", name)
    # run from the project root so paths in messages are stable
    cwd = os.getcwd()
    os.chdir(os.path.join(HERE, ".."))
    try:
        code, out, err = run_cli(path)
    finally:
        os.chdir(cwd)
    return f"exit code: {code}\n--- stdout ---\n{out}--- stderr ---\n{err}"


NAMES = sorted(f for f in os.listdir(EXAMPLES) if f.endswith(".lum"))


@pytest.mark.parametrize("name", NAMES)
def test_golden(name):
    gold = os.path.join(GOLDEN, name[:-4] + ".out")
    assert os.path.exists(gold), f"no golden file; run: python tests/make_golden.py"
    with open(gold, encoding="utf-8") as fh:
        expected = fh.read()
    assert snapshot(name) == expected


def test_example_count():
    assert len(NAMES) >= 20


def test_exit_codes():
    root = os.path.join(HERE, "..")
    cwd = os.getcwd()
    os.chdir(root)
    try:
        assert run_cli("examples/fact.lum")[0] == 0
        assert run_cli("examples/mars_bug.lum")[0] == 1
        assert run_cli("examples/err_runtime.lum")[0] == 3
        assert run_cli("examples/nonexistent.lum")[0] == 2
    finally:
        os.chdir(cwd)


def test_cli_phase_flags():
    root = os.path.join(HERE, "..")
    cwd = os.getcwd()
    os.chdir(root)
    try:
        for flag, needle in [("--tokens", "IDENT"), ("--ast", "FuncDecl"), ("--ir", "func main"),
                             ("--ir-opt", "func main"), ("--bytecode", "== main"),
                             ("--units", "min")]:
            code, out, _ = run_cli("examples/travel_time.lum", flag)
            assert code == 0 and needle in out, flag
    finally:
        os.chdir(cwd)
