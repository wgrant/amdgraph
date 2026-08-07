"""Layer 3 -- live history service, independent of any frontend."""

import os
import math
import socket
import time
from datetime import datetime

from .model import Source
from .sampler import Sampler
from .session import DATA_DIR, Recorder, record_keys
from .store import Store


class LocalHistoryService:
    """Own sampling, live history, markers, and optional CSV recording."""

    def __init__(self, interval=1.0, source=None, data_dir=DATA_DIR,
                 persistence=None):
        self.interval = max(0.1, float(interval))
        self.source = source if source is not None else Sampler()
        self.data_dir = data_dir
        self.persistence = persistence
        self.store = persistence.load() if persistence is not None else Store()
        self.started = time.monotonic() - self.store.span()[1]
        self.recorder = None
        self.closed = False
        self.sample_once()

    def sample_once(self):
        sample = self.source.sample()
        self.last_sample = sample
        t = time.monotonic() - self.started
        self.store.append(t, sample)
        if self.persistence is not None:
            self.persistence.append(t, sample)
            retention = self.persistence.retention_seconds
            if retention is not None:
                self.store.drop_before(t - retention)
        if self.recorder is not None:
            self.recorder.write(t, sample)
        return t, sample

    def capabilities(self):
        if hasattr(self.source, "metric_keys"):
            return tuple(self.source.metric_keys())
        return tuple(self.store.cols)

    def notes(self):
        return list(self.source.notes())

    def history(self, start=None, end=None):
        if self.persistence is not None:
            return self.persistence.load(start, end)
        if start is None and end is None:
            return self.store
        result = Store()
        for i in range(self.store.n):
            t = float(self.store.t[i])
            if (start is not None and t < start) or (end is not None and t > end):
                continue
            values = {key: float(column[i]) for key, column in
                      self.store.cols.items()
                      if not math.isnan(float(column[i]))}
            result.append(t, values)
        result.markers = [(t, label) for t, label in self.store.markers
                          if (start is None or t >= start)
                          and (end is None or t <= end)]
        result.meta = dict(self.store.meta)
        return result

    def metadata(self):
        return dict(self.source.meta())

    def reset(self):
        self.store = Store()
        self.started = time.monotonic()
        self.source.reset()
        if self.persistence is not None:
            self.persistence.clear()

    def mark(self, label, t=None):
        if t is None:
            t = self.store.span()[1] if self.store.n else 0.0
        self.store.markers.append((float(t), str(label)))
        if self.persistence is not None:
            self.persistence.mark(t, label)
        if self.recorder is not None:
            self.recorder.mark(float(t), str(label))
        return float(t)

    def start_recording(self, path=None):
        if self.recorder is not None:
            return self.recorder.path
        os.makedirs(self.data_dir, exist_ok=True)
        if path is None:
            path = os.path.join(
                self.data_dir, datetime.now().strftime("%Y%m%d-%H%M%S") + ".csv")
        meta = {"amdgraph": "session v1",
                "started": datetime.now().astimezone().isoformat(),
                "host": socket.gethostname(), "interval": f"{self.interval:g}",
                **self.metadata()}
        keys = self.capabilities() or tuple(record_keys())
        self.recorder = Recorder(path, keys, meta)
        return path

    def stop_recording(self):
        if self.recorder is not None:
            self.recorder.close()
        self.recorder = None

    def set_cap_rate(self, hz):
        self.source.set_cap_rate(hz)

    def close(self):
        if self.closed:
            return
        self.stop_recording()
        self.source.close()
        if self.persistence is not None:
            self.persistence.close()
        self.closed = True
