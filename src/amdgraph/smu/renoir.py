"""Renoir / Lucienne SMU PM-table layout 0x00370005.

Offsets are float indices. This module is data only so the evidence and ABI
map stay together, independently of the decoder that consumes them.

The field order comes from the renoir_tuning_utility / sysmon.cs map, which
was built against physical SMU memory.  Its offsets are the 0x00370004
layout: 0x00370005 inserts seven VCN telemetry floats (Busy, Decode, Encode
Gen/Low/Real, PG, JPEG) between MaxDramBW (191) and CORE POWER 0 -- the tool's
own 0x00370005 logging header lists them there, and it reads the shifted
fields with the 0x00370004 offsets, so its live sensor list is off by seven
for every block from the cores onward.  The 0x00370004 table is 555 floats;
0x00370005 is 562, which is exactly the seven it adds.

Every index below was rechecked on live silicon (Ryzen 7 PRO 4750U, ThinkPad
X13 Gen 1) rather than transcribed:
"""

VERSION = 0x00370005
NCORES = 8

# Scalars 0-191 agree with the sysmon.cs map one for one.  Limits match the
# machine's 15 W envelope (STAPM 12.5 W); THM VALUE CORE (17) tracks k10temp
# Tctl (62 -> 93 degC under all-core load against 71 -> 90.5); CCLK GLOBAL
# FREQ (39) reads 4.15 GHz against a 4.19 GHz /proc/cpuinfo boost; VID (29)
# reads 0.91 V.  VDDCR CPU POWER (34) and CPU TELEMETRY POWER (100) both read
# 3.7 W -- a single counter shown twice, so neither is exported on its own.
# vddcr_soc is the SOC SET VOLTAGE (101), 0.74 V at idle.
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
    "vid": (29, 1.0), "vid_lim": (28, 1.0),
    "vddcr_soc": (101, 1.0),
    # sysmon.cs puts FCLK/UCLK/MEMCLK at 371/372/373 (the 0x00370004 layout);
    # with the seven VCN floats in they sit at 378/379/380.  Verified against
    # pp_dpm_fclk / pp_dpm_mclk: during memory load they hold the current DPM
    # state (1200 MHz), where the unshifted positions read 2.6 / 318 / 28 --
    # nothing clock-shaped.
    "fclk": (378, 1.0), "uclk": (379, 1.0), "mclk": (380, 1.0),
}

CORES = {
    # Base = sysmon.cs position + 7 (the VCN insert).  Bases earned by
    # burning a single core: only that slot's C0/CC6 pair moves, C0 + CC6
    # sums to 100%, its frequency reads the boost clock in GHz (scale x1000)
    # while the others fold, and its temperature leads the rest of the block
    # (55-93 degC across an all-core run).
    "core_power": (199, 1.0), "core_volt": (207, 1.0),
    "core_temp": (215, 1.0), "core_freq": (239, 1000.0),
    "core_freqeff": (247, 1000.0), "core_c0": (255, 1.0),
    "core_cc6": (271, 1.0),
}
