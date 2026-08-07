# Decisions

Things that were decided, and the ones that were tried and rejected. Kept so
they are not re-litigated, and so a future reader can tell an intentional
absence from an oversight.

Newest first. Where the evidence lives in code, this points there rather than
repeating it.

---

### Panes are declarative, drawing is not

`panes.py` lists what is plotted with no drawing code; `ChartPane` renders a
`PaneSpec` and knows nothing about what a key means. Keeps "what to show"
arguable in one file and reviewable as data.

### Limits are drawn as time series, not as scenery

Every ceiling on this platform moves — `ppt_fast` 30/25/12 W across platform
profiles, thermal limits dropping 100 → 70 °C, `stapm_lim` drifting on a slow
integrator. A dashed line at the *current* limit drawn across the whole window
silently re-judged history against a ceiling that was not in force at the time.
Now each limit is plotted from its own recorded column.

### Three views of the same constraint collapsed to one

There were briefly a value-with-dashed-limit pane, a ceilings-only pane, and a
limit-minus-value pane. All three existed to *infer* what was capping the part.
Once the SMU's own throttler bits were being read, inference was unnecessary;
the other two were removed rather than kept in sync. Headroom columns are still
recorded.

### No Reliability/FIT pane

FIT is real — Failures In Time, the ageing budget the SMU spends by capping
voltage; the desktop pm_table exposes `FIT_VOLTAGE`/`FIT_PRE_VOLTAGE` beside the
limit/value pair. What was never established is that indices 26/27 are it on
*this* table. They carry the labels only by the APU pairing convention, their
ratio holds a near-constant 0.39% so the "value" never approaches its "limit",
and neighbours 24/25/30/31 read constant zero — so the convention demonstrably
does not hold across that block. Drawing them asserted a constraint that could
not be substantiated. Both still recorded. Full reasoning in `panes.py`.

Worth picking up if anyone returns to it: index 28 correlates −0.80 with
temperature, frequency and voltage while index 29 correlates +0.89/+0.93/+0.94 —
the shape of a voltage ceiling lowered by a reliability model.

### `pwr_rest` is recorded but never plotted

`socket − cores − soc` is negative in 54% of samples, ranging −14.3 to +18.6 W
about a mean of +0.15 W, because the three fields carry different SMU averaging
windows. Smoothing does not rescue it: still 44–65% negative at a 4.5 s window.
The visible gap between the socket and cores traces carries the same information
without pretending to a precision that is not there.

### CPU core power comes from pm_table, not gpu_metrics

Both exist. Measured against `socket_power` over the same window:

| source | jitter | exceeds socket | worst overshoot |
|---|---|---|---|
| gpu_metrics cores | 3.92 W | 42.7% | +14.09 W |
| **pm_table cores** | **1.43 W** | 38.0% | **+2.99 W** |

Every other pm_table index was scanned for a better aggregate; there is none,
only the per-core values and IDDMAX. **Unresolved:** cores + SoC still exceeds
socket by ~1 W on average, systematic rather than noise, unexplained. RAPL is
the obvious tiebreaker but is root-only.

### DRAM bandwidth is GiB/s, not GB/s

Fits 0.94–0.99 of known rate as GiB/s against 0.88–0.92 as GB/s, consistently at
every load level. A 7% systematic error is exactly the kind that survives for
years; the label was wrong, the readings were always right.

### Cap reasons are a duty cycle, sampled off-thread at 20 Hz

The bits are instantaneous flags on a controller that toggles ~19 times a second
(12.7% duty at idle, rarely asserted longer than 270 ms). A 1 Hz sample inspects
one 6.6 ms window in every thousand and reports a coin flip — a continuously
regulating limiter renders as unrelated-looking scatter. Costs ~1.2% of a core,
adjustable, and at 1 Hz the thread does not run.

This also revealed EDC at 67–80% duty at idle, invisible at 1 Hz — which is why
VRM current is the second pane, not the last.

### The amdgpu device is discovered, never named

`card1` was correct on exactly one machine. Discovery is by PCI vendor,
preferring a device whose `gpu_metrics` header actually *validates* — not merely
one that has the file, since discrete Radeons publish `v1_x` too, which made the
preference a coin flip on precisely the machine it was written for.

### RAPL is deliberately unread

`/sys/class/powercap/*/energy_uj` is root-only on most distributions since the
PLATYPUS disclosure. Reading it would cost the program its no-privileges
property for one more power figure that agrees with the others to 4% anyway.

### `k10temp`, and three of the four thinkpad temperatures, are unread

`temp1`, `temp3`, `temp6` and `temp7` report identical values and track exactly
— aliases of one CPU sensor. The EC publishes exactly two distinct temperatures
to Linux: CPU (`0x78`) and skin (`0x7C`). Reading the aliases would cost ~0.45 ms
of EC transactions per sample for a third copy of a line already on the chart.
This was checked while hunting the lap-mode trigger; there is no unread sensor
hiding.

### No dual-axis panes

