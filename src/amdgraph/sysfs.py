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


def card_index(dev):
    """Sort key for a DRM device path: the card number, as a number.

    Plain sorted() is lexicographic, which puts card10 before card2. Only the
    fallback path below depends on the order, but a tie-break that reorders
    itself once a machine reaches ten DRM nodes is not a tie-break.
    """
    name = os.path.basename(os.path.dirname(dev))
    digits = "".join(c for c in name if c.isdigit())
    return (int(digits) if digits else 1 << 30), dev


def find_drm_device(pattern, vendor, validate):
    """Pick the DRM device to read, preferring one `validate` accepts.

    Same discipline as find_hwmon: identify by what a node *is*, never by the
    index it happened to get.

    The preference has to be validation, not merely "publishes gpu_metrics".
    An earlier version tested only for the file's presence, on the theory that
    it would pick the APU on a machine that also has a discrete Radeon -- but
    amdgpu exports gpu_metrics for discrete parts too, in the v1_x layouts, so
    on exactly the machine that motivated the preference both candidates match
    and the first one wins by accident. Asking whether the blob is one we can
    actually decode is the question we meant to ask.

    Falls back to any AMD device, so a part whose layout we do not decode still
    gets its plain hwmon and DPM sensors. If several AMD devices are present
    and none validates, the choice among them is arbitrary -- there is no
    reliable way to tell an integrated GPU from a discrete one here -- and the
    caller reports the layout as undecoded either way.
    """
    fallback = None
    for dev in sorted(glob.glob(pattern), key=card_index):
        if read_text(f"{dev}/vendor") != vendor:
            continue
        if validate(dev):
            return dev
        if fallback is None:
            fallback = dev
    return fallback


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
