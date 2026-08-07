"""Layer 2 -- acquisition.

Composes the backends in backends/ into one flat dict of key -> float per
tick, which is the only shape the rest of the program ever sees; nothing
above this layer opens a file in /sys, and nothing here knows how any
particular part is read -- that is what makes a backend a backend.

May import: fields, sysfs, backends.
"""

from .backends import amdgpu, host, platform, zen_smu
from .sysfs import RealFS

# Order matters only for notes(): it decides which "why is this empty"
# string comes first in the status bar. Kept as SMU-then-GPU, matching what
# this program has always shown.
_PROBES = (host.probe, platform.probe, zen_smu.probe, amdgpu.probe)


class Sampler:
    """One sample = one dict of key -> float (or None where unavailable).

    This is also *the source protocol*: the only surface the window is
    allowed to use, so that a second one can exist. Everything above layer 2
    goes through these six methods and touches no backend directly:

        sample()        -> dict of key -> float, one tick's worth
        notes()         -> list of strings for the status bar, "" filtered out
        meta()          -> dict folded into a recording's header comments
        set_cap_rate(hz)-> change how often the cap-reason source is polled
        reset()         -> forget any differencing state; the buffer was cleared
        close()         -> stop background threads

    The window used to reach past all of this -- reassigning `sampler.cpubusy`
    to reset the /proc/stat differ, and calling `sampler.throttle.set_rate()`
    and `.stop()` directly. That made Main untestable without real hardware
    and would have made a Renoir or Strix Halo backend a rewrite of the
    window rather than a new module. Anything specific to how *this* part is
    read belongs behind a backend's own methods, not here.

    Discovery happens once, at construction: each backend in backends/
    decides for itself whether it applies (a version match, a vendor ID, a
    device found) and is kept only if it does. A second platform is a new
    backend module plus one more entry in _PROBES, not a change here.
    """

    def __init__(self, fs=None):
        self.fs = fs or RealFS()
        self.backends = []
        self._unavailable = []
        for probe in _PROBES:
            backend, note = probe(self.fs)
            if note:
                self._unavailable.append(note)
            if backend:
                self.backends.append(backend)

    def sample(self):
        s = {}
        for b in self.backends:
            b.sample(s, self.fs)
        return s

    # -- the source protocol ----------------------------------------------

    def notes(self):
        """What could not be read, and why, for the status bar."""
        return list(self._unavailable) + [n for b in self.backends
                                          for n in b.notes()]

    def meta(self):
        """Backend-specific header fields for a recording.

        A recording is only interpretable against the layout it was taken
        with, so the version goes in the file rather than being assumed at
        read time. Defaulted here rather than in zen_smu.py, so a recording's
        header always says something about it even when unsupported --
        overwritten by ZenSmuBackend.meta() when one exists.
        """
        m = {"pm_table_version": "none"}
        for b in self.backends:
            m.update(b.meta())
        return m

    def set_cap_rate(self, hz):
        for b in self.backends:
            b.set_cap_rate(hz)

    def reset(self):
        """Drop differencing state. Called when the buffer is cleared, so the
        first sample afterwards is not a delta against a stale baseline."""
        for b in self.backends:
            b.reset(self.fs)

    def close(self):
        for b in self.backends:
            b.close()
