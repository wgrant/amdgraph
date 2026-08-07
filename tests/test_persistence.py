from amdgraph.persistence import SQLiteHistory


def test_sqlite_roundtrip_range_retention_and_markers(tmp_path):
    history = SQLiteHistory(str(tmp_path / "history.db"), retention_seconds=5)
    history.set_metadata({"host": "test"})
    history.append(1, {"power": 10.0})
    history.append(10, {"power": 20.0})
    history.mark(10, "load")
    store = history.load(9, 11)
    assert store.n == 1 and store.latest("power") == 20.0
    assert store.markers == [(10.0, "load")]
    assert store.meta == {"host": "test"}
    history.close()


def test_sqlite_csv_interchange(tmp_path):
    first = SQLiteHistory(str(tmp_path / "first.db"))
    first.append(1, {"power": 12.5})
    first.mark(1, "event")
    csv_path = str(tmp_path / "history.csv")
    first.export_csv(csv_path)
    second = SQLiteHistory(str(tmp_path / "second.db"))
    second.import_csv(csv_path)
    assert second.load().latest("power") == 12.5
    assert second.load().markers == [(1.0, "event")]
    first.close()
    second.close()