Every series in a pane shares one unit and one y-scale. A second y-scale makes
two traces cross wherever the author chose, and means nothing.

### Rasters for the throttle strip and per-core view

Thirteen reasons and eight cores are both far past where categorical colour
stays separable. Identity comes from the row label and fixed vertical order;
colour carries family (throttle) or magnitude (cores), on a sequential ramp.
Painted as a row-per-thing `QImage` the width of the plot rather than thousands
of primitives.

### Markers are manual, because the machine cannot see you

No accelerometer, ambient sensor or lid-angle input exists on this model — the
`dytc_lapmode` bit is a firmware black box that flips without the machine being
moved. A physical intervention therefore leaves no trace in the data unless you
say so. Markers are that trace, stored as `# marker <t> <label>` comment lines
rather than a mostly-empty column.

---

## Tooling

### stdlib `unittest` → pytest, plus uv

The original argument for stdlib — "a suite needing a package the program does
not is a suite that goes unrun" — conflated two things. The *program* and the
*probe* must run on a bare Steam Deck shell; the *test suite* only ever runs on a
development machine. Both invocation paths are kept and both are tested:
`uv run pytest` against the locked environment, and plain `pytest` from a
checkout with apt-installed numpy/PyQt6, where `conftest.py` falls back to
putting `src/` on `sys.path`.

The launcher is untouched: `./amdgraph` still needs no install step.

### No golden pixel hashes

Pane rendering draws text, so a hash fingerprints the font stack as much as the
code, and a golden that breaks on a Qt upgrade gets deleted rather than
investigated. Asserted instead: geometry, exact view state after a gesture, and
that everything paints without raising — all portable. For a refactor, hash
renders against the previous commit in a scratch script and throw it away. That
is how the layer split was verified: 93 renders and the full gesture trace,
identical to the pre-split original.

### The single file became a layered package

2733 lines in one file had stopped being navigable, and the three pane classes
had drifted into three copies of the same mouse handling. The layer map lives in
`src/amdgraph/__init__.py` and `tools/check-layers.py` enforces the import
direction — including absolute self-imports, which the first version of the
checker missed and which run fine at runtime.

### The source is injected

`Main` takes a `source=` implementing six methods. Added because the window had
0% coverage — it constructed its own `Sampler`, so it could not exist without
the right hardware. The same seam is what a second platform plugs into.

### The filesystem is injected too

`Sampler` takes an `fs=` (`RealFS`/`RecordingFS`/`ReplayFS` in `sysfs.py`), one
layer below `source=`. Before this, exercising the real decode logic —
version guards, the throttle poller, hwmon/DRM discovery — against anything
but the literal machine underneath meant hand-authoring a synthetic
`tmp_path` tree per test, one narrow case at a time. `RecordingFS` captures
what a real machine's filesystem returned over a real session;
`tools/amdgraph-record` drives a real `Sampler` through one. `ReplayFS`
serves that capture back to an unmodified `Sampler`, so a real exceptional
condition — the SMU module disappearing mid-session, a `gpu_metrics` version
this build refuses — replays deterministically without the hardware doing it
again, and `amdgraph --replay` makes it possible to develop and manually run
the program somewhere with no AMD part in it at all.

### Sampler split into a backends package

One module per hardware family (`host`, `platform`, `zen_smu`, `amdgpu`) under
`src/amdgraph/backends/`, each with a `probe(fs)` deciding for itself whether
it applies. `Sampler` composes whichever backends probe true; it is layer 2,
backends are a new layer 1 between it and `fields`/`sysfs`, not a same-layer
exception -- `Sampler` composing implementations is a real hierarchy, the
same relationship `__main__`/`window` do not have (they are peers, which is
why that one *is* a same-layer exception).

Done now rather than speculatively earlier because a concrete second and
third platform are both arriving at once: a Strix Halo host (different
pm_table version, `gpu_metrics v3_0`'s residency-counter strategy instead of
a bitmask, 16 cores over two CCDs, almost certainly not `thinkpad_acpi`) and
an RTX 3070 over Thunderbolt (a vendor with no representation in this
program at all, and no sysfs precedent checked yet for how much of it is
readable without a subprocess). Splitting first, against hardware already in
hand and already verified, means the actual new decoding lands as new
modules rather than edits threaded through one growing `sample()` method.

---

## Open questions

- **cores + SoC exceeds socket power by ~1 W**, systematically. Unexplained.
- **`stt_lim` reads 43 during an EC thermal clamp**, and 43 appears nowhere in
  the DSDT's `STTS` table. Source unknown.
- **Lap mode halves `edc_lim` (105 → 52 A)** and correlates with nothing Linux
  can see — no threshold in any available sensor fits all observed transitions.
  The trigger is inside the EC.
- **The 63 °C trip / 60 °C release thresholds** live in EC firmware; ACPI only
  relays alarm bits the EC has already decided. Whether they are RAM-backed and
  therefore writable is unknown, and testing it on real hardware is genuinely
  risky.
