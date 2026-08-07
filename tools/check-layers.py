#!/usr/bin/env python3
"""Fail if a module imports from a layer below its own.

The layering in src/amdgraph/__init__.py is only worth writing down if it is
also checked; this is what makes it a rule rather than an intention. Parses
imports statically, so it needs neither Qt nor the ryzen_smu module and runs
anywhere.

    python3 tools/check-layers.py [PACKAGE_DIR]

Three kinds of import reach a sibling module and all three are checked, because
an earlier version looked only at relative ones and a plain
`from amdgraph.palette import INK` in layer-0 sysfs.py passed as clean -- it
works at runtime, since the launcher puts src/ on sys.path and the package is
importable by its own absolute name from inside itself.
"""

import argparse
import ast
import os
import sys

PKG_NAME = "amdgraph"

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

# "no Qt below this line", from the layer map. Acquisition and storage have to
# stay importable without a display, so a recording can be produced or read
# headlessly; numpy is fine there, Qt is not.
QT_FREE_THROUGH_LAYER = 1
QT_ROOTS = ("PyQt6", "PyQt5", "PySide6")


def imports_of(path, modules):
    """(package siblings, third-party roots) this module imports.

    `modules` is the set of module names in the package, needed to read
    `from . import X`: X may be a submodule or just an attribute of __init__
    (`from . import HELP`), and only the former is an edge in the graph.
    """
    siblings, third = set(), set()
    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, ast.ImportFrom):
            if n.level == 1:                       # from .render import ...
                if n.module:
                    siblings.add(n.module.split(".")[0])
                else:                              # from . import render
                    siblings.update(a.name for a in n.names
                                    if a.name in modules)
            elif n.level == 0 and n.module:
                root, _, rest = n.module.partition(".")
                if root == PKG_NAME:               # from amdgraph.render import
                    if rest:
                        siblings.add(rest.split(".")[0])
                else:
                    third.add(root)
        elif isinstance(n, ast.Import):
            for a in n.names:
                root, _, rest = a.name.partition(".")
                if root == PKG_NAME:               # import amdgraph.render
                    if rest:
                        siblings.add(rest.split(".")[0])
                else:
                    third.add(root)
    return siblings, third


def check(pkg):
    problems, listed = [], set()
    modules = {f[:-3] for f in os.listdir(pkg)
               if f.endswith(".py") and f != "__init__.py"}

    init = os.path.join(pkg, "__init__.py")
    if os.path.isfile(init):
        # __init__ runs on every `import amdgraph.anything`, so a submodule
        # import here would pull Qt in ahead of __main__'s dependency check and
        # turn a one-line "apt install python3-pyqt6" into a traceback.
        sib, third = imports_of(init, modules)
        for d in sorted(sib):
            problems.append(f"__init__ imports the package module {d}: it must "
                            "stay importable before the dependency check")
        for t in sorted(third):
            if t in QT_ROOTS or t == "numpy":
                problems.append(f"__init__ imports {t}: same reason")

    for fn in sorted(os.listdir(pkg)):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        mod = fn[:-3]
        if mod not in LAYER:
            problems.append(f"{mod}: not assigned a layer in this script")
            continue
        listed.add(mod)
        sib, third = imports_of(os.path.join(pkg, fn), modules)
        for dep in sorted(sib):
            if dep not in LAYER:
                problems.append(f"{mod} imports {dep}, which has no layer")
            elif LAYER[dep] > LAYER[mod]:
                problems.append(f"{mod} (layer {LAYER[mod]}) imports {dep} "
                                f"(layer {LAYER[dep]})")
            elif (LAYER[dep] == LAYER[mod]
                    and (mod, dep) not in ALLOWED_SAME_LAYER):
                problems.append(f"{mod} imports its own layer: {dep}")
        if LAYER[mod] <= QT_FREE_THROUGH_LAYER:
            for t in sorted(third & set(QT_ROOTS)):
                problems.append(f"{mod} (layer {LAYER[mod]}) imports {t}: "
                                f"layers 0-{QT_FREE_THROUGH_LAYER} must stay "
                                "importable without a display")

    for missing in sorted(set(LAYER) - listed):
        problems.append(f"{missing}: assigned a layer but no such module")
    return problems, listed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("package", nargs="?", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", PKG_NAME))
    args = ap.parse_args()

    problems, listed = check(args.package)
    if problems:
        print("layering violations:")
        for p in problems:
            print(f"  {p}")
        return 1
    print(f"{len(listed)} modules, layering clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
