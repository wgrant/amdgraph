from conftest import FakeSource

from amdgraph.service import LocalHistoryService
from amdgraph.session import load_session


def test_local_service_owns_sampling_reset_and_markers(tmp_path):
    source = FakeSource()
    service = LocalHistoryService(0.5, source, str(tmp_path))
    assert service.store.n == 1
    service.sample_once()
    service.mark("load")
    assert service.store.markers[0][1] == "load"
    service.reset()
    assert service.store.n == 0 and source.resets == 1
    service.close()
    service.close()
    assert source.closed == 1


def test_local_service_records_its_history_stream(tmp_path):
    service = LocalHistoryService(0.5, FakeSource(), str(tmp_path))
    path = service.start_recording()
    service.sample_once()
    service.mark("event")
    service.stop_recording()
    stored = load_session(path)
    assert stored.n == 1
    assert stored.markers[0][1] == "event"
