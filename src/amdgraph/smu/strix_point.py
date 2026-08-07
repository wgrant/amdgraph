"""Source-derived Strix Point SMU PM-table layouts.

Unlike the Phoenix and Strix Halo profiles, these offsets have not been
reproduced on hardware available to this project.  They come from modern
RyzenAdj accessors whose comments record tests with RAPL, gpu_metrics_v3_0,
targeted CPU/GPU/memory loads, and platform-profile changes.  amkillam's
ryzen_smu independently confirms versions 0x005d0008/9 and a 0xd54-byte table.

Only internally consistent, explicitly tested fields are included.  In
particular, contradictory or calculated accessors (including offset 0xd0,
named both package power and a boost target in that source) are omitted.
Offsets below are float indices, converted from RyzenAdj byte offsets.
"""

VERSIONS = (0x005D0008, 0x005D0009)
NCORES = 12

SCALARS = {
    # Common PM-table header. RyzenAdj reports the APU pair as plausible but
    # its value as untested/usually zero, so it remains recorded but unplotted.
    "stapm": (1, 1.0), "stapm_lim": (0, 1.0),
    "ppt_fast": (3, 1.0), "ppt_fast_lim": (2, 1.0),
    "ppt_slow": (5, 1.0), "ppt_slow_lim": (4, 1.0),
    "ppt_apu": (7, 1.0), "ppt_apu_lim": (6, 1.0),
    # Selective Zen 5 / Zen 5c CPU loads and gpu_metrics-backed GFX/SoC loads
    # establish four separate (limit, value) thermal pairs.
    "thm_core0": (17, 1.0), "thm_core0_lim": (16, 1.0),
    "thm_core1": (19, 1.0), "thm_core1_lim": (18, 1.0),
    "thm_gfx": (21, 1.0), "thm_gfx_lim": (20, 1.0),
    "thm_soc": (23, 1.0), "thm_soc_lim": (22, 1.0),
    # These current pairs were tested/profile-sensitive in RyzenAdj. They map
    # onto the existing TDC vocabulary; the source aliases its EDC accessors
    # to the same offsets, so duplicate EDC series are deliberately omitted.
    "tdc": (13, 1.0), "tdc_lim": (12, 1.0),
    "tdc_soc": (15, 1.0), "tdc_soc_lim": (14, 1.0),
    # RyzenAdj identifies 0x4c0 as the better of two adjacent GFX clocks and
    # validates it against gpu_metrics and GPU workloads. It is already MHz.
    "gfx_clk": (304, 1.0),
}

# Twelve entries per block. RyzenAdj notes that fused-off cores retain a
# temperature but report zero power, voltage, and clock.
CORES = {
    "core_power": (630, 1.0),
    "core_volt": (642, 1.0),
    "core_temp": (654, 1.0),
    "core_freq": (666, 1000.0),  # GHz -> MHz
}
