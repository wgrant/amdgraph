"""gpu_metrics: the version guard, the decode, and the background poller.

The guards matter more than the decode. Printing a plausible number off a
layout we have not verified is the one failure mode this program is built to
avoid, so the tests that assert it *refuses* are the load-bearing ones.
"""

import time

import pytest
from conftest import gm_blob, gm3_blob

from amdgraph import fields
from amdgraph.backends import amdgpu
from amdgraph.backends.amdgpu import AmdGpuBackend, ThrottleSampler
from amdgraph.gpu_metrics import v2
from amdgraph.sysfs import RealFS


@pytest.fixture
def check_gm(tmp_path):
    def run(blob):
        p = tmp_path / "gpu_metrics"
        p.write_bytes(blob)
        return amdgpu.check_gpu_metrics(str(p), RealFS())
    return run


def test_accepts_the_verified_layout(check_gm):
    ok, note = check_gm(gm_blob())
    assert ok and note == ""


def test_accepts_renoir_gpu_metrics_v2_2(check_gm):
    ok, note = check_gm(gm_blob(fmt_rev=2, cont_rev=2,
                                size=fields.GM2_2_SIZE))
    assert ok and note == ""


def test_accepts_strix_gpu_metrics_v3(check_gm):
    ok, note = check_gm(gm3_blob())
    assert ok and note == ""


@pytest.mark.parametrize("kwargs, needle", [
    (dict(fmt_rev=2, cont_rev=4), "v2_4"),      # Van Gogh on newer firmware
    (dict(fmt_rev=2, cont_rev=2, size=120), "v2_2"),  # v2_2 declared too small
    (dict(fmt_rev=3, cont_rev=0, size=400), "v3_0"),   # wrong v3_0 size
    (dict(fmt_rev=1, cont_rev=3, size=160), "v1_3"),   # a discrete part
])
def test_rejects_layouts_we_have_not_verified(check_gm, kwargs, needle):
    ok, note = check_gm(gm_blob(**kwargs))
    assert not ok
    assert needle in note


def test_rejects_right_version_wrong_size(check_gm):
    assert not check_gm(gm_blob(size=160))[0]


@pytest.mark.parametrize("path", ["/nope/gpu_metrics", None])
def test_rejects_absent(path):
    assert not amdgpu.check_gpu_metrics(path, RealFS())[0]


def test_rejects_truncated(check_gm):
    assert not check_gm(b"\x01")[0]


class TestThrottleSampler:
    def test_no_path_means_no_thread(self):
        """Regression: the toolbar's cap-poll dropdown calls set_rate(), which
        calls start(). Gating only at construction let a rate change revive a
        poller for a layout the program had already refused to decode, reading
        it at up to 50 Hz forever."""
        t = ThrottleSampler(None, hz=20.0)
        t.start()
        assert t._thread is None
        t.set_rate(50.0)
        assert t._thread is None

    def test_one_hz_means_no_thread(self):
        t = ThrottleSampler("/dev/null", hz=1.0)
        t.start()
        assert t._thread is None

    def test_drain_is_empty_before_any_sample(self):
        duty, raw, n, pwr = ThrottleSampler(None).drain()
        assert duty is None
        assert (raw, n, pwr) == (0, 0, None)

    def test_undecodable_layout_leaves_the_poller_disarmed(self):
        """AmdGpuBackend hands the poller a path only when the check passed
        -- the one choke point every caller goes through."""
        backend = AmdGpuBackend.__new__(AmdGpuBackend)
        gpu_metrics = "/sys/class/drm/card0/device/gpu_metrics"
        backend.throttle = ThrottleSampler(None)      # gm_ok was False
        backend.throttle.set_rate(50.0)
        assert backend.throttle._thread is None


