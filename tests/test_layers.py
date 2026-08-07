"""The layer checker has to catch violations that actually run.

Every case below was a hole in the first version of check-layers.py, found by
review rather than by the checker itself -- which is the whole argument for
testing a tool whose only job is to say "clean".
"""

import os

import pytest


@pytest.fixture
def build(check_layers, tmp_path):
    """Write a minimal legal package, overlay `files`, and check it."""
    def run(files):
        pkg = tmp_path / "amdgraph"
        pkg.mkdir()
        (pkg / "__init__.py").write_text('"""doc"""\n')
        for mod in check_layers.LAYER:
            (pkg / f"{mod}.py").write_text("")
        for name, body in files.items():
            (pkg / name).write_text(body)
        return check_layers.check(str(pkg))[0]
    return run


def test_real_package_is_clean(check_layers, repo_root):
    problems, listed = check_layers.check(
        os.path.join(repo_root, "src", "amdgraph"))
    assert problems == []
    assert listed == set(check_layers.LAYER)


@pytest.mark.parametrize("mod, body, needles", [
    # sysfs is layer 0, palette layer 2.
    ("sysfs.py", "from .palette import INK\n", ("sysfs", "palette")),
    # Absolute self-import: works at runtime because the launcher puts src/ on
    # sys.path, so the package can import itself by name. The first checker
    # never saw it.
    ("sysfs.py", "from amdgraph.palette import INK\n", ("sysfs", "palette")),
    ("sysfs.py", "import amdgraph.window\n", ("sysfs", "window")),
    ("sysfs.py", "from . import palette\n", ("sysfs", "palette")),
    # "no Qt below this line" is stated in the layer map and was never a rule.
    ("store.py", "from PyQt6.QtGui import QColor\n", ("store", "PyQt6")),
    # Previously a KeyError with a traceback instead of a finding.
    ("sysfs.py", "from .newthing import x\n", ("newthing",)),
    ("sysfs.py", "from .sub.thing import x\n", ("sub",)),
    # __init__ executes on every `import amdgraph.x`, so this would drag Qt in
    # ahead of __main__'s dependency check.
    ("__init__.py", "from .window import Main\n", ("__init__", "window")),
    ("__init__.py", "import PyQt6\n", ("__init__",)),
    # chart -> timepane is allowed; the reverse is not.
    ("timepane.py", "from .chart import C\n", ("timepane",)),
])
def test_violations_are_caught(build, mod, body, needles):
    problems = build({mod: body})
    assert any(all(n in p for n in needles) for p in problems), problems


@pytest.mark.parametrize("mod, body", [
    ("store.py", "import numpy as np\n"),                 # numpy is fine at L1
    ("palette.py", "from PyQt6.QtGui import QColor\n"),   # Qt is fine at L2
    ("chart.py", "from .timepane import P\n"),            # declared base class
    ("window.py", "from .sysfs import x\n"),              # upward is fine
    # `from . import HELP` pulls a string out of __init__, not a module.
    # Reporting unknown names as violations made this a false positive.
    ("window.py", "from . import HELP\n"),
])
def test_legal_imports_pass(build, mod, body):
    assert build({mod: body}) == []
