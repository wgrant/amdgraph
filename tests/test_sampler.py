"""Sampler: composing backends/, not any one backend's decode.

Per-backend guards and decode logic have their own test_backend_*.py files;
what belongs here is what Sampler itself is responsible for -- discovery
order, notes() aggregation, meta()'s default, and that a real exceptional
condition (captured once via RecordingFS) replays deterministically through
the composed Sampler, unmodified.
"""

import struct

import pytest
from conftest import gm_blob, pm_blob

from amdgraph import fields
from amdgraph.backends import amdgpu, host, zen_smu
from amdgraph.fields import PM_VER_SUPPORTED
from amdgraph.sampler import Sampler
from amdgraph.sysfs import HWMON, ReplayFS


class TestComposition:
    def test_host_backend_always_present(self):
        s = Sampler(fs=ReplayFS({}))
        try:
            assert any(isinstance(b, host.HostBackend) for b in s.backends)
        finally:
            s.close()

    def test_meta_defaults_pm_table_version_when_unsupported(self):
        s = Sampler(fs=ReplayFS({}))
        try:
            assert s.meta() == {"pm_table_version": "none"}
        finally:
            s.close()

    def test_meta_is_overwritten_when_zen_smu_applies(self):
        log = {
            ("bytes", fields.PM_VERSION): [struct.pack("<I", PM_VER_SUPPORTED)],
            ("bytes", fields.PM_TABLE): [pm_blob({})],
        }
        s = Sampler(fs=ReplayFS(log))
        try:
            assert s.meta() == {"pm_table_version": "0x004c0009"}
        finally:
            s.close()


class TestReplayThroughSampler:
    """The point of the whole exercise: a real machine's exceptional
    conditions, captured once via RecordingFS, replay through the
    unmodified Sampler deterministically -- proving the guard holds a second
    time without needing the hardware to misbehave again.

    No AMD device in either log: that keeps ThrottleSampler's background
    thread out of the picture (gm_ok stays False, so it never starts), which
    is what makes replay through the real Sampler deterministic here.
    """

    def base_log(self):
        return {
            ("bytes", fields.PM_VERSION): [struct.pack("<I", PM_VER_SUPPORTED)],
            ("glob", fields.DRM_DEVICES): [[]],
            ("listdir", HWMON): [[]],
        }

    def test_smu_disappearing_mid_session_degrades_not_crashes(self):
        """Shape of a real incident: ryzen_smu gets rmmod'd (or the SMU
        driver hiccups) after the version guard already passed, so pm_table
        reads start failing on a Sampler that believes it is fine."""
        good = pm_blob({0: 30.0, 1: 20.0})
        log = self.base_log()
        log[("bytes", fields.PM_TABLE)] = [good, None, good]
        s = Sampler(fs=ReplayFS(log))
        try:
            assert any(isinstance(b, zen_smu.ZenSmuBackend) for b in s.backends)
            assert s.sample()["stapm"] == pytest.approx(20.0)
            assert "stapm" not in s.sample()      # the miss: no key, no crash
            assert s.sample()["stapm"] == pytest.approx(20.0)
        finally:
            s.close()

    def test_gpu_metrics_version_seen_live_still_refuses_on_replay(self):
        """A layout this build does not decode, captured from a real part
        (v2_2 -- Renoir), replays as the same refusal it got live."""
        dev = "/sys/class/drm/card0/device"
        seen_live = gm_blob(fmt_rev=2, cont_rev=2)
        log = self.base_log()
        log[("glob", fields.DRM_DEVICES)] = [[dev]]
        log[("text", f"{dev}/vendor")] = [fields.AMD_VENDOR]
        log[("bytes", f"{dev}/gpu_metrics")] = [seen_live]
        s = Sampler(fs=ReplayFS(log))
        try:
            gpu_backends = [b for b in s.backends
                           if isinstance(b, amdgpu.AmdGpuBackend)]
            assert gpu_backends and not gpu_backends[0].gm_ok
            assert any("v2_2" in n for n in s.notes())
        finally:
            s.close()
