"""Layer 0 -- pure gpu_metrics_v2_1 / v2_2 field decoders."""

import struct

from ..fields import (GM_CORE_PWR_OFF, GM_INDEP_THROTTLE_OFF, GM_PWR_OFF,
                      GM_THROTTLE_OFF)


def throttle_status(raw):
    if raw is None or len(raw) < GM_THROTTLE_OFF + 4:
        return None
    return struct.unpack_from("<I", raw, GM_THROTTLE_OFF)[0]


def indep_throttle_status(raw):
    """The ASIC-independent bitmask only v2_2 and later carry (u64 at 120).
    The kernel fills it from the ASIC mask via renoir_throttler_map, so its
    bit meanings are the SMU_THROTTLER_*_BIT constants of amdgpu_smu.h."""
    if raw is None or len(raw) < GM_INDEP_THROTTLE_OFF + 8:
        return None
    return struct.unpack_from("<Q", raw, GM_INDEP_THROTTLE_OFF)[0]


def power(raw, socket_scale=1000.0):
    """Power fields. Everything is milliwatts except average_socket_power on
    v2_2, which the smu12 driver fills in W (see fields.GM2_2_*). Phoenix
    v2_1 keeps the default /1000; Renoir v2_2 passes 1.0."""
    if raw is None or len(raw) < GM_CORE_PWR_OFF + 16:
        return None
    socket, _cpu, soc, gfx = struct.unpack_from("<HHHH", raw, GM_PWR_OFF)
    cores = struct.unpack_from("<8H", raw, GM_CORE_PWR_OFF)

    def watts(value):
        return None if value == 0xFFFF else value / 1000.0

    socket_w = None if socket == 0xFFFF else socket / socket_scale
    return {"pwr_socket": socket_w, "pwr_soc": watts(soc),
            "pwr_gfxslot": watts(gfx),
            "pwr_cores": sum(value for value in cores
                             if value != 0xFFFF) / 1000.0}
