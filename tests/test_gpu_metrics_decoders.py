"""Pure gpu_metrics ABI tests, independent of device discovery."""

from conftest import gm3_blob, gm_blob

from amdgraph.backends.amdgpu import AmdGpuBackend
from amdgraph.gpu_metrics import v2
from amdgraph.gpu_metrics import v3


def test_v2_power_and_unpopulated_markers():
    decoded = v2.power(gm_blob(socket=20000, soc=2000,
                               cores=(1000, 0xFFFF) + (500,) * 6))
    assert decoded["pwr_socket"] == 20.0
    assert decoded["pwr_soc"] == 2.0
    assert decoded["pwr_cores"] == 4.0


def test_v2_throttle_status_rejects_short_blob():
    assert v2.throttle_status(b"short") is None


def test_v3_decoder_emits_only_declared_metrics():
    decoded, _residency = v3.decode(gm3_blob())
    assert set(decoded) <= set(AmdGpuBackend.ALL_METRIC_KEYS)
