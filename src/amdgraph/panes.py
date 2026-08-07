"""Layer 2 -- the pane catalogue.

What gets plotted, against which ceiling, with which caveat. Declarative on
purpose: no Qt, no drawing, no sampling. Adding a pane means adding an entry
here, and the argument for why a pane exists (or was removed) belongs in the
comment beside it rather than in a commit message nobody will find.

May import: nothing in this package.
"""


class Series:
    def __init__(self, key, label, limit=None, good_high=False):
        self.key, self.label, self.limit = key, label, limit
        # good_high marks a series whose limit is a headroom ceiling rather
        # than a throttle point -- reaching it means nothing is holding the
        # part back, so it must not raise the CAPPED flag.
        self.good_high = good_high
        self.visible = True
        self.hit = None


class PaneGroup:
    """A consecutive run of panes behind one collapsible header.

    Declared by title rather than by nesting the specs, so PANES stays a flat
    catalogue you can read top to bottom in the order it appears on screen --
    the same way HEAT_AFTER names its anchor.

    The point is vertical budget. The column is about 2.4 screens tall, so
    everything is a choice about what a reader sees before scrolling; a group
    is for panes that are worth having but are not usually the question.
    """

    def __init__(self, title, titles, collapsed=True, note=None):
        self.title = title
        self.titles = tuple(titles)
        self.collapsed = collapsed
        self.note = note


class PaneSpec:
    """One chart pane. Every series in a pane shares a single unit and a single
    y-axis -- there are no dual-scale panes here, because a second y-scale
    makes two traces cross wherever the author chose and means nothing."""

    def __init__(self, title, unit, series, floor0=True, height=112,
                 note=None):
        self.title, self.unit = title, unit
        self.series = [Series(*s) for s in series]
        self.floor0 = floor0
        self.height = height
        self.note = note


def available_catalogue(keys):
    """Return fresh pane/group specs containing only data this source owns.

    Backends put keys in every sample even when the current reading is absent,
    using ``None`` for that instant.  That makes the first sample a capability
    description without adding a seventh method to the source protocol.  A
    transiently missing sensor therefore remains in the catalogue, while a
    Phoenix-only field that a Strix backend never emits does not consume a row
    forever labelled "no data".

    Fresh specs matter too: legend clicks mutate ``Series.visible``.  Sharing
    the module-level catalogue between two windows otherwise leaks visibility
    state from one session into the next.
    """
    keys = set(keys)
    specs = []
    for original in PANES:
        series = [(s.key, s.label, s.limit, s.good_high)
                  for s in original.series if s.key in keys]
        if series:
            specs.append(PaneSpec(original.title, original.unit, series,
                                  original.floor0, original.height,
                                  original.note))
    titles = {s.title for s in specs}
    groups = []
    for original in GROUPS:
        members = tuple(t for t in original.titles if t in titles)
        if members:
            groups.append(PaneGroup(original.title, members,
                                    original.collapsed, original.note))
    return specs, groups


