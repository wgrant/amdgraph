"""Layer 3 -- reconnecting Unix-socket history service client."""

import json
import socket
import threading
import time

from .protocol import PROTOCOL_VERSION, apply_snapshot, encode
from .store import Store


class RemoteHistoryService:
    def __init__(self, path, connect_timeout=3.0):
        self.path = path
        self.store = Store()
        self.interval = 1.0
        self.recorder = None
        self.source = self
        self._capabilities = ()
        self._metadata = {}
        self._notes = ["connecting to amdgraph service"]
        self._socket = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(connect_timeout):
            raise ConnectionError(f"cannot connect to {path}")
        self.started = time.monotonic() - self.store.span()[1]
        self.last_sample = {}

    def _run(self):
        while not self._stop.is_set():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.connect(self.path)
                self._socket = sock
                self._notes = []
                with sock.makefile("r") as stream:
                    for line in stream:
                        self._apply(json.loads(line))
                        if self._stop.is_set():
                            return
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._notes = [f"service disconnected: {error}; reconnecting"]
                self._socket = None
                self._stop.wait(1.0)

    def _apply(self, message):
        kind = message.get("type")
        with self._lock:
            if kind == "hello":
                if message.get("protocol") != PROTOCOL_VERSION:
                    raise ValueError("incompatible service protocol")
                self._capabilities = tuple(message.get("capabilities", ()))
                self._metadata = dict(message.get("metadata", {}))
                self.interval = float(message.get("interval", 1.0))
            elif kind == "snapshot":
                self.store = apply_snapshot(message)
                self._ready.set()
            elif kind == "sample":
                self.last_sample = dict(message.get("values", {}))
                self.store.append(float(message["t"]), self.last_sample)
            elif kind == "marker":
                self.store.markers.append((float(message["t"]),
                                           str(message["label"])))

    def _send(self, message):
        sock = self._socket
        if sock is None:
            raise ConnectionError("history service is disconnected")
        sock.sendall(encode(message))

    def sample_once(self):
        return self.store.span()[1], self.last_sample

    def capabilities(self):
        return self._capabilities

    metric_keys = capabilities

    def metadata(self):
        return dict(self._metadata)

    meta = metadata

    def notes(self):
        return list(self._notes)

    def mark(self, label, t=None):
        self._send({"type": "mark", "label": label})
        return self.store.span()[1]

    def set_cap_rate(self, hz):
        self._send({"type": "cap_rate", "hz": hz})

    def reset(self):
        self._send({"type": "snapshot"})

    def start_recording(self, path=None):
        self._send({"type": "record_start", "path": path})

    def stop_recording(self):
        self._send({"type": "record_stop"})

    def close(self):
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        self._thread.join(timeout=2.0)
