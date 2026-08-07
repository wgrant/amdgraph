"""Layer 0 -- the hardware map.

Which byte of which sysfs blob holds which quantity, on this part. Every entry
below was checked against live silicon rather than taken from a header, and the
comments record how; they are the substance of this module. No logic, no
imports from the rest of the package.
"""

PM_TABLE = "/sys/kernel/ryzen_smu_drv/pm_table"
PM_VERSION = "/sys/kernel/ryzen_smu_drv/pm_table_version"

# pm_table indices are FLOAT INDEX (byte offset / 4) for version 0x004C0009
# (Phoenix / Hawk Point). The header scalars match RyzenAdj lib/api.c; the
# clock and per-core blocks are the empirical map from ryzen_smu's
# userspace/monitor_cpu.c, which located the Cezanne core-telemetry block at a
# constant +313 shift. Every index below was re-checked against live hardware:
# per-core C0+C1+C6 sums to 100%, mclk 800 / fclk 1600 matches LPDDR5-6400, and
# the limit fields agree with `ryzenadj -i`.
#
# Other table versions place these elsewhere, so we decode nothing but this one
# rather than print plausible garbage.
PM_VER_SUPPORTED = 0x004C0009
PM_HALO_VER_SUPPORTED = 0x0064020C

PM_SCALAR = {
    # key                index  scale
    "stapm":            (1,     1.0),
    "stapm_lim":        (0,     1.0),
    "ppt_fast":         (3,     1.0),
    "ppt_fast_lim":     (2,     1.0),
    "ppt_slow":         (5,     1.0),
    "ppt_slow_lim":     (4,     1.0),
    "ppt_apu":          (7,     1.0),
    "ppt_apu_lim":      (6,     1.0),
    "tdc":              (9,     1.0),
    "tdc_lim":          (8,     1.0),
    "tdc_soc":          (11,    1.0),
    "tdc_soc_lim":      (10,    1.0),
    "edc":              (13,    1.0),
    "edc_lim":          (12,    1.0),
    "edc_soc":          (15,    1.0),
    "edc_soc_lim":      (14,    1.0),
    "tctl":             (17,    1.0),
    "tctl_lim":         (16,    1.0),
    "thm_gfx":          (19,    1.0),
    "thm_gfx_lim":      (18,    1.0),
    "thm_soc":          (21,    1.0),
    "thm_soc_lim":      (20,    1.0),
    "stt":              (23,    1.0),
    "stt_lim":          (22,    1.0),
    "fit":              (27,    1.0),
    "fit_lim":          (26,    1.0),
    "vid":              (29,    1.0),
    "vid_lim":          (28,    1.0),
    # The instantaneous GFX clock; index 57 is its ceiling and reads a
    # constant 2700, matching the top pp_dpm_sclk level.
    #
    # This was briefly mislabelled here as a "permitted" clock, on the strength
    # of one reading of 2.67 GHz taken while amdgpu's freq1_input and
    # pp_dpm_sclk both said 800. Watching it properly, index 56 tracks GPU
    # activity and falls to exactly 800 when the GPU goes quiet -- it is the
    # real clock, sampled instantaneously, and the disagreement is because
    # freq1_input and pp_dpm_sclk report the coarse DPM *level*. Neither is
    # more authoritative; they answer different questions, so both are plotted.
    "gfx_clk":          (56,    1000.0),   # GHz -> MHz
    "gfx_clk_max":      (57,    1000.0),
    "fclk":             (89,    1.0),
    "uclk":             (93,    1.0),
    "mclk":             (97,    1.0),
    "vddcr_soc":        (101,   1.0),
    # Validated against known traffic rather than trusted. Driving reads with
    # 1/2/4/8 processes each scanning a 128 MiB array (>> the 16 MiB L3) over a
    # 32-41 GB/s range gives correlation +0.997 against index 194, and index
    # 195 stays at its 0.17 idle baseline throughout -- so these are two
    # genuinely separate counters, not one signal split in two. A copy
    # workload then moves both together, as it should.
    #
    # Absolute scale lands at 0.94-0.99 of the known rate read as GiB/s against
    # 0.88-0.92 read as GB/s, consistently at every load level, so the counters
    # are binary units and the axis says GiB/s. The values are passed through
    # unscaled -- the reading was always GiB/s; only the label was wrong.
    "dram_rd":          (194,   1.0),
    "dram_wr":          (195,   1.0),
    "cldo_vddp":        (477,   1.0),
}

# Per-core arrays, 8 consecutive floats each, indexed by physical core.
PM_CORE = {
    "core_power":   (513,  1.0),
    "core_volt":    (521,  1.0),
    "core_temp":    (529,  1.0),
    "core_freq":    (553,  1000.0),   # GHz -> MHz, actual P-state (shows boost)
    "core_freqeff": (561,  1000.0),   # GHz -> MHz, gating-averaged
    "core_c0":      (569,  1.0),
    "core_cc6":     (585,  1.0),
}

