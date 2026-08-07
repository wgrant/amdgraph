"""Layer 1 -- acquisition.

Turns the hardware map into samples. One tick of `Sampler.sample()` yields one
flat dict of key -> float, which is the only shape the rest of the program ever
sees; nothing above this layer opens a file in /sys.

May import: fields, sysfs.
"""

import struct
import threading
import time

from .fields import (AMD_VENDOR, DRM_DEVICES, GM_CORE_PWR_OFF, GM_PWR_OFF,
                     GM_SIZE, GM_THROTTLE_OFF, GM_VERSION, N_CORES,
                     PLATFORM_PROFILE, PM_CORE, PM_SCALAR, PM_TABLE,
                     PM_VERSION, PM_VER_SUPPORTED, PROFILES, THROTTLE_BITS,
                     TPACPI)
from .sysfs import (dpm_current, find_drm_device, find_hwmon, read_num,
                    read_text)


class CPUBusy:
    """Aggregate non-idle time from /proc/stat, differenced between samples."""

    def __init__(self):
        self.prev = self._read()

    @staticmethod
    def _read():
        txt = read_text("/proc/stat")
        if not txt:
            return None
        f = [int(x) for x in txt.splitlines()[0].split()[1:]]
        return sum(f), f[3] + f[4]          # total, idle + iowait

    def sample(self):
        cur = self._read()
        if not cur or not self.prev:
            return None
        dt, di = cur[0] - self.prev[0], cur[1] - self.prev[1]
        self.prev = cur
        return 100.0 * (dt - di) / dt if dt else None


class ThrottleSampler:
    """Polls the throttler bitmask off-thread and reports, per reason, the
    fraction of the interval it was asserted.

    The bits are instantaneous flags on a controller that duty-cycles fast.
    Measured on this part: the SMU refreshes gpu_metrics at ~149 Hz, and SPL
    toggles ~19 times a second with a duty cycle of 12.7% at idle and runs
    rarely longer than 270 ms. Sampling that once a second reads one 6.6 ms
    window out of every 1000 and reports a coin flip -- a limiter that is
    continuously regulating shows up as a scatter of unrelated-looking marks.

    So the reading is decoupled from the display: a background thread
    accumulates, and each UI tick drains a duty cycle. Costs about 0.6 ms per
    fresh read (the driver caches for 5 ms), hence roughly 1.2% of a core at
    20 Hz -- worth it for the one pane whose entire job is naming the cause,
    but tunable, and set to 1 Hz it degrades to the old instantaneous sample.
    """

    def __init__(self, gpu_metrics, hz=20.0):
        self.gpu_metrics = gpu_metrics
        self.hz = hz
        self._lock = threading.Lock()
        self._counts = {b: 0.0 for b, _n, _f in THROTTLE_BITS}
        self._total = 0
        self._raw = 0
        self._stop = threading.Event()
        self._thread = None
        # The power fields ride along free: this thread already has the blob
        # open 20 times a second, so sampling them here costs nothing extra
        # and spares the main loop a 0.6 ms read.
        self._pwr = None

    def start(self):
        if self._thread or self.hz <= 1.0 or not self.gpu_metrics:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def set_rate(self, hz):
        self.stop()
        self.hz = hz
        with self._lock:
            self._counts = {b: 0.0 for b in self._counts}
            self._total = 0
        self.start()

    def _run(self):
        period = 1.0 / self.hz
        nxt = time.monotonic()
        while not self._stop.is_set():
            try:
                with open(self.gpu_metrics, "rb") as f:
                    raw = f.read()
                ts = struct.unpack_from("<I", raw, GM_THROTTLE_OFF)[0]
            except (OSError, struct.error):
                ts = None
            if ts is not None:
                sock, _cpu, soc, gfx = struct.unpack_from("<HHHH", raw,
                                                          GM_PWR_OFF)
                cores = struct.unpack_from("<8H", raw, GM_CORE_PWR_OFF)
                # 0xFFFF is the SMU's "not populated" marker; drop those
                # rather than plot 65.535 W.
                def w(x):
                    return None if x == 0xFFFF else x / 1000.0
                pwr = {"pwr_socket": w(sock), "pwr_soc": w(soc),
                       "pwr_gfxslot": w(gfx),
                       "pwr_cores": sum(c for c in cores
                                        if c != 0xFFFF) / 1000.0}
                with self._lock:
                    self._total += 1
                    self._raw |= ts
                    self._pwr = pwr
                    for b in self._counts:
                        if (ts >> b) & 1:
                            self._counts[b] += 1.0
            nxt += period
            delay = nxt - time.monotonic()
            if delay < 0:                 # fell behind; resync rather than spin
                nxt = time.monotonic()
                delay = 0.0
            self._stop.wait(delay)

    def drain(self):
        """(duty per bit, OR of raw values, sample count, latest power) since
        the last call."""
        with self._lock:
            n = self._total
            duty = ({b: c / n for b, c in self._counts.items()} if n else None)
            raw = self._raw
            pwr = self._pwr
            self._counts = {b: 0.0 for b in self._counts}
            self._total = 0
            self._raw = 0
        return duty, raw, n, pwr


