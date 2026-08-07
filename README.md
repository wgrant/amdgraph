# amdgraph

Live strip charts for AMD Ryzen laptops — the SMU's own view of itself, not the
handful of sensors a generic monitor finds.

![amdgraph running on a Ryzen 7 PRO 7840U: a cap-reason strip showing SPL, FPPT
and SPPT asserted, package power against its limits, SMU and system
temperatures, CPU clock, and a per-core clock heat strip, all on one time
axis](docs/screenshot.png)

Nine minutes on a ThinkPad X13. Around 6:00 the platform pulls the budget down
and everything follows: package power from 28 W to 10, the per-core strip going
dark, both temperatures falling away. The dashed ceilings step down with it —
they are plotted as the time series they are, not drawn at whatever the limit
happens to read now, because on this machine they move constantly and a flat
line would silently rewrite history.

STAPM and PPT budgets against their moving limits, the STT skin-temperature
model that actually governs sustained clocks, VRM current (TDC/EDC), per-core
power/clock/residency, and the SMU's own answer to *why* it is holding the part
back. Everything shares one time axis, so hovering anywhere reads out that
instant across every pane at once.

Sessions record to CSV and reload, either alone or as a ghost behind the live
trace — so "did that `ryzenadj` change actually help" has an answer rather than
an impression.

> **Verified on Ryzen 7040-series (Phoenix) and Strix Halo.** Both parts have
> independently validated, version-gated `pm_table` maps; Strix Halo also uses
> the mainline kernel's self-described `gpu_metrics_v3_0` fields. Sensor layouts are
> part-specific and undocumented, so amdgraph decodes just the one it has
> checked against live silicon, and leaves the affected panes empty on anything
> else rather than showing numbers read from the wrong offsets. Adding a part is
> a documented procedure — see [`docs/HARDWARE.md`](docs/HARDWARE.md).

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

Python 3.9+, `numpy`, `PyQt6`. Either get them from the distribution:

```
apt install python3-numpy python3-pyqt6
./amdgraph
```

or let [uv](https://docs.astral.sh/uv/) manage them:

```
uv run amdgraph
```

Both work, and neither is the primary. The distribution path matters because
one of the machines this targets is a Steam Deck, where the useful thing is to
clone and run rather than to provision an environment; `./amdgraph` is a
launcher that puts `src/` on `sys.path` and needs no install step, and a symlink
to it from anywhere on your `PATH` works too.

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

Missing modules degrade rather than crash — the affected panes read "no data".
For the two SMU sources the status bar also names what is absent and why; a
missing `thinkpad_acpi` or `nvme` just leaves those panes empty, with nothing
said about it.

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

`tools/amdgraph-probe` reports the version decoded, alongside `drv_version` and
everything else. It records `codename` raw: the index is into `ryzen_smu`'s own
enum, which differs between forks, and a stale table would turn an unknown part
into a confidently mislabelled one.

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
`0x004C0009`, `gpu_metrics_v2_1`; and **Ryzen AI MAX+ 395 (Strix Halo)**:
`pm_table 0x0064020C`, `gpu_metrics_v3_0` (264 B). Strix Halo provides moving
STAPM/PPT budgets, per-core power/voltage/temperature/clock/C0/C1/C6, thermal
ceilings, package/APU/GPU/IPU power, bandwidth and cap-reason activity.

Other parts place these fields elsewhere, so amdgraph checks both layout
versions at startup and **refuses to decode one it has not verified** rather
than print plausible garbage. A wrong field map is worse than a blank pane: it
looks authoritative.

Every index in the Phoenix map was checked against something independent — DRAM
bandwidth correlated +0.997 against known traffic, per-core C0+C1+C6 summing to
100%, mclk against the memory's rated speed, limits against `ryzenadj -i`. The
comments in `src/amdgraph/smu/*.py` record that evidence, and are the most
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
uv run pytest              # or: pytest, from a checkout with system packages
uv run mypy                # typed acquisition core, targeting Python 3.9
```

The layering check is one of the tests, and also stands alone as
`tools/check-layers.py` if you want it in a pre-commit hook.

Nothing in the suite touches real hardware. Device discovery, the pm_table
decode and the `gpu_metrics` version guards all run against synthetic trees and
blobs under `tmp_path`, so the tests are meaningful on a machine with no AMD
part in it — which is the only way to test the paths that matter for the parts
this does not support yet. Qt tests render offscreen and skip if PyQt6 is
absent. Both invocations above are checked: `uv run pytest` against the locked
environment, and a bare checkout where `conftest.py` falls back to putting
`src/` on `sys.path`.

They are weighted toward the guards rather than the arithmetic. The one failure
this program is built to avoid is printing a plausible number off a layout
nobody verified, so the tests asserting that it *refuses* — v2_2, v2_4, v3_0,
v1_3, right version wrong size, truncated, absent — carry more weight than any
that check a decode.

### The source protocol

`Main` takes a `source=` and uses exactly six methods of it — `sample()`,
`notes()`, `meta()`, `set_cap_rate()`, `reset()`, `close()`. `Sampler` is the
one that reads this machine; the tests pass a fake, which is why the window has
coverage at all. Anything specific to how a *particular* part is read belongs
behind those six methods, so a Renoir or Strix Halo backend is a new class
rather than an edit to the window.

Coverage, for orientation rather than as a target:

| layer | |
|---|---|
| `sysfs` `fields` `palette` `panes` `axis` | 100% |
| `render` `store` `view` `rasters` `window` | 92–98% |
| `session` `chart` `timepane` | 91–93% |
| `sampler` | 44% — the part that reads real sysfs |
| `__main__` | 0% by coverage; exercised as a subprocess in `test_cli.py` |

`sampler` is the honest floor: everything below it that can be faked has been,
and what remains is the code that opens `/sys` directly. Making *that* testable
means giving the readers an injectable root, which is the same change a second
platform needs.

There are deliberately no golden pixel hashes. Pane rendering draws text, so a
hash fingerprints the font stack as much as the code, and a golden file that
breaks on a Qt upgrade gets deleted rather than investigated. What is asserted
is what is portable: that every pane paints without raising, that the geometry
contract holds, and that gestures produce exact view state — which is pure
arithmetic. For an A/B check across a refactor, hash the renders in a scratch
script against the previous commit; that is a refactoring aid, not a regression
test.

Two rules worth keeping. Panes are declared in `panes.py`, which contains no
drawing code — if a decision about *what* to show has landed anywhere else, it
is in the wrong place. And any claim about a field belongs in a comment next to
it, with the measurement that supports it.

### Further reading

| | |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | the house rules, in short — start here |
| [`docs/DESIGN.md`](docs/DESIGN.md) | architecture, the layer contract, the source protocol |
| [`docs/HARDWARE.md`](docs/HARDWARE.md) | what varies between AMD parts, and how to add one |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | what was tried and rejected, with the measurements |

`docs/HARDWARE.md` tags every claim as **measured**, **source** or
**unverified**. That distinction is the discipline the project runs on: a field
map transcribed from someone else's table looks identical in the source to one
that was earned, and is worth much less.
