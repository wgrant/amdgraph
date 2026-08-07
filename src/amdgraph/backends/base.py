"""Layer 1 -- the backend protocol.

A backend owns one hardware family -- CPU/mem, the platform EC, the SMU's
pm_table, the AMD GPU's gpu_metrics, eventually an NVIDIA one. Each decides
for itself whether it applies to the running machine (a version match, a
vendor ID, a device actually found) and, if so, contributes keys to the
shared sample dict. `Sampler` discovers which backends apply and composes
them, the same discipline `docs/DESIGN.md`'s source protocol already applies
one layer up: nothing above `Sampler` knows a backend exists, and nothing
here knows `Sampler` exists.

May import: fields, sysfs.
"""

from typing import Tuple

from ..model import Metric


class Backend:
    """No-op defaults for everything but sample(): most backends need only
    that one method, and reset()/close()/set_cap_rate() exist for the few
    that hold differencing state or a background thread, not for every
    backend to reimplement as a pass.
    """

    def sample(self, s, fs):
        """Mutate `s` in place: add whatever keys this backend owns. Must
        never raise -- a value that cannot be read is left out, the same
        discipline read_text/read_num already follow at layer 0."""
        raise NotImplementedError

    def notes(self):
        """Strings for the status bar: what could not be read, and why."""
        return []

    def meta(self):
        """Fields folded into a recording's header comments."""
        return {}

    def reset(self, fs):
        """Forget any differencing state; the buffer was cleared."""

    def close(self):
        """Stop any background thread this backend started."""

    def set_cap_rate(self, hz):
        """Change how often a high-rate background poller runs, if this
        backend has one."""
    METRIC_KEYS: Tuple[str, ...] = ()

    def metrics(self):
        """Telemetry this backend supports, independent of the latest read."""
        return tuple(Metric(key) for key in self.METRIC_KEYS)
