from conftest import FakeSource

from amdgraph.service import LocalHistoryService
from amdgraph.tui import dashboard


def test_dashboard_renders_available_metrics_only():
    service = LocalHistoryService(source=FakeSource(keys=("stapm", "tctl")))
    rendered = str(dashboard(service))
    # Rich renderables do not stringify their cells; inspect the row count and
    # ensure absent preferred metrics do not create empty rows instead.
    assert len(dashboard(service).rows) == 1
    service.close()
