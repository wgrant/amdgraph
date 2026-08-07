"""Device discovery against synthetic /sys trees.

The card the program attaches to decides whether cap reasons work at all, and
getting it wrong is silent -- empty panes, no error. Worth pinning down every
shape of machine rather than the one on the desk.
"""

import os
import struct
import tempfile
import unittest

from amdgraph.sampler import Sampler
from amdgraph.sysfs import card_index, find_drm_device, read_num, read_text

AMD, INTEL = "0x1002", "0x8086"


def gm_blob(fmt_rev=2, cont_rev=1, size=120):
    return struct.pack("<HBB", size, fmt_rev, cont_rev) + b"\0" * (size - 4)


class Tree:
    """Builds /sys/class/drm/cardN/device/… under a temp dir."""

    def __init__(self, tmp):
        self.root = os.path.join(tmp, "drm")
        os.makedirs(self.root)

    def card(self, n, vendor=None, gm=None):
        dev = os.path.join(self.root, f"card{n}", "device")
        os.makedirs(dev)
        if vendor:
            with open(f"{dev}/vendor", "w") as f:
                f.write(vendor + "\n")
        if gm is not None:
            with open(f"{dev}/gpu_metrics", "wb") as f:
                f.write(gm)
        return dev

    @property
    def pattern(self):
        return os.path.join(self.root, "card[0-9]*", "device")


def decodable(dev):
    return Sampler._check_gpu_metrics(f"{dev}/gpu_metrics")[0]


class TestFindDrmDevice(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.t = Tree(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def find(self):
        return find_drm_device(self.t.pattern, AMD, decodable)

    def test_no_devices(self):
        self.assertIsNone(self.find())

    def test_intel_only_is_not_ours(self):
        self.t.card(0, INTEL, gm_blob())
        self.assertIsNone(self.find())

    def test_single_apu(self):
        want = self.t.card(1, AMD, gm_blob())
        self.assertEqual(self.find(), want)

    def test_amd_without_gpu_metrics_still_selected(self):
        # No cap reasons, but hwmon and DPM sensors still work, so the device
        # must still be found rather than discarded.
        want = self.t.card(0, AMD)
        self.assertEqual(self.find(), want)

    def test_prefers_the_decodable_one(self):
        # The case the preference exists for: a discrete Radeon also publishes
        # gpu_metrics, in a v1_x layout. Testing for the file's mere presence
        # picked whichever enumerated first; testing whether it decodes picks
        # the APU.
        self.t.card(0, AMD, gm_blob(fmt_rev=1, cont_rev=3, size=160))
        apu = self.t.card(1, AMD, gm_blob())
        self.assertEqual(self.find(), apu)

    def test_prefers_decodable_regardless_of_order(self):
        apu = self.t.card(0, AMD, gm_blob())
        self.t.card(1, AMD, gm_blob(fmt_rev=1, cont_rev=3, size=160))
        self.assertEqual(self.find(), apu)

    def test_falls_back_to_first_when_none_decode(self):
        first = self.t.card(0, AMD, gm_blob(fmt_rev=3, cont_rev=0, size=400))
        self.t.card(1, AMD, gm_blob(fmt_rev=3, cont_rev=0, size=400))
        self.assertEqual(self.find(), first)

    def test_connector_dirs_are_not_devices(self):
        # /sys/class/drm/card1-eDP-1/ matches a loose glob but has no vendor.
        os.makedirs(os.path.join(self.t.root, "card1-eDP-1", "device"))
        want = self.t.card(1, AMD, gm_blob())
        self.assertEqual(self.find(), want)

    def test_unreadable_vendor_is_skipped(self):
        self.t.card(0)                       # no vendor file at all
        want = self.t.card(1, AMD, gm_blob())
        self.assertEqual(self.find(), want)


class TestCardIndex(unittest.TestCase):
    def test_numeric_not_lexicographic(self):
        paths = [f"/sys/class/drm/card{n}/device" for n in (2, 10, 1)]
        got = [p.split("/")[-2] for p in sorted(paths, key=card_index)]
        self.assertEqual(got, ["card1", "card2", "card10"])


class TestReaders(unittest.TestCase):
    def test_missing_paths_are_none(self):
        self.assertIsNone(read_text("/sys/definitely/not/here"))
        self.assertIsNone(read_num("/sys/definitely/not/here"))

    def test_read_num_scales_and_rejects_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "v")
            with open(p, "w") as f:
                f.write("72000\n")
            self.assertEqual(read_num(p, 1000), 72.0)
            with open(p, "w") as f:
                f.write("not a number\n")
            self.assertIsNone(read_num(p))


if __name__ == "__main__":
    unittest.main()
