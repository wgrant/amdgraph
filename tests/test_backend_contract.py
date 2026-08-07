"""Common invariants for every hardware backend implementation."""

from amdgraph.backends.host import HostBackend
from amdgraph.model import Metric
from amdgraph.sysfs import MemoryFS


def test_declared_metrics_are_unique_and_typed():
    backend = HostBackend(MemoryFS())
    metrics = backend.metrics()
    assert all(isinstance(metric, Metric) for metric in metrics)
    assert len(metrics) == len({metric.key for metric in metrics})


def test_backend_lifecycle_defaults_are_idempotent():
    backend = HostBackend(MemoryFS())
    backend.reset(MemoryFS())
    backend.reset(MemoryFS())
    backend.close()
    backend.close()
