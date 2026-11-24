"""Build Lumen_Case_Study.pdf: cover + front matter (roman pages) + body (arabic pages).

The contents page numbers are read back from the rendered body, so they are always right.
Needs Google Chrome (headless print) and pypdf.   Run:  python docs/report/build.py
"""
import re
import subprocess
from pathlib import Path

from pypdf import PdfReader, PdfWriter

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
OUT = HERE / "Lumen_Case_Study.pdf"

# (level, heading text exactly as in body.html)
TOC = [
    (1, "1. Introduction"), (2, "1.1 Background"), (2, "1.2 Project Overview"),
    (2, "1.3 Purpose and Organization of This Case Study"),
    (1, "2. Problem Statement"), (2, "2.1 Numbers Without Units"), (2, "2.2 Silent Conversion Errors"),
    (2, "2.3 Unit Libraries Are Rarely Used"), (2, "2.4 Engineering Question"),
    (1, "3. Objectives and Scope"), (2, "3.1 Objectives"), (2, "3.2 In Scope"), (2, "3.3 Out of Scope"),
    (1, "4. Background and Related Work"), (2, "4.1 Compiler Phases"), (2, "4.2 Dimensional Analysis"),
    (2, "4.3 Syntax-Directed Definitions"), (2, "4.4 Related Approaches"),
    (1, "5. System Architecture"), (2, "5.1 Overview"), (2, "5.2 Module Responsibilities"),
    (2, "5.3 Design Principles"), (2, "5.4 Command-Line Interface"),
    (1, "6. The Lumen Language"), (2, "6.1 A First Program"), (2, "6.2 Lexical Rules and Grammar"),
    (2, "6.3 Units and Dimensions"), (2, "6.4 Typing Rules"),
    (1, "7. The Seven-Phase Compiler Pipeline"), (2, "7.1 Phase 1: Lexical Analysis"),
    (2, "7.2 Phase 2: Syntax Analysis"), (2, "7.3 Phase 3: Unit and Type Checking"),
    (2, "7.4 Phase 4: Intermediate Code"), (2, "7.5 Phase 5: Optimization"),
    (2, "7.6 Phase 6: Code Generation"), (2, "7.7 Phase 7: The Virtual Machine"),
    (2, "7.8 Diagnostics"), (2, "7.9 Worked Example Summary"),
    (1, "8. Real Unit Failures Reproduced"), (2, "8.1 Mars Climate Orbiter (1999)"),
    (2, "8.2 Gimli Glider (1983)"), (2, "8.3 Other Error Classes"),
    (1, "9. Correctness and Safety"),
    (1, "10. Testing and Quality Assurance"), (2, "10.1 Results Reproduced in This Study"),
    (2, "10.2 What the Tests Do and Do Not Show"),
    (1, "11. Evaluation"), (2, "11.1 Compile Latency"), (2, "11.2 Zero Run-Time Cost"),
    (2, "11.3 Effect of the Optimizer"), (2, "11.4 Cautions"),
    (1, "12. Contributions and Novelty"), (1, "13. Limitations"),
    (1, "14. Future Work and Scope for Improvement"), (2, "14.1 Language"), (2, "14.2 Compiler"),
    (2, "14.3 Learner Experience"), (2, "14.4 Verification"),
    (1, "15. Conclusion"), (1, "References"),
    (1, "Appendix A: Sample Session"), (1, "Appendix B: Repository Structure"),
    (1, "Appendix C: Running and Testing the Project"), (1, "Appendix D: Team Responsibilities"),
]

