"""Acquisition: the version guards, the decode, and the background poller.

The guards matter more than the decode. Printing a plausible number off a
layout we have not verified is the one failure mode this program is built to
avoid, so the tests that assert it *refuses* are the load-bearing ones.
"""

import os
import struct
import tempfile
import unittest

from amdgraph import fields, sampler
from amdgraph.fields import GM_SIZE, N_CORES, PM_VER_SUPPORTED
from amdgraph.sampler import Sampler, ThrottleSampler


def gm_blob(fmt_rev=2, cont_rev=1, size=GM_SIZE, throttle=0, socket=20000,
            soc=2000, cores=(1000,) * 8):
    b = bytearray(size)
    struct.pack_into("<HBB", b, 0, size, fmt_rev, cont_rev)
    if size >= 56:
        struct.pack_into("<HHHH", b, fields.GM_PWR_OFF, socket, 0xFFFF, soc, 0)
        struct.pack_into("<8H", b, fields.GM_CORE_PWR_OFF, *cores)
    if size >= fields.GM_THROTTLE_OFF + 4:
        struct.pack_into("<I", b, fields.GM_THROTTLE_OFF, throttle)
    return bytes(b)


def pm_blob(values):
    a = [0.0] * 704
    for i, v in values.items():
        a[i] = v
    return struct.pack("<704f", *a)


class TestGpuMetricsGuard(unittest.TestCase):
    """A layout we have not verified must be refused, with a note naming it."""

    def check(self, blob):
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(blob)
            path = f.name
        self.addCleanup(os.unlink, path)
        return Sampler._check_gpu_metrics(path)

    def test_accepts_the_verified_layout(self):
        ok, note = self.check(gm_blob())
        self.assertTrue(ok)
        self.assertEqual(note, "")

    def test_rejects_newer_content_revision(self):
        ok, note = self.check(gm_blob(fmt_rev=2, cont_rev=2))
        self.assertFalse(ok)
        self.assertIn("v2_2", note)

    def test_rejects_v3_0(self):
        # Strix Point / Strix Halo. Different fields at every offset we use.
        ok, note = self.check(gm_blob(fmt_rev=3, cont_rev=0, size=400))
        self.assertFalse(ok)
        self.assertIn("v3_0", note)

    def test_rejects_right_version_wrong_size(self):
        ok, _ = self.check(gm_blob(size=160))
        self.assertFalse(ok)

    def test_rejects_truncated_and_absent(self):
        self.assertFalse(self.check(b"\x01")[0])
        self.assertFalse(Sampler._check_gpu_metrics("/nope/gpu_metrics")[0])
        self.assertFalse(Sampler._check_gpu_metrics(None)[0])


class TestThrottleSampler(unittest.TestCase):
    def test_no_path_means_no_thread(self):
        """Regression: the toolbar's cap-poll dropdown calls set_rate(), which
        calls start(). Gating only at construction let a rate change revive a
        poller for a layout the program had already refused to decode, reading
        it at up to 50 Hz forever."""
        t = ThrottleSampler(None, hz=20.0)
        t.start()
        self.assertIsNone(t._thread)
        t.set_rate(50.0)
        self.assertIsNone(t._thread)
        self.addCleanup(t.stop)

    def test_one_hz_means_no_thread(self):
        t = ThrottleSampler("/dev/null", hz=1.0)
        t.start()
        self.assertIsNone(t._thread)

    def test_drain_is_empty_before_any_sample(self):
        duty, raw, n, pwr = ThrottleSampler(None).drain()
        self.assertIsNone(duty)
        self.assertEqual((raw, n, pwr), (0, 0, None))

    def test_undecodable_layout_leaves_the_poller_disarmed(self):
        """The Sampler must hand the poller a path only when the check passed;
        that is the single choke point every caller goes through."""
        s = Sampler.__new__(Sampler)
        s.gm_ok = False
        s.gpu_metrics = "/sys/class/drm/card0/device/gpu_metrics"
        s.throttle = ThrottleSampler(s.gpu_metrics if s.gm_ok else None)
        s.throttle.set_rate(50.0)
        self.assertIsNone(s.throttle._thread)


