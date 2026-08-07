# Hardware

What varies between AMD parts, what is actually known versus assumed, and how to
add support for one.

Every claim below is tagged:

- **measured** — checked against live silicon on the machine named
- **source** — read out of the Linux tree or RyzenAdj, not observed
- **unverified** — plausible, believed, untested. Treat as a hypothesis.

The distinction is the point. A field map transcribed from someone else's table
looks identical in the source to one that was earned, and is worth much less.

## The two blobs

| | path | gate |
|---|---|---|
| `pm_table` | `/sys/kernel/ryzen_smu_drv/pm_table` | version `u32` must equal `PM_VER_SUPPORTED` |
| `gpu_metrics` | `<amdgpu device>/gpu_metrics` | format/content revision **and** declared size |

Both are world-readable, which is why the program needs no privileges. Neither
is self-describing beyond its version, so a version we have not verified means
empty panes plus a note naming what was found — never a guess.

`pm_table` needs the out-of-tree `ryzen_smu` module. `gpu_metrics` comes from
mainline `amdgpu`.

## Currently supported

**Ryzen 7 PRO 7840U (Phoenix), ThinkPad X13 Gen 4.** pm_table `0x004C0009`,
`gpu_metrics_v2_1` (120 B), 8 cores, one L3 group.

The field map in `src/amdgraph/fields.py` is **measured**. What that meant:

- DRAM read/write (194/195): driven with 1/2/4/8 processes each scanning a
  128 MiB array over a 32–41 GB/s range. Correlation +0.997 against index 194
  while 195 held its 0.17 idle baseline, proving two independent counters rather
  than one signal shown twice. Absolute scale fits GiB/s at 0.94–0.99 of known
  rate versus 0.88–0.92 as GB/s, consistently at every load level — which is how
  the axis label got corrected.
- Per-core block: C0 + C1 + C6 sums to 100%.
- Memory clocks: mclk 800 / fclk 1600 against rated LPDDR5-6400.
- Limits: agree with `ryzenadj -i`.
- Socket power: three independent paths within 4% at one instant — RAPL
  package-0 25.32 W, gpu_metrics 24.89 W, pm_table ppt_slow 25.90 W.
- Throttler bits: under all-core load SPL asserted in 92% of samples with STAPM
  pinned at its limit, FPPT 100%, nothing thermal at Tctl 87/100.

Fields deliberately *not* plotted despite having plausible labels, each with its
reasoning in `fields.py` or `panes.py`: `ppt_apu` (constant zero), indices 26/27
("FIT", pairing never confirmed), index 28 ("VID limit", the value routinely
exceeds it), `average_gfx_power` (correlates +0.943 with the CPU core sum, not
with GPU busy), `pwr_rest` (differencing noise an order of magnitude larger than
the quantity).

## What varies, and how much

Four independent axes. One `PM_VER_SUPPORTED` constant does not stretch across
them.

### 1. pm_table layout

**source**, from RyzenAdj `lib/api.c`:

| part | table version | note |
|---|---|---|
| Renoir / Lucienne | `0x0037xxxx` | |
| Phoenix / Hawk Point | `0x004C0006`–`0x004C0009` | ours is `0009` |
| Strix Point | `0x005D0008`–`0x005D000B` | RyzenAdj: *"looks correct from dumping table"* |
| Strix Halo | `0x0064020C` | RyzenAdj: *"looks correct… defaults to 70W"*, and *"untested!"* on one accessor |
| Krackan Point | `0x00650005` | |
| Granite Ridge | desktop family (`0x38xxxx` / `0x54xxxx` in ryzen_smu) | different shape entirely |

Van Gogh (Steam Deck **Aerith** and **Sephiroth**) has `FAM_VANGOGH` in
RyzenAdj's enum but is **absent from `request_table_ver_and_size`** — so there
may be no pm_table path at all on a Deck. **unverified**; the probe settles it
in one run.

RyzenAdj's own annotations are the reason for the tagging discipline in this
file. Do not copy those tables in and call the result supported.

### 2. gpu_metrics version — this is the big one

**source**, from `drivers/gpu/drm/amd/pm/swsmu/`:

| ppt file | part | emits | throttler map |
|---|---|---|---|
| `smu12/renoir_ppt.c` | Renoir | `v2_2` | yes |
| `smu11/vangogh_ppt.c` | Van Gogh | `v2_2` / `v2_3` / `v2_4` | yes |
| `smu13/smu_v13_0_4_ppt.c` | **Phoenix** | `v2_1` | **no** |
| `smu14/smu_v14_0_0_ppt.c` | Strix Point, Strix Halo | `v3_0` | n/a |

Three consequences:

**Phoenix is the worst case, and we built on it.** `v2_1` is the only layout
with neither `indep_throttle_status` nor residency counters. From `v2_2` the
kernel fills an **ASIC-independent** 64-bit bitmask whose meanings are fixed in
`swsmu/inc/amdgpu_smu.h` (`SMU_THROTTLER_*_BIT`) — so the hand-maintained
`THROTTLE_BITS` table in `fields.py` is needed *only* for Phoenix.

That is a driver gap, not a hardware limit. Ten ppt files define a
`*_throttler_map[]`; `smu_v13_0_4_ppt.c` does not. The per-bit constants already
exist in `smu13_driver_if_v13_0_4.h`, and we have empirically validated their
meanings. **A ~15-line upstream patch would fix Phoenix cap reasons in every
tool that reads `indep_throttle_status`**, not just this one. Worth sending.

