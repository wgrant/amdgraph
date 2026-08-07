"""Layer 1 -- the host itself: CPU, memory, battery, generic ACPI.

Everything here reads the same on any Linux box, no vendor driver needed --
which is what makes this backend the one that still produces real, moving
numbers on a machine with no AMD part in it at all, the thing that makes it
possible to develop the rest of this program in a container.

May import: fields, sysfs, backends.base.
"""

from ..fields import PLATFORM_PROFILE, PROC_MEMINFO, PROC_STAT, PROFILES
from ..sysfs import find_hwmon, physical_core_count
from .base import Backend

AC_ONLINE = "/sys/class/power_supply/AC/online"
BAT0_STATUS = "/sys/class/power_supply/BAT0/status"


def _cpu_stat(fs):
    txt = fs.read_text(PROC_STAT)
    if not txt:
        return None
    f = [int(x) for x in txt.splitlines()[0].split()[1:]]
    return sum(f), f[3] + f[4]          # total, idle + iowait


def host_memory(fs):
    """Used memory and swap, as percentages, from /proc/meminfo.

    MemAvailable rather than MemFree: free-but-reclaimable page cache is not
    memory pressure, and MemFree alone makes an idle Linux box with a warm
    cache look nearly out of RAM. MemAvailable has counted that in since 3.14.

    No differencing, no privileges, no ASIC to be wrong about -- unlike
    everything else in this program, this is the same read on every Linux
    box there is.
    """
    txt = fs.read_text(PROC_MEMINFO)
    if not txt:
        return None, None
    kb = {}
    for line in txt.splitlines():
        name, _, rest = line.partition(":")
        try:
            kb[name] = int(rest.split()[0])
        except (IndexError, ValueError):
            continue
    mem = swap = None
    total, avail = kb.get("MemTotal"), kb.get("MemAvailable")
    if total:
        mem = 100.0 * (total - avail) / total if avail is not None else None
    total, free = kb.get("SwapTotal"), kb.get("SwapFree")
    if total:                      # 0 on a swapless container; not a reading
        swap = 100.0 * (total - free) / total if free is not None else None
    return mem, swap


class HostBackend(Backend):
    """CPU busy, mem/swap, platform profile, and battery/AC -- none of it
    specific to a CPU vendor or a laptop's EC, unlike everything else in this
    package. Always applies; there is no machine this isn't useful on.

    # Reading the NVMe composite temperature costs ~1.9 ms, because it is an
    # admin command to the drive rather than a cached value -- a third of the
    # whole sample budget for a sensor that moves over tens of seconds. It
    # gets sampled every Nth tick and held in between, same as AC online,
    # which is ~0.5 ms, an order of magnitude dearer than its neighbours.
    """

    SLOW_EVERY = 5
    METRIC_KEYS = (
        "core_count", "cpu_busy", "mem_used_pct", "swap_used_pct", "pprof",
        "batt_charging", "ac_online", "nvme", "batt_power")

    def __init__(self, fs):
        self.hwmon = find_hwmon(fs=fs)
        self.core_count = physical_core_count(fs)
        self._cpu_prev = _cpu_stat(fs)
        self.tick = 0
        self.slow = {}

    def _slow(self, key, fs, path, scale=1.0):
        if key not in self.slow or self.tick % self.SLOW_EVERY == 0:
            self.slow[key] = fs.read_num(path, scale)
        return self.slow[key]

    def sample(self, s, fs):
        self.tick += 1
        s["core_count"] = (None if self.core_count is None
                           else float(self.core_count))
        cur = _cpu_stat(fs)
        if cur and self._cpu_prev:
            dt = cur[0] - self._cpu_prev[0]
            di = cur[1] - self._cpu_prev[1]
            s["cpu_busy"] = 100.0 * (dt - di) / dt if dt else None
        else:
            s["cpu_busy"] = None
        self._cpu_prev = cur

        s["mem_used_pct"], s["swap_used_pct"] = host_memory(fs)

        # Platform policy. Any of these can move the power budget out from
        # under you without the SMU rows showing a cause, so they belong on
        # the same timeline as the drop they explain.
        s["pprof"] = PROFILES.get(fs.read_text(PLATFORM_PROFILE) or "")
        st = fs.read_text(BAT0_STATUS)
        s["batt_charging"] = None if st is None else float(st == "Charging")
        s["ac_online"] = self._slow("ac", fs, AC_ONLINE)

        if (nv := self.hwmon.get("nvme")):
            s["nvme"] = self._slow("nvme", fs, f"{nv}/temp1_input", 1000)
        if (bat := self.hwmon.get("BAT0")):
            s["batt_power"] = fs.read_num(f"{bat}/power1_input", 1_000_000)

    def reset(self, fs):
        """Drop differencing state. Called when the buffer is cleared, so
        the first sample afterwards is not a delta against a stale
        baseline."""
        self._cpu_prev = _cpu_stat(fs)


def probe(fs):
    """Always applies -- there is no machine this backend isn't useful on."""
    return HostBackend(fs), ""