# Ordered as the diagnosis runs: what is capping it, then the three things that
# can cap it (power, current, heat), then what that bought in clocks, then the
# physical system, then platform policy.
#
# Every governed quantity is drawn once, as value plus its own ceiling over
# time. There were briefly three views of this -- value with a dashed limit, the
# ceilings alone, and limit-minus-value -- which existed only to *infer* the
# cause before the SMU's throttler bits were being read. Cap reason states it
# outright now, so the other two were removed rather than kept in sync.
#
# Firmware limits per platform profile on this machine, measured with no
# ryzenadj override running:
#
#   profile      ppt_fast  ppt_slow  stt_lim  tctl/gfx/soc_lim
#   performance      30.0     23-24       46               100
#   balanced         25.0        14       40               100
#   low-power        12.0        12       40                70
#
# Every one of these moves with the profile, so none is safe to treat as a
# constant and draw as scenery -- which is why the dashed ceilings are plotted
# as time series rather than at their current value. The thermal ceilings
# dropping to 70 matter most: a part at 87-95 C handed a 70 C ceiling clamps to
# hold 70, collapsing clocks far harder than the power cut it arrives with.
#
# stapm_lim is absent above because it is not a per-profile constant -- it
# tracks a slow integrator and drifts (30.0 -> 13.8 over ten idle seconds in
# performance), settling well below the nameplate.
#
# Measure this with nothing re-applying limits in the background. An earlier
# version of this table read ppt_slow 28 and stt_lim 58 flat across all three
# profiles, which was a `watch ryzenadj --slow-limit 28000 --apu-skin-temp=58`
# loop winning every two seconds, not the firmware. The brief pre-override
# values were the real ones.
PANES = [
    PaneSpec("Package power", "W", [
        ("stapm", "STAPM", "stapm_lim"),
        ("ppt_fast", "PPT fast", "ppt_fast_lim"),
        ("ppt_slow", "PPT slow", "ppt_slow_lim"),
    ], note="dashed = that limit at the time, not the limit now"),
    # Second, not last: EDC is measured at 67-80% duty at idle on this machine,
    # so current binds here more often than power does.
    PaneSpec("VRM current", "A", [
        ("edc", "EDC core", "edc_lim"),
        ("tdc", "TDC core", "tdc_lim"),
        ("edc_soc", "EDC SoC", "edc_soc_lim"),
        ("tdc_soc", "TDC SoC", "tdc_soc_lim"),
    ], note="often binds before power does"),
    # ppt_apu is not plotted: it reads a constant 0 on this part in every state
    # tested, so it is a flat line at the axis floor that only costs a colour
    # slot. Still recorded, in case it means something on another SKU.
    # batt_power is kept despite reading 0 on AC -- that zero is information.
    # Where the budget goes: the measured components only.
    #
    # `socket - cores - soc` is recorded as pwr_rest but deliberately NOT
    # plotted. It is negative in 54% of samples and ranges -14.3 to +18.6 W
    # about a mean of +0.15 W, because the three fields carry different SMU
    # averaging windows and differencing them at one instant yields noise an
    # order of magnitude larger than the quantity. Smoothing does not rescue
    # it: still 44-65% negative at a 4.5 s window. The visible gap between
    # socket and cores carries the same information without pretending to a
    # precision that is not there, and the eye averages it better than a
    # difference trace does.
    # Core power comes from pm_table, not from gpu_metrics, though both exist.
    # Measured against socket_power over the same window:
    #
    #   source                jitter   exceeds socket   worst overshoot
    #   gpu_metrics cores      3.92 W        42.7%           +14.09 W
    #   pm_table cores         1.43 W        38.0%            +2.99 W
    #
    # 2.7x less sample-to-sample jitter and an overshoot bounded to a few
    # watts rather than fourteen. Scanning every other pm_table index for an
    # aggregate CPU-power field turned up nothing better -- only the per-core
    # values themselves and IDDMAX.
    #
    # Neither is fully consistent with socket_power: cores + SoC exceeds it by
    # ~1 W on average, which is systematic rather than noise and is not
    # explained. Read the gap between socket and cores as indicative, not as a
    # GPU measurement.
    PaneSpec("Power breakdown", "W", [
        ("pwr_socket", "socket total", None),
        ("core_power_sum", "CPU cores", None),
        ("pwr_soc", "SoC", None),
    ], note="gap ≈ GPU/PHY/fabric; cores can still overshoot socket by ~1 W"),
    PaneSpec("Rail power", "W", [
        ("gpu_power", "amdgpu hwmon", None),
        ("batt_power", "battery", None),
    ], note="independent views: driver-reported APU power, and DC draw"),
    # VID carries no limit line. Index 28 is a "VID limit" by the APU table
    # convention, but on this part it jitters and the value at index 29
    # routinely exceeds it -- whatever it is, it is not a ceiling this value
    # respects, so drawing it as one would invent a constraint.
    PaneSpec("Voltage", "V", [
        ("vid", "VID", None),
        ("core_volt_mean", "mean core", None),
        ("vddcr_soc", "VDDCR_SOC", None),
        ("cldo_vddp", "cLDO_VDDP", None),
    ], floor0=False),
    PaneSpec("SMU temperature", "°C", [
        ("tctl", "Tctl", "tctl_lim"),
        ("stt", "STT skin", "stt_lim"),
        ("thm_gfx", "GFX", "thm_gfx_lim"),
        ("thm_soc", "SoC", "thm_soc_lim"),
    ], floor0=False, height=124,
        note="STT is the model that governs sustained clocks"),
    PaneSpec("System temperature", "°C", [
        ("ec_skin", "EC skin", None),
        ("ec_cpu", "EC CPU", None),
        ("gpu_edge", "GPU edge", None),
        ("nvme", "NVMe", None),
    ], floor0=False),
    PaneSpec("CPU clock", "MHz", [
        ("core_freq_max", "peak core", None),
        ("core_freq_mean", "mean core", None),
        ("core_freqeff_mean", "mean effective", None),
    ], height=124, note="peak vs mean = how evenly load is spread"),
    PaneSpec("SoC clock", "MHz", [
        ("fclk", "fclk", None),
        ("uclk", "uclk", None),
        ("mclk", "mclk", None),
        ("socclk", "socclk", None),
    ]),
    PaneSpec("GPU clock", "MHz", [
        ("gfx_clk", "gfx (SMU, instant)", "gfx_clk_max", True),
        ("sclk_hw", "sclk (DPM level)", None),
    ], note="SMU samples instantaneously; DPM reports a coarse level"),
    # mem/swap are host OS figures, not SMU telemetry -- they read the same on
    # any Linux box, which is why they are also the only two series here that
    # still move on a machine with no ryzen_smu or amdgpu at all (a container).
    PaneSpec("Utilisation", "%", [
        ("cpu_busy", "CPU busy", None),
        ("gpu_busy", "GPU busy", None),
        ("core_c0_mean", "mean C0", None),
        ("core_cc6_mean", "mean C6", None),
        ("mem_used_pct", "memory used", None),
        ("swap_used_pct", "swap used", None),
    ]),
    PaneSpec("DRAM bandwidth", "GiB/s", [
        ("dram_rd", "read", None),
        ("dram_wr", "write", None),
    ], note="peak here ≈ 95 GiB/s (6400 MT/s × 128-bit)"),
    PaneSpec("Fan command", "level", [
        ("fan_cmd", "commanded", None),
    ], height=76, note="8 = disengaged; blank = firmware auto"),
    PaneSpec("Fan speed", "rpm", [
        ("fan1", "fan 1", None),
        ("fan2", "fan 2", None),
    ], height=90),
    # No Reliability/FIT pane. FIT itself is real -- Failures In Time, the
    # ageing/electromigration budget, which AMD's SMU spends by capping
    # voltage (the desktop table exposes FIT_VOLTAGE / FIT_PRE_VOLTAGE beside
    # the FIT_LIMIT / FIT_VALUE pair, and the kernel has an
    # SMU_THROTTLER_FIT_BIT, though not for Phoenix).
    #
    # What is not established is that indices 26/27 are it on this table.
    # They carry the FIT labels only by the APU (limit, value) convention,
    # never confirmed for Phoenix, and they do not behave like a pair:
    # idx27/idx26 holds a near-constant 0.39% (0.29-0.58% observed), so the
    # "value" never approaches its "limit", and both drift with temperature
    # in a way no failure-rate budget explains. Their neighbours 24, 25, 30
    # and 31 all read a constant zero, so the pairing convention demonstrably
    # does not hold across this block.
    #
    # Drawing them as value-against-ceiling asserted a constraint that could
    # not be substantiated, so the pane is gone; both are still recorded.
    #
    # Worth a look if this is ever picked up again: index 28 correlates -0.80
    # with temperature, frequency and voltage alike while index 29 correlates
    # +0.89/+0.93/+0.94. That is the shape of a genuine voltage ceiling being
    # lowered by a reliability model, with 29 as the VID beneath it.
    # Step traces. Unitless on purpose -- these are states, not quantities, and
    # the only thing being read off them is when they change.
    PaneSpec("Platform state", "", [
        ("lapmode", "lap mode", None),
        ("palm", "palm sensor", None),
        ("pprof", "profile", None),
        ("ac_online", "AC", None),
    ], height=90,
        note="profile 0=low-power 1=balanced 2=performance; a step = budget change"),
]

