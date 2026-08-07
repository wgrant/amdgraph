"""Strix Halo SMU PM-table layout 0x0064020c.

Measured on a Ryzen AI MAX+ 395. Offsets are float indices; unlisted fields
remain unnamed because plausible neighbouring values are not ABI evidence.
"""

VERSION = 0x0064020C
NCORES = 16

# Eight 4 Hz captures covered idle, selective/all-core CPU, memory, GPU, and
# mixed loads. Package values correlate with gpu_metrics socket power; loading
# CPUs 0-7 then 8-15 separates the two core-cluster thermal pairs. GFX and SoC
# temperatures agree with gpu_metrics after their 100 C ceilings.
SCALARS = {
    "stapm": (1, 1.0), "stapm_lim": (0, 1.0),
    "ppt_fast": (3, 1.0), "ppt_fast_lim": (2, 1.0),
    "ppt_slow": (5, 1.0), "ppt_slow_lim": (4, 1.0),
    "thm_core0": (19, 1.0), "thm_core0_lim": (18, 1.0),
    "thm_core1": (21, 1.0), "thm_core1_lim": (20, 1.0),
    "thm_gfx": (23, 1.0), "thm_gfx_lim": (22, 1.0),
    "thm_soc": (25, 1.0), "thm_soc_lim": (24, 1.0),
}

# Power correlates +0.956 with gpu_metrics (+0.891..+0.978 per core), clock
# +0.830, and C0 +0.975. C0+C1+CC6 sums to 100%; C1 follows Linux shallow C2
# and CC6 its deep C3 counter. Voltage ranges 0.666..1.309 V and responds only
# on selectively loaded cores. A separate workload series establishes 804 as
# the native sampled/effective clock array rather than an estimate.
CORES = {
    "core_power": (740, 1.0), "core_volt": (756, 1.0),
    "core_temp": (772, 1.0), "core_freq": (788, 1000.0),
    "core_freqeff": (804, 1000.0), "core_c0": (820, 1.0),
    "core_c1": (836, 1.0), "core_cc6": (852, 1.0),
}
