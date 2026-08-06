"""Layer 2 -- shared view state.

May import: nothing in this package.
"""


class View:
    """What every pane agrees on: the visible time window, the crosshair, and
    which stores are being drawn. Panes hold a reference and never own any of
    it, which is what keeps them locked together."""

    WINDOWS = [(60, "1m"), (300, "5m"), (900, "15m"), (3600, "1h"),
               (0, "all")]

    def __init__(self, store):
        self.store = store
        self.overlay = None
        self.overlay_name = ""
        self.window = 300.0        # seconds; 0 means "all"
        self.follow = True         # right edge pinned to newest sample
        self.t0 = 0.0
        self.t1 = 60.0
        self.cursor = None         # crosshair time, or None
        self.frozen = False        # view held still; sampling continues
        # Manually placed events: [(t, label)]. This machine has no
        # accelerometer, ambient sensor or lid-angle input -- nothing that
        # notices you moved it -- so a physical intervention leaves no trace in
        # the data unless you say so. Markers are that trace, and they work for
        # anything the hardware cannot see: propping it up, changing the room,
        # switching a limit by hand.
        self.markers = []

    def update_range(self):
        if not self.follow:
            return
        lo, hi = self.store.span()
        if self.window <= 0:
            # "all" is the only mode where the overlay gets a say in the
            # range -- when following a window, the right edge tracks the live
            # trace, not a recording that may run longer than this session has.
            if self.overlay is not None:
                olo, ohi = self.overlay.span()
                lo, hi = min(lo, olo), max(hi, ohi)
            self.t0, self.t1 = lo, max(hi, lo + 10.0)
        else:
            self.t1 = max(hi, self.window)
            self.t0 = self.t1 - self.window
        if self.t1 - self.t0 < 1.0:
            self.t1 = self.t0 + 1.0

    def zoom_to(self, t0, t1):
        if t1 - t0 < 2.0:
            return
        self.t0, self.t1 = t0, t1
        self.follow = False

    def unzoom(self):
        self.follow = True
        self.update_range()

    def pan(self, dt):
        self.t0 += dt
        self.t1 += dt
        self.follow = False

    def zoom_at(self, t, factor):
        span = (self.t1 - self.t0) * factor
        span = max(4.0, min(span, 86400.0))
        frac = (t - self.t0) / max(1e-9, self.t1 - self.t0)
        self.t0 = t - span * frac
        self.t1 = self.t0 + span
        self.follow = False
