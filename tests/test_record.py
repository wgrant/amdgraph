"""amdgraph-record drives a real Sampler through RecordingFS.

The point of the tool is fidelity: whatever a live Sampler read while being
captured has to come back out of ReplayFS bit-for-bit, against a synthetic
tree here so the assertion holds with no AMD part in it.
"""

from amdgraph import sampler
from amdgraph.sampler import Sampler
from amdgraph.sysfs import RealFS, RecordingFS, ReplayFS


def test_replay_reproduces_a_live_capture(tmp_path, monkeypatch, record):
    """Build a tiny synthetic pm_table tree, capture a few ticks of the real
    Sampler reading it, then confirm a fresh Sampler backed by the saved
    cassette reports exactly the same samples, tick for tick."""
    smu = tmp_path / "ryzen_smu_drv"
    smu.mkdir()
    (smu / "pm_table_version").write_bytes((0x004C0009).to_bytes(4, "little"))
    (smu / "pm_table").write_bytes(b"\x00\x00\xf0\x41" * 704)   # all 30.0s

    monkeypatch.setattr(sampler, "PM_VERSION", str(smu / "pm_table_version"))
    monkeypatch.setattr(sampler, "PM_TABLE", str(smu / "pm_table"))

    fs = RecordingFS(RealFS())
    live, live_samples = record.capture(fs, n=3, interval=0.0)
    try:
        assert live.pm_ok
        assert live_samples[0]["stapm"] == 30.0

        out = tmp_path / "capture.json"
        fs.save(str(out))

        replayed = Sampler(fs=ReplayFS.load(str(out)))
        replayed_samples = [replayed.sample() for _ in range(3)]
        assert replayed.pm_ok

        for want, got in zip(live_samples, replayed_samples):
            assert got.get("stapm") == want.get("stapm")
    finally:
        live.close()
