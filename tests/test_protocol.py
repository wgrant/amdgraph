import asyncio
import json
import threading
import time

from conftest import FakeSource

from amdgraph.daemon import HistoryServer
from amdgraph.protocol import PROTOCOL_VERSION, apply_snapshot, encode, snapshot
from amdgraph.remote import RemoteHistoryService
from amdgraph.service import LocalHistoryService
from amdgraph.store import Store


def test_snapshot_round_trip_preserves_history_markers_and_metadata():
    store = Store()
    store.append(1.0, {"power": 12.5})
    store.markers = [(1.0, "load")]
    store.meta = {"host": "test"}
    restored = apply_snapshot(snapshot(store))
    assert restored.latest("power") == 12.5
    assert restored.markers == [(1.0, "load")]
    assert restored.meta == {"host": "test"}


def test_server_handshake_snapshot_and_marker(tmp_path):
    async def scenario():
        path = str(tmp_path / "amdgraph.sock")
        service = LocalHistoryService(60, FakeSource(), str(tmp_path))
        server = await HistoryServer(service, path).start()
        reader, writer = await asyncio.open_unix_connection(path)
        hello = json.loads(await reader.readline())
        history = json.loads(await reader.readline())
        assert hello["protocol"] == PROTOCOL_VERSION
        assert history["type"] == "snapshot"
        writer.write(encode({"type": "mark", "label": "event"}))
        await writer.drain()
        marker = json.loads(await asyncio.wait_for(reader.readline(), 1.0))
        assert marker["type"] == "marker" and marker["label"] == "event"
        writer.close()
        await writer.wait_closed()
        await server.close()

    asyncio.run(scenario())


def test_remote_client_end_to_end_with_history_server(tmp_path):
    path = str(tmp_path / "integrated.sock")
    ready = threading.Event()
    state = {}

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        service = LocalHistoryService(0.05, FakeSource(), str(tmp_path))
        server = loop.run_until_complete(HistoryServer(service, path).start())
        state.update(loop=loop, server=server)
        ready.set()
        loop.run_forever()
        loop.close()

    thread = threading.Thread(target=run_server)
    thread.start()
    assert ready.wait(2)
    remote = RemoteHistoryService(path)
    deadline = time.monotonic() + 2
    while remote.store.n < 3 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert remote.store.n >= 3
    remote.mark("integrated")
    while not remote.store.markers and time.monotonic() < deadline:
        time.sleep(0.02)
    assert remote.store.markers[-1][1] == "integrated"
    remote.close()
    future = asyncio.run_coroutine_threadsafe(
        state["server"].close(), state["loop"])
    future.result(2)
    state["loop"].call_soon_threadsafe(state["loop"].stop)
    thread.join(timeout=2)
