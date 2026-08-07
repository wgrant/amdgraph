"""Layer 1 -- the SMU's pm_table, via ryzen_smu.

Sensor layouts are part-specific and undocumented, so this decodes only maps
checked against live silicon: Phoenix 0x004C0009 and Strix Halo 0x0064020C.
See fields.py for the evidence behind every index and docs/HARDWARE.md for what
adding another part involves.

May import: fields, sysfs, backends.base.
"""

import struct

from ..fields import PM_PROFILES, PM_TABLE, PM_VERSION, PM_VER_SUPPORTED
from .base import Backend


class ZenSmuBackend(Backend):
    def __init__(self, version=PM_VER_SUPPORTED):
        self.version = version
        self.scalars, self.cores, self.ncores = PM_PROFILES[version]

    def sample(self, s, fs):
        raw = fs.read_bytes(PM_TABLE)
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
        for base_key, (base, scale) in self.cores.items():
            vals = [v[base + i] * scale for i in range(self.ncores)
                    if base + i < n]
            if not vals:
                continue
            for i, val in enumerate(vals):
                s[f"{base_key}_{i}"] = val
            s[f"{base_key}_mean"] = sum(vals) / len(vals)
            s[f"{base_key}_max"] = max(vals)
        if "core_power_mean" in s:
            s["core_power_sum"] = s["core_power_mean"] * self.ncores

        if self.version != PM_VER_SUPPORTED:
            # Strix Halo reports one thermal value per eight-core cluster. The
            # governing CPU temperature is the hotter cluster; its conservative
            # ceiling is the lower of their two limits.
            temps = [s[k] for k in ("thm_core0", "thm_core1") if k in s]
            limits = [s[k] for k in ("thm_core0_lim", "thm_core1_lim")
                      if k in s]
            if temps:
                s["tctl"] = max(temps)
            if limits:
                s["tctl_lim"] = min(limits)
            # Frequency times C0 residency is the interval's useful clock;
            # both inputs carry the same SMU time filter.
            effective = []
            for i in range(self.ncores):
                freq, c0 = s.get(f"core_freq_{i}"), s.get(f"core_c0_{i}")
                if freq is not None and c0 is not None:
                    value = freq * c0 / 100.0
                    s[f"core_freqeff_{i}"] = value
                    effective.append(value)
            if effective:
                s["core_freqeff_mean"] = sum(effective) / len(effective)
                s["core_freqeff_max"] = max(effective)

        # Unused budget: limit minus value. This is the signal that
        # separates "throttled because it ran out of power" from "held down
        # by something else entirely". Near zero means the power governor is
        # the binding constraint. A large positive number while clocks are
        # on the floor means the budget is going unspent -- an external
        # clamp (EC PROCHOT, adapter current limit) rather than the SMU's
        # own governor.
        for name, val, lim in (("stapm_head", "stapm", "stapm_lim"),
                               ("ppt_slow_head", "ppt_slow", "ppt_slow_lim"),
                               ("ppt_fast_head", "ppt_fast", "ppt_fast_lim")):
            if val in s and lim in s:
                s[name] = s[lim] - s[val]

    def meta(self):
        """A recording is only interpretable against the layout it was taken
        with, so the version goes in the file rather than being assumed at
        read time."""
        return {"pm_table_version": f"{self.version:#010x}"}


def probe(fs):
    raw = fs.read_bytes(PM_VERSION)
    try:
        ver = None if raw is None else struct.unpack("<I", raw[:4])[0]
    except struct.error:
        ver = None
    if ver is None:
        return None, ("ryzen_smu not loaded -- SMU panes are empty. "
                      "modprobe ryzen_smu to populate them.")
    if ver not in PM_PROFILES:
        supported = ", ".join(f"{v:#010x}" for v in PM_PROFILES)
        return None, (f"pm_table version {ver:#010x} is not decoded "
                      f"(this build maps {supported}) -- "
                      "pm_table-only series are empty.")
    return ZenSmuBackend(ver), ""
