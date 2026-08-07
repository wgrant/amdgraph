# Design

What the pieces are, and why they are arranged this way. Details that belong
next to code stay in the code — this describes the shape and the reasoning, and
points at the modules that carry the specifics.

## The premise

The SMU knows why it is holding the part back. Almost every Linux monitor
infers that from temperatures and clocks; this reads the governor's own answer.
That single choice drives most of the rest: the interesting data lives in two
binary blobs whose layouts are undocumented and part-specific, so the program is
mostly *decode discipline* wrapped in a chart library.

Three properties follow, and none is incidental:

**Read-only, unprivileged, no subprocesses.** A monitor that shells out to
`ryzenadj` once a second becomes a top wakeup source and changes the thermal
behaviour you are trying to tune. Both blobs are world-readable, so the whole
program runs as the user with a few dozen `open`/`read`/`close` per tick.

**One shared time axis.** Every pane draws the same window, and hovering
anywhere drops a crosshair on all of them at once. Reading the STT ceiling being
hit and the core clocks folding in the same glance is the entire point; two
windows would not do it.

**Refuse to decode what has not been verified.** A wrong field map looks
exactly like a right one. Both blobs are version-gated and produce empty panes
plus a note naming what was found, rather than plausible numbers.

## Layers

Modules are listed in dependency order in `src/amdgraph/__init__.py`, and
`tools/check-layers.py` enforces the direction by parsing imports — relative,
absolute, and plain `import amdgraph.x` alike, because the launcher puts `src/`
on `sys.path` and all three forms run.

```
0  model fields         shared telemetry types; hardware constants
   smu/* gpu_metrics/*  one descriptor or pure decoder per versioned ABI
   sysfs                sysfs readers and real/replay/memory FS implementations
1  backends             one module per hardware family, each deciding for
                        itself whether it applies to this machine
2  sampler normalize    isolated backend merge; hardware-neutral derivations
   store                NaN-filled numpy columns
                        ── no Qt below this line ──
3  session panes        the CSV format; the pane catalogue
   palette view         colours; the shared time window
4  render               axis ranges, formatting, polylines, raster column-hold
5  timepane             base: time projection + zoom/pan/crosshair gestures
   frame                base: the widget chrome a painted body sits inside
   chart rasters axis   the three kinds of pane, and the ruler
   section              the collapsible group header
6  window  __main__     assembly; argparse and QApplication
```

The "no Qt below layer 2" rule is checked, not just stated. It means a
recording can be produced or read headlessly, and it is why `--help` works on a
machine with neither numpy nor PyQt6 installed.

Some edges the numbering cannot express, all declared in the checker: `chart`
and `rasters` may import `timepane` and `frame` (their base classes), each
backend module may import `backends.base` (likewise), and `__main__` may import
`window`.

## Data flow

```
sysfs ──> backends ──> explicit merge ──> normalize ──> Store (numpy columns)
                                     │                      │
                                     └──> Recorder ──> CSV   └──> panes read
                                                              via View
```

One tick produces one flat dict. That is the only shape anything above layer 2
sees, which is what makes a recording and a live session interchangeable: `Open`
swaps `View.store` for one loaded from disk and every pane follows, with the
live buffer left untouched underneath.

`LocalHistoryService` owns the sampler, live Store, markers, and CSV writer.
Qt and Rich are clients of that interface. `amdgraphd` exposes it over a
versioned Unix-socket snapshot-plus-stream protocol; `RemoteHistoryService`
maintains the same Store-shaped client view and reconnects without involving
frontend code. The daemon additionally writes one JSON telemetry object per
sample to SQLite WAL—not one row per metric—so range reads and crash recovery
remain cheap while CSV stays available for interchange.

Missing values are NaN, never zero. A sensor that vanishes must leave a hole in
the trace, not a cliff to the floor, and `polylines()` splits on NaN to draw it
that way.

### The throttler is sampled off-thread

