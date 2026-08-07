"""Layer 1 -- the ThinkPad EC.

`thinkpad_acpi` supplies EC skin and CPU temperature, fans, the palm sensor
and `dytc_lapmode`. None of that exists on another vendor's laptop -- this is
the module a Framework (`cros_ec`), Steam Deck (`steamdeck`/jupiter) or
desktop (`nct6775`-class) backend gets added next to, per docs/HARDWARE.md's
"Adding a part" §4.

May import: fields, sysfs, backends.base.
"""

from ..fields import TPACPI
from ..sysfs import find_hwmon
from .base import Backend


class ThinkpadBackend(Backend):
    def __init__(self, tp):
        self.tp = tp

    def sample(self, s, fs):
        # temp5 is the EC's TMP3 sensor (EC RAM 0x7C) -- the palm-rest skin
        # temperature the firmware fan curve reacts to, and the closest EC
        # analogue of the SMU's STT model. temp1 is its CPU sensor.
        s["ec_skin"] = fs.read_num(f"{self.tp}/temp5_input", 1000)
        s["ec_cpu"] = fs.read_num(f"{self.tp}/temp1_input", 1000)
        # Only these two. temp1/3/6/7 all report the identical value and
        # track each other exactly -- they are aliases of one CPU sensor, so
        # the EC publishes just two distinct temperatures to Linux. Reading
        # the other three would cost ~0.45 ms per sample of EC transactions
        # for a third copy of a line already on the chart.
        #
        # This was checked while hunting the lap-mode trigger, which halves
        # edc_lim (105 -> 52 A, ~8 W) and correlates with none of the sensors
        # Linux can see. It is not hiding in an unread thermistor: there
        # aren't any. The EC decides privately.
        s["palm"] = fs.read_num(f"{TPACPI}/palmsensor")
        s["lapmode"] = fs.read_num(f"{TPACPI}/dytc_lapmode")
        s["fan1"] = fs.read_num(f"{self.tp}/fan1_input")
        s["fan2"] = fs.read_num(f"{self.tp}/fan2_input")
        s["fan_cmd"], s["fan_mode"] = fan_command(self.tp, fs)


def fan_command(tp, fs):
    """(level, mode) as COMMANDED by software, not as achieved.

    thinkpad_acpi maps pwm1_enable 0 to "disengaged" (fan unrestricted), 2 to
    firmware auto, 1 to a manual level. In disengaged mode pwm1 still reports
    the last manual level, so the mode has to win. Level is pwm1 rescaled
    from 0..255 onto 0..7; disengaged plots as 8 so it sits above level 7
    rather than aliasing onto it.

    Plotted directly above the tachometers on purpose -- sharing a time axis
    makes the lag between what the fan daemon asks for and what the fan does
    readable straight off the two traces.
    """
    mode = fs.read_num(f"{tp}/pwm1_enable")
    if mode is None:
        return None, None
    if mode == 0:
        return 8.0, "FULL"
    if mode == 2:
        return None, "AUTO"
    pwm = fs.read_num(f"{tp}/pwm1")
    return (None, None) if pwm is None else (round(pwm * 7 / 255), None)


def probe(fs):
    """Silent when absent: most machines simply aren't ThinkPads, which is
    not a degraded condition worth a status-bar note the way an unsupported
    pm_table version is."""
    tp = find_hwmon(fs=fs).get("thinkpad")
    if not tp:
        return None, ""
    return ThinkpadBackend(tp), ""
