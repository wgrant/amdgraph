"""Pure gpu_metrics ABI tests, independent of device discovery."""

from conftest import gm_blob

from amdgraph.gpu_metrics import v2


def test_v2_power_and_unpopulated_markers():
    decoded = v2.power(gm_blob(socket=20000, soc=2000,
                               cores=(1000, 0xFFFF) + (500,) * 6))
    assert decoded["pwr_socket"] == 20.0
    assert decoded["pwr_soc"] == 2.0
    assert decoded["pwr_cores"] == 4.0


def test_v2_throttle_status_rejects_short_blob():
    assert v2.throttle_status(b"short") is None
