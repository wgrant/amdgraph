"""Layer 3 -- crash-safe SQLite history and CSV interchange."""

import json
import math
import os
import sqlite3
import time

from .session import Recorder, load_session
from .store import Store


class SQLiteHistory:
    """One JSON object per sample: queryable time chunks, not metric rows."""

    def __init__(self, path, retention_seconds=None):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.retention_seconds = retention_seconds
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS samples (
                t REAL PRIMARY KEY, wall REAL NOT NULL, values_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS markers (
                t REAL NOT NULL, label TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
        """)

    def append(self, t, values, wall=None):
        clean = {key: value for key, value in values.items()
                 if value is not None and
                 not (isinstance(value, float) and not math.isfinite(value))}
        self.db.execute(
            "INSERT OR REPLACE INTO samples VALUES (?, ?, ?)",
            (float(t), float(wall or time.time()),
             json.dumps(clean, separators=(",", ":"))))
        if self.retention_seconds is not None:
            self.db.execute("DELETE FROM samples WHERE t < ?",
                            (float(t) - self.retention_seconds,))
            self.db.execute("DELETE FROM markers WHERE t < ?",
                            (float(t) - self.retention_seconds,))
        self.db.commit()

    def mark(self, t, label):
        self.db.execute("INSERT INTO markers VALUES (?, ?)",
                        (float(t), str(label)))
        self.db.commit()

    def set_metadata(self, metadata):
        self.db.executemany(
            "INSERT OR REPLACE INTO metadata VALUES (?, ?)",
            ((str(key), str(value)) for key, value in metadata.items()))
        self.db.commit()

    def load(self, start=None, end=None):
        clauses, args = [], []
        if start is not None:
            clauses.append("t >= ?")
            args.append(float(start))
        if end is not None:
            clauses.append("t <= ?")
            args.append(float(end))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute(
            "SELECT t, values_json FROM samples" + where + " ORDER BY t", args)
        store = Store()
        for t, values in rows:
            store.append(float(t), json.loads(values))
        store.markers = [(float(t), label) for t, label in self.db.execute(
            "SELECT t, label FROM markers" + where + " ORDER BY t", args)]
        store.meta = dict(self.db.execute("SELECT key, value FROM metadata"))
        return store

    def clear(self):
        self.db.execute("DELETE FROM samples")
        self.db.execute("DELETE FROM markers")
        self.db.commit()

    def export_csv(self, path, keys=None):
        store = self.load()
        keys = list(keys or store.cols)
        recorder = Recorder(path, keys, store.meta)
        for i in range(store.n):
            values = {}
            for key in keys:
                column = store.cols.get(key)
                if column is not None and not math.isnan(float(column[i])):
                    values[key] = float(column[i])
            recorder.write(float(store.t[i]), values)
        for t, label in store.markers:
            recorder.mark(t, label)
        recorder.close()

    def import_csv(self, path):
        store = load_session(path)
        self.set_metadata(store.meta)
        for i in range(store.n):
            values = {key: float(column[i]) for key, column in store.cols.items()
                      if not math.isnan(float(column[i]))}
            self.append(float(store.t[i]), values)
        for t, label in store.markers:
            self.mark(t, label)

    def close(self):
        self.db.close()