**Van Gogh picks its version at runtime from SMU firmware**
(`vangogh_common_get_gpu_metrics`, `smu11/vangogh_ppt.c`):

```c
smu_program = (smu->smc_fw_version >> 24) & 0xff;
if (smu_program == 6) { fw >= 0x3F0800 ? v2_4 : v2_3; }
else if (smc_fw_version >= 0x043F3E00) { ... v2_3 ... }
else { ... v2_2 ... }
```

`smu_program == 6` is a separate Valve firmware line. So **Aerith and Sephiroth
may report different versions from each other, and the same Deck may change
across a SteamOS update.** The decoder must be chosen from the header at
startup, never baked in at build time. The existing guard already fails safe.

**`v3_0` replaces the bitmask with residency counters.** Strix Point and Strix
Halo export `throttle_residency_{prochot,spl,fppt,sppt,thm_core,thm_gfx,thm_soc}`
— already-accumulated. The 20 Hz background poller exists solely to reconstruct
duty cycles the hardware counts there; on `v3_0` you difference the counters per
tick instead. `v3_0` also carries `average_all_core_power` (the aggregate CPU
power field that does not exist in Phoenix's pm_table),
`stapm_power_limit` / `current_stapm_power_limit`, separate
`average_apu_power` / `average_dgpu_power` / `average_ipu_power`, and 16-core
arrays.

So cap reasons need **three** source strategies, and the oldest part drives the
most code.

### 3. Core count and topology

`N_CORES = 8` is hardcoded. Van Gogh has 4, Granite Ridge up to 16 across two
CCDs, Strix Halo 16 (`v3_0` arrays are `[16]`).

Worse, the per-core panes assume one flat set. The only reliable view of CCX
boundaries from userspace is L3 sharing —
`/sys/devices/system/cpu/cpuN/cache/index3/shared_cpu_list`. Phoenix
(**measured**) reports one group covering all 16 threads; a two-CCD part will
report two. The probe captures this as `l3_groups`.

### 4. Platform / EC

`thinkpad_acpi` supplies EC skin and CPU temperature, fans, palm sensor and
`dytc_lapmode`. None of that exists elsewhere. Framework uses `cros_ec`, the
Steam Deck a jupiter/`steamdeck` driver, desktops `nct6775`-class chips.

**The Framework 13 Phoenix is the ideal first port**: same silicon, different
platform, so it isolates this axis from the other three. Do it before any new
SoC.

## Adding a part

1. **Probe it.** Two captures, because fields only separate when something moves:

   ```
   tools/amdgraph-probe --label idle
   tools/amdgraph-probe --label load-8t -n 120     # while something runs
   ```

   Stdlib-only and read-only. Records the pm_table version and size, the
   `gpu_metrics` header, core topology including L3 groups, hwmon inventory,
   platform drivers, perf PMUs, RAPL readability, and raw base64 dumps of both
   blobs over time — deliberately raw, since the whole question is what the
   fields mean.

2. **Derive, do not transcribe.** Correlate the dumps against something
   independent: known DRAM traffic, `cpufreq` clocks, `ryzenadj -i` limits,
   residency summing to 100%, RAPL. RyzenAdj's table is a hint about *where* to
   look, not evidence.

3. **Mark confidence per field.** A map should carry which fields are earned and
   which are guessed, and only earned ones should plot by default. This does not
   exist yet and is the right shape for the `fields/` package.

4. **Write a backend, not an edit.** A module in `src/amdgraph/backends/`
   implementing `Backend` (`backends/base.py`) plus a module-level `probe(fs)`
   that decides whether it applies -- `zen_smu.py` and `amdgpu.py` are the
   templates, one version-gated blob each. Add it to `Sampler`'s `_PROBES`
   tuple. Nothing in layers 3–6 should need to change, and nothing in another
   backend module either -- that isolation is the whole point of the split.

5. **Make the pane catalogue conditional.** `PANES` is currently unconditional;
   it needs to drop series whose key never appears and panes left empty.

### Porting roadmap

Parts available for validation, in the order they are worth doing — Framework
first because it isolates the platform axis, then the newer silicon where
`gpu_metrics` does more of the work for us:

Phoenix (Framework 13) · Renoir · Strix Halo · Aerith · Sephiroth ·
Granite Ridge.

**Granite Ridge is arguably a different tool.** No STT, no skin governor, no
unified APU power budget — the panes that make this useful have no analogue. It
would become a per-CCD boost/FIT observer sharing only the chart machinery: a
second pane catalogue, not a profile.

## A future source class: data fabric counters

Strix Halo exposes DF traffic counters per port — to each CCX, the GPU, and
other peripherals. These are **monotonic counters** needing setup, held state
and differencing, not stateless sysfs polls, so they break the shape layer 2
currently assumes. On this Phoenix (**measured**) `amd_df` is not even
registered — only `amd_iommu_0`, `power`, `power_core`, `ibs_*` — and
`perf_event_paranoid` is 4, so unprivileged perf is off entirely. Reading them
means either `perf_event_open` with `CAP_PERFMON` or programming the DF PMCs
over SMN as root.

The abstraction pays for itself twice: `v3_0`'s `throttle_residency_*` needs
exactly the same counter-differencing treatment for the *existing* cap-reason
pane. Whatever is built should degrade to absent without privileges, as
everything else does.

Rendering is nearly free — per-port traffic is "N rows, one metric", which is
`CorePane`'s shape. Though the question DF counters actually answer on Strix
Halo (GPU versus CCX0 versus CCX1 contending for the same controllers) wants a
stacked area, which does not exist yet.
