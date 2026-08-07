"""Layer 2 -- versioned wire representation for history services."""

import json
import math

from .store import Store

PROTOCOL_VERSION = 1


def encode(message):
    return (json.dumps(message, separators=(",", ":"), allow_nan=False)
            + "\n").encode()


def snapshot(store):
    samples = []
    keys = tuple(store.cols)
    for i in range(store.n):
        values = {}
        for key in keys:
            value = float(store.cols[key][i])
            if not math.isnan(value):
                values[key] = value
        samples.append([float(store.t[i]), values])
    return {"type": "snapshot", "samples": samples,
            "markers": list(store.markers), "metadata": dict(store.meta)}


def apply_snapshot(message):
    store = Store(cap=max(16, len(message.get("samples", ()))))
    for t, values in message.get("samples", ()):
        store.append(float(t), values)
    store.markers = [(float(t), str(label))
                     for t, label in message.get("markers", ())]
    store.meta = dict(message.get("metadata", {}))
    return store
