import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from lumen.compiler import compile_source
from lumen.errors import CompileError, LumenRuntimeError
from lumen.vm import VM

EXAMPLES = os.path.join(os.path.dirname(__file__), "..", "examples")


def run(src: str, optimize: bool = True, **vm_kw):
    """Compile and run; returns the printed text."""
    out = []
    c = compile_source(src, optimize=optimize)
    VM(c.bytecode, out=out.append, **vm_kw).run()
    return "".join(out)


def errors(src: str) -> list[str]:
    """Compile a program that must fail; return the error messages."""
    try:
        compile_source(src)
    except CompileError as e:
        return [d.message for d in e.diagnostics if d.severity == "error"]
    raise AssertionError("program compiled but was expected to fail")


def diags(src: str):
    try:
        compile_source(src)
    except CompileError as e:
        return e.diagnostics
    raise AssertionError("expected failure")


def main_body(body: str, extra: str = "") -> str:
    return f"{extra}\nfn main() {{\n{body}\n}}\n"


@pytest.fixture
def example():
    def read(name):
        with open(os.path.join(EXAMPLES, name), encoding="utf-8") as fh:
            return fh.read()
    return read
