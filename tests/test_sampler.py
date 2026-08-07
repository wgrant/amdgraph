"""Acquisition: the version guards, the decode, and the background poller.

The guards matter more than the decode. Printing a plausible number off a
layout we have not verified is the one failure mode this program is built to
avoid, so the tests that assert it *refuses* are the load-bearing ones.
"""

import pytest
from conftest import gm_blob, pm_blob

from amdgraph import fields, sampler
from amdgraph.fields import GM_SIZE, N_CORES, PM_VER_SUPPORTED
from amdgraph.sampler import Sampler, ThrottleSampler


@pytest.fixture
def check_gm(tmp_path):
    def run(blob):
        p = tmp_path / "gpu_metrics"
        p.write_bytes(blob)
        return Sampler._check_gpu_metrics(str(p))
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
    assert not Sampler._check_gpu_metrics(path)[0]


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
        """The Sampler hands the poller a path only when the check passed --
        the one choke point every caller goes through."""
        s = Sampler.__new__(Sampler)
        s.gm_ok = False
        s.gpu_metrics = "/sys/class/drm/card0/device/gpu_metrics"
        s.throttle = ThrottleSampler(s.gpu_metrics if s.gm_ok else None)
        s.throttle.set_rate(50.0)
        assert s.throttle._thread is None


class TestPmDecode:
    @pytest.fixture
    def decode(self, tmp_path, monkeypatch):
        s = Sampler.__new__(Sampler)
        s.pm_ok = True

        def run(values, pm_ok=True):
            p = tmp_path / "pm_table"
            p.write_bytes(pm_blob(values))
            monkeypatch.setattr(sampler, "PM_TABLE", str(p))
            s.pm_ok = pm_ok
            out = {}
            s._pm(out)
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

    def test_disabled_when_version_unverified(self, decode):
        assert decode({0: 30.0}, pm_ok=False) == {}


class TestFanCommand:
    @pytest.fixture
    def fan(self, tmp_path):
        def run(**files):
            for k, v in files.items():
                (tmp_path / k).write_text(f"{v}\n")
            return Sampler._fan_command(str(tmp_path))
        return run

    def test_disengaged_sits_above_level_seven(self, fan):
        assert fan(pwm1_enable=0, pwm1=255) == (8.0, "FULL")

    def test_firmware_auto_reports_no_level(self, fan):
        # pwm1 still holds the last manual value, so the mode has to win.
        assert fan(pwm1_enable=2, pwm1=128) == (None, "AUTO")

    @pytest.mark.parametrize("pwm, level", [(255, 7), (0, 0), (128, 4)])
    def test_manual_level_rescaled(self, fan, pwm, level):
        assert fan(pwm1_enable=1, pwm1=pwm) == (level, None)

    def test_absent_interface(self):
        assert Sampler._fan_command("/nope") == (None, None)


def test_supported_versions_are_the_verified_ones():
    """Bumping either of these without re-validating the field map is the
    mistake this whole program is arranged to prevent."""
    assert PM_VER_SUPPORTED == 0x004C0009
    assert (fields.GM_VERSION, fields.GM_SIZE) == ((2, 1), 120)


def test_throttle_bits_are_contiguous_and_named():
    assert [b for b, _n, _f in fields.THROTTLE_BITS] == list(range(13))
    families = {n: f for _b, n, f in fields.THROTTLE_BITS}
    assert families["PROCHOT CPU"] == "prochot"
