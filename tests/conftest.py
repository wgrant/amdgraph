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
def record():
    return load_tool("amdgraph-record")


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


def gm3_blob(residencies=(0,) * 7):
    """A naturally aligned gpu_metrics_v3_0 blob with known Strix values."""
    from amdgraph import fields
    b = bytearray(fields.GM3_SIZE)
    struct.pack_into("<HBB", b, 0, fields.GM3_SIZE, *fields.GM3_VERSION)
    struct.pack_into("<HH16HH", b, 4, 5500, 5000,
                     *range(4000, 4016), 4200)
    struct.pack_into("<HH8H16H4H", b, 42, 25, 3, *range(10, 18),
                     *range(16), 2048, 1024, 512, 256)
    struct.pack_into("<I", b, fields.GM3_SOCKET_PWR_OFF, 70000)
    struct.pack_into("<I", b, fields.GM3_IPU_PWR_OFF, 5000)
    struct.pack_into("<I", b, fields.GM3_APU_PWR_OFF, 65000)
    struct.pack_into("<I", b, fields.GM3_GFX_PWR_OFF, 12000)
    struct.pack_into("<I", b, fields.GM3_DGPU_PWR_OFF, 0)
    struct.pack_into("<I", b, fields.GM3_ALL_CORE_PWR_OFF, 40000)
    struct.pack_into("<16H", b, fields.GM3_CORE_PWR_OFF, *(2500,) * 16)
    struct.pack_into("<3H", b, 168, 50000, 60000, 55000)
    struct.pack_into("<8H", b, fields.GM3_CLOCKS_OFF,
                     1800, 900, 600, 1000, 2000, 800, 1000, 700)
    struct.pack_into("<16H", b, fields.GM3_CORE_CLOCK_OFF, *range(3000, 3016))
    struct.pack_into("<2H", b, 222, 5100, 2900)
    struct.pack_into("<7I", b, fields.GM3_RESIDENCY_OFF, *residencies)
    return bytes(b)


def pm_blob(values, size=704):
    """A pm_table of the chosen float width with the given indices set."""
    a = [0.0] * size
    for i, v in values.items():
        a[i] = v
    return struct.pack(f"<{size}f", *a)


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


# -- a source with no hardware behind it -----------------------------------

class FakeSource:
    """Implements Sampler's protocol and reads nothing.

    This is the whole point of the protocol existing: the window can be built
    and driven on a machine with no AMD part in it, and a second platform's
    backend is a class like this one with real reads behind it rather than a
    change to the window.
    """

    def __init__(self, notes=(), meta=None, keys=None):
        if keys is None:
            from amdgraph.panes import PANES
            keys = tuple(s.key for pane in PANES for s in pane.series)
            keys += ("thr0",)
        self._notes = list(notes)
        self._meta = dict(meta or {"pm_table_version": "0x004c0009"})
        self._keys = keys
        self.ticks = 0
        self.resets = 0
        self.closed = 0
        self.cap_rates = []

    def sample(self):
        self.ticks += 1
        # Deterministic and distinguishable per tick, so a test can tell which
        # sample landed where.
        return {k: float(self.ticks * 10 + i)
                for i, k in enumerate(self._keys)}

    def notes(self):
        return list(self._notes)

    def meta(self):
        return dict(self._meta)

    def set_cap_rate(self, hz):
        self.cap_rates.append(hz)

    def reset(self):
        self.resets += 1

    def close(self):
        self.closed += 1


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def main(qapp, source, tmp_path, monkeypatch):
    """A real Main over a fake source, with every modal neutered.

    A blocking dialog in a headless test is not a failure, it is a hang -- one
    already cost this project a stray process at 96% of a core for 36 minutes.
    """
    from PyQt6.QtWidgets import QInputDialog, QMessageBox

    from amdgraph import window as W

    # Never write to the user's real recordings directory.
    monkeypatch.setattr(W, "DATA_DIR", str(tmp_path / "recordings"))
    warned = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a[-1])))
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("a marker", True)))

    w = W.Main(interval=0.5, source=source)
    w.timer.stop()               # tests drive tick() by hand
    w.warned = warned
    yield w
    w.close()