FRONT = """<!doctype html><html><head><meta charset="utf-8"><title>Lumen Front Matter</title>
<link rel="stylesheet" href="style.css">
<style>
  body {{ page: roman; }}
  .toc {{ width: 100%; border-collapse: collapse; font-size: 11.5pt; }}
  .toc td {{ border: none; padding: 1.5pt 0; }}
  .toc td.n {{ width: 10mm; text-align: right; }}
  .toc tr.l1 td {{ font-weight: bold; padding-top: 7pt; }}
  .toc tr.l2 td.t {{ padding-left: 7mm; }}
  .dots {{ display: flex; align-items: baseline; }}
  .dots .x {{ flex: 1; border-bottom: 1.2pt dotted #000; margin: 0 4pt; transform: translateY(-3pt); }}
</style></head><body>
<h1 style="margin-top:0">Abstract</h1>
<p>Ordinary programming languages treat a number as just a number, so a program can add metres to seconds, or pass pounds where
kilograms were expected, and no compiler will object. Unit mistakes of exactly this kind caused the loss of NASA's Mars Climate
Orbiter in 1999 and the fuel exhaustion of Air Canada Flight 143 in 1983. This case study examines Lumen, a small statically typed
language in which every number carries its unit, together with a complete hand-written compiler for it.</p>
<p>The compiler has seven phases: a lexer, a recursive-descent parser with two context rules that tell units from variables, a
unit and type checker that computes the dimension of every expression as a synthesized attribute, a three-address code generator,
an optimizer, a bytecode generator and a stack-based virtual machine. Compatible units are converted automatically using exact
rational arithmetic; incompatible ones are rejected with a located error message and a suggested fix. After checking, units are
erased, so the program that runs contains no unit logic at all, and the optimizer folds conversions into constants.</p>
<p>The study documents the design from the source code (3,437 lines of Python, no third-party dependencies), reproduces the test
suite (187 of 187 tests pass, with golden outputs for 34 example programs), and measures compilation at about 0.16 ms for a 10-line
program and 49 ms for a 1,603-line program. It reproduces the Mars and Gimli bugs as compile-time errors. It also states what Lumen
does not do: it checks one program at a time, has no temperature units, tracks dimensions rather than quantity kinds, and runs on a
Python virtual machine. A roadmap for future work closes the study.</p>
<p style="text-align:left"><b>Keywords:</b> <i>compiler design, units of measure, dimensional analysis, type checking,
syntax-directed definition, three-address code, code optimization, stack virtual machine.</i></p>
<h1 class="page">Contents</h1>
<table class="toc">{rows}</table>
</body></html>
"""


def chrome_pdf(html: Path, pdf: Path) -> None:
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html.as_uri()],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def heading_pages(pdf: Path) -> dict[str, int]:
    """Page (1-based) on which each TOC heading starts, searching forward in order."""
    lines_per_page = [[norm(l) for l in (p.extract_text() or "").splitlines()] for p in PdfReader(pdf).pages]
    found, page = {}, 0
    for _, text in TOC:
        for i in range(page, len(lines_per_page)):
            if any(l == norm(text) for l in lines_per_page[i]):
                found[text], page = i + 1, i
                break
        else:
            raise SystemExit(f"heading not found in body PDF: {text!r}")
    return found


def main() -> None:
    tmp = HERE / "_build"
    tmp.mkdir(exist_ok=True)
    cover_pdf, body_pdf, front_pdf = tmp / "cover.pdf", tmp / "body.pdf", tmp / "front.pdf"
    chrome_pdf(HERE / "cover.html", cover_pdf)
    chrome_pdf(HERE / "body.html", body_pdf)

    pages = heading_pages(body_pdf)
    rows = "".join(
        f'<tr class="l{lvl}"><td class="t"><div class="dots"><span>{text}</span><span class="x"></span></div></td>'
        f'<td class="n">{pages[text]}</td></tr>'
        for lvl, text in TOC)
    front_html = HERE / "front.html"
    front_html.write_text(FRONT.format(rows=rows), encoding="utf-8")
    chrome_pdf(front_html, front_pdf)

    out = PdfWriter()
    for part in (cover_pdf, front_pdf, body_pdf):
        out.append(str(part))
    out.add_metadata({"/Title": "Lumen: A Case Study in Unit-Aware Compilation",
                      "/Author": "Sanjay Suresh, Sugesh Kumar, Noel Ninan, Advaith Sivakumar, Ajay Kumar"})
    with open(OUT, "wb") as f:
        out.write(f)
    total = sum(len(PdfReader(p).pages) for p in (cover_pdf, front_pdf, body_pdf))
    print(f"wrote {OUT} ({total} pages: cover 1, front {len(PdfReader(front_pdf).pages)}, body {len(PdfReader(body_pdf).pages)})")


if __name__ == "__main__":
    main()