class TestProbe:
    def test_no_device_reports_and_declines(self, monkeypatch):
        monkeypatch.setattr(amdgpu, "DRM_DEVICES", "/nope/card[0-9]*/device")
        backend, note = amdgpu.probe(RealFS())
        assert backend is None
        assert "no amdgpu device" in note

    def test_device_without_decodable_metrics_still_gets_a_backend(
            self, tmp_path, monkeypatch):
        """No cap reasons, but hwmon and DPM sensors still work, so the
        device must be kept rather than discarded."""
        dev = tmp_path / "card0" / "device"
        dev.mkdir(parents=True)
        (dev / "vendor").write_text(fields.AMD_VENDOR + "\n")
        (dev / "gpu_metrics").write_bytes(gm_blob(fmt_rev=2, cont_rev=4))
        monkeypatch.setattr(amdgpu, "DRM_DEVICES",
                            str(tmp_path / "card[0-9]*" / "device"))
        backend, note = amdgpu.probe(RealFS())
        try:
            assert isinstance(backend, AmdGpuBackend)
            assert not backend.gm_ok
            assert "v2_4" in note or "v2_4" in backend.gm_note
        finally:
            if backend:
                backend.close()


def test_throttle_bits_are_contiguous_and_named():
    assert [b for b, _n, _f in fields.THROTTLE_BITS] == list(range(13))
    families = {n: f for _b, n, f in fields.THROTTLE_BITS}
    assert families["PROCHOT CPU"] == "prochot"


def test_indep_throttle_bits_match_throttle_bits_by_row():
    """Same thirteen reasons, same order and names as the Phoenix table --
    the panes key off THROTTLE_BITS, so a row can only move if both move."""
    assert len(fields.INDEP_THROTTLE_BITS) == len(fields.THROTTLE_BITS)
    assert ([n for _b, n, _f in fields.INDEP_THROTTLE_BITS]
            == [n for _b, n, _f in fields.THROTTLE_BITS])
    assert ([f for _b, _n, f in fields.INDEP_THROTTLE_BITS]
            == [f for _b, _n, f in fields.THROTTLE_BITS])
    # The FPPT row is the one confirmed live (indep mask 0x20 with ASIC bit 1
    # set): it must be SMU_THROTTLER_FPPT_BIT, 5.
    assert fields.INDEP_THROTTLE_BITS[1][0] == 5
    assert fields.INDEP_THROTTLE_BITS[4][0] == 33   # THM core, TEMP_CORE_BIT
    assert len({b for b, _n, _f in fields.INDEP_THROTTLE_BITS}) == 13


def test_decodes_strix_v3_and_differences_residencies(tmp_path):
    path = tmp_path / "gpu_metrics"
    path.write_bytes(gm3_blob())
    backend = AmdGpuBackend(str(tmp_path), str(path), True, "", RealFS())
    try:
        first = {}
        backend._metrics_v3(first, RealFS())
        assert first["pwr_socket"] == pytest.approx(70.0)
        assert first["pwr_ipu"] == pytest.approx(5.0)
        assert first["pwr_system"] == pytest.approx(50.0)
        assert first["thm_gfx"] == pytest.approx(55.0)
        assert first["vcn_busy"] == 3.0
        assert first["ipu_busy_7"] == 17.0
        assert first["ipu_busy_mean"] == pytest.approx(13.5)
        assert first["core_temp_15"] == pytest.approx(40.15)
        assert first["core_power_sum"] == pytest.approx(40.0)
        assert first["dram_rd"] == pytest.approx(2.0)
        assert first["ipu_rd"] == pytest.approx(0.5)
        assert first["ipu_wr"] == pytest.approx(0.25)
        assert first["core_freq_15"] == 3015.0
        assert first["core_freq_limit"] == 5100.0
        assert first["gfx_clk_max"] == 2900.0
        assert first["stapm_lim"] == pytest.approx(55.0)
        assert "thr0" not in first

        path.write_bytes(gm3_blob(residencies=(0, 10, 0, 4, 0, 0, 0)))
        second = {}
        backend._metrics_v3(second, RealFS())
        assert second["thr0"] == 1.0       # SPL advanced
        assert second["thr1"] == 0.0       # FPPT did not
        assert second["thr2"] == 1.0       # SPPT advanced
    finally:
        backend.close()


