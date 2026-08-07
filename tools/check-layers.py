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

Modules one directory down (backends/*) are supported too, named by their
dotted path (`backends.host`). Deliberately one level only: a second level of
nesting would need a recursive walker, which is not a problem this package
has, and building one now would be solving something that doesn't exist.
"""

import argparse
import ast
import os
import sys

PKG_NAME = "amdgraph"

# Module -> layer. Lower may not import higher.
LAYER = {
    "fields": 0, "sysfs": 0,
    "backends.base": 1, "backends.host": 1, "backends.platform": 1,
    "backends.zen_smu": 1, "backends.amdgpu": 1,
    "sampler": 2, "store": 2,
    "palette": 3, "panes": 3, "session": 3, "view": 3,
    "render": 4,
    "timepane": 5, "chart": 5, "rasters": 5, "axis": 5,
    "window": 6, "__main__": 6,
}

# Edges within one layer, which the numbering cannot express. Each is a base
# class or an entry point, not a peer reaching sideways for a helper.
ALLOWED_SAME_LAYER = {
    ("backends.host", "backends.base"),
    ("backends.platform", "backends.base"),
    ("backends.zen_smu", "backends.base"),
    ("backends.amdgpu", "backends.base"),
    ("chart", "timepane"),
    ("rasters", "timepane"),
    ("__main__", "window"),
}

# "no Qt below this line", from the layer map. Acquisition and storage (and
# the backends underneath them) have to stay importable without a display, so
# a recording can be produced or read headlessly; numpy is fine there, Qt is
# not.
QT_FREE_THROUGH_LAYER = 2
QT_ROOTS = ("PyQt6", "PyQt5", "PySide6")


def discover(pkg):
    """dotted module name -> absolute file path, for every module in the
    package: top-level `foo.py` as `"foo"`, and one directory down as
    `"dirname.foo"`. Directories starting with `_` (i.e. `__pycache__`) are
    skipped.
    """
    out = {}
    for fn in sorted(os.listdir(pkg)):
        full = os.path.join(pkg, fn)
        if fn.endswith(".py") and fn != "__init__.py":
            out[fn[:-3]] = full
        elif os.path.isdir(full) and not fn.startswith("_"):
            for sub in sorted(os.listdir(full)):
                if sub.endswith(".py") and sub != "__init__.py":
                    out[f"{fn}.{sub[:-3]}"] = os.path.join(full, sub)
    return out


def imports_of(path, modules, own):
    """(package siblings, third-party roots) this module imports.

    `own` is this module's own dotted name -- `"sampler"` for a top-level
    module, `"backends.host"` for one nested a directory down -- needed to
    resolve how far a relative import's leading dots actually reach, now
    that the package is not perfectly flat: level 1 means "from the package
    containing this module" (its own directory), and each further dot trims
    one more parent off that. A top-level module has no containing package,
    so this collapses to the historical behaviour unchanged for every module
    that isn't in a subpackage.

    `modules` is the set of every module name in the package (dotted where
    nested). It disambiguates two different shapes:

    * `from . import X` / `from .. import X` -- X may be a submodule (a real
      edge) or just an attribute of `__init__` (`from . import HELP`, no
      edge). Membership decides; an unmatched name is assumed to be an
      attribute, not reported.
    * `from <package> import a, b` where `<package>` names a module
      explicitly (`from .base import Backend`, `from .backends import
      host`, `from .newthing import x`) -- `<package>` itself might be the
      target module (`base`), or each imported name might be *its* submodule
      (`backends.host`, when `backends` is only a namespace). Tried in that
      order; if neither matches anything real, the bare `<package>` path is
      still recorded as the edge, because an unknown target (`newthing`) is
      exactly the violation worth reporting, not silently dropping it.
    """
    siblings, third = set(), set()
    own_pkg = own.split(".")[:-1]        # this module's containing package

    def named_module_edges(base_parts, module_dotted, names):
        dotted = ".".join(base_parts + module_dotted.split("."))
        if dotted in modules:
            return {dotted}
        hits = {f"{dotted}.{n}" for n in names if f"{dotted}.{n}" in modules}
        return hits or {dotted}

    def bare_name_edges(base_parts, names):
        prefix = ".".join(base_parts)
        for name in names:
            cand = f"{prefix}.{name}" if prefix else name
            if cand in modules:
                siblings.add(cand)

    for n in ast.walk(ast.parse(open(path).read())):
        if isinstance(n, ast.ImportFrom):
            if n.level >= 1:
                trim = n.level - 1
                base_parts = (own_pkg[: len(own_pkg) - trim]
                             if trim <= len(own_pkg) else [])
                if n.module:                        # from .render import ...
                    siblings |= named_module_edges(
                        base_parts, n.module, [a.name for a in n.names])
                else:                                # from . import render
                    bare_name_edges(base_parts, [a.name for a in n.names])
            elif n.level == 0 and n.module:
                root, _, rest = n.module.partition(".")
                if root == PKG_NAME:                 # from amdgraph.render import
                    if rest:
                        siblings |= named_module_edges(
                            [], rest, [a.name for a in n.names])
                    else:
                        bare_name_edges([], [a.name for a in n.names])
                else:
                    third.add(root)
        elif isinstance(n, ast.Import):
            for a in n.names:
                root, _, rest = a.name.partition(".")
                if root == PKG_NAME:                 # import amdgraph.backends.host
                    if rest:
                        siblings.add(rest)
                else:
                    third.add(root)
    return siblings, third


def check(pkg):
    problems, listed = [], set()
    discovered = discover(pkg)
    modules = set(discovered)

    init = os.path.join(pkg, "__init__.py")
    if os.path.isfile(init):
        # __init__ runs on every `import amdgraph.anything`, so a submodule
        # import here would pull Qt in ahead of __main__'s dependency check and
        # turn a one-line "apt install python3-pyqt6" into a traceback.
        sib, third = imports_of(init, modules, "")
        for d in sorted(sib):
            problems.append(f"__init__ imports the package module {d}: it must "
                            "stay importable before the dependency check")
        for t in sorted(third):
            if t in QT_ROOTS or t == "numpy":
                problems.append(f"__init__ imports {t}: same reason")

    for mod in sorted(discovered):
        if mod not in LAYER:
            problems.append(f"{mod}: not assigned a layer in this script")
            continue
        listed.add(mod)
        sib, third = imports_of(discovered[mod], modules, mod)
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
