"""amdgraph -- live strip charts for AMD Ryzen laptops.

Every number comes from sysfs, read directly, with no subprocesses and no root.
That matters more than it sounds -- a monitor that shells out to ryzenadj once a
second becomes a top wakeup source and perturbs the very thermal behaviour you
are trying to tune.

What it shows that off-the-shelf Linux monitors do not: the SMU's own view of
itself. STAPM/PPT budgets against their limits, the STT skin-temperature model
that actually governs sustained clocks on this platform, VRM current (TDC/EDC)
against its limits, and per-core power/clock/residency -- all from ryzen_smu's
world-readable pm_table.

Everything shares one time axis. Hovering anywhere drops a crosshair on every
pane at once and reads out that instant across all of them, which is the whole
point: you want to see the STT ceiling being hit and the core clocks folding in
the same glance, not in two separate windows.

Sessions can be recorded to disk and reloaded, either on their own or as a ghost
behind the live trace, so "did that ryzenadj change actually help" has an answer
rather than an impression. A filesystem capture made by tools/amdgraph-record
can stand in for the machine itself, which is what makes it possible to develop
amdgraph somewhere with no AMD part in it.

    amdgraph [--interval SECONDS] [--open FILE] [--replay FILE]

Keys:  space freeze   r reset   m mark   Esc unzoom   [ ] window   q quit

Requires PyQt6 and the ryzen_smu kernel module (SMU panes degrade to empty
without it; hwmon and cpufreq panes still work).

Sensor layouts are part-specific and undocumented, so amdgraph decodes only what
has been checked against live silicon: pm_table 0x004C0009 and gpu_metrics v2_1,
as found on Ryzen 7040-series (Phoenix). On anything else the affected panes stay
empty and the status bar names the version it found, rather than showing numbers
read from the wrong offsets. See docs/HARDWARE.md for what adding a part
involves.


Layers
======

Modules are listed in dependency order. Each may import from the layers above
it and never from those below; the header of every module restates its own
budget, so a cycle is visible where it is introduced rather than at import time.

  0. hardware map, no logic
     fields    pm_table indices, gpu_metrics offsets, throttler bits, paths.
               Everything here was checked against live silicon; the comments
               are the evidence and are the most valuable thing in the tree.
     sysfs     open/read/parse helpers that know nothing about any field.

  1. acquisition and storage -- no Qt below this line
     sampler   Sampler (one tick -> one dict), plus the off-thread throttler
               poller and the /proc/stat differ.
     store     Store: NaN-filled numpy column store, the in-memory format.

  2. session and presentation policy -- still no widgets
     session   CSV recording and playback, and which keys get recorded.
     panes     the pane catalogue: what is plotted, against what ceiling, with
               what caveat. Declarative; contains no drawing code.
     palette   colours, validated against the chart surface.
     view      the time window, crosshair and overlay every pane shares.

  3. drawing primitives
     render    axis ranges, number and time formatting, polyline building,
               raster column-hold. Free functions over numpy and QPainter.

  4. widgets, one per kind of pane
     timepane  the base every pane shares: time projection and the zoom, pan
               and crosshair gestures.
     chart     ChartPane, the line-chart pane driven by a PaneSpec.
     rasters   ThrottlePane and CorePane, the two QImage strip charts.
     axis      TimeAxis, the shared ruler pinned below the scroll area.

  5. assembly
     window    Main: builds the pane column, owns the sample timer, wires the
               toolbar to the layers below.
     __main__  argument parsing and QApplication.
"""

# --help shows the part of the docstring aimed at whoever is running the
# program, not the layer map, which is aimed at whoever is editing it. Split
# rather than duplicated: two copies of the key bindings would disagree.
HELP = __doc__.split("\nLayers\n")[0].strip()