# Strix Halo pm_table 0x0064020C, measured on a Ryzen AI MAX+ 395.
#
# This is deliberately narrower than RyzenAdj's candidate map. Eight captures
# (idle; 1, 8 and 16 CPU cores; memory; GPU; mixed CPU/GPU) at 4 Hz supplied
# independent references from gpu_metrics_v3_0, cpufreq, k10temp and Linux
# cpuidle counters:
#
# * package values 3/5 correlate +0.972/+0.938 with gpu_metrics socket power;
# * loading CPUs 0-7 then 8-15 separates cluster temperatures 19/21. 23/25
#   agree with amdgpu GFX/SoC temperature, each after its 100 C ceiling;
# * core power at 740 correlates +0.956 with gpu_metrics (per-core
#   +0.891..+0.978); clock at 788 correlates +0.830 after GHz -> MHz;
# * a separate prior-session workload series identified 804 as the sampled /
#   effective-clock array: it falls near zero for sleeping cores while 788
#   continues to report their requested/current P-state.  The live full-size
#   table contains all sixteen entries and reports them in GHz;
# * C0 at 820 correlates +0.975 with gpu_metrics. 820+836+852 sums to 100.00%
#   (99.9999..100.934 observed); 836 follows Linux's shallow C2 idle counter
#   (+0.882) and 852 its deep C3 counter (+0.744), establishing C1/core-C6;
# * voltage at 756 is 0.666..1.309 V, rises only on selectively loaded cores,
#   and power / voltage predicts the separate current block at 932 with
#   correlation +0.959 and median scale 0.956.
#
# Unlisted fields were not earned. The apparent current limits and late fabric
# blocks remain unnamed despite plausible accessors elsewhere.
PM_HALO_SCALAR = {
    "stapm":            (1,     1.0),
    "stapm_lim":        (0,     1.0),
    "ppt_fast":         (3,     1.0),
    "ppt_fast_lim":     (2,     1.0),
    "ppt_slow":         (5,     1.0),
    "ppt_slow_lim":     (4,     1.0),
    "thm_core0":        (19,    1.0),
    "thm_core0_lim":    (18,    1.0),
    "thm_core1":        (21,    1.0),
    "thm_core1_lim":    (20,    1.0),
    "thm_gfx":          (23,    1.0),
    "thm_gfx_lim":      (22,    1.0),
    "thm_soc":          (25,    1.0),
    "thm_soc_lim":      (24,    1.0),
}

PM_HALO_CORE = {
    "core_power":   (740,  1.0),
    "core_volt":    (756,  1.0),
    "core_temp":    (772,  1.0),
    "core_freq":    (788,  1000.0),
    "core_freqeff": (804,  1000.0),
    "core_c0":      (820,  1.0),
    "core_c1":      (836,  1.0),
    "core_cc6":     (852,  1.0),
}

PM_PROFILES = {
    PM_VER_SUPPORTED: (PM_SCALAR, PM_CORE, 8),
    PM_HALO_VER_SUPPORTED: (PM_HALO_SCALAR, PM_HALO_CORE, 16),
}
# The rendering/storage ceiling. gpu_metrics_v3_0, used by Strix Point and
# Strix Halo, publishes sixteen physical cores. Older backends simply omit the
# rows they do not own; a future topology-aware catalogue can hide those empty
# rows rather than making the hardware decoder lie about the ABI's width.
N_CORES = 16
PHOENIX_CORES = 8

# The amdgpu device is discovered, not named. It was hardcoded to card1 for as
# long as this only ran on one machine, which is true there and false almost
# everywhere else -- enumeration order depends on what else claims a DRM node,
# so a second GPU, a different kernel or a different laptop moves it. A wrong
# guess is silent: empty GPU panes and no cap reasons, with nothing to say why.
DRM_DEVICES = "/sys/class/drm/card[0-9]*/device"
AMD_VENDOR = "0x1002"

# The SMU's own answer to "why am I being held back", which beats inferring it
# from limits and values. amdgpu exports it in the gpu_metrics blob; this is
# the same source amdgpu_top decodes.
#
# Bit meanings are ASIC-dependent and these are Phoenix's, taken from the
# kernel that drives this part: smu13_driver_if_v13_0_4.h, reached via
# amdgpu_smu.c IP_VERSION(13, 0, 4) / (13, 0, 11) -> smu_v13_0_4_set_ppt_funcs,
# whose get_gpu_metrics does `gpu_metrics->throttle_status =
# metrics.ThrottlerStatus`. Do not reuse this table for another ASIC.
#
# Offset 108 and the (2, 1) version guard below are specific to
# gpu_metrics_v2_1, the 120-byte layout this machine reports. Later revisions
# move the field and add an ASIC-independent bitmask, so we decode nothing but
# the layout that was actually verified.
GM_VERSION = (2, 1)
GM_SIZE = 120
GM_THROTTLE_OFF = 108

