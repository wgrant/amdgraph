"""Layer 0 -- pure gpu_metrics_v2_1 field decoders."""

import struct

from ..fields import GM_CORE_PWR_OFF, GM_PWR_OFF, GM_THROTTLE_OFF


def throttle_status(raw):
    if raw is None or len(raw) < GM_THROTTLE_OFF + 4:
        return None
    return struct.unpack_from("<I", raw, GM_THROTTLE_OFF)[0]


def power(raw):
    if raw is None or len(raw) < GM_CORE_PWR_OFF + 16:
        return None
    socket, _cpu, soc, gfx = struct.unpack_from("<HHHH", raw, GM_PWR_OFF)
    cores = struct.unpack_from("<8H", raw, GM_CORE_PWR_OFF)

    def watts(value):
        return None if value == 0xFFFF else value / 1000.0

    return {"pwr_socket": watts(socket), "pwr_soc": watts(soc),
            "pwr_gfxslot": watts(gfx),
            "pwr_cores": sum(value for value in cores
                             if value != 0xFFFF) / 1000.0}