The cap-reason bits are instantaneous flags on a controller that duty-cycles at
roughly 20 Hz. Sampled once a second they report a coin flip — a continuously
active limiter looks intermittent. A background thread accumulates at 20 Hz and
each UI tick drains a *duty cycle*. The power fields ride along free, since that
thread already has the blob open.

This is the one place the program spends real CPU (~1.2% of a core) and it is
adjustable in the toolbar; at 1 Hz the thread does not run at all.

## The source protocol

`Main` takes a `source=` implementing the typed `Source` protocol:

| | |
|---|---|
| `sample()` | one tick's worth, `dict[str, float]` |
| `notes()` | strings for the status bar — what could not be read, and why |
| `meta()` | fields folded into a recording's header comments |
| `metric_keys()` | supported telemetry, independent of a successful read |
| `set_cap_rate(hz)` | how often the cap-reason source is polled |
| `reset()` | forget differencing state; the buffer was cleared |
| `close()` | stop background threads |

`Sampler` is the implementation that reads this machine -- or rather,
composes what `backends/` reads: it discovers which backend modules apply at
construction, samples each into an isolated dictionary, applies explicit
collision priorities, then adds hardware-independent derived values. Anything specific to how a *particular*
part is read belongs behind a backend's own methods, not here; see
`src/amdgraph/backends/base.py` and "Adding a part" in `docs/HARDWARE.md`.

Each backend also declares immutable `Metric` descriptors. Those declarations
drive GUI capability discovery and CSV columns, so a transient startup miss
cannot hide a supported pane and a newly decoded value cannot silently vanish
from recordings. Cross-layer tests require every plotted field and limit to be
recordable, and pure ABI decoder tests require emitted keys to be declared.

This seam was added because the window had no tests: it constructed its own
`Sampler`, so it could not exist without a Phoenix underneath. It had also been
reaching past the interface — reassigning `sampler.cpubusy` to reset the
`/proc/stat` differ, calling `sampler.throttle.set_rate()` directly, formatting
the pm_table version into the recording header itself. Each of those is exactly
what a second backend would do differently, so the same change that made the
window testable is the one a second platform needs. See `docs/HARDWARE.md`.

## The filesystem backend

One layer below the backends, each of them takes an `fs=` implementing four
primitives -- `read_text`, `read_bytes`, `glob`, `listdir` -- in
`src/amdgraph/sysfs.py` (`Sampler` just holds the one instance and passes it
through). `RealFS` is the only one used outside development: it is what
every read in `backends/*.py` goes through instead of a bare
`open()`/`glob.glob()`/`os.listdir()`.

`RecordingFS` wraps another `FS` and logs every call, in order, keyed by
`(op, path)`. `tools/amdgraph-record` drives a real `Sampler` through one for
a session and saves the log as a flat, hand-editable JSON file. `ReplayFS`
serves that log back to an unmodified `Sampler` -- each `(op, path)` has its
own cursor, so the Nth read of a path gets the Nth recorded value and holds at
the last one once the sequence runs out.

This is what makes it possible to develop and manually run `amdgraph
--replay capture.json` against something that behaves like a real Phoenix
with no AMD part underneath, and to reproduce an exceptional condition --
`ryzen_smu` disappearing mid-session, a `gpu_metrics` version the build does
not decode -- deterministically, by editing the one JSON record for the path
in question rather than waiting for the hardware to misbehave again.

## Rendering

Panes are declarative. `panes.py` lists what is plotted, against which ceiling,
with what caveat, and contains no drawing code; `ChartPane` turns one `PaneSpec`
into pixels and knows nothing about what any key means. Adding a pane is an
entry in the catalogue.

### Widgets outside, painting inside

Each pane is a `PaneFrame`: a header row of real Qt widgets above one
custom-painted body.

```
PaneFrame (fixed height = spec.height)
├── header (QWidget, QHBoxLayout)
│   ├── QLabel     title
│   ├── QComboBox  where the pane owns a setting
│   ├── ElidedLabel  the note — yields its width to everything else
│   └── Readout    live values at the crosshair (painted)
└── body           grid, traces, gutters, cursor (painted)
```

