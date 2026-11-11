"""Diagnostics: how every phase reports problems to the programmer.

All phases (lexer, parser, checker, VM) describe a problem as a Diagnostic:
a message, a line and column, and an optional "help" line that suggests a fix.
`render` turns a Diagnostic into the friendly multi-line text shown on screen:

    prog.lum:16:21: error: cannot add length (km) to time (min)
       16 |     let oops = race + t;
          |                     ^
          = help: did you mean `race / t` (a speed)?

A phase never crashes with a Python traceback on bad user input. It collects
diagnostics, and the driver prints all of them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Diagnostic:
    severity: str          # "error" or "warning"
    message: str
    line: int
    col: int
    length: int = 1        # how many characters the caret underline covers
    help: str | None = None
    phase: str = ""        # "lexer", "parser", "checker", "runtime"


class CompileError(Exception):
    """Raised when compilation cannot continue; carries every diagnostic found."""

    def __init__(self, diagnostics: list[Diagnostic]):
        super().__init__(f"{len(diagnostics)} error(s)")
        self.diagnostics = diagnostics


class LumenRuntimeError(Exception):
    """A problem found while the VM is running (division by zero, ...)."""

    def __init__(self, message: str, line: int = 0):
        super().__init__(message)
        self.message = message
        self.line = line


def render(diag: Diagnostic, source: str, filename: str = "<input>") -> str:
    """Format one diagnostic with the source line and a caret under the spot."""
    out = [f"{filename}:{diag.line}:{diag.col}: {diag.severity}: {diag.message}"]
    lines = source.splitlines()
    if 1 <= diag.line <= len(lines):
        text = lines[diag.line - 1].replace("\t", " ")
        gutter = f"{diag.line:>5} | "
        pad = " " * (len(gutter) - 2) + "| "
        caret = " " * (diag.col - 1) + "^" + "~" * max(0, diag.length - 1)
        out.append(gutter + text)
        out.append(pad + caret)
    if diag.help:
        out.append("      = help: " + diag.help)
    return "\n".join(out)


def render_all(diags: list[Diagnostic], source: str, filename: str = "<input>") -> str:
    parts = [render(d, source, filename) for d in diags]
    errors = sum(1 for d in diags if d.severity == "error")
    warnings = sum(1 for d in diags if d.severity == "warning")
    summary = []
    if errors:
        summary.append(f"{errors} error{'s' if errors != 1 else ''}")
    if warnings:
        summary.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
    text = "\n\n".join(parts)
    if summary:
        text += "\n\n" + ", ".join(summary) + " generated."
    return text
