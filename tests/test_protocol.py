import asyncio
import json

from conftest import FakeSource

from amdgraph.daemon import HistoryServer
from amdgraph.protocol import PROTOCOL_VERSION, apply_snapshot, encode, snapshot
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
