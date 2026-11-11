"""Regenerate tests/golden/*.out (review the diff before committing!)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

from test_examples import GOLDEN, NAMES, snapshot  # noqa: E402

os.makedirs(GOLDEN, exist_ok=True)
for n in NAMES:
    with open(os.path.join(GOLDEN, n[:-4] + ".out"), "w", encoding="utf-8") as fh:
        fh.write(snapshot(n))
print(f"wrote {len(NAMES)} golden files")
