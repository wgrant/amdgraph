"""The probe is the thing that gets run on hardware nobody here has.

It has no chance to be debugged interactively on a Steam Deck, so its failure
modes are worth pinning down: it must never invent a value, and its answers
have to survive a machine that lacks whatever it is looking for.
"""

import base64
import json
import os
import struct
import tempfile
import unittest

from tests import load_tool

P = load_tool("amdgraph-probe")


class TestReadText(unittest.TestCase):
    def test_missing_is_none_not_a_message(self):
        """Regression: this returned "<No such file or directory>", which is
        truthy, and poisoned every `if value:` downstream."""
        self.assertIsNone(P.read_text("/sys/definitely/not/here"))
        self.assertIsNone(P.read_bytes("/sys/definitely/not/here"))

    def test_reads_and_strips(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "v")
            open(p, "w").write("  hello \n")
            self.assertEqual(P.read_text(p), "hello")


class TestTopology(unittest.TestCase):
    """The L3 grouping is the only reliable view of CCX boundaries, and the
    flat eight-core assumption is wrong on Granite Ridge and Strix Halo. A
    wrong answer here is worse than no answer."""

    def test_real_machine_is_self_consistent(self):
        t = P.topology()
        self.assertGreaterEqual(t["physical_cores"], 1)
        listed = sum(len(g["cpus"]) for g in t["l3_groups"])
        if t["l3_groups"]:
            self.assertEqual(listed, os.cpu_count())
            self.assertEqual(t["ccx_count"], len(t["l3_groups"]))

    def test_no_group_is_keyed_by_an_error_string(self):
        for g in P.topology()["l3_groups"]:
            self.assertNotIn("<", g["shared_cpu_list"])

    def test_absent_l3_reports_unknown_rather_than_one(self):
        """With cache/index3 missing the old code put every CPU in a single
        group keyed by the error string and reported ccx_count 1 -- a
        confidently wrong answer for exactly the field that matters."""
        real = P.read_text

        def no_l3(path):
            return None if "cache/index3" in path else real(path)

        P.read_text = no_l3
        try:
            t = P.topology()
        finally:
            P.read_text = real
        self.assertEqual(t["l3_groups"], [])
        self.assertIsNone(t["ccx_count"])
        self.assertGreaterEqual(t["physical_cores"], 1)   # still counted


class TestCardsAndCounters(unittest.TestCase):
    def test_only_amd_devices_are_reported(self):
        for c in P.amdgpu_cards():
            self.assertEqual(c["vendor"], "0x1002")
            self.assertTrue(os.path.isdir(c["path"]))

    def test_gpu_metrics_header_is_decoded_when_present(self):
        for c in P.amdgpu_cards():
            gm = c["gpu_metrics"]
            if gm:
                self.assertRegex(gm["note"], r"^gpu_metrics_v\d+_\d+$")
                self.assertGreater(gm["actual_size"], 0)

    def test_counter_inventory_shape(self):
        c = P.counter_sources()
        self.assertIn("perf_pmus", c)
        self.assertIsInstance(c["euid"], int)
        for name, info in c["powercap"].items():
            # A domain whose name is unreadable must be skipped, not recorded
            # with an error string standing in for the name.
            self.assertIsInstance(info["name"], str)
            self.assertNotIn("<", info["name"])
            self.assertIsInstance(info["energy_readable"], bool)


class TestCapture(unittest.TestCase):
    def test_blobs_round_trip_through_base64(self):
        samples = P.capture(2, 0.0, P.amdgpu_cards()[0]["path"]
                            if P.amdgpu_cards() else None)
        self.assertEqual(len(samples), 2)
        for s in samples:
            if "pm_table" in s:
                raw = base64.b64decode(s["pm_table"])
                self.assertEqual(len(raw) % 4, 0)
                struct.unpack(f"<{len(raw) // 4}f", raw)
            if "gpu_metrics" in s:
                self.assertGreaterEqual(
                    len(base64.b64decode(s["gpu_metrics"])), 4)

    def test_no_trailing_sleep(self):
        import time
        t0 = time.monotonic()
        P.capture(1, 5.0, None)
        self.assertLess(time.monotonic() - t0, 1.0)

    def test_whole_document_is_json_serialisable(self):
        doc = {
            "cpu": P.cpu_identity(), "topology": P.topology(),
            "smu": P.smu_info(), "drm_cards": P.amdgpu_cards(),
            "hwmon": P.hwmon_inventory(), "platform": P.platform_layer(),
            "counters": P.counter_sources(),
        }
        text = json.dumps(doc)
        self.assertGreater(len(text), 200)
        self.assertNotIn("<No such file", text)
        self.assertIn("codename_enum_index", text)
        self.assertIn("drv_version", text)


if __name__ == "__main__":
    unittest.main()
