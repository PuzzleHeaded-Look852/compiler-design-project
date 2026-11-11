#!/bin/bash
# Double-click (macOS) or run in a terminal to start the Lumen Playground (needs Python 3.10+).
cd "$(dirname "$0")" || exit 1
python3 playground/server.py
