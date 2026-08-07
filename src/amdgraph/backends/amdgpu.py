"""Layer 1 -- the AMD GPU: gpu_metrics, and its plain hwmon/DPM sensors.

Sensor layouts are part-specific and undocumented, so this decodes only what
has been checked against live silicon: gpu_metrics v2_1, as found on
Ryzen 7040-series (Phoenix). See docs/HARDWARE.md for what adding a part
involves and fields.py for the evidence behind every offset below.

May import: fields, sysfs, backends.base.
"""

import struct
import threading
import time

from ..fields import (AMD_VENDOR, DRM_DEVICES, GM_CORE_PWR_OFF, GM_PWR_OFF,
                     GM_SIZE, GM_THROTTLE_OFF, GM_VERSION, THROTTLE_BITS)
from ..sysfs import RealFS, dpm_current, find_drm_device, find_hwmon
from .base import Backend


def check_gpu_metrics(path, fs):
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
    raw = fs.read_bytes(path)
    if raw is None:
        return False, "gpu_metrics unavailable — no cap reasons"
    if len(raw) < 4:
        return False, "gpu_metrics too short — no cap reasons"
    size, fmt_rev, cont_rev = struct.unpack_from("<HBB", raw, 0)
    if (fmt_rev, cont_rev) != GM_VERSION or size != GM_SIZE:
        return False, (f"gpu_metrics v{fmt_rev}_{cont_rev} ({size}B) is not "
                       f"decoded (this build maps v{GM_VERSION[0]}_"
                       f"{GM_VERSION[1]}, {GM_SIZE}B) — no cap reasons")
    return True, ""


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

    def __init__(self, gpu_metrics, fs=None, hz=20.0):
        self.gpu_metrics = gpu_metrics
        self.fs = fs or RealFS()
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
            raw = self.fs.read_bytes(self.gpu_metrics)
            try:
                ts = (None if raw is None else
                     struct.unpack_from("<I", raw, GM_THROTTLE_OFF)[0])
            except struct.error:
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


class AmdGpuBackend(Backend):
    def __init__(self, card, gpu_metrics, gm_ok, gm_note, fs):
        self.card = card
        self.gpu_metrics = gpu_metrics
        self.gm_ok = gm_ok
        self.gm_note = gm_note
        self.hwmon = find_hwmon(fs=fs)
        # The poller is handed a path only when the layout checked out.
        # Gating solely on the start() call below is not enough: changing
        # the cap-poll rate in the toolbar calls set_rate(), which calls
        # start() again, and a decode we already refused would come back to
        # life at up to 50 Hz -- burning ~1.2% of a core unpacking offsets
        # that mean nothing on this part. Withholding the path is the one
        # guard every caller goes through.
        self.throttle = ThrottleSampler(gpu_metrics if gm_ok else None, fs)
        self.throttle.start()

    def notes(self):
        return [self.gm_note] if self.gm_note else []

    def sample(self, s, fs):
        s["gpu_busy"] = fs.read_num(f"{self.card}/gpu_busy_percent")
        s["sclk"] = dpm_current(f"{self.card}/pp_dpm_sclk", fs)
        s["socclk"] = dpm_current(f"{self.card}/pp_dpm_socclk", fs)
        if (amd := self.hwmon.get("amdgpu")):
            s["gpu_edge"] = fs.read_num(f"{amd}/temp1_input", 1000)
            # The driver's own sclk readout, in Hz. This is the achieved GPU
            # clock; the SMU's permitted ceiling is a different number.
            s["sclk_hw"] = fs.read_num(f"{amd}/freq1_input", 1_000_000)
            w = fs.read_num(f"{amd}/power1_average", 1_000_000)
            if w is None:
                w = fs.read_num(f"{amd}/power1_input", 1_000_000)
            s["gpu_power"] = w
        self._throttle(s, fs)

    def _throttle(self, s, fs):
        """Per-reason duty cycle over the interval, from the background
        poller.

        Values are fractions, not flags: 0.62 means the reason was asserted
        in 62% of the samples taken since the last tick. Falling back to a
        single instantaneous read only happens when high-rate polling is
        switched off, and then the value is 0 or 1 as before.
        """
        if not self.gm_ok:
            return
        duty, raw, n, pwr = self.throttle.drain()
        if pwr:
            s.update(pwr)
            # What the socket is spending that the measured parts do not
            # account for: GPU, memory PHY, fabric, display. Derived rather
            # than measured, because the one field that claims to be GPU
            # power is not (see GM_PWR_OFF). Labelled as a remainder, not as
            # "GPU".
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
        buf = fs.read_bytes(self.gpu_metrics)
        if buf is None or len(buf) < GM_THROTTLE_OFF + 4:
            return
        ts = struct.unpack_from("<I", buf, GM_THROTTLE_OFF)[0]
        s["throttle_raw"] = float(ts)
        s["throttle_n"] = 1.0
        for bit, _name, _fam in THROTTLE_BITS:
            s[f"thr{bit}"] = float((ts >> bit) & 1)

    def set_cap_rate(self, hz):
        self.throttle.set_rate(hz)

    def close(self):
        self.throttle.stop()


def probe(fs):
    card = find_drm_device(
        DRM_DEVICES, AMD_VENDOR,
        lambda dev: check_gpu_metrics(f"{dev}/gpu_metrics", fs)[0],
        fs=fs)
    gpu_metrics = f"{card}/gpu_metrics" if card else None
    gm_ok, gm_note = check_gpu_metrics(gpu_metrics, fs)
    if not card:
        # No cap reasons and no amdgpu hwmon/DPM either -- nothing to add.
        return None, gm_note
    return AmdGpuBackend(card, gpu_metrics, gm_ok, gm_note, fs), ""
