import socket
import threading
import time

from amdgraph.protocol import PROTOCOL_VERSION, encode
from amdgraph.remote import RemoteHistoryService


def test_remote_client_reconnects_and_replaces_snapshot(tmp_path):
    path = str(tmp_path / "service.sock")
    ready = threading.Event()
    stop = threading.Event()

    def server():
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        listener.listen()
        ready.set()
        for attempt in range(2):
            conn, _ = listener.accept()
            conn.sendall(encode({"type": "hello", "protocol": PROTOCOL_VERSION,
                                 "capabilities": ["power"], "metadata": {},
                                 "interval": 0.1}))
            conn.sendall(encode({"type": "snapshot",
                                 "samples": [[float(attempt),
                                              {"power": 10.0 + attempt}]],
                                 "markers": [], "metadata": {}}))
            if attempt == 0:
                conn.close()
            else:
                stop.wait(3)
                conn.close()
        listener.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(1)
    remote = RemoteHistoryService(path)
    deadline = time.monotonic() + 4
    while remote.store.latest("power") != 11.0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert remote.store.latest("power") == 11.0
    stop.set()
    remote.close()
    thread.join(timeout=1)
