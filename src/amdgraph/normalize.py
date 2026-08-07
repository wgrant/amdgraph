"""Layer 2 -- hardware-independent derived telemetry."""


def normalize(sample):
    """Add derived values after backend results have been merged."""
    for name, value, limit in (
            ("stapm_head", "stapm", "stapm_lim"),
            ("ppt_slow_head", "ppt_slow", "ppt_slow_lim"),
            ("ppt_fast_head", "ppt_fast", "ppt_fast_lim")):
        if sample.get(value) is not None and sample.get(limit) is not None:
            sample[name] = sample[limit] - sample[value]

    count = int(sample.get("core_count") or 0)
    powers = [sample.get(f"core_power_{i}") for i in range(count)]
    powers = [value for value in powers if value is not None]
    if powers:
        sample.setdefault("core_power_sum", sum(powers))
    return sample
