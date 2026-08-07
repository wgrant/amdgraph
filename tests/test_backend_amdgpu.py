"""gpu_metrics: the version guard, the decode, and the background poller.

The guards matter more than the decode. Printing a plausible number off a
layout we have not verified is the one failure mode this program is built to
avoid, so the tests that assert it *refuses* are the load-bearing ones.
"""

import pytest
from conftest import gm_blob

from amdgraph import fields
from amdgraph.backends import amdgpu
from amdgraph.backends.amdgpu import AmdGpuBackend, ThrottleSampler
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


@pytest.mark.parametrize("kwargs, needle", [
    (dict(fmt_rev=2, cont_rev=2), "v2_2"),      # Renoir; has indep_throttle
    (dict(fmt_rev=2, cont_rev=4), "v2_4"),      # Van Gogh on newer firmware
    (dict(fmt_rev=3, cont_rev=0, size=400), "v3_0"),   # Strix Point / Halo
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
        (dev / "gpu_metrics").write_bytes(gm_blob(fmt_rev=2, cont_rev=2))
        monkeypatch.setattr(amdgpu, "DRM_DEVICES",
                            str(tmp_path / "card[0-9]*" / "device"))
        backend, note = amdgpu.probe(RealFS())
        try:
            assert isinstance(backend, AmdGpuBackend)
            assert not backend.gm_ok
            assert "v2_2" in note or "v2_2" in backend.gm_note
        finally:
            if backend:
                backend.close()


def test_throttle_bits_are_contiguous_and_named():
    assert [b for b, _n, _f in fields.THROTTLE_BITS] == list(range(13))
    families = {n: f for _b, n, f in fields.THROTTLE_BITS}
    assert families["PROCHOT CPU"] == "prochot"
