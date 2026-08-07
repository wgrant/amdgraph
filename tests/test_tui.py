from conftest import FakeSource

from amdgraph.service import LocalHistoryService
from amdgraph.store import Store
from amdgraph.tui import dashboard, sparkline


def test_dashboard_renders_available_metrics_only():
    service = LocalHistoryService(source=FakeSource(keys=("stapm", "tctl")))
    rendered = str(dashboard(service))
    # Rich renderables do not stringify their cells; inspect the row count and
    # ensure absent preferred metrics do not create empty rows instead.
    assert len(dashboard(service).rows) == 1
    service.close()


def test_sparkline_resamples_scales_and_preserves_gaps():
    store = Store()
    store.append(0.0, {"cpu_busy": 0.0})
    store.append(1.0, {})
    store.append(2.0, {"cpu_busy": 100.0})
    line = sparkline(store, "cpu_busy", width=3, seconds=60)
    assert line == "▁ █"


def test_sparkline_auto_scales_unbounded_metric():
    store = Store()
    for i, value in enumerate((10.0, 20.0, 30.0)):
        store.append(float(i), {"stapm": value})
    assert sparkline(store, "stapm", width=3) == "▁▅█"
