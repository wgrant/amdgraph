# amdgraph

Live strip charts for AMD Ryzen laptops — the SMU's own view of itself, not the
handful of sensors a generic monitor finds.

STAPM and PPT budgets against their moving limits, the STT skin-temperature
model that actually governs sustained clocks, VRM current (TDC/EDC), per-core
power/clock/residency, and the SMU's own answer to *why* it is holding the part
back. Everything shares one time axis, so hovering anywhere reads out that
instant across every pane at once.

Sessions record to CSV and reload, either alone or as a ghost behind the live
trace — so "did that `ryzenadj` change actually help" has an answer rather than
an impression.

```
./amdgraph [-i SECONDS] [--open FILE]
```

| key | |
|---|---|
| `space` | freeze the view (sampling continues) |
| `r` | discard history |
| `m` | drop a labelled marker |
| `Esc` | unzoom / follow again |
| `[` `]` | shrink / grow the window |
| `q` | quit |

Drag on a chart to zoom a range, wheel to zoom, middle-drag to pan. Click a
legend entry to hide that series.

## Requirements

Python 3, `numpy`, `PyQt6`. On Debian/Ubuntu:

```
apt install python3-numpy python3-pyqt6
```

No install step — `./amdgraph` runs from the checkout, and a symlink to it from
anywhere on your `PATH` works too.

**It never needs root**, and that is deliberate rather than incidental: a
monitor that shells out to a privileged helper once a second becomes a top
wakeup source and perturbs the very thermal behaviour you are trying to tune.
Everything is read straight from sysfs with no subprocesses.

## Kernel modules

Only one of these is out of tree, and it is the one that matters most.

| module | in mainline | what you lose without it |
|---|---|---|
| **`ryzen_smu`** | **no** — see below | every SMU pane: STAPM/PPT, STT, TDC/EDC, per-core, SoC and GPU clocks, DRAM bandwidth |
| `amdgpu` | yes | cap reasons, the power breakdown, GPU clock and busy |
| `thinkpad_acpi` | yes | EC skin/CPU temperature, fans, palm sensor, lap mode |
| `nvme` | yes | drive temperature |

Missing modules degrade rather than crash: the affected panes read "no data",
and the status bar says which source is absent and why.

### ryzen_smu

The pm_table is not exposed by any mainline driver. `ryzen_smu` is an
out-of-tree DKMS module that maps it into sysfs:

```
git clone https://github.com/kylon/ryzen_smu_amkillam
cd ryzen_smu_amkillam && sudo make dkms-install
sudo modprobe ryzen_smu
echo ryzen_smu | sudo tee /etc/modules-load.d/ryzen_smu.conf   # load at boot
```

That is a fork of Leonardo Gates' original driver, and worth preferring on
recent silicon: its codename table covers Granite Ridge, Strix Point and Strix
Halo. Check `smu.h` against your part before assuming either one knows it.

Check it is up. Note that `pm_table_version` is a binary `u32`, not text, so
`cat` prints four raw bytes — and `codename` is a numeric enum index rather than
a name:

```
$ cat /sys/kernel/ryzen_smu_drv/drv_version
0.1.7
$ od -An -tx4 /sys/kernel/ryzen_smu_drv/pm_table_version
 004c0009
```

`tools/amdgraph-probe` prints both, decoded, along with everything else.

The driver publishes `pm_table` **world-readable** (`-r--r--r--`), which is what
lets amdgraph run unprivileged. Nothing here writes to `smu_args`, `smn`, or any
of the module's command interfaces.

### amdgpu

In mainline and normally already loaded. amdgraph finds the card by PCI vendor
rather than by index, preferring one that publishes `gpu_metrics`, so a machine
with both an APU and a discrete GPU attaches to the right one.

`gpu_metrics` is also world-readable. It is polled on a background thread at up
to 50 Hz (20 Hz by default, ~1.2% of a core) because the throttler bits are
instantaneous flags on a controller that duty-cycles at around 20 Hz — sampled
once a second they report a coin flip rather than a duty cycle. Drop the rate to
1 Hz in the toolbar to disable the background thread entirely.

### Not used, on purpose

RAPL (`/sys/class/powercap/*/energy_uj`) is root-only on most distributions
since the platypus disclosure, and reading it would cost the whole program its
"no privileges" property for one more power figure. `k10temp` likewise adds
nothing the SMU does not already report more precisely.

## Hardware support

Decoded and verified on **Ryzen 7 PRO 7840U (Phoenix)**: pm_table
`0x004C0009`, `gpu_metrics_v2_1`.

Other parts place these fields elsewhere, so amdgraph checks both layout
versions at startup and **refuses to decode one it has not verified** rather
than print plausible garbage. A wrong field map is worse than a blank pane: it
looks authoritative.

Every index in the Phoenix map was checked against something independent — DRAM
bandwidth correlated +0.997 against known traffic, per-core C0+C1+C6 summing to
100%, mclk against the memory's rated speed, limits against `ryzenadj -i`. The
comments in `src/amdgraph/fields.py` record that evidence, and are the most
valuable thing in the tree.

To add a part, start by capturing what a new map has to be derived from:

```
tools/amdgraph-probe --label idle
tools/amdgraph-probe --label load-8t -n 120     # while something runs
```

Two captures, because fields only separate when something is moving. It writes
one JSON holding the pm_table version and size, the `gpu_metrics` header, core
topology (including L3 groups, the only reliable view of CCX boundaries), the
hwmon inventory, platform drivers, perf PMUs and RAPL readability — plus raw
periodic dumps of both binary blobs so the correlation work can happen later and
off the machine. It is stdlib-only and read-only: no MSRs, no limit writes, no
module loads.

## Recordings

`~/.local/share/amdgraph/YYYYmmdd-HHMMSS.csv`, one row per sample, every key the
sampler can produce rather than only the plotted ones. Plain CSV with `#`
comment headers, so `awk` and pandas can both read it and markers survive as
`# marker <t> <label>` lines.

## Development

`./amdgraph` is a launcher; the code is the package under `src/amdgraph/`. Start
at its `__init__.py` — the docstring maps the layers, from the hardware field
map up through sampling, storage, drawing primitives and widgets to the window.

Each module states what it is allowed to import, and that is enforced:

```
python3 tools/check-layers.py
```

Two rules worth keeping. Panes are declared in `panes.py`, which contains no
drawing code — if a decision about *what* to show has landed anywhere else, it
is in the wrong place. And any claim about a field belongs in a comment next to
it, with the measurement that supports it.
