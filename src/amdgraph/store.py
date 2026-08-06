"""Layer 1 -- in-memory storage.

The one data structure every pane reads from. Knows nothing about what any
column means. May import: nothing in this package.
"""

import math
import time

import numpy as np


class Store:
    """Column store: one time array plus one float32 array per key.

    Capacity doubles on demand. Missing samples are NaN, which both numpy and
    the polyline builder treat as a gap rather than a zero -- important,
    because a sensor that vanishes should leave a hole in the trace, not a
    cliff to the floor.
    """

    def __init__(self, cap=4096):
        self.n = 0
        self.cap = cap
        self.t = np.zeros(cap, dtype=np.float64)
        self.cols = {}
        self.t0_wall = time.time()
        self.meta = {}
        self.markers = []

    def _grow(self):
        self.cap *= 2
        self.t = np.resize(self.t, self.cap)
        for k, a in self.cols.items():
            b = np.empty(self.cap, dtype=np.float32)
            b[:self.n] = a[:self.n]
            b[self.n:] = np.nan
            self.cols[k] = b

    def _col(self, key):
        a = self.cols.get(key)
        if a is None:
            a = np.full(self.cap, np.nan, dtype=np.float32)
            self.cols[key] = a
        return a

    def append(self, t, sample):
        if self.n >= self.cap:
            self._grow()
        i = self.n
        self.t[i] = t
        for k, v in sample.items():
            if isinstance(v, (int, float)) and v is not None:
                self._col(k)[i] = v
        self.n += 1

    def times(self):
        return self.t[:self.n]

    def col(self, key):
        a = self.cols.get(key)
        return None if a is None else a[:self.n]

    def latest(self, key):
        a = self.col(key)
        if a is None or self.n == 0:
            return None
        # Walk back over trailing NaNs: a sensor that stalls for a sample or
        # two should keep showing its last real reading, not blank out.
        for i in range(self.n - 1, max(-1, self.n - 16), -1):
            if not math.isnan(a[i]):
                return float(a[i])
        return None

    def at(self, key, t):
        """Value of `key` at (or just before) time `t`.

        Outside the recorded span this is None, not the nearest sample: a
        crosshair parked to the right of a short trace must read as "no data"
        rather than silently repeating the last value it saw.
        """
        a = self.col(key)
        if a is None or self.n == 0:
            return None
        lo, hi = self.t[0], self.t[self.n - 1]
        tol = (hi - lo) / max(1, self.n - 1) * 2.0 if self.n > 1 else 1.0
        if t < lo - tol or t > hi + tol:
            return None
        i = int(np.searchsorted(self.t[:self.n], t, side="right")) - 1
        if i < 0:
            return None
        v = a[min(i, self.n - 1)]
        return None if math.isnan(v) else float(v)

    def span(self):
        return (0.0, 0.0) if self.n == 0 else (float(self.t[0]),
                                               float(self.t[self.n - 1]))
