"""The probe is the thing that gets run on hardware nobody here has.

It has no chance to be debugged interactively on a Steam Deck, so its failure
modes are worth pinning down: it must never invent a value, and its answers
have to survive a machine that lacks whatever it is looking for.
"""

import base64
import json
import os
import struct
import time

import pytest


def test_missing_is_none_not_a_message(probe):
    """Regression: this returned "<No such file or directory>", which is
    truthy, and poisoned every `if value:` downstream."""
    assert probe.read_text("/sys/definitely/not/here") is None
    assert probe.read_bytes("/sys/definitely/not/here") is None


def test_reads_and_strips(probe, tmp_path):
    p = tmp_path / "v"
    p.write_text("  hello \n")
    assert probe.read_text(str(p)) == "hello"


class TestTopology:
    """The L3 grouping is the only reliable view of CCX boundaries, and the
    flat eight-core assumption is wrong on Granite Ridge and Strix Halo. A
    wrong answer here is worse than no answer."""

    def test_real_machine_is_self_consistent(self, probe):
        t = probe.topology()
        assert t["physical_cores"] >= 1
        if t["l3_groups"]:
            listed = sum(len(g["cpus"]) for g in t["l3_groups"])
            assert listed == os.cpu_count()
            assert t["ccx_count"] == len(t["l3_groups"])

    def test_no_group_is_keyed_by_an_error_string(self, probe):
        for g in probe.topology()["l3_groups"]:
            assert "<" not in g["shared_cpu_list"]

    def test_absent_l3_reports_unknown_rather_than_one(self, probe,
                                                       monkeypatch):
        """With cache/index3 missing the old code put every CPU in a single
        group keyed by the error string and reported ccx_count 1 -- a
        confidently wrong answer for exactly the field that matters."""
        real = probe.read_text
        monkeypatch.setattr(probe, "read_text",
                            lambda p: None if "cache/index3" in p else real(p))
        t = probe.topology()
        assert t["l3_groups"] == []
        assert t["ccx_count"] is None
        assert t["physical_cores"] >= 1          # still counted


class TestCardsAndCounters:
    def test_only_amd_devices_are_reported(self, probe):
        for c in probe.amdgpu_cards():
            assert c["vendor"] == "0x1002"
            assert os.path.isdir(c["path"])

    def test_gpu_metrics_header_is_decoded_when_present(self, probe):
        for c in probe.amdgpu_cards():
            if c["gpu_metrics"]:
                assert c["gpu_metrics"]["note"].startswith("gpu_metrics_v")
                assert c["gpu_metrics"]["actual_size"] > 0

    def test_counter_inventory_shape(self, probe):
        c = probe.counter_sources()
        assert "perf_pmus" in c
        assert isinstance(c["euid"], int)
        for info in c["powercap"].values():
            # A domain whose name is unreadable must be skipped, not recorded
            # with an error string standing in for the name.
            assert isinstance(info["name"], str) and "<" not in info["name"]
            assert isinstance(info["energy_readable"], bool)


class TestCapture:
    def test_blobs_round_trip_through_base64(self, probe):
        cards = probe.amdgpu_cards()
        samples = probe.capture(2, 0.0, cards[0]["path"] if cards else None)
        assert len(samples) == 2
        for s in samples:
            if "pm_table" in s:
                raw = base64.b64decode(s["pm_table"])
                assert len(raw) % 4 == 0
                struct.unpack(f"<{len(raw) // 4}f", raw)
            if "gpu_metrics" in s:
                assert len(base64.b64decode(s["gpu_metrics"])) >= 4

    def test_no_trailing_sleep(self, probe):
        t0 = time.monotonic()
        probe.capture(1, 5.0, None)
        assert time.monotonic() - t0 < 1.0

    def test_whole_document_is_json_serialisable(self, probe):
        doc = {
            "cpu": probe.cpu_identity(), "topology": probe.topology(),
            "smu": probe.smu_info(), "drm_cards": probe.amdgpu_cards(),
            "hwmon": probe.hwmon_inventory(),
            "platform": probe.platform_layer(),
            "counters": probe.counter_sources(),
        }
        text = json.dumps(doc)
        assert len(text) > 200
        assert "<No such file" not in text
        assert "codename_enum_index" in text
        assert "drv_version" in text


def test_probe_needs_no_third_party_packages(probe, repo_root):
    """It has to run on a bare install with nothing but CPython."""
    import ast
    src = open(os.path.join(repo_root, "tools", "amdgraph-probe")).read()
    roots = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            roots.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            roots.add(n.module.split(".")[0])
    assert not (roots - set(sys_stdlib()))


def sys_stdlib():
    import sys
    return sys.stdlib_module_names
