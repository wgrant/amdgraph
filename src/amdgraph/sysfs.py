"""Layer 0 -- generic sysfs access.

Nothing here knows what any particular attribute means; that is fields.py's
job. May import: nothing in this package.
"""

import base64
import glob
import json
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


class FS:
    """What a backend must implement: four primitives, everything else
    derived from them. `Sampler` reads through one of these instead of
    calling `open()`/`glob`/`os.listdir` directly, the same seam `Main` has
    at the sample-dict level via `source=` -- see docs/DESIGN.md.

    read_num is derived here, uniformly, so a backend never re-implements the
    int/scale parsing that already lives in the free function of the same
    name above.
    """

    def read_num(self, path, scale=1.0):
        v = self.read_text(path)
        try:
            return int(v) / scale
        except (TypeError, ValueError):
            return None


class RealFS(FS):
    """Reads the actual machine. The only backend used outside development
    and tests."""

    def read_text(self, path):
        return read_text(path)

    def read_bytes(self, path):
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def glob(self, pattern):
        return glob.glob(pattern)

    def listdir(self, path):
        try:
            return os.listdir(path)
        except OSError:
            return []


class MemoryFS(FS):
    """Small mapping-backed filesystem for decoder and discovery tests."""

    def __init__(self, text=None, data=None, globs=None, listings=None):
        self.text = dict(text or {})
        self.data = dict(data or {})
        self.globs = dict(globs or {})
        self.listings = dict(listings or {})

    def read_text(self, path):
        return self.text.get(path)

    def read_bytes(self, path):
        return self.data.get(path)

    def glob(self, pattern):
        return list(self.globs.get(pattern, ()))

    def listdir(self, path):
        return list(self.listings.get(path, ()))


class RecordingFS(FS):
    """Wraps another FS -- always a RealFS in practice -- and logs every
    call, in order, keyed by (op, path). Played back with ReplayFS to
    reproduce exactly what a real machine returned, including the misses:
    that is the only way to exercise an exceptional condition deterministically
    without waiting for the hardware to misbehave again.
    """

    def __init__(self, inner):
        self.inner = inner
        self.log = {}

    def _record(self, op, path, value):
        self.log.setdefault((op, path), []).append(value)
        return value

    def read_text(self, path):
        return self._record("text", path, self.inner.read_text(path))

    def read_bytes(self, path):
        return self._record("bytes", path, self.inner.read_bytes(path))

    def glob(self, pattern):
        return self._record("glob", pattern, self.inner.glob(pattern))

    def listdir(self, path):
        return self._record("listdir", path, self.inner.listdir(path))

    def save(self, path, host=""):
        """A flat list of records rather than a dict keyed by (op, path): a
        tuple is not a valid JSON key, and a list is trivial to hand-edit --
        find the record for a path, splice a null or a truncated base64
        string into `values` to inject an exceptional condition without
        waiting for one to happen on real hardware."""
        log = []
        for (op, key), values in self.log.items():
            if op == "bytes":
                values = [None if v is None else base64.b64encode(v).decode()
                         for v in values]
            log.append({"op": op, "path": key, "values": values})
        doc = {"schema": "amdgraph-fs-recording/1", "host": host, "log": log}
        with open(path, "w") as f:
            json.dump(doc, f, indent=1)


class ReplayFS(FS):
    """Serves a RecordingFS capture. Each (op, path) has its own cursor: the
    Nth read of a path gets the Nth recorded value, and once a sequence is
    exhausted the last value repeats -- so a session recorded for 60 ticks
    can still back a Sampler asked to run for 200.
    """

    def __init__(self, log):
        self.log = log
        self.pos = {}

    def _next(self, op, path, empty):
        key = (op, path)
        seq = self.log.get(key)
        if not seq:
            return empty
        i = min(self.pos.get(key, 0), len(seq) - 1)
        self.pos[key] = i + 1
        return seq[i]

    def read_text(self, path):
        return self._next("text", path, None)

    def read_bytes(self, path):
        return self._next("bytes", path, None)

    def glob(self, pattern):
        return list(self._next("glob", pattern, []))

    def listdir(self, path):
        return list(self._next("listdir", path, []))

    @classmethod
    def load(cls, path):
        with open(path) as f:
            doc = json.load(f)
        log = {}
        for rec in doc["log"]:
            values = rec["values"]
            if rec["op"] == "bytes":
                values = [None if v is None else base64.b64decode(v)
                         for v in values]
            log[(rec["op"], rec["path"])] = values
        return cls(log)


HWMON = "/sys/class/hwmon"
CPU_SYSFS = "/sys/devices/system/cpu"


def physical_core_count(fs=None, base=CPU_SYSFS):
    """Count detected physical cores from Linux topology, or return ``None``.

    ``cpuN`` directories are logical CPUs.  The package/die/core tuple is the
    stable identity that collapses SMT siblings without assuming Linux numbers
    the first thread of every core before the second.  ``die_id`` is optional
    on older kernels, where package+core remains the best available identity.
    """
    fs = fs or RealFS()
    cores = set()
    for name in fs.listdir(base):
        if not (name.startswith("cpu") and name[3:].isdigit()):
            continue
        top = f"{base}/{name}/topology"
        core = fs.read_num(f"{top}/core_id")
        package = fs.read_num(f"{top}/physical_package_id")
        if core is None or package is None:
            continue
        die = fs.read_num(f"{top}/die_id")
        cores.add((int(package), None if die is None else int(die), int(core)))
    return len(cores) or None


def trailing_index(name):
    """Sort key that reads hwmon7 / card10 as numbers, not as strings.

    Plain sorting puts card10 and hwmon10 ahead of card2 and hwmon2.
    """
    digits = "".join(c for c in name if c.isdigit())
    return (int(digits) if digits else 1 << 30), name


def find_hwmon(base=HWMON, fs=None):
    """Map hwmon driver name -> sysfs dir. Indices move across boots, so this
    has to be done by name at startup rather than hardcoded.

    Names are not unique -- two NVMe drives both register as `nvme` -- and the
    first one found wins. Which one that is has to be decided by something, so
    the listing is sorted: without it the winner came from os.listdir order,
    which is whatever the filesystem hands back, and the drive whose
    temperature you were plotting could change between runs of the program.
    Lowest index wins, which at least matches how they are numbered.

    `base` is a parameter so this can be pointed at a synthetic tree; a reader
    whose root is a literal cannot be tested anywhere but the machine it was
    written on. `fs` picks the backend it reads through -- default RealFS, so
    every existing caller and test that omits it is unaffected.
    """
    fs = fs or RealFS()
    out = {}
    for h in sorted(fs.listdir(base), key=trailing_index):
        name = fs.read_text(f"{base}/{h}/name")
        if name:
            out.setdefault(name, f"{base}/{h}")
    return out


def card_index(dev):
    """Sort key for a DRM device path: the card number, as a number."""
    return trailing_index(os.path.basename(os.path.dirname(dev)))


def find_drm_device(pattern, vendor, validate, fs=None):
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

    `fs` picks the backend it reads through -- default RealFS, so every
    existing caller and test that omits it is unaffected.
    """
    fs = fs or RealFS()
    fallback = None
    for dev in sorted(fs.glob(pattern), key=card_index):
        if fs.read_text(f"{dev}/vendor") != vendor:
            continue
        if validate(dev):
            return dev
        if fallback is None:
            fallback = dev
    return fallback


def dpm_current(path, fs=None):
    """Parse pp_dpm_* -- the active DPM level is the one flagged with '*'."""
    txt = (fs or RealFS()).read_text(path)
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
