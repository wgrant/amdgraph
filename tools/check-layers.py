#!/usr/bin/env python3
"""Fail if a module imports from a layer below its own.

The layering in src/amdgraph/__init__.py is only worth writing down if it is
also checked; this is what makes it a rule rather than an intention. Parses
imports statically, so it needs neither Qt nor the ryzen_smu module and runs
anywhere.

    python3 tools/check-layers.py
"""

import ast
import os
import sys

# Module -> layer. Lower may not import higher.
LAYER = {
    "fields": 0, "sysfs": 0,
    "sampler": 1, "store": 1,
    "palette": 2, "panes": 2, "session": 2, "view": 2,
    "render": 3,
    "timepane": 4, "chart": 4, "rasters": 4, "axis": 4,
    "window": 5, "__main__": 5,
}

# Edges within one layer, which the numbering cannot express. Each is a base
# class or an entry point, not a peer reaching sideways for a helper.
ALLOWED_SAME_LAYER = {
    ("chart", "timepane"),
    ("rasters", "timepane"),
    ("__main__", "window"),
}

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "amdgraph")


def deps_of(path):
    """Names this module imports from its own package."""
    out = set()
    for n in ast.walk(ast.parse(open(path).read())):
        if not isinstance(n, ast.ImportFrom) or n.level != 1:
            continue
        if n.module:
            out.add(n.module)
        else:
            # `from . import HELP` pulls an attribute, not a module.
            out.update(a.name for a in n.names if a.name in LAYER)
    return out


def main():
    problems = []
    listed = set()
    for fn in sorted(os.listdir(PKG)):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        mod = fn[:-3]
        if mod not in LAYER:
            problems.append(f"{mod}: not assigned a layer in this script")
            continue
        listed.add(mod)
        for dep in sorted(deps_of(os.path.join(PKG, fn))):
            if LAYER[dep] > LAYER[mod]:
                problems.append(f"{mod} (layer {LAYER[mod]}) imports {dep} "
                                f"(layer {LAYER[dep]})")
            elif (LAYER[dep] == LAYER[mod]
                    and (mod, dep) not in ALLOWED_SAME_LAYER):
                problems.append(f"{mod} imports its own layer: {dep}")
    for missing in sorted(set(LAYER) - listed):
        problems.append(f"{missing}: assigned a layer but no such module")

    if problems:
        print("layering violations:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"{len(listed)} modules, layering clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
