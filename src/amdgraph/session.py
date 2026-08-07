"""Layer 2 -- recordings on disk.

The on-disk format, in both directions, plus the decision about which columns
go into it. Kept out of the window so the format is readable without reading
any GUI code, and so a recording can be produced or consumed headlessly.

May import: fields, store.
"""

import csv
import os

import numpy as np

from .fields import N_CORES, PM_PROFILES, THROTTLE_BITS
from .store import Store

DATA_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
    "amdgraph")


def record_keys():
    """Record every key the sampler can produce, not just the plotted ones --
    a recording you have to re-take because you did not log the column you now
    want is worse than a slightly larger file."""
    keys, core_bases = [], []
    for scalars, cores, _ncores in PM_PROFILES.values():
        keys += list(scalars)
        core_bases += list(cores)
    for base in dict.fromkeys(core_bases):
        keys += [f"{base}_{i}" for i in range(N_CORES)]
        keys += [f"{base}_mean", f"{base}_max"]
    keys += ["throttle_raw", "throttle_n", "pwr_socket",
             "pwr_cores", "pwr_soc", "pwr_gfxslot", "pwr_rest"]
    keys += [f"thr{b}" for b, _n, _f in THROTTLE_BITS]
    keys += ["stapm_head", "ppt_slow_head", "ppt_fast_head",
             "core_power_sum", "cpu_busy", "gpu_busy", "sclk", "sclk_hw",
             "socclk", "gpu_edge", "gpu_power", "ec_skin", "ec_cpu",
             "ec_cpu_virtual", "ec_power", "ec_memory", "ec_ambient",
             "fan1", "fan2", "fan3", "fan_cmd", "nvme", "batt_power",
             "pprof", "ac_online", "batt_charging", "lapmode", "palm"]
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


class Recorder:
    """Append-only CSV, flushed regularly so a crash costs at most a second or
    two of samples. Plain text on purpose: `awk` and pandas can both read it,
    and a recording that needs this program to be interpreted is a recording
    you will not look at in six months."""

    FLUSH_EVERY = 8

    def __init__(self, path, keys, meta):
        self.path = path
        self.keys = list(keys)
        self.f = open(path, "w", newline="")
        for k, v in meta.items():
            self.f.write(f"# {k}: {v}\n")
        self.w = csv.writer(self.f)
        self.w.writerow(["t"] + self.keys)
        self.count = 0

    def mark(self, t, label):
        """Markers go in as `# marker <t> <label>` comment lines rather than a
        column: an event is not a per-sample measurement, and a column of
        mostly-empty strings would be in every reader's way. pandas skips these
        with comment='#', and load_session parses them back."""
        self.f.write(f"# marker {t:.3f} {label}\n")
        self.f.flush()

    def write(self, t, sample):
        row = [f"{t:.3f}"]
        for k in self.keys:
            v = sample.get(k)
            row.append("" if not isinstance(v, (int, float)) else f"{v:.5g}")
        self.w.writerow(row)
        self.count += 1
        if self.count % self.FLUSH_EVERY == 0:
            self.f.flush()

    def close(self):
        """Idempotent. Closing twice used to raise ValueError -- flush() on an
        already-closed file is not an OSError -- and the second close arrives
        from a Qt virtual override, where an exception aborts the process
        rather than propagating."""
        if self.f.closed:
            return
        try:
            self.f.flush()
            self.f.close()
        except (OSError, ValueError):
            pass


def load_session(path):
    """Read a recording back into a Store."""
    st = Store()
    with open(path, newline="") as f:
        rows = []
        header = None
        for line in f:
            if line.startswith("#"):
                body = line[1:].strip()
                if body.startswith("marker "):
                    parts = body.split(None, 2)
                    if len(parts) >= 2:
                        try:
                            st.markers.append((float(parts[1]),
                                               parts[2] if len(parts) > 2
                                               else ""))
                        except ValueError:
                            pass
                elif ":" in body:
                    k, _, v = body.partition(":")
                    st.meta[k.strip()] = v.strip()
                continue
            rows.append(line)
        if not rows:
            raise ValueError("no data rows")
        rd = csv.reader(rows)
        header = next(rd)
        if header[0] != "t":
            raise ValueError("not an amdgraph recording (no 't' column)")
        keys = header[1:]
        data = list(rd)
    n = len(data)
    st.cap = max(16, n)
    st.n = n
    st.t = np.zeros(st.cap, dtype=np.float64)
    for k in keys:
        st.cols[k] = np.full(st.cap, np.nan, dtype=np.float32)
    for i, row in enumerate(data):
        try:
            st.t[i] = float(row[0])
        except (ValueError, IndexError):
            continue
        for j, k in enumerate(keys, start=1):
            if j < len(row) and row[j]:
                try:
                    st.cols[k][i] = float(row[j])
                except ValueError:
                    pass
    return st
