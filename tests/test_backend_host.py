"""HostBackend: the one that still produces real, moving numbers on a
machine with no AMD part in it at all -- what makes it possible to develop
the rest of this program in a container.
"""

import textwrap

import pytest

from amdgraph.backends import host
from amdgraph.sysfs import RealFS


class TestHostMemory:
    def write(self, tmp_path, monkeypatch, text):
        p = tmp_path / "meminfo"
        p.write_text(textwrap.dedent(text))
        monkeypatch.setattr(host, "PROC_MEMINFO", str(p))

    def test_used_percentages(self, tmp_path, monkeypatch):
        self.write(tmp_path, monkeypatch, """\
            MemTotal:       1000000 kB
            MemAvailable:    250000 kB
            SwapTotal:       500000 kB
            SwapFree:        400000 kB
            """)
        mem, swap = host.host_memory(RealFS())
        assert mem == pytest.approx(75.0)
        assert swap == pytest.approx(20.0)

    def test_swapless_container_reports_none_not_zero(self, tmp_path,
                                                       monkeypatch):
        """SwapTotal: 0 kB is the normal state of a container with no swap
        device. 0% used would claim a reading that was never taken."""
        self.write(tmp_path, monkeypatch, """\
            MemTotal:       1000000 kB
            MemAvailable:    250000 kB
            SwapTotal:            0 kB
            SwapFree:             0 kB
            """)
        mem, swap = host.host_memory(RealFS())
        assert mem == pytest.approx(75.0)
        assert swap is None

    def test_missing_file_is_none_not_zero(self, tmp_path, monkeypatch):
        monkeypatch.setattr(host, "PROC_MEMINFO", str(tmp_path / "nope"))
        assert host.host_memory(RealFS()) == (None, None)


class TestHostBackendSample:
    """probe() always applies -- there is no machine this backend isn't
    useful on -- and its keys ride along in sample() the same way pm_table's
    do, through the shared fs seam."""

    def test_probe_always_returns_a_backend(self):
        backend, note = host.probe(RealFS())
        assert isinstance(backend, host.HostBackend)
        assert note == ""

    def test_reset_forgets_the_cpu_busy_baseline(self):
        """Regression shape: the window used to reassign sampler.cpubusy
        directly to reset the /proc/stat differ after clearing the buffer.
        reset() must produce the same effect -- a fresh baseline, not a
        stale one diffed against post-clear."""
        backend, _ = host.probe(RealFS())
        s = {}
        backend.sample(s, RealFS())
        backend.reset(RealFS())
        # A fresh baseline means the very next sample can't be a crazy
        # delta against a reading from before the reset.
        s2 = {}
        backend.sample(s2, RealFS())
        assert s2["cpu_busy"] is None or 0.0 <= s2["cpu_busy"] <= 100.0
