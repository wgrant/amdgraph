"""Pure gpu_metrics ABI tests, independent of device discovery."""

from conftest import gm3_blob, gm_blob

from amdgraph import fields
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


def test_v2_2_indep_throttle_status_and_socket_watts():
    blob = gm_blob(fmt_rev=2, cont_rev=2, size=fields.GM2_2_SIZE,
                   throttle=0x02, indep=1 << 5, socket=10, soc=1219,
                   cores=(1500,) * 8)
    # The same blob: ASIC throttle bit 1 (FPPT) and its independent twin,
    # SMU_THROTTLER_FPPT_BIT 5, assert together -- exactly what was read live.
    assert v2.indep_throttle_status(blob) == 1 << 5
    assert v2.throttle_status(blob) == 0x02
    # Socket power is W on v2_2, so the mW default must be overridden by the
    # backend. cpu/soc/core stay milliwatts on both layouts.
    assert v2.power(blob, socket_scale=1.0)["pwr_socket"] == 10.0
    assert v2.power(blob, socket_scale=1.0)["pwr_soc"] == 1.219
    assert v2.power(blob, socket_scale=1.0)["pwr_cores"] == 12.0
    assert v2.power(blob)["pwr_socket"] == 0.01   # the wrong reading: /1000


def test_v2_2_indep_throttle_status_rejects_short_blob():
    assert v2.indep_throttle_status(gm_blob(fmt_rev=2, cont_rev=2)) is None
    assert v2.indep_throttle_status(b"short") is None


def test_v3_decoder_emits_only_declared_metrics():
    decoded, _residency = v3.decode(gm3_blob())
    assert set(decoded) <= set(AmdGpuBackend.ALL_METRIC_KEYS)
