"""Device discovery against synthetic /sys trees.

The card the program attaches to decides whether cap reasons work at all, and
getting it wrong is silent -- empty panes, no error. Worth pinning down every
shape of machine rather than the one on the desk.
"""

import pytest
from conftest import gm_blob

from amdgraph.sampler import Sampler
from amdgraph.sysfs import card_index, find_drm_device, read_num, read_text

AMD, INTEL = "0x1002", "0x8086"
V1_X = dict(fmt_rev=1, cont_rev=3, size=160)      # a discrete Radeon
V3_0 = dict(fmt_rev=3, cont_rev=0, size=400)      # Strix Point / Strix Halo


def decodable(dev):
    return Sampler._check_gpu_metrics(f"{dev}/gpu_metrics")[0]


@pytest.fixture
def tree(tmp_path):
    """Builds /sys/class/drm/cardN/device/… under tmp_path."""
    root = tmp_path / "drm"
    root.mkdir()

    class Tree:
        pattern = str(root / "card[0-9]*" / "device")

        def card(self, n, vendor=None, gm=None):
            dev = root / f"card{n}" / "device"
            dev.mkdir(parents=True)
            if vendor:
                (dev / "vendor").write_text(vendor + "\n")
            if gm is not None:
                (dev / "gpu_metrics").write_bytes(gm)
            return str(dev)

        def find(self):
            return find_drm_device(self.pattern, AMD, decodable)

        def connector(self, name):
            (root / name / "device").mkdir(parents=True)

    return Tree()


def test_no_devices(tree):
    assert tree.find() is None


def test_intel_only_is_not_ours(tree):
    tree.card(0, INTEL, gm_blob())
    assert tree.find() is None


def test_single_apu(tree):
    want = tree.card(1, AMD, gm_blob())
    assert tree.find() == want


def test_amd_without_gpu_metrics_still_selected(tree):
    # No cap reasons, but hwmon and DPM sensors still work, so the device must
    # be found rather than discarded.
    want = tree.card(0, AMD)
    assert tree.find() == want


@pytest.mark.parametrize("apu_n, dgpu_n", [(1, 0), (0, 1)])
def test_prefers_the_decodable_one(tree, apu_n, dgpu_n):
    """The case the preference exists for. A discrete Radeon also publishes
    gpu_metrics, in a v1_x layout, so testing for the file's mere presence
    picked whichever enumerated first; testing whether it decodes picks the
    APU, either way round."""
    tree.card(dgpu_n, AMD, gm_blob(**V1_X))
    apu = tree.card(apu_n, AMD, gm_blob())
    assert tree.find() == apu


def test_falls_back_to_first_when_none_decode(tree):
    first = tree.card(0, AMD, gm_blob(**V3_0))
    tree.card(1, AMD, gm_blob(**V3_0))
    assert tree.find() == first


def test_connector_dirs_are_not_devices(tree):
    # /sys/class/drm/card1-eDP-1/ matches a loose glob but has no vendor.
    tree.connector("card1-eDP-1")
    want = tree.card(1, AMD, gm_blob())
    assert tree.find() == want


def test_unreadable_vendor_is_skipped(tree):
    tree.card(0)                            # no vendor file at all
    want = tree.card(1, AMD, gm_blob())
    assert tree.find() == want


def test_card_index_is_numeric_not_lexicographic():
    paths = [f"/sys/class/drm/card{n}/device" for n in (2, 10, 1)]
    got = [p.split("/")[-2] for p in sorted(paths, key=card_index)]
    assert got == ["card1", "card2", "card10"]


def test_missing_paths_are_none():
    assert read_text("/sys/definitely/not/here") is None
    assert read_num("/sys/definitely/not/here") is None


def test_read_num_scales_and_rejects_junk(tmp_path):
    p = tmp_path / "v"
    p.write_text("72000\n")
    assert read_num(str(p), 1000) == 72.0
    p.write_text("not a number\n")
    assert read_num(str(p)) is None
