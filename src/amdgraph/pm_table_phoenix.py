"""Phoenix / Hawk Point SMU PM-table layout 0x004c0009.

Offsets are float indices.  This module is data only so the evidence and ABI
map stay together, independently of the decoder that consumes them.
"""

VERSION = 0x004C0009
NCORES = 8

# Header fields agree with RyzenAdj; clocks and core arrays were rechecked on
# live Phoenix silicon.  C0+C1+C6 sums to 100%, and mclk/fclk agree with the
# machine's LPDDR5-6400 configuration.
SCALARS = {
    "stapm": (1, 1.0), "stapm_lim": (0, 1.0),
    "ppt_fast": (3, 1.0), "ppt_fast_lim": (2, 1.0),
    "ppt_slow": (5, 1.0), "ppt_slow_lim": (4, 1.0),
    "ppt_apu": (7, 1.0), "ppt_apu_lim": (6, 1.0),
    "tdc": (9, 1.0), "tdc_lim": (8, 1.0),
    "tdc_soc": (11, 1.0), "tdc_soc_lim": (10, 1.0),
    "edc": (13, 1.0), "edc_lim": (12, 1.0),
    "edc_soc": (15, 1.0), "edc_soc_lim": (14, 1.0),
    "tctl": (17, 1.0), "tctl_lim": (16, 1.0),
    "thm_gfx": (19, 1.0), "thm_gfx_lim": (18, 1.0),
    "thm_soc": (21, 1.0), "thm_soc_lim": (20, 1.0),
    "stt": (23, 1.0), "stt_lim": (22, 1.0),
    "fit": (27, 1.0), "fit_lim": (26, 1.0),
    "vid": (29, 1.0), "vid_lim": (28, 1.0),
    # Instantaneous SMU clock, unlike the coarse amdgpu DPM level. Index 57
    # is its 2700 MHz ceiling on the measured part.
    "gfx_clk": (56, 1000.0), "gfx_clk_max": (57, 1000.0),
    "fclk": (89, 1.0), "uclk": (93, 1.0), "mclk": (97, 1.0),
    "vddcr_soc": (101, 1.0),
    # 1/2/4/8-process memory tests correlated +0.997 with index 194. Absolute
    # scaling against known traffic establishes binary GiB/s units.
    "dram_rd": (194, 1.0), "dram_wr": (195, 1.0),
    "cldo_vddp": (477, 1.0),
}

CORES = {
    "core_power": (513, 1.0), "core_volt": (521, 1.0),
    "core_temp": (529, 1.0), "core_freq": (553, 1000.0),
    "core_freqeff": (561, 1000.0), "core_c0": (569, 1.0),
    "core_cc6": (585, 1.0),
}