# Power breakdown, from the same blob. Offsets are gpu_metrics_v2_1 as declared
# in the kernel's kgd_pp_interface.h, not inferred:
#   40 average_socket_power   42 average_cpu_power
#   44 average_soc_power      46 average_gfx_power
#   48 average_core_power[8]
# All are milliwatts.
#
# Two of those are not usable on this part, checked rather than assumed:
#   average_cpu_power reads a constant 0xFFFF -- unpopulated.
#   average_gfx_power is NOT GPU power. It correlates +0.093 with gpu_busy and
#   +0.943 with the sum of average_core_power, and its mean (10.90 W) sits
#   within 6% of that sum (10.29 W). The SMU fills the gfx slot with CPU power
#   here. It is recorded as pwr_gfxslot and deliberately not plotted as "GPU".
#
# What is trustworthy: socket_power, soc_power and the per-core array.
# Cross-checked three ways at one instant -- RAPL package-0 (which is what
# turbostat reads) 25.32 W, gpu_metrics socket_power 24.89 W, pm_table
# ppt_slow 25.90 W: agreement within 4% between three independent paths. RAPL's
# `core` domain reads 2.40 W, which is AMD's per-core MSR rather than a total;
# x8 gives 19.2 W against pm_table's 19.50 W summed over the eight cores.
#
# RAPL is not sampled here: /sys/class/powercap/*/energy_uj is root-only, and
# nothing else in this program needs privileges.
GM_PWR_OFF = 40
GM_CORE_PWR_OFF = 48

# gpu_metrics_v3_0 is the mainline kernel ABI used by Strix Point / Strix Halo.
# Unlike the undocumented pm_table it is declared by the driver, including the
# units, and this exact 264-byte layout was observed on the Ryzen AI MAX+ 395
# used for the port. Offsets follow struct gpu_metrics_v3_0 in
# drivers/gpu/drm/amd/include/kgd_pp_interface.h; natural alignment matters at
# system_clock_counter and average_apu_power.
GM3_VERSION = (3, 0)
GM3_SIZE = 264
GM3_ACTIVITY_OFF = 42
GM3_IPU_ACTIVITY_OFF = 46
GM3_DRAM_BW_OFF = 94
GM3_IPU_BW_OFF = 98
GM3_SYSTEM_CLOCK_OFF = 104
GM3_SOCKET_PWR_OFF = 112
GM3_IPU_PWR_OFF = 116
GM3_APU_PWR_OFF = 120
GM3_GFX_PWR_OFF = 124
GM3_DGPU_PWR_OFF = 128
GM3_ALL_CORE_PWR_OFF = 132
GM3_CORE_PWR_OFF = 136
GM3_SYS_PWR_OFF = 168
GM3_STAPM_LIMIT_OFF = 170
GM3_STAPM_CURRENT_LIMIT_OFF = 172
GM3_CLOCKS_OFF = 174
GM3_CORE_CLOCK_OFF = 190
GM3_CORE_MAXFREQ_OFF = 222
GM3_GFX_MAXFREQ_OFF = 224
GM3_RESIDENCY_OFF = 228

THROTTLE_BITS = [
    (0,  "SPL",         "power"),
    (1,  "FPPT",        "power"),
    (2,  "SPPT",        "power"),
    (3,  "SPPT APU",    "power"),
    (4,  "THM core",    "thermal"),
    (5,  "THM GFX",     "thermal"),
    (6,  "THM SoC",     "thermal"),
    (7,  "TDC VDD",     "current"),
    (8,  "TDC SoC",     "current"),
    (9,  "PROCHOT CPU", "prochot"),
    (10, "PROCHOT GFX", "prochot"),
    (11, "EDC CPU",     "current"),
    (12, "EDC GFX",     "current"),
]
TPACPI = "/sys/devices/platform/thinkpad_acpi"
PLATFORM_PROFILE = "/sys/firmware/acpi/platform_profile"

# Generic kernel ABI, not part-specific -- no version to gate on, unlike
# pm_table and gpu_metrics above. Useful on any machine, including one with no
# AMD silicon at all: a container has no ryzen_smu and no amdgpu, but it still
# has memory pressure, which is what makes it possible to develop the rest of
# this program somewhere other than the hardware it targets.
PROC_MEMINFO = "/proc/meminfo"
PROC_STAT = "/proc/stat"

# Plotted as a step trace so a profile switch lines up against the power drop
# it caused. Ordered by how much power each profile allows.
PROFILES = {"low-power": 0.0, "quiet": 0.0, "cool": 0.0,
            "balanced": 1.0, "balanced-performance": 1.5,
            "performance": 2.0}