class Sampler:
    """One sample = one dict of key -> float (or None where unavailable).

    Deliberately open/read/close per attribute rather than holding descriptors
    open: a few dozen sysfs reads cost well under a millisecond, and some sysfs
    attributes do not survive being re-read from a held fd.
    """

    # Reading the NVMe composite temperature costs ~1.9 ms here, because it is
    # an admin command to the drive rather than a cached value -- a third of
    # the whole sample budget for a sensor that moves over tens of seconds. It
    # gets sampled every Nth tick and held in between. The EC fan tachometers
    # are nearly as expensive (~0.85 ms each) but stay at full rate: fan
    # response is the thing being tuned, so decimating it would defeat the
    # purpose.
    SLOW_EVERY = 5

    def _slow(self, key, path, scale=1.0):
        """Read `path` every SLOW_EVERY ticks, holding the value in between.
        Always reads the first time it is asked for, so a decimated sensor is
        never blank for the opening samples of a recording."""
        if key not in self.slow or self.tick % self.SLOW_EVERY == 0:
            self.slow[key] = read_num(path, scale)
        return self.slow[key]

    def __init__(self):
        self.hwmon = find_hwmon()
        self.cpubusy = CPUBusy()
        self.tick = 0
        self.slow = {}
        self.pm_ok = False
        self.pm_note = ""
        self.card = find_drm_device(
            DRM_DEVICES, AMD_VENDOR,
            lambda dev: self._check_gpu_metrics(f"{dev}/gpu_metrics")[0])
        self.gpu_metrics = (f"{self.card}/gpu_metrics" if self.card else None)
        self.gm_ok, self.gm_note = self._check_gpu_metrics(self.gpu_metrics)
        # The poller is handed a path only when the layout checked out. Gating
        # solely on the start() call below is not enough: changing the cap-poll
        # rate in the toolbar calls set_rate(), which calls start() again, and
        # a decode we already refused would come back to life at up to 50 Hz --
        # burning ~1.2% of a core unpacking offsets that mean nothing on this
        # part. Withholding the path is the one guard every caller goes through.
        self.throttle = ThrottleSampler(self.gpu_metrics if self.gm_ok else None)
        self.throttle.start()
        try:
            with open(PM_VERSION, "rb") as f:
                ver = struct.unpack("<I", f.read(4))[0]
        except (OSError, struct.error):
            self.pm_note = ("ryzen_smu not loaded -- SMU panes are empty. "
                            "modprobe ryzen_smu to populate them.")
            return
        if ver != PM_VER_SUPPORTED:
            self.pm_note = (f"pm_table version {ver:#010x} is not decoded "
                            f"(this build maps {PM_VER_SUPPORTED:#010x}) -- "
                            "SMU panes are empty.")
            return
        self.pm_ok = True

    @staticmethod
    def _check_gpu_metrics(path):
        """Refuse to decode a layout we have not verified. The throttler bits
        are ASIC-dependent and the field moves between revisions, so a wrong
        guess would label the wrong cap reason -- worse than showing none.

        The version reported here is worth reading rather than working around:
        v2_2 and later carry indep_throttle_status, an ASIC-independent bitmask
        the kernel fills in, and v3_0 replaces the bitmask with per-reason
        residency counters. This build decodes v2_1, the one layout that has
        neither and therefore needs the hand-checked bit table in fields.py.
        """
        if not path:
            return False, "no amdgpu device found — no cap reasons"
        try:
            with open(path, "rb") as f:
                raw = f.read()
        except OSError:
            return False, "gpu_metrics unavailable — no cap reasons"
        if len(raw) < 4:
            return False, "gpu_metrics too short — no cap reasons"
        size, fmt_rev, cont_rev = struct.unpack_from("<HBB", raw, 0)
        if (fmt_rev, cont_rev) != GM_VERSION or size != GM_SIZE:
            return False, (f"gpu_metrics v{fmt_rev}_{cont_rev} ({size}B) is not "
                           f"decoded (this build maps v{GM_VERSION[0]}_"
                           f"{GM_VERSION[1]}, {GM_SIZE}B) — no cap reasons")
        return True, ""

    def _pm(self, s):
        if not self.pm_ok:
            return
        try:
            with open(PM_TABLE, "rb") as f:
                raw = f.read()
        except OSError:
            return
        n = len(raw) // 4
        v = struct.unpack(f"<{n}f", raw[:n * 4])

        for key, (idx, scale) in PM_SCALAR.items():
            if idx < n:
                s[key] = v[idx] * scale

        # Per-core, plus the aggregates the charts actually plot. The peak and
        # the mean are both worth having: the gap between them is how unevenly
        # the scheduler is spreading load, which changes what the power budget
        # buys you.
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

        # Unused budget: limit minus value. This is the signal that separates
        # "throttled because it ran out of power" from "held down by something
        # else entirely". Near zero means the power governor is the binding
        # constraint. A large positive number while clocks are on the floor
        # means the budget is going unspent -- an external clamp (EC PROCHOT,
        # adapter current limit) rather than the SMU's own governor.
        for name, val, lim in (("stapm_head", "stapm", "stapm_lim"),
                               ("ppt_slow_head", "ppt_slow", "ppt_slow_lim"),
                               ("ppt_fast_head", "ppt_fast", "ppt_fast_lim")):
            if val in s and lim in s:
                s[name] = s[lim] - s[val]

    def _throttle(self, s):
        """Per-reason duty cycle over the interval, from the background poller.

        Values are fractions, not flags: 0.62 means the reason was asserted in
        62% of the samples taken since the last tick. Falling back to a single
        instantaneous read only happens when high-rate polling is switched off,
        and then the value is 0 or 1 as before.
        """
        if not self.gm_ok:
            return
        duty, raw, n, pwr = self.throttle.drain()
        if pwr:
            s.update(pwr)
            # What the socket is spending that the measured parts do not
            # account for: GPU, memory PHY, fabric, display. Derived rather
            # than measured, because the one field that claims to be GPU power
            # is not (see GM_PWR_OFF). Labelled as a remainder, not as "GPU".
            if pwr.get("pwr_socket") is not None:
                s["pwr_rest"] = (pwr["pwr_socket"] - pwr.get("pwr_cores", 0.0)
                                 - (pwr.get("pwr_soc") or 0.0))
        # pwr_cores (the gpu_metrics sum) stays recorded for comparison, but
        # the plotted CPU-core figure is pm_table's core_power_sum -- see the
        # jitter table above the Power breakdown pane in panes.py.
        if duty is not None:
            s["throttle_raw"] = float(raw)
            s["throttle_n"] = float(n)
            for bit, _name, _fam in THROTTLE_BITS:
                s[f"thr{bit}"] = duty.get(bit, 0.0)
            return
        try:
            with open(self.gpu_metrics, "rb") as f:
                buf = f.read()
        except OSError:
            return
        if len(buf) < GM_THROTTLE_OFF + 4:
            return
        ts = struct.unpack_from("<I", buf, GM_THROTTLE_OFF)[0]
        s["throttle_raw"] = float(ts)
        s["throttle_n"] = 1.0
        for bit, _name, _fam in THROTTLE_BITS:
            s[f"thr{bit}"] = float((ts >> bit) & 1)

    def sample(self):
        s = {}
        self.tick += 1
        self._pm(s)
        self._throttle(s)

        s["cpu_busy"] = self.cpubusy.sample()
        if self.card:
            s["gpu_busy"] = read_num(f"{self.card}/gpu_busy_percent")
            s["sclk"] = dpm_current(f"{self.card}/pp_dpm_sclk")
            s["socclk"] = dpm_current(f"{self.card}/pp_dpm_socclk")

        if (amd := self.hwmon.get("amdgpu")):
            s["gpu_edge"] = read_num(f"{amd}/temp1_input", 1000)
            # The driver's own sclk readout, in Hz. This is the achieved GPU
            # clock; the SMU's permitted ceiling is a different number.
            s["sclk_hw"] = read_num(f"{amd}/freq1_input", 1_000_000)
            w = read_num(f"{amd}/power1_average", 1_000_000)
            if w is None:
                w = read_num(f"{amd}/power1_input", 1_000_000)
            s["gpu_power"] = w
        if (tp := self.hwmon.get("thinkpad")):
            # temp5 is the EC's TMP3 sensor (EC RAM 0x7C) -- the palm-rest skin
            # temperature the firmware fan curve reacts to, and the closest EC
            # analogue of the SMU's STT model. temp1 is its CPU sensor.
            s["ec_skin"] = read_num(f"{tp}/temp5_input", 1000)
            s["ec_cpu"] = read_num(f"{tp}/temp1_input", 1000)
            # Only these two. temp1/3/6/7 all report the identical value and
            # track each other exactly -- they are aliases of one CPU sensor,
            # so the EC publishes just two distinct temperatures to Linux.
            # Reading the other three would cost ~0.45 ms per sample of EC
            # transactions for a third copy of a line already on the chart.
            #
            # This was checked while hunting the lap-mode trigger, which
            # halves edc_lim (105 -> 52 A, ~8 W) and correlates with none of
            # the sensors Linux can see. It is not hiding in an unread
            # thermistor: there aren't any. The EC decides privately.
            s["palm"] = read_num(f"{TPACPI}/palmsensor")
            s["fan1"] = read_num(f"{tp}/fan1_input")
            s["fan2"] = read_num(f"{tp}/fan2_input")
            s["fan_cmd"], s["fan_mode"] = self._fan_command(tp)
        if (nv := self.hwmon.get("nvme")):
            s["nvme"] = self._slow("nvme", f"{nv}/temp1_input", 1000)
        if (bat := self.hwmon.get("BAT0")):
            s["batt_power"] = read_num(f"{bat}/power1_input", 1_000_000)

        # Platform policy. Any of these can move the power budget out from
        # under you without the SMU rows showing a cause, so they belong on
        # the same timeline as the drop they explain.
        s["pprof"] = PROFILES.get(read_text(PLATFORM_PROFILE) or "")
        s["lapmode"] = read_num(f"{TPACPI}/dytc_lapmode")
        st = read_text("/sys/class/power_supply/BAT0/status")
        s["batt_charging"] = None if st is None else float(st == "Charging")
        # ~0.5 ms, an order of magnitude dearer than its neighbours.
        s["ac_online"] = self._slow("ac", "/sys/class/power_supply/AC/online")
        return s

    @staticmethod
    def _fan_command(tp):
        """(level, mode) as COMMANDED by software, not as achieved.

        thinkpad_acpi maps pwm1_enable 0 to "disengaged" (fan unrestricted), 2
        to firmware auto, 1 to a manual level. In disengaged mode pwm1 still
        reports the last manual level, so the mode has to win. Level is pwm1
        rescaled from 0..255 onto 0..7; disengaged plots as 8 so it sits above
        level 7 rather than aliasing onto it.

        Plotted directly above the tachometers on purpose -- sharing a time
        axis makes the lag between what the fan daemon asks for and what the
        fan does readable straight off the two traces.
        """
        mode = read_num(f"{tp}/pwm1_enable")
        if mode is None:
            return None, None
        if mode == 0:
            return 8.0, "FULL"
        if mode == 2:
            return None, "AUTO"
        pwm = read_num(f"{tp}/pwm1")
        return (None, None) if pwm is None else (round(pwm * 7 / 255), None)
