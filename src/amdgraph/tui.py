"""Layer 6 -- Rich terminal frontend for a history service."""

import argparse
import bisect
import math
import time

from rich.console import Console
from rich.live import Live
from rich.table import Table

from .service import LocalHistoryService


PREFERRED = (
    "stapm", "stapm_lim", "ppt_fast", "ppt_fast_lim", "pwr_socket",
    "core_power_sum", "cpu_busy", "gpu_busy", "core_freq_mean",
    "core_freq_max", "gfx_clk", "tctl", "thm_gfx", "thm_soc", "stt",
    "dram_rd", "dram_wr", "fan1", "fan2", "fan3", "nvme")

BLOCKS = "▁▂▃▄▅▆▇█"
FIXED_RANGES = {
    "cpu_busy": (0.0, 100.0), "gpu_busy": (0.0, 100.0),
    "tctl": (30.0, 100.0), "thm_gfx": (30.0, 100.0),
    "thm_soc": (30.0, 100.0), "stt": (30.0, 100.0),
    "core_freq_mean": (0.0, 5200.0), "core_freq_max": (0.0, 5200.0),
    "gfx_clk": (0.0, 3000.0), "fan1": (0.0, 7000.0),
    "fan2": (0.0, 7000.0), "fan3": (0.0, 7000.0),
}


def sparkline(store, key, width=24, seconds=60.0):
    """Resample recent history into one Unicode block per terminal column."""
    column = store.col(key)
    if column is None or store.n == 0 or width <= 0:
        return " " * max(0, width)
    times = store.times()
    end = float(times[-1])
    start = max(float(times[0]), end - seconds)
    span = max(1e-9, end - start)
    time_values = [float(value) for value in times]
    reduced = []
    for i in range(width):
        target = start + (i / max(1, width - 1)) * span
        index = bisect.bisect_right(time_values, target) - 1
        value = float(column[index]) if index >= 0 else math.nan
        reduced.append(None if math.isnan(value) else value)
    present = [value for value in reduced if value is not None]
    if not present:
        return " " * width
    low, high = FIXED_RANGES.get(key, (min(present), max(present)))
    if high - low < 1e-9:
        low, high = low - 0.5, high + 0.5
    chars = []
    for value in reduced:
        if value is None:
            chars.append(" ")
            continue
        fraction = max(0.0, min(1.0, (value - low) / (high - low)))
        chars.append(BLOCKS[round(fraction * (len(BLOCKS) - 1))])
    return "".join(chars)


def dashboard(service, spark_width=24, spark_seconds=60.0):
    table = Table(title="amdgraph", expand=True)
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("value", justify="right")
    table.add_column(f"last {spark_seconds:g}s", style="green", no_wrap=True)
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("value", justify="right")
    table.add_column(f"last {spark_seconds:g}s", style="green", no_wrap=True)
    values = []
    for key in PREFERRED:
        value = service.store.latest(key)
        if value is not None:
            values.append((key, f"{value:.2f}",
                           sparkline(service.store, key, spark_width,
                                     spark_seconds)))
    half = (len(values) + 1) // 2
    for i in range(half):
        left = values[i]
        right = (values[i + half] if i + half < len(values)
                 else ("", "", ""))
        table.add_row(left[0], left[1], left[2],
                      right[0], right[1], right[2])
    span = service.store.span()
    table.caption = (f"{service.store.n} samples · {span[1] - span[0]:.1f}s · "
                     "Ctrl-C to quit")
    return table


def run(service, console=None, spark_seconds=60.0):
    console = console or Console()
    spark_width = max(8, min(30, (console.width - 76) // 2))
    try:
        with Live(dashboard(service, spark_width, spark_seconds),
                  console=console, refresh_per_second=4) as live:
            while True:
                started = time.monotonic()
                service.sample_once()
                live.update(dashboard(service, spark_width, spark_seconds))
                time.sleep(max(0.0, service.interval -
                               (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        service.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Terminal AMD telemetry")
    parser.add_argument("-i", "--interval", type=float, default=1.0)
    parser.add_argument("--socket", help="connect to amdgraphd")
    parser.add_argument("--spark-window", type=float, default=60.0,
                        metavar="SECONDS")
    args = parser.parse_args(argv)
    if args.socket:
        from .remote import RemoteHistoryService
        service = RemoteHistoryService(args.socket)
    else:
        service = LocalHistoryService(args.interval)
    return run(service, spark_seconds=max(1.0, args.spark_window))