class TestPmDecode(unittest.TestCase):
    def setUp(self):
        self.s = Sampler.__new__(Sampler)
        self.s.pm_ok = True

    def decode(self, values):
        blob = pm_blob(values)
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(blob)
            path = f.name
        self.addCleanup(os.unlink, path)
        old = sampler.PM_TABLE
        sampler.PM_TABLE = path
        try:
            out = {}
            self.s._pm(out)
            return out
        finally:
            sampler.PM_TABLE = old

    def test_scalars_and_scaling(self):
        s = self.decode({0: 30.0, 1: 20.5, 17: 72.3, 56: 2.7})
        self.assertAlmostEqual(s["stapm_lim"], 30.0)
        self.assertAlmostEqual(s["stapm"], 20.5, places=4)
        self.assertAlmostEqual(s["tctl"], 72.3, places=4)
        self.assertAlmostEqual(s["gfx_clk"], 2700.0, places=1)   # GHz -> MHz

    def test_per_core_aggregates(self):
        vals = {513 + i: float(i + 1) for i in range(N_CORES)}   # 1..8 W
        s = self.decode(vals)
        self.assertAlmostEqual(s["core_power_max"], 8.0)
        self.assertAlmostEqual(s["core_power_mean"], 4.5)
        self.assertAlmostEqual(s["core_power_sum"], 36.0)
        self.assertAlmostEqual(s["core_power_0"], 1.0)
        self.assertAlmostEqual(s["core_power_7"], 8.0)

    def test_headroom_is_limit_minus_value(self):
        s = self.decode({0: 30.0, 1: 20.0, 4: 25.0, 5: 24.0})
        self.assertAlmostEqual(s["stapm_head"], 10.0)
        self.assertAlmostEqual(s["ppt_slow_head"], 1.0)

    def test_disabled_when_version_unverified(self):
        self.s.pm_ok = False
        self.assertEqual(self.decode({0: 30.0}), {})


class TestFanCommand(unittest.TestCase):
    def fan(self, **files):
        tmp = tempfile.mkdtemp()
        for k, v in files.items():
            with open(os.path.join(tmp, k), "w") as f:
                f.write(str(v) + "\n")
        return Sampler._fan_command(tmp)

    def test_disengaged_sits_above_level_seven(self):
        self.assertEqual(self.fan(pwm1_enable=0, pwm1=255), (8.0, "FULL"))

    def test_firmware_auto_reports_no_level(self):
        # pwm1 still holds the last manual value, so the mode has to win.
        self.assertEqual(self.fan(pwm1_enable=2, pwm1=128), (None, "AUTO"))

    def test_manual_level_rescaled(self):
        self.assertEqual(self.fan(pwm1_enable=1, pwm1=255), (7, None))
        self.assertEqual(self.fan(pwm1_enable=1, pwm1=0), (0, None))

    def test_absent_interface(self):
        self.assertEqual(Sampler._fan_command("/nope"), (None, None))


class TestConstants(unittest.TestCase):
    def test_supported_versions_are_the_verified_ones(self):
        """Bumping either of these without re-validating the field map is the
        mistake this whole program is arranged to prevent."""
        self.assertEqual(PM_VER_SUPPORTED, 0x004C0009)
        self.assertEqual((fields.GM_VERSION, fields.GM_SIZE), ((2, 1), 120))

    def test_throttle_bits_are_contiguous_and_named(self):
        bits = [b for b, _n, _f in fields.THROTTLE_BITS]
        self.assertEqual(bits, list(range(13)))
        self.assertEqual(dict((n, f) for _b, n, f in
                              fields.THROTTLE_BITS)["PROCHOT CPU"], "prochot")


if __name__ == "__main__":
    unittest.main()
