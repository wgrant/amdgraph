"""Layer 0 -- generic sysfs access.

Nothing here knows what any particular attribute means; that is fields.py's
job. May import: nothing in this package.
"""

import glob
import os


def read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def read_num(path, scale=1.0):
    v = read_text(path)
    try:
        return int(v) / scale
    except (TypeError, ValueError):
        return None


def find_hwmon():
    """Map hwmon driver name -> sysfs dir. Indices move across boots, so this
    has to be done by name at startup rather than hardcoded."""
    out = {}
    base = "/sys/class/hwmon"
    try:
        for h in os.listdir(base):
            name = read_text(f"{base}/{h}/name")
            if name:
                out.setdefault(name, f"{base}/{h}")
    except OSError:
        pass
    return out


def find_drm_device(pattern, vendor, prefer):
    """First matching DRM device dir, preferring one that has `prefer`.

    Same discipline as find_hwmon: identify by what a node *is*, never by the
    index it happened to get. The preference matters because a machine can
    carry two AMD GPUs -- an APU and a discrete part -- and only the one whose
    SMU publishes gpu_metrics can answer why the package is being held back.
    Falls back to the first AMD device so the plain GPU sensors still work.
    """
    found = None
    for dev in sorted(glob.glob(pattern)):
        if read_text(f"{dev}/vendor") != vendor:
            continue
        if os.path.exists(f"{dev}/{prefer}"):
            return dev
        if found is None:
            found = dev
    return found


def dpm_current(path):
    """Parse pp_dpm_* -- the active DPM level is the one flagged with '*'."""
    txt = read_text(path)
    if not txt:
        return None
    for line in txt.splitlines():
        if "*" in line:
            parts = line.split()
            if len(parts) >= 2:
                digits = "".join(c for c in parts[1] if c.isdigit())
                if digits:
                    return float(digits)
    return None
