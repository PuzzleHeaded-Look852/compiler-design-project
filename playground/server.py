"""Lumen Playground: a tiny local web server around the real compiler.

    python3 playground/server.py          then open http://localhost:8765

Standard library only. Every phase's output comes from the actual compiler in src/lumen.
"""

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from lumen.ast_nodes import dump_ast  # noqa: E402
from lumen.codegen import count_bytecode, format_bytecode  # noqa: E402
from lumen.compiler import compile_source  # noqa: E402
from lumen.errors import CompileError, LumenRuntimeError, render_all  # noqa: E402
from lumen.ir import format_program  # noqa: E402
from lumen.vm import VM  # noqa: E402

# (file, title, group, one-line note shown under the editor)
EXAMPLES = [
    ("travel_time", "Road trip", "Basics", "Mixed units are converted automatically: km/min becomes km/h."),
    ("unit_algebra", "Unit algebra", "Basics", "m / s, m * m, km / m: the compiler does the dimensional analysis."),
    ("fact", "Factorial", "Basics", "Plain integers work too: recursion and loops."),
    ("fib", "Fibonacci", "Basics", "Recursion; look at --bytecode to see CALL / RET."),
    ("primes", "Primes", "Basics", "Loops and conditions."),
    ("mars_bug", "Mars Orbiter: the bug", "Real disasters", "1999. A bare 12.5 where N*s was needed. Rejected at compile time."),
    ("mars_fixed", "Mars Orbiter: fixed", "Real disasters", "12.5 lbf*s is converted to 55.6 N*s exactly."),
    ("gimli_bug", "Gimli Glider: the bug", "Real disasters", "1983. 1.77 used as kg/L. Rejected at compile time."),
    ("gimli_fixed", "Gimli Glider: fixed", "Real disasters", "1.77 lb/L converts to 0.803 kg/L automatically."),
    ("dosing_bug", "Drug dosing: the bug", "Real disasters", "mg versus mcg mistakes caught before they reach a patient."),
    ("dosing", "Drug dosing: fixed", "Real disasters", "mcg/kg/min orders converted to mg/h for the pump."),
    ("currency", "Currency", "More units", "INR and USD are separate dimensions and never mix silently."),
    ("data_rate", "Data rate", "More units", "Megabits per second versus megabytes: the factor-of-8 mistake."),
    ("energy", "Kinetic energy", "More units", "kg * (m/s)^2 comes out exactly as joules."),
    ("freefall", "Free fall", "More units", "d = 1/2 g t^2 and sqrt of an area back to a length."),
    ("force", "Newton's law", "More units", "kg * m/s^2 is exactly a newton."),
    ("err_lexical", "Error: lexical", "Compile errors", "An illegal character. Reported on its own."),
    ("err_syntax", "Error: syntax", "Compile errors", "Several syntax mistakes found in one run (panic-mode recovery)."),
    ("err_units", "Error: units", "Compile errors", "Metres plus seconds, wrong unit passed, misspelt unit."),
    ("err_types", "Error: types", "Compile errors", "int / bool / string mismatches."),
    ("err_scope", "Error: scope", "Compile errors", "Undefined and out-of-scope names."),
    ("err_return", "Error: return", "Compile errors", "Missing and unexpected returns."),
    ("err_runtime", "Error: runtime", "Compile errors", "Compiles fine, then fails at run time with a line number."),
    ("err_recursion", "Error: runaway recursion", "Compile errors", "A clean Lumen error, never a Python crash."),
    ("warnings", "Warnings", "Compile errors", "Compiles and runs, but points out suspicious code."),
    ("optimizer_demo", "Optimizer demo", "Under the hood", "Open the Optimized IR tab: 20 instructions shrink to 6."),
    ("zero_cost", "Zero runtime cost", "Under the hood", "The whole program compiles down to v = 36.0."),
    ("phases_demo", "Every phase", "Under the hood", "The program used in the report to show each phase."),
]

