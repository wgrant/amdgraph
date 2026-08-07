"""Device discovery against synthetic /sys trees.

The card the program attaches to decides whether cap reasons work at all, and
getting it wrong is silent -- empty panes, no error. Worth pinning down every
shape of machine rather than the one on the desk.
"""

import pytest
from conftest import gm_blob

from amdgraph.backends.amdgpu import check_gpu_metrics
from amdgraph.sysfs import (RealFS, RecordingFS, ReplayFS, card_index,
                            dpm_current, find_drm_device, find_hwmon,
                            read_num, read_text)

AMD, INTEL = "0x1002", "0x8086"
V1_X = dict(fmt_rev=1, cont_rev=3, size=160)      # a discrete Radeon
V3_0 = dict(fmt_rev=3, cont_rev=0, size=400)      # Strix Point / Strix Halo


def decodable(dev):
    return check_gpu_metrics(f"{dev}/gpu_metrics", RealFS())[0]


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


class TestFindHwmon:
    @pytest.fixture
    def hwmon(self, tmp_path):
        def build(**names):
            base = tmp_path / "hwmon"
            base.mkdir(exist_ok=True)
            for dirname, name in names.items():
                d = base / dirname
                d.mkdir()
                if name is not None:
                    (d / "name").write_text(name + "\n")
            return find_hwmon(str(base))
        return build

    def test_maps_name_to_directory(self, hwmon):
        got = hwmon(hwmon0="amdgpu", hwmon1="thinkpad", hwmon2="nvme")
        assert set(got) == {"amdgpu", "thinkpad", "nvme"}
        assert got["thinkpad"].endswith("hwmon1")

    def test_a_directory_with_no_name_is_skipped(self, hwmon):
        got = hwmon(hwmon0=None, hwmon1="amdgpu")
        assert list(got) == ["amdgpu"]
        assert got["amdgpu"].endswith("hwmon1")

    def test_lowest_index_wins_when_a_name_repeats(self, hwmon):
        """Two NVMe drives both register as `nvme`. Which one is plotted has to
        be decided by something: before the listing was sorted it came from
        os.listdir order, so it could differ between runs."""
        got = hwmon(hwmon2="nvme", hwmon0="nvme", hwmon1="amdgpu")
        assert got["nvme"].endswith("hwmon0")

    def test_double_digit_indices_sort_numerically(self, hwmon):
        got = hwmon(hwmon10="nvme", hwmon2="nvme")
        assert got["nvme"].endswith("hwmon2")

    def test_absent_base_is_empty_not_an_error(self):
        assert find_hwmon("/sys/definitely/not/here") == {}


class TestDpmCurrent:
    def write(self, tmp_path, text):
        p = tmp_path / "pp_dpm_sclk"
        p.write_text(text)
        return str(p)

    def test_reads_the_starred_level(self, tmp_path):
        p = self.write(tmp_path, "0: 200Mhz\n1: 800Mhz *\n2: 2700Mhz\n")
        assert dpm_current(p) == 800.0

    def test_no_star_is_none(self, tmp_path):
        assert dpm_current(self.write(tmp_path, "0: 200Mhz\n")) is None

    def test_absent_file_is_none(self):
        assert dpm_current("/sys/definitely/not/here") is None

    def test_malformed_line_is_none(self, tmp_path):
        assert dpm_current(self.write(tmp_path, "*\n")) is None


def test_missing_paths_are_none():
    assert read_text("/sys/definitely/not/here") is None
    assert read_num("/sys/definitely/not/here") is None


def test_read_num_scales_and_rejects_junk(tmp_path):
    p = tmp_path / "v"
    p.write_text("72000\n")
    assert read_num(str(p), 1000) == 72.0
    p.write_text("not a number\n")
    assert read_num(str(p)) is None


class TestRecordingReplay:
    """RecordingFS wraps a real read and logs it; ReplayFS serves the log
    back. Together they let a real machine's exceptional conditions -- a
    miss, a truncated blob, a device that stops enumerating -- be captured
    once and replayed deterministically forever, without the hardware."""

    def test_round_trips_text_bytes_glob_and_listdir(self, tmp_path):
        # A subdirectory, so nothing written by the test itself (like the
        # capture file below) shows up in what gets recorded or replayed.
        root = tmp_path / "sys"
        root.mkdir()
        (root / "temp1_input").write_text("45000\n")
        (root / "hwmon0").mkdir()
        (root / "hwmon1").mkdir()
        gm = gm_blob()

        rec = RecordingFS(RealFS())
        assert rec.read_text(str(root / "temp1_input")) == "45000"
        assert rec.read_bytes(str(root / "pm_table")) is None        # a miss
        (root / "pm_table").write_bytes(gm)
        assert rec.read_bytes(str(root / "pm_table")) == gm
        want_glob = sorted(rec.glob(str(root / "hwmon*")))
        want_listdir = sorted(rec.listdir(str(root)))
        assert want_glob == sorted(str(root / h) for h in ("hwmon0", "hwmon1"))
        assert want_listdir == sorted(f.name for f in root.iterdir())

        out = tmp_path / "capture.json"
        rec.save(str(out), host="test-host")
        replayed = ReplayFS.load(str(out))

        assert replayed.read_text(str(root / "temp1_input")) == "45000"
        assert replayed.read_bytes(str(root / "pm_table")) is None
        assert replayed.read_bytes(str(root / "pm_table")) == gm
        assert sorted(replayed.glob(str(root / "hwmon*"))) == want_glob
        assert sorted(replayed.listdir(str(root))) == want_listdir

    def test_exhausted_sequence_holds_the_last_value(self):
        fs = ReplayFS({("text", "/x"): ["1", "2", "3"]})
        assert [fs.read_text("/x") for _ in range(5)] == \
            ["1", "2", "3", "3", "3"]

    def test_unrecorded_path_reads_as_a_miss(self):
        fs = ReplayFS({})
        assert fs.read_text("/never/recorded") is None
        assert fs.read_bytes("/never/recorded") is None
        assert fs.glob("/never/recorded/*") == []
        assert fs.listdir("/never/recorded") == []

    def test_read_num_is_derived_from_read_text_on_every_backend(self):
        """FS.read_num is implemented once, in the base class -- a backend
        only has to get read_text right."""
        fs = ReplayFS({("text", "/v"): ["72000"]})
        assert fs.read_num("/v", 1000) == 72.0