The split is by *what the region does*. A title, a note and a control are
chrome, and chrome is what widgets are for: the layout negotiates widths, a
combo can be seen and tabbed to instead of hiding in a context menu, and text is
text. Two things stay painted:

- **the body**, because splitting the y-axis gutter into its own widget would
  mean handing it the y-scale, which is computed during the body's own fit;
- **the readout**, because four series across seventeen panes rewritten at
  ~30 Hz while the pointer sweeps is around seventy label updates a frame, each
  triggering layout, versus one `drawText` loop.

Two consequences worth knowing. `spec.height` is the *whole row*, header
included, so the body is sized to `spec.height - render.HEADER_H` and the fold
arithmetic stays comparable across the change. And a frame can be indented —
`PaneFrame(indent=n)`, used to show a section containing its panes — in which
case the body subtracts the same `n` from its own left gutter, because every
pane shares one time axis and a plot that moved would stop lining up with the
ruler beneath it.

The three bodies share `TimePane`, which owns the time↔pixel projection and
every gesture (drag to zoom, wheel, middle-drag pan, crosshair). Before it
existed those were copied three times and had already drifted — the selection
band was drawn two different ways.

Gestures are scoped to the plot, not the whole pane. The wheel only zooms over
it (otherwise the event is ignored and scrolls the column, which is over two
screens tall), and the crosshair only tracks over it (outside, the store has no
sample at that time, so every readout would drop to `--`).

### Geometry comes from the font

Anything that has to hold text is sized from `QFontMetrics`, never from a
constant. `render.calibrate()` runs once at startup, after a `QApplication`
exists, and sets the gutters (`LEFT`, `RIGHT`), the body's insets (`TOP`,
`BOTTOM`) and the header height from the fonts actually in use; the raster row
heights and the axis height come from each widget's own metrics. Six separate
clipping bugs came from constants tuned against one machine's font — see
`CLAUDE.md`, which states the rule, and `DECISIONS.md` for the list.

Two panes are rasters rather than line charts, because thirteen throttle reasons
and modern core counts are both far past where categorical colour stays
separable. They
paint a row-per-thing `QImage` the width of the plot, which keeps a full-window
repaint cheap; identity comes from the row label and fixed order, and colour
carries only magnitude (cores) or family (throttle reasons).

Performance is a real constraint and was a real bug: painting, not sampling,
dominates. A full sample of ~150 keys costs about 4 ms; repainting was 52 ms
until the per-point projection was vectorised, the plot rect cached, off-screen
panes skipped, and cursor updates coalesced onto a 33 ms timer. If it feels
heavy again, profile the paint path first.

## Conventions worth knowing

- **Limits are time series, not scenery.** Every ceiling on this platform moves,
  so a dashed limit line is drawn from its recorded column rather than at
  whatever it reads now. Drawing "now" across history silently re-judged the
  past against a ceiling that was not in force.
- **Value and limit are read at the same instant.** Reading the value at the
  crosshair and the limit at "now" compares two different moments.
- **Colour is bound to slot, not rank.** Hiding a series does not repaint the
  others.
- **Every recorded key is recorded**, not just the plotted ones. A recording you
  must re-take because you did not log the column you now want is worse than a
  slightly larger file.

## Testing

`uv run pytest`. Nothing touches real hardware: device discovery, the pm_table
decode and the version guards run against synthetic trees and blobs under
`tmp_path`, and the window runs against a fake source. That is deliberate —
the paths that matter most are the ones for parts nobody here owns.

No golden pixel hashes. Pane rendering draws text, so a hash fingerprints the
font stack as much as the code, and a golden that breaks on a Qt upgrade gets
deleted rather than investigated. What is asserted is portable: geometry, exact
view state after a gesture, and that everything paints without raising.

`sampler.py` sits around 44% and that is the honest floor — what remains is code
that opens `/sys` directly. Making it testable means giving the readers an
injectable root, the way `find_hwmon(base=...)` already has. That is the same
change a second platform needs, and it is the next structural work.
