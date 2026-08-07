"""Layer 6 -- Rich terminal frontend for a history service."""

import argparse
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


def dashboard(service):
    table = Table(title="amdgraph", expand=True)
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("value", justify="right")
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("value", justify="right")
    values = []
    for key in PREFERRED:
        value = service.store.latest(key)
        if value is not None:
            values.append((key, f"{value:.2f}"))
    half = (len(values) + 1) // 2
    for i in range(half):
        left = values[i]
        right = values[i + half] if i + half < len(values) else ("", "")
        table.add_row(left[0], left[1], right[0], right[1])
    span = service.store.span()
    table.caption = (f"{service.store.n} samples · {span[1] - span[0]:.1f}s · "
                     "Ctrl-C to quit")
    return table


def run(service, console=None):
    console = console or Console()
    try:
        with Live(dashboard(service), console=console, refresh_per_second=4) as live:
            while True:
                started = time.monotonic()
                service.sample_once()
                live.update(dashboard(service))
                time.sleep(max(0.0, service.interval -
                               (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        service.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Terminal AMD telemetry")
    parser.add_argument("-i", "--interval", type=float, default=1.0)
    args = parser.parse_args(argv)
    return run(LocalHistoryService(args.interval))
