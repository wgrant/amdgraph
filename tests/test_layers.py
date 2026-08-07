"""The layer checker has to catch violations that actually run.

Every case below was a hole in the first version of check-layers.py, found by
review rather than by the checker itself -- which is the whole argument for
testing a tool whose only job is to say "clean".
"""

import os
import tempfile
import unittest

from tests import load_tool

CL = load_tool("check-layers.py")
REAL_PKG = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src", "amdgraph")


def build(tmp, files):
    pkg = os.path.join(tmp, "amdgraph")
    os.makedirs(pkg)
    base = {"__init__.py": '"""doc"""\n'}
    # A minimal legal package: one module per layer name the checker knows.
    for mod in CL.LAYER:
        base[f"{mod}.py"] = ""
    base.update(files)
    for name, body in base.items():
        with open(os.path.join(pkg, name), "w") as f:
            f.write(body)
    return pkg


class TestRealPackage(unittest.TestCase):
    def test_clean(self):
        problems, listed = CL.check(REAL_PKG)
        self.assertEqual(problems, [])
        self.assertEqual(listed, set(CL.LAYER))


class TestViolations(unittest.TestCase):
    def one(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            return CL.check(build(tmp, files))[0]

    def test_relative_downward_import(self):
        # sysfs is layer 0, palette layer 2.
        p = self.one({"sysfs.py": "from .palette import INK\n"})
        self.assertTrue(any("sysfs" in x and "palette" in x for x in p), p)

    def test_absolute_self_import(self):
        # Works at runtime because the launcher puts src/ on sys.path, so the
        # package can import itself by name. Invisible to the first checker.
        p = self.one({"sysfs.py": "from amdgraph.palette import INK\n"})
        self.assertTrue(any("sysfs" in x and "palette" in x for x in p), p)

    def test_plain_import_statement(self):
        p = self.one({"sysfs.py": "import amdgraph.window\n"})
        self.assertTrue(any("sysfs" in x and "window" in x for x in p), p)

    def test_qt_below_the_line(self):
        # "no Qt below this line" is stated in the layer map and was never
        # expressed as a rule.
        p = self.one({"store.py": "from PyQt6.QtGui import QColor\n"})
        self.assertTrue(any("store" in x and "PyQt6" in x for x in p), p)
        # ...but numpy at layer 1 is expected and must not trip it.
        self.assertEqual(self.one({"store.py": "import numpy as np\n"}), [])

    def test_qt_allowed_above_the_line(self):
        self.assertEqual(
            self.one({"palette.py": "from PyQt6.QtGui import QColor\n"}), [])

    def test_init_must_not_import_submodules(self):
        # __init__ runs on every `import amdgraph.x`, so this would drag Qt in
        # ahead of __main__'s dependency check.
        p = self.one({"__init__.py": "from .window import Main\n"})
        self.assertTrue(any("__init__" in x and "window" in x for x in p), p)

    def test_init_must_not_import_qt(self):
        p = self.one({"__init__.py": "import PyQt6\n"})
        self.assertTrue(any("__init__" in x for x in p), p)

    def test_unknown_module_reported_not_raised(self):
        # Previously a KeyError with a traceback instead of a finding.
        p = self.one({"sysfs.py": "from .newthing import x\n"})
        self.assertTrue(any("newthing" in x for x in p), p)

    def test_dotted_relative_import(self):
        p = self.one({"sysfs.py": "from .sub.thing import x\n"})
        self.assertTrue(any("sub" in x for x in p), p)

    def test_from_dot_import_of_an_attribute_is_not_an_edge(self):
        # `from . import HELP` pulls a string out of __init__, not a module.
        # Reporting unknown names as violations made this a false positive.
        self.assertEqual(
            self.one({"window.py": "from . import HELP\n"}), [])

    def test_from_dot_import_of_a_module_is_an_edge(self):
        p = self.one({"sysfs.py": "from . import palette\n"})
        self.assertTrue(any("sysfs" in x and "palette" in x for x in p), p)

    def test_allowed_same_layer_edge(self):
        self.assertEqual(self.one({"chart.py": "from .timepane import P\n"}), [])

    def test_same_layer_edge_is_directional(self):
        # timepane -> chart is the wrong way round even though chart ->
        # timepane is allowed.
        p = self.one({"timepane.py": "from .chart import C\n"})
        self.assertTrue(any("timepane" in x for x in p), p)

    def test_upward_import_is_fine(self):
        self.assertEqual(self.one({"window.py": "from .sysfs import x\n"}), [])


if __name__ == "__main__":
    unittest.main()
