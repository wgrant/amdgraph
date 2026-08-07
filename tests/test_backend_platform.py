"""The ThinkPad EC: fan command decode, and probe()'s silent skip on any
other machine.
"""

import pytest

from amdgraph.backends import platform
from amdgraph.sysfs import RealFS


class TestFanCommand:
    @pytest.fixture
    def fan(self, tmp_path):
        def run(**files):
            for k, v in files.items():
                (tmp_path / k).write_text(f"{v}\n")
            return platform.fan_command(str(tmp_path), RealFS())
        return run

    def test_disengaged_sits_above_level_seven(self, fan):
        assert fan(pwm1_enable=0, pwm1=255) == (8.0, "FULL")

    def test_firmware_auto_reports_no_level(self, fan):
        # pwm1 still holds the last manual value, so the mode has to win.
        assert fan(pwm1_enable=2, pwm1=128) == (None, "AUTO")

    @pytest.mark.parametrize("pwm, level", [(255, 7), (0, 0), (128, 4)])
    def test_manual_level_rescaled(self, fan, pwm, level):
        assert fan(pwm1_enable=1, pwm1=pwm) == (level, None)

    def test_absent_interface(self):
        assert platform.fan_command("/nope", RealFS()) == (None, None)


def test_probe_is_silent_when_not_a_thinkpad():
    """Most machines simply aren't ThinkPads -- that isn't a degraded
    condition worth a status-bar note the way an unsupported pm_table
    version is."""
    backend, note = platform.probe(RealFS())
    # This container/CI box is not a ThinkPad either way; either outcome
    # (found or not) must carry no note when nothing is wrong.
    assert note == ""


def test_cros_ec_reads_framework_temperatures_and_fans(tmp_path):
    for name, value in (("temp1_input", 43850), ("temp2_input", 39850),
                        ("temp3_input", 33850), ("temp4_input", 41850),
                        ("temp5_input", 40850), ("fan1_input", 900),
                        ("fan2_input", 800), ("fan3_input", 700)):
        (tmp_path / name).write_text(f"{value}\n")
    out = {}
    platform.CrosEcBackend(str(tmp_path)).sample(out, RealFS())
    assert out == {"ec_power": 43.85, "ec_memory": 39.85,
                   "ec_ambient": 33.85, "ec_cpu": 41.85,
                   "ec_cpu_virtual": 40.85, "fan1": 900.0,
                   "fan2": 800.0, "fan3": 700.0}
