"""Layer 6 -- persistent local history server."""

import argparse
import asyncio
import os
import signal

from .protocol import PROTOCOL_VERSION, encode, snapshot
from .persistence import SQLiteHistory
from .service import LocalHistoryService

DEFAULT_SOCKET = os.path.join(
    os.environ.get("XDG_RUNTIME_DIR", f"/tmp/amdgraph-{os.getuid()}"),
    "amdgraph.sock")
DEFAULT_DATABASE = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "amdgraph", "history.sqlite3")
DEFAULT_RETENTION = 7 * 24 * 60 * 60
DEFAULT_SNAPSHOT = 60 * 60


class HistoryServer:
    def __init__(self, service, path=DEFAULT_SOCKET,
                 snapshot_seconds=DEFAULT_SNAPSHOT):
        self.service = service
        self.path = path
        self.snapshot_seconds = snapshot_seconds
        self.clients = set()
        self.server = None
        self._sampling = None

    async def start(self):
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.server = await asyncio.start_unix_server(self._client, self.path)
        os.chmod(self.path, 0o600)
        self._sampling = asyncio.create_task(self._sample_loop())
        return self

    async def _sample_loop(self):
        while True:
            await asyncio.sleep(self.service.interval)
            t, values = self.service.sample_once()
            await self.broadcast({"type": "sample", "t": t, "values": values})

    async def broadcast(self, message):
        stale = []
        for queue in self.clients:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.clients.discard(queue)

    async def _writer(self, writer, queue):
        while True:
            writer.write(encode(await queue.get()))
            await writer.drain()

    async def _client(self, reader, writer):
        queue = asyncio.Queue(maxsize=128)
        self.clients.add(queue)
        peer_writer = asyncio.create_task(self._writer(writer, queue))
        await queue.put({"type": "hello", "protocol": PROTOCOL_VERSION,
                         "capabilities": list(self.service.capabilities()),
                         "metadata": self.service.metadata(),
                         "interval": self.service.interval})
        end = self.service.store.span()[1]
        await queue.put(snapshot(self.service.history(
            max(0.0, end - self.snapshot_seconds), end)))
        try:
            while line := await reader.readline():
                import json
                request = json.loads(line)
                kind = request.get("type")
                if kind == "mark":
                    t = self.service.mark(request.get("label", "mark"))
                    message = {"type": "marker", "t": t,
                               "label": request.get("label", "mark")}
                    await self.broadcast(message)
                elif kind == "cap_rate":
                    self.service.set_cap_rate(float(request["hz"]))
                elif kind == "record_start":
                    path = self.service.start_recording(request.get("path"))
                    await queue.put({"type": "recording", "path": path})
                elif kind == "record_stop":
                    self.service.stop_recording()
                    await queue.put({"type": "recording", "path": None})
                elif kind == "snapshot":
                    await queue.put(snapshot(self.service.history(
                        request.get("start"), request.get("end"))))
        finally:
            self.clients.discard(queue)
            peer_writer.cancel()
            writer.close()
            await writer.wait_closed()

    async def close(self):
        if self._sampling is not None:
            self._sampling.cancel()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        self.service.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


async def serve(interval=1.0, path=DEFAULT_SOCKET, database=DEFAULT_DATABASE,
                retention=DEFAULT_RETENTION):
    persistence = SQLiteHistory(database, retention) if database else None
    service = LocalHistoryService(interval, persistence=persistence)
    if persistence is not None:
        persistence.set_metadata(service.metadata())
    server = await HistoryServer(service, path).start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        await server.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="amdgraph history server")
    parser.add_argument("-i", "--interval", type=float, default=1.0)
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--retention", type=float, metavar="SECONDS",
                        default=DEFAULT_RETENTION)
    migration = parser.add_mutually_exclusive_group()
    migration.add_argument("--import-csv", metavar="FILE")
    migration.add_argument("--export-csv", metavar="FILE")
    args = parser.parse_args(argv)
    if args.import_csv or args.export_csv:
        history = SQLiteHistory(args.database, args.retention)
        try:
            if args.import_csv:
                history.import_csv(args.import_csv)
            else:
                history.export_csv(args.export_csv)
        finally:
            history.close()
        return 0
    asyncio.run(serve(max(0.1, args.interval), args.socket,
                      args.database, args.retention))