BLANK = """// Write your own Lumen program here and press Run.
unit h = 3600 s;

fn main() {
    let d = 120 km;
    let t = 1.5 h;
    print(d / t);
}
"""


def load_examples():
    out = []
    for name, title, group, note in EXAMPLES:
        path = os.path.join(ROOT, "examples", name + ".lum")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                out.append({"id": name, "title": title, "group": group, "note": note, "source": fh.read()})
    return out


def units_table(c):
    rows = []
    for n in c.units.order:
        u = c.units.units[n]
        rows.append(f"{n:<8} {c.units.dim_name(u.dim):<22} = {float(u.scale):g} x {c.units.si_label(u.dim)}")
    return "\n".join(rows)


def compile_all(source, optimize=True, filename="program.lum"):
    res = {"ok": False, "exit": 0, "stdout": "", "diagnostics": "", "warnings": "",
           "tokens": "", "ast": "", "ir": "", "ir_opt": "", "bytecode": "", "units": "", "stats": ""}
    try:
        c = compile_source(source, optimize=optimize)
    except CompileError as e:
        res["exit"] = 1
        res["fail_phase"] = (e.diagnostics[0].phase if e.diagnostics else "") or "checker"
        res["diagnostics"] = render_all(e.diagnostics, source, filename)
        return res
    if c.warnings:
        res["warnings"] = render_all(c.warnings, source, filename)
    res["tokens"] = "\n".join(f"{t.line:>3}:{t.col:<3} {t}" for t in c.tokens)
    res["units"] = units_table(c)
    res["ast"] = dump_ast(c.ast, show_types=True)
    res["ir"] = format_program(c.ir)
    res["ir_opt"] = format_program(c.ir_opt) if c.ir_opt is not None else "(optimizer is off)"
    res["bytecode"] = format_bytecode(c.bytecode)

    buf = []
    vm = VM(c.bytecode, out=buf.append, max_steps=2_000_000)
    stats = None
    try:
        stats = vm.run()
        res["ok"] = True
    except LumenRuntimeError as e:
        res["exit"] = 3
        res["fail_phase"] = "runtime"
        lines = source.splitlines()
        where = f"{filename}:{e.line}: " if e.line else ""
        msg = f"{where}runtime error: {e.message}"
        if e.line and 1 <= e.line <= len(lines):
            msg += f"\n{e.line:>5} | {lines[e.line - 1]}"
        res["diagnostics"] = msg
    res["stdout"] = "".join(buf)

    s = []
    if c.opt_stats:
        s += c.opt_stats.lines()
    s.append(f"bytecode instructions            : {count_bytecode(c.bytecode)}")
    if stats:
        s += [f"VM steps executed                : {stats.steps}",
              f"function calls                   : {stats.calls}",
              f"max call depth                   : {stats.max_depth}"]
    res["stats"] = "\n".join(s)
    return res


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/examples":
            data = json.dumps({"examples": load_examples(), "blank": BLANK}).encode()
            return self._send(200, data, "application/json")
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(HERE, path.lstrip("/")))
        if not full.startswith(HERE) or not os.path.isfile(full) or full.endswith("server.py"):
            return self._send(404, b"not found", "text/plain")
        ctype = {"html": "text/html; charset=utf-8", "png": "image/png", "css": "text/css", "js": "text/javascript",
                 "json": "application/json"}.get(full.rsplit(".", 1)[-1], "application/octet-stream")
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    def do_POST(self):
        if self.path != "/api/compile":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            out = compile_all(str(req.get("source", "")), bool(req.get("optimize", True)))
        except Exception as e:  # never let a bad request kill the server
            out = {"ok": False, "exit": 2, "diagnostics": f"server error: {e}", "stdout": ""}
        self._send(200, json.dumps(out).encode(), "application/json")


def main():
    port = int(os.environ.get("PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://localhost:{port}"
    print(f"Lumen Playground running at {url}  (Ctrl+C to stop)")
    if "--no-open" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
