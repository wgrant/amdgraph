"""Shared fixtures.

Nothing here touches real hardware. Device discovery, the pm_table decode and
the version guards all run against synthetic trees and blobs under tmp_path, so
the suite is meaningful on a machine with no AMD part in it.
"""

import importlib.machinery
import importlib.util
import math
import os
import struct
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Under `uv run pytest` the project is installed and this is a no-op. It exists
# so the suite also runs from a bare checkout with apt-installed numpy/PyQt6 and
# a system pytest -- the same "clone it and run it" path the program itself
# supports.
if importlib.util.find_spec("amdgraph") is None:            # pragma: no cover
    sys.path.insert(0, os.path.join(ROOT, "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def load_tool(name):
    """Import a tools/ script that has no .py suffix."""
    path = os.path.join(ROOT, "tools", name)
    loader = importlib.machinery.SourceFileLoader(name.replace("-", "_"), path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def repo_root():
    return ROOT


@pytest.fixture(scope="session")
def check_layers():
    return load_tool("check-layers.py")


@pytest.fixture(scope="session")
def probe():
    return load_tool("amdgraph-probe")


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole run, or skip if Qt is not installed."""
    QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


# -- synthetic blobs -------------------------------------------------------

def gm_blob(fmt_rev=2, cont_rev=1, size=120, throttle=0, socket=20000,
            soc=2000, cores=(1000,) * 8):
    """A gpu_metrics blob with a chosen header, for the version guards."""
    from amdgraph import fields
    b = bytearray(size)
    struct.pack_into("<HBB", b, 0, size, fmt_rev, cont_rev)
    if size >= fields.GM_CORE_PWR_OFF + 16:
        struct.pack_into("<HHHH", b, fields.GM_PWR_OFF, socket, 0xFFFF, soc, 0)
        struct.pack_into("<8H", b, fields.GM_CORE_PWR_OFF, *cores)
    if size >= fields.GM_THROTTLE_OFF + 4:
        struct.pack_into("<I", b, fields.GM_THROTTLE_OFF, throttle)
    return bytes(b)


def pm_blob(values):
    """A 704-float pm_table with the given indices set."""
    a = [0.0] * 704
    for i, v in values.items():
        a[i] = v
    return struct.pack("<704f", *a)


@pytest.fixture
def store():
    """A deterministic recording: no clock, no RNG, no hardware."""
    from amdgraph.store import Store
    st = Store()
    for i in range(200):
        st.append(i * 0.5, {
            "stapm": 15.0 + 5.0 * math.sin(i / 9.0),
            "stapm_lim": 30.0,
            "ppt_fast": 12.0, "ppt_fast_lim": 30.0,
            "ppt_slow": 14.0, "ppt_slow_lim": 25.0,
            "tctl": 60.0 + i % 20, "tctl_lim": 100.0,
            "pwr_socket": 20.0, "pwr_soc": 2.0, "core_power_sum": 14.0,
            "thr0": (i % 5) / 5.0, "thr11": 1.0 if i % 3 else 0.0,
            "core_freq_max": 2600.0, "core_freq_mean": 1800.0,
            **{f"core_freq_{c}": 1000.0 + 200 * c for c in range(8)},
            **{f"core_c0_{c}": float(c * 10) for c in range(8)},
        })
    return st


@pytest.fixture
def view(store):
    from amdgraph.view import View
    v = View(store)
    v.window = 300.0
    v.update_range()
    return v
