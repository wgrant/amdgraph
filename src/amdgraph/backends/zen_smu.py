"""Layer 1 -- the SMU's pm_table, via ryzen_smu.

Sensor layouts are part-specific and undocumented, so this decodes only maps
checked against live silicon: Phoenix 0x004C0009 and Strix Halo 0x0064020C.
See fields.py for the evidence behind every index and docs/HARDWARE.md for what
adding another part involves.

May import: fields, sysfs, backends.base.
"""

import struct

from ..smu.pm_tables import (PHOENIX_VERSION, PROFILES, TABLE, VERSION_PATH)
from .base import Backend


class ZenSmuBackend(Backend):
    REQUIRES = ("core_count",)

    def __init__(self, version=PHOENIX_VERSION):
        self.version = version
        self.layout = PROFILES[version]
        self.scalars = self.layout.scalars
        self.cores = self.layout.cores
        self.ncores = self.layout.core_slots

    def metrics(self):
        from ..model import Metric, MetricKind
        keys = list(self.scalars)
        for base in self.cores:
            keys.extend(f"{base}_{i}" for i in range(self.ncores))
            keys.extend((f"{base}_mean", f"{base}_max"))
        keys.extend(("core_power_sum", "stapm_head", "ppt_slow_head",
                     "ppt_fast_head"))
        if self.layout.thermal_clusters:
            keys.extend(("tctl", "tctl_lim"))
        return tuple(Metric(key, kind=(MetricKind.PER_CORE
                                      if any(key.startswith(f"{base}_")
                                             for base in self.cores)
                                      else MetricKind.SCALAR))
                     for key in dict.fromkeys(keys))

    def sample(self, s, fs):
        raw = fs.read_bytes(TABLE)
        if raw is None:
            return
        n = len(raw) // 4
        v = struct.unpack(f"<{n}f", raw[:n * 4])

        for key, (idx, scale) in self.scalars.items():
            if idx < n:
                s[key] = v[idx] * scale

        # Per-core, plus the aggregates the charts actually plot. The peak
        # and the mean are both worth having: the gap between them is how
        # unevenly the scheduler is spreading load, which changes what the
        # power budget buys you.
        detected = s.get("core_count")
        active_cores = (min(self.ncores, int(detected))
                        if detected else self.ncores)
        for base_key, (base, scale) in self.cores.items():
            vals = [v[base + i] * scale for i in range(active_cores)
                    if base + i < n]
            if not vals:
                continue
            for i, val in enumerate(vals):
                s[f"{base_key}_{i}"] = val
            s[f"{base_key}_mean"] = sum(vals) / len(vals)
            s[f"{base_key}_max"] = max(vals)
        if self.layout.thermal_clusters:
            # Strix Halo reports one thermal value per eight-core cluster. The
            # governing CPU temperature is the hotter cluster; its conservative
            # ceiling is the lower of their two limits.
            temps = [s[value] for value, _limit in
                     self.layout.thermal_clusters if value in s]
            limits = [s[limit] for _value, limit in
                      self.layout.thermal_clusters if limit in s]
            if temps:
                s["tctl"] = max(temps)
            if limits:
                s["tctl_lim"] = min(limits)
    def meta(self):
        """A recording is only interpretable against the layout it was taken
        with, so the version goes in the file rather than being assumed at
        read time."""
        return {"pm_table_version": f"{self.version:#010x}"}


def probe(fs):
    raw = fs.read_bytes(VERSION_PATH)
    try:
        ver = None if raw is None else struct.unpack("<I", raw[:4])[0]
    except struct.error:
        ver = None
    if ver is None:
        return None, ("ryzen_smu not loaded -- SMU panes are empty. "
                      "modprobe ryzen_smu to populate them.")
    if ver not in PROFILES:
        supported = ", ".join(f"{v:#010x}" for v in PROFILES)
        return None, (f"pm_table version {ver:#010x} is not decoded "
                      f"(this build maps {supported}) -- "
                      "pm_table-only series are empty.")
    return ZenSmuBackend(ver), ""
