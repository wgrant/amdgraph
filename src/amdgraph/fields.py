"""Layer 0 -- the hardware map.

Which byte of which sysfs blob holds which quantity, on this part. Every entry
below was checked against live silicon rather than taken from a header, and the
comments record how; they are the substance of this module. No logic, no
imports from the rest of the package.
"""

# Largest per-core ABI currently decoded. This is not the detected core count
# and not a recording-schema width: topology and backend descriptors own those
# separate concepts.
MAX_CORE_SLOTS = 16

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
# gpu_metrics_v2_1, the 120-byte layout Phoenix reports. Renoir reports v2_2,
# which keeps every field above and appends an ASIC-independent bitmask at
# 120; both are decoded here, each against offsets that were verified live.
GM_VERSION = (2, 1)
GM_SIZE = 120
GM_THROTTLE_OFF = 108

# gpu_metrics_v2_2 is what Renoir (smu12) and Van Gogh actually emit: the v2_1
# layout plus indep_throttle_status, a u64 the kernel builds from the
# ASIC-specific throttle_status via renoir_throttler_map. The version is a
# per-SMU-family driver choice, not an ordering by SoC age -- this Ryzen 7 PRO
# 4750U (2020) reports (2, 2) while Phoenix (2023) reports (2, 1) -- so a
# higher content_rev must not be read as "newer hardware".
#
# Struct gpu_metrics_v2_2 in kgd_pp_interface.h puts the field at 120 after
# v2_1's padding[3], giving 128 bytes; the live blob's header confirms it
# (128/2/2). The shared offsets were verified against hwmon on this machine:
# temperature_gfx at 4 read 5525 (55.25 degC vs temp1_input 55000),
# average_socket_power at 40 read 10 vs power1_input 10 W, and throttle_status
# at 108 read 0x2 in the same blob whose indep_throttle_status at 120 read
# 0x20 (bit 5, FPPT) -- the ASIC bit and its independent twin asserting
# together.
GM2_2_VERSION = (2, 2)
GM2_2_SIZE = 128
GM_INDEP_THROTTLE_OFF = 120

# average_socket_power is in W on v2_2, not the mW the struct comment claims:
# renoir_get_gpu_metrics copies metrics.CurrentSocketPower into the field
# straight, while the read_sensor path is the one that multiplies by 1000, and
# only when the firmware is new enough (MP1 12.0.0 fw >= 0x373200, 12.0.1 fw
# >= 0x40000f). Every shipped Renoir has long passed that gate, so the decoder
# scales the socket slot by 1 on v2_2 and keeps /1000 everywhere else.
# Verified live: the field read 10 against hwmon power1_input 10 W.

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

# The same cap reasons as THROTTLE_BITS above, but as the ASIC-independent
# indep_throttle_status bits that v2_2 and later carry. Renoir's SMU does not
# publish the independent mask itself: the kernel builds it by translating
# each ASIC bit through renoir_throttler_map (smu12/renoir_ppt.c) onto the
# SMU_THROTTLER_*_BIT constants of swsmu/inc/amdgpu_smu.h:
#
#   SPL 4, FPPT 5, SPPT 6, SPPT APU 7, THM core 33, THM GFX 32, THM SoC 37,
#   TDC VDD 19, TDC SoC 17, PROCHOT CPU 46, PROCHOT GFX 47, EDC CPU 21,
#   EDC GFX 22.
#
# Row order and names match THROTTLE_BITS so the panes need no changes: each
# row here is the independent-mask bit for the same cap reason. One bit was
# confirmed live: the read whose ASIC throttle_status had FPPT (bit 1) set had
# indep_throttle_status 0x20 -- SMU_THROTTLER_FPPT_BIT, 5.
INDEP_THROTTLE_BITS = [
    (4,  "SPL",         "power"),
    (5,  "FPPT",        "power"),
    (6,  "SPPT",        "power"),
    (7,  "SPPT APU",    "power"),
    (33, "THM core",    "thermal"),
    (32, "THM GFX",     "thermal"),
    (37, "THM SoC",     "thermal"),
    (19, "TDC VDD",     "current"),
    (17, "TDC SoC",     "current"),
    (46, "PROCHOT CPU", "prochot"),
    (47, "PROCHOT GFX", "prochot"),
    (21, "EDC CPU",     "current"),
    (22, "EDC GFX",     "current"),
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
