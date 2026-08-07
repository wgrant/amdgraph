# Working on amdgraph

A read-only PyQt6 strip-chart monitor for AMD Ryzen laptops. Read `docs/DESIGN.md`
before changing structure, `docs/HARDWARE.md` before touching anything that
decodes a sensor, and `docs/DECISIONS.md` before re-proposing something that was
already tried.

## Rules that are not negotiable

**Never write to hardware.** Every hardware access is `open(..., "r")` or
`"rb"`. Nothing touches `smu_args`, `smn`, `mp1_smu_cmd`, `rsmu_cmd`, MSRs, or
any EC RAM. The only files this program creates are its own recordings and the
probe's JSON. A change that needs a write is a change that needs to be discussed
first.

**Never require root.** The two data sources are world-readable and that is why.
If a feature needs privileges it degrades to absent, with a note in the status
bar, exactly as a missing `ryzen_smu` does. RAPL is deliberately unread for this
reason.

**Never decode a layout that has not been verified on hardware.** `pm_table` is
gated on its version and `gpu_metrics` on both its version *and* its declared
size. Widening either without validating the fields against something
independent is the one failure this project is arranged to prevent — a plausible
wrong number looks authoritative and can survive for years. See
`docs/HARDWARE.md` for what validation means here.

**Do not perturb the machine being measured.** The user may be recording while
you work. Do not change power limits, platform profiles, or run load generators
without saying so first; a sampler that shells out to `ryzenadj` or polls at high
rate becomes a wakeup source and changes the thermal behaviour being tuned. If
you measure something, account for every writer before attributing a change to
firmware — a `watch ryzenadj` loop in another terminal has already been mistaken
for the platform once.

**Put the evidence next to the claim.** A comment asserting what a field means
must say how that was established. The comments in `src/amdgraph/fields.py` are
the most valuable thing in the tree; they are why the Phoenix map is trustworthy
and a transcribed one would not be.

## Verifying

```
uv run pytest                       # 278 tests, no hardware needed
python3 tools/check-layers.py       # import direction (also a test)
./amdgraph                          # the real thing, on real hardware
```

Tests must not need an AMD part present. Anything that reads `/sys` gets a
synthetic tree under `tmp_path`; the window gets a fake source. If you cannot
test a change without hardware, that is usually a sign the seam is in the wrong
place — see the source protocol in `docs/DESIGN.md`.

For GUI changes, assert behaviour that is portable: geometry, exact view state
after a gesture, that a pane paints without raising. Do not add golden pixel
hashes. For a refactor, hash renders against the previous commit in a scratch
script and throw it away.

## Conventions

- Panes are declared in `src/amdgraph/panes.py`, which contains no drawing code.
  A decision about *what* to show belongs there and nowhere else.
- Each module's docstring states the layer it is in and what it may import.
  `tools/check-layers.py` enforces it.
- No new runtime dependencies. numpy and PyQt6, both imported late enough that
  `--help` still works on a bare machine.
- Match the surrounding comment density. This codebase explains *why*, at
  length, and reads oddly if new code does not.
- Local repo, no remote. Commit as `William Grant <me@williamgrant.id.au>`.

## Where things are

```
amdgraph              launcher; the code is src/amdgraph/
src/amdgraph/         the package, layered (start at __init__.py)
tools/amdgraph-probe  dumps an unfamiliar part's sensor sources
tools/check-layers.py import-direction checker
tests/                pytest, no hardware
docs/                 design, hardware, decisions
```
