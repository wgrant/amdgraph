"""Layer 0 -- pure gpu_metrics_v3_0 decoder."""

import struct

from ..fields import (GM3_ACTIVITY_OFF, GM3_ALL_CORE_PWR_OFF, GM3_APU_PWR_OFF,
                      GM3_CLOCKS_OFF, GM3_CORE_CLOCK_OFF,
                      GM3_CORE_MAXFREQ_OFF, GM3_CORE_PWR_OFF,
                      GM3_DGPU_PWR_OFF, GM3_DRAM_BW_OFF, GM3_GFX_MAXFREQ_OFF,
                      GM3_GFX_PWR_OFF, GM3_IPU_ACTIVITY_OFF, GM3_IPU_BW_OFF,
                      GM3_IPU_PWR_OFF, GM3_RESIDENCY_OFF, GM3_SIZE,
                      GM3_SOCKET_PWR_OFF, GM3_STAPM_CURRENT_LIMIT_OFF,
                      GM3_SYS_PWR_OFF)


def _valid(value, scale=1.0):
    return None if value in (0xFFFF, 0xFFFFFFFF) else value / scale


def decode(raw):
    """Return ``(telemetry, residency counters)`` without merge policy."""
    if raw is None or len(raw) != GM3_SIZE:
        return {}, None
    u16 = lambda off, n=1: struct.unpack_from(f"<{n}H", raw, off)
    u32 = lambda off: struct.unpack_from("<I", raw, off)[0]
    out = {}
    out["thm_gfx"] = _valid(u16(4)[0], 100.0)
    out["thm_soc"] = _valid(u16(6)[0], 100.0)
    for i, value in enumerate(u16(8, 16)):
        if value not in (0, 0xFFFF):
            out[f"core_temp_{i}"] = value / 100.0
    skin = u16(40)[0]
    if skin not in (0, 0xFFFF):
        out["stt"] = skin / 100.0
    out["gpu_busy"], out["vcn_busy"] = (
        _valid(value) for value in u16(GM3_ACTIVITY_OFF, 2))
    ipu_busy = u16(GM3_IPU_ACTIVITY_OFF, 8)
    for i, value in enumerate(ipu_busy):
        out[f"ipu_busy_{i}"] = _valid(value)
    valid_ipu = [value for value in ipu_busy if value != 0xFFFF]
    if valid_ipu:
        out["ipu_busy_mean"] = sum(valid_ipu) / len(valid_ipu)
    c0 = u16(62, 16)
    for i, value in enumerate(c0):
        out[f"core_c0_{i}"] = _valid(value)
    valid_c0 = [value for value in c0 if value != 0xFFFF]
    if valid_c0:
        out["core_c0_mean"] = sum(valid_c0) / len(valid_c0)
    out["dram_rd"] = _valid(u16(GM3_DRAM_BW_OFF)[0], 1024.0)
    out["dram_wr"] = _valid(u16(GM3_DRAM_BW_OFF + 2)[0], 1024.0)
    out["ipu_rd"] = _valid(u16(GM3_IPU_BW_OFF)[0], 1024.0)
    out["ipu_wr"] = _valid(u16(GM3_IPU_BW_OFF + 2)[0], 1024.0)
    out["pwr_ipu"] = _valid(u16(GM3_IPU_PWR_OFF)[0], 1000.0)
    for key, offset in (("pwr_socket", GM3_SOCKET_PWR_OFF),
                        ("pwr_apu", GM3_APU_PWR_OFF),
                        ("pwr_gfx", GM3_GFX_PWR_OFF),
                        ("pwr_dgpu", GM3_DGPU_PWR_OFF),
                        ("core_power_sum", GM3_ALL_CORE_PWR_OFF)):
        out[key] = _valid(u32(offset), 1000.0)
    for i, value in enumerate(u16(GM3_CORE_PWR_OFF, 16)):
        out[f"core_power_{i}"] = _valid(value, 1000.0)
    out["pwr_system"] = _valid(u16(GM3_SYS_PWR_OFF)[0], 1000.0)
    out["stapm_lim"] = _valid(u16(GM3_STAPM_CURRENT_LIMIT_OFF)[0], 1000.0)
    out["stapm"] = out.get("pwr_socket")
    clocks = u16(GM3_CLOCKS_OFF, 8)
    for key, value in zip(("gfx_clk", "socclk", "vpeclk", "ipuclk", "fclk",
                           "vclk", "uclk", "mpipuclk"), clocks):
        out[key] = _valid(value)
    core_clocks = u16(GM3_CORE_CLOCK_OFF, 16)
    for i, value in enumerate(core_clocks):
        out[f"core_freq_{i}"] = _valid(value)
    valid_clocks = [value for value in core_clocks if value != 0xFFFF]
    if valid_clocks:
        out["core_freq_mean"] = sum(valid_clocks) / len(valid_clocks)
        out["core_freq_max"] = max(valid_clocks)
    out["core_freq_limit"] = _valid(u16(GM3_CORE_MAXFREQ_OFF)[0])
    out["gfx_clk_max"] = _valid(u16(GM3_GFX_MAXFREQ_OFF)[0])
    return out, struct.unpack_from("<7I", raw, GM3_RESIDENCY_OFF)