def test_strix_v3_keeps_verified_pm_per_core_values(tmp_path):
    """The PM C0/C1/C6 blocks are one synchronized 100% partition. When that
    backend ran first, replacing C0 with a later gpu_metrics read broke the
    identity even though each individual source was correct."""
    path = tmp_path / "gpu_metrics"
    path.write_bytes(gm3_blob())
    backend = AmdGpuBackend(str(tmp_path), str(path), True, "", RealFS())
    try:
        out = {"core_c0_0": 12.5, "core_c0_mean": 20.0,
               "core_power_0": 1.25, "core_power_sum": 10.0,
               "core_temp_0": 42.5, "core_freq_0": 4321.0,
               "core_freq_mean": 3000.0, "core_freq_max": 4321.0}
        backend._metrics_v3(out, RealFS())
        assert out["core_c0_0"] == 12.5
        assert out["core_c0_mean"] == 20.0
        assert out["core_power_0"] == 1.25
        assert out["core_power_sum"] == 10.0
        assert out["core_temp_0"] == 42.5
        assert out["core_freq_0"] == 4321.0
        assert out["core_freq_mean"] == 3000.0
        assert out["core_freq_max"] == 4321.0
    finally:
        backend.close()


def test_strix_ipu_power_is_u16_not_ipu_plus_padding(tmp_path):
    path = tmp_path / "gpu_metrics"
    raw = bytearray(gm3_blob())
    # Zero power followed by the ABI's unavailable/padding marker used to be
    # unpacked together as 0xFFFF0000 and displayed as 4.29 million watts.
    raw[fields.GM3_IPU_PWR_OFF:fields.GM3_IPU_PWR_OFF + 4] = \
        b"\x00\x00\xff\xff"
    path.write_bytes(raw)
    backend = AmdGpuBackend(str(tmp_path), str(path), True, "", RealFS())
    try:
        out = {}
        backend._metrics_v3(out, RealFS())
        assert out["pwr_ipu"] == 0.0
    finally:
        backend.close()


def test_renoir_v2_2_poller_counts_indep_bits(tmp_path):
    """The v2_2 poller must test the SMU_THROTTLER positions, not the
    ASIC-dependent 0-12: the live-captured shape (ASIC FPPT bit 1 with indep
    mask 0x20) has to land on the FPPT row."""
    path = tmp_path / "gpu_metrics"
    path.write_bytes(gm_blob(fmt_rev=2, cont_rev=2, size=fields.GM2_2_SIZE,
                             throttle=0x02, indep=1 << 5))
    t = ThrottleSampler(str(path), hz=200.0, bits=fields.INDEP_THROTTLE_BITS,
                        reader=v2.indep_throttle_status)
    t.start()
    try:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            duty, raw, n, _pwr = t.drain()
            if n:
                assert raw == 1 << 5
                assert duty[1] == 1.0     # FPPT row
                assert duty[0] == 0.0     # SPL row
                return
            time.sleep(0.002)
    finally:
        t.stop()
    pytest.fail("poller never sampled")


def test_renoir_v2_2_backend_wires_indep_reader_and_w_socket(tmp_path):
    path = tmp_path / "gpu_metrics"
    path.write_bytes(gm_blob(fmt_rev=2, cont_rev=2, size=fields.GM2_2_SIZE,
                             throttle=0x02, indep=1 << 5,
                             socket=10, soc=1219, cores=(1500,) * 8))
    backend = AmdGpuBackend(str(tmp_path), str(path), True, "", RealFS())
    try:
        assert backend.gm_version == (2, 2)
        backend.throttle.stop()          # force the instantaneous fallback
        out = {}
        backend._throttle(out, RealFS())
        assert out["thr1"] == 1.0        # FPPT row from indep bit 5
        assert out["thr0"] == 0.0        # SPL row from indep bit 4
        assert out["throttle_raw"] == float(1 << 5)
        # Socket power is W on v2_2: the backend must have passed 1.0 rather
        # than the milliwatt default.
        blob = gm_blob(fmt_rev=2, cont_rev=2, size=fields.GM2_2_SIZE,
                       socket=10)
        assert backend.throttle._power_fn(blob)["pwr_socket"] == 10.0
    finally:
        backend.close()
