"""Layer 1 -- the SMU's pm_table, via ryzen_smu.

Sensor layouts are part-specific and undocumented, so this decodes only what
has been checked against live silicon: pm_table 0x004C0009, as found on
Ryzen 7040-series (Phoenix). See docs/HARDWARE.md for what adding a part
involves and fields.py for the evidence behind every index below.

Deliberately single-version, not a registry: there is no second verified map
yet, and building one now for a table that has not been captured would be
exactly the kind of invented number this module exists to refuse. Adding a
second platform's map is a small, obvious extension to this same shape once
it has been earned the same way this one was.

May import: fields, sysfs, backends.base.
"""

import struct

from ..fields import (N_CORES, PM_CORE, PM_SCALAR, PM_TABLE, PM_VERSION,
                     PM_VER_SUPPORTED)
from .base import Backend


class ZenSmuBackend(Backend):
    def sample(self, s, fs):
        raw = fs.read_bytes(PM_TABLE)
        if raw is None:
            return
        n = len(raw) // 4
        v = struct.unpack(f"<{n}f", raw[:n * 4])

        for key, (idx, scale) in PM_SCALAR.items():
            if idx < n:
                s[key] = v[idx] * scale

        # Per-core, plus the aggregates the charts actually plot. The peak
        # and the mean are both worth having: the gap between them is how
        # unevenly the scheduler is spreading load, which changes what the
        # power budget buys you.
        for base_key, (base, scale) in PM_CORE.items():
            vals = [v[base + i] * scale for i in range(N_CORES)
                    if base + i < n]
            if not vals:
                continue
            for i, val in enumerate(vals):
                s[f"{base_key}_{i}"] = val
            s[f"{base_key}_mean"] = sum(vals) / len(vals)
            s[f"{base_key}_max"] = max(vals)
        if "core_power_mean" in s:
            s["core_power_sum"] = s["core_power_mean"] * N_CORES

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
        return {"pm_table_version": f"{PM_VER_SUPPORTED:#010x}"}


def probe(fs):
    raw = fs.read_bytes(PM_VERSION)
    try:
        ver = None if raw is None else struct.unpack("<I", raw[:4])[0]
    except struct.error:
        ver = None
    if ver is None:
        return None, ("ryzen_smu not loaded -- SMU panes are empty. "
                      "modprobe ryzen_smu to populate them.")
    if ver != PM_VER_SUPPORTED:
        return None, (f"pm_table version {ver:#010x} is not decoded "
                      f"(this build maps {PM_VER_SUPPORTED:#010x}) -- "
                      "SMU panes are empty.")
    return ZenSmuBackend(), ""
