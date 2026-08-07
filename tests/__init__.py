"""Test suite.

stdlib unittest rather than pytest, on purpose: amdgraph's install story is
"clone it and run it", and a test suite that needs a package the program does
not is a test suite that does not get run on the machine where something broke.

    python3 -m unittest discover -s tests -t .        (from the repo root)
    tools/run-tests

Tests that need Qt skip themselves when PyQt6 is absent. Nothing here touches
real hardware; everything reads synthetic trees under a temp dir.
"""

import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

TOOLS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")


def load_tool(name):
    """Import a tools/ script that has no .py suffix."""
    import importlib.machinery
    import importlib.util
    path = os.path.join(TOOLS, name)
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod
