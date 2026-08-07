"""pm_table: the version guard and the decode.

The guard matters more than the decode. Printing a plausible number off a
layout we have not verified is the one failure mode this program is built to
avoid, so the tests that assert it *refuses* are the load-bearing ones.
"""

import pytest
from conftest import pm_blob

from amdgraph import fields
from amdgraph.backends import zen_smu
from amdgraph.fields import N_CORES, PM_VER_SUPPORTED
from amdgraph.sysfs import RealFS


class TestPmDecode:
    @pytest.fixture
    def decode(self, tmp_path, monkeypatch):
        backend = zen_smu.ZenSmuBackend()

        def run(values):
            p = tmp_path / "pm_table"
            p.write_bytes(pm_blob(values))
            monkeypatch.setattr(zen_smu, "PM_TABLE", str(p))
            out = {}
            backend.sample(out, RealFS())
            return out
        return run

    def test_scalars_and_scaling(self, decode):
        s = decode({0: 30.0, 1: 20.5, 17: 72.3, 56: 2.7})
        assert s["stapm_lim"] == pytest.approx(30.0)
        assert s["stapm"] == pytest.approx(20.5, abs=1e-4)
        assert s["tctl"] == pytest.approx(72.3, abs=1e-4)
        assert s["gfx_clk"] == pytest.approx(2700.0, abs=0.1)    # GHz -> MHz

    def test_per_core_aggregates(self, decode):
        s = decode({513 + i: float(i + 1) for i in range(N_CORES)})  # 1..8 W
        assert s["core_power_max"] == pytest.approx(8.0)
        assert s["core_power_mean"] == pytest.approx(4.5)
        assert s["core_power_sum"] == pytest.approx(36.0)
        assert s["core_power_0"] == pytest.approx(1.0)
        assert s["core_power_7"] == pytest.approx(8.0)

    def test_headroom_is_limit_minus_value(self, decode):
        s = decode({0: 30.0, 1: 20.0, 4: 25.0, 5: 24.0})
        assert s["stapm_head"] == pytest.approx(10.0)
        assert s["ppt_slow_head"] == pytest.approx(1.0)


class TestProbe:
    def test_missing_driver_reports_and_declines(self, tmp_path, monkeypatch):
        monkeypatch.setattr(zen_smu, "PM_VERSION", str(tmp_path / "nope"))
        backend, note = zen_smu.probe(RealFS())
        assert backend is None
        assert "not loaded" in note

    def test_unsupported_version_reports_and_declines(self, tmp_path,
                                                       monkeypatch):
        p = tmp_path / "pm_table_version"
        p.write_bytes((0xDEADBEEF).to_bytes(4, "little"))
        monkeypatch.setattr(zen_smu, "PM_VERSION", str(p))
        backend, note = zen_smu.probe(RealFS())
        assert backend is None
        assert "0xdeadbeef" in note

    def test_supported_version_is_accepted(self, tmp_path, monkeypatch):
        p = tmp_path / "pm_table_version"
        p.write_bytes(PM_VER_SUPPORTED.to_bytes(4, "little"))
        monkeypatch.setattr(zen_smu, "PM_VERSION", str(p))
        backend, note = zen_smu.probe(RealFS())
        assert isinstance(backend, zen_smu.ZenSmuBackend)
        assert note == ""
        assert backend.meta() == {"pm_table_version": "0x004c0009"}


def test_supported_versions_are_the_verified_ones():
    """Bumping either of these without re-validating the field map is the
    mistake this whole program is arranged to prevent."""
    assert PM_VER_SUPPORTED == 0x004C0009
    assert (fields.GM_VERSION, fields.GM_SIZE) == ((2, 1), 120)