# Collapsible sections, named by the run of pane titles they wrap.
#
# Package power stays outside: it carries most of the governing limits -- STAPM
# and both PPT budgets against their own moving ceilings -- so it is the second
# thing to look at after the cap reason, not detail. What is behind the header
# is the breakdown you go to once you know power is the binding constraint, and
# collapsing it lifts the temperatures, the CPU clock and the per-core strip
# above the fold on a 900 px window.
GROUPS = [
    PaneGroup("Power detail",
              ("VRM current", "Power breakdown", "Rail power", "Voltage"),
              collapsed=True,
              note="current, where the watts go, rails, voltage"),
]

# Throttler poll rates. 1 Hz means "no background thread" and gives the old
# instantaneous flag; the default is chosen to resolve a ~20 Hz duty cycle
# without the cost running away.
CAP_RATES = [(1.0, "1 Hz"), (10.0, "10 Hz"), (20.0, "20 Hz"), (50.0, "50 Hz")]
CAP_DEFAULT = 2

HEAT_MODES = [
    ("core_freq", "clock", "MHz", 400.0, 5200.0),
    ("core_c0", "C0 residency", "%", 0.0, 100.0),
    ("core_temp", "temperature", "°C", 30.0, 100.0),
    ("core_power", "power", "W", 0.0, 15.0),
    ("core_volt", "voltage", "V", 0.6, 1.4),
    ("core_cc6", "C6 residency", "%", 0.0, 100.0),
]

# Where the two raster strips are inserted in the pane column. The cap-reason
# strip goes first, above everything: it is the answer, and the panes below it
# are the corroboration.
THROTTLE_FIRST = True
HEAT_AFTER = "CPU clock"
