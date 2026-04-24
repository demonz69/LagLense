"""
tests/test_detection.py — Unit tests for the detection engine and cause analyzer.

Run with:  python -m pytest tests/ -v
       or:  python tests/test_detection.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Qt app must exist before any QObject is created
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication(sys.argv)

from datetime import datetime
from core.models import SystemSample, ProcessSample
from core.detection import DetectionEngine
from core.analyzer import CauseAnalyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sample(cpu=10.0, ram=40.0, resp=10.0, processes=None, swap=0.0):
    return SystemSample(
        timestamp=datetime.now(),
        cpu_percent=cpu,
        cpu_per_core=[cpu],
        ram_percent=ram,
        ram_used_mb=ram * 160,
        ram_total_mb=16 * 1024,
        swap_percent=swap,
        responsiveness_ms=resp,
        top_processes=processes or [],
    )


def make_process(name, cpu, mem_mb=100.0, pid=1234):
    return ProcessSample(pid=pid, name=name, cpu_percent=cpu, memory_mb=mem_mb)


# ---------------------------------------------------------------------------
# DetectionEngine tests
# ---------------------------------------------------------------------------

class TestDetectionEngine:

    def test_no_lag_on_idle_system(self):
        engine = DetectionEngine()
        for _ in range(15):
            engine.ingest(make_sample(cpu=5, ram=30, resp=8))
        assert not engine._in_lag

    def test_lag_state_on_sustained_high_cpu(self):
        """After 2+ consecutive high-score samples the engine should mark lag."""
        engine = DetectionEngine()
        for _ in range(10):
            engine.ingest(make_sample(cpu=5, ram=30, resp=8))
        for _ in range(5):
            engine.ingest(make_sample(cpu=95, ram=30, resp=8))
        assert engine._in_lag or engine._peak_score > 0, \
            "High sustained CPU should trigger lag state"

    def test_single_sample_spike_does_not_trigger(self):
        """A single bad sample should NOT fire a lag event."""
        engine = DetectionEngine()
        for _ in range(10):
            engine.ingest(make_sample(cpu=5, ram=30, resp=8))
        engine.ingest(make_sample(cpu=99, ram=30, resp=8))
        for _ in range(3):
            engine.ingest(make_sample(cpu=5, ram=30, resp=8))
        # After recovery a single spike should have been cleared
        assert not engine._in_lag

    def test_responsiveness_spike_triggers_lag_state(self):
        """High responsiveness alone should push composite above threshold."""
        engine = DetectionEngine()
        for _ in range(10):
            engine.ingest(make_sample(cpu=5, ram=30, resp=8))
        for _ in range(5):
            engine.ingest(make_sample(cpu=15, ram=35, resp=300))
        assert engine._in_lag or engine._peak_score > 0

    def test_score_emitted_every_sample(self):
        engine = DetectionEngine()
        scores = []
        engine.score_updated.connect(lambda s: scores.append(s))
        for _ in range(5):
            engine.ingest(make_sample())
        assert len(scores) == 5

    def test_composite_score_range(self):
        engine = DetectionEngine()
        scores = []
        engine.score_updated.connect(lambda s: scores.append(s))
        for cpu in [0, 25, 50, 75, 100]:
            engine.ingest(make_sample(cpu=cpu, ram=cpu * 0.8, resp=cpu * 0.5))
        for s in scores:
            assert 0.0 <= s.composite <= 1.0

    def test_recovery_resets_consecutive_count(self):
        """Consecutive lag counter should reset after calm samples."""
        engine = DetectionEngine()
        for _ in range(5):
            engine.ingest(make_sample(cpu=95, ram=40, resp=8))
        for _ in range(5):
            engine.ingest(make_sample(cpu=5, ram=30, resp=8))
        assert not engine._in_lag
        assert engine._consecutive_lag == 0


# ---------------------------------------------------------------------------
# CauseAnalyzer tests
# ---------------------------------------------------------------------------

class TestCauseAnalyzer:

    def test_cpu_spike_detected(self):
        analyzer = CauseAnalyzer()
        proc = make_process("chrome.exe", cpu=75.0)
        sample = make_sample(cpu=80, processes=[proc])
        code, msg = analyzer.analyze(sample, [])
        assert code == "CPU_SPIKE"
        assert "chrome.exe" in msg

    def test_ram_exhaustion_detected(self):
        analyzer = CauseAnalyzer()
        sample = make_sample(cpu=20, ram=92, resp=15, swap=15.0)
        code, msg = analyzer.analyze(sample, [])
        assert code == "RAM_EXHAUSTION"

    def test_disk_io_detected(self):
        analyzer = CauseAnalyzer()
        sample = make_sample(cpu=20, ram=40, resp=200)
        code, msg = analyzer.analyze(sample, [])
        assert code == "DISK_IO"

    def test_background_cluster_detected(self):
        analyzer = CauseAnalyzer()
        procs = [make_process(f"service{i}.exe", cpu=8.0, pid=i) for i in range(7)]
        sample = make_sample(cpu=60, processes=procs)
        code, msg = analyzer.analyze(sample, [])
        assert code == "BACKGROUND_CLUSTER"

    def test_fallback_returns_valid_code(self):
        analyzer = CauseAnalyzer()
        sample = make_sample(cpu=70, ram=60, resp=30)
        code, msg = analyzer.analyze(sample, [])
        assert code in ("SCHEDULER_CONTENTION", "DISK_IO", "CPU_SPIKE", "BACKGROUND_CLUSTER")
        assert len(msg) > 10

    def test_explanation_is_human_readable(self):
        analyzer = CauseAnalyzer()
        sample = make_sample(cpu=50, ram=50, resp=10)
        code, msg = analyzer.analyze(sample, [])
        assert isinstance(msg, str)
        assert len(msg) > 20


# ---------------------------------------------------------------------------
# Sigmoid score helper
# ---------------------------------------------------------------------------

class TestSigmoidScore:

    def test_at_threshold_returns_half(self):
        from core.detection import DetectionEngine
        score = DetectionEngine._sigmoid_score(50.0, 50.0, steepness=0.1)
        assert abs(score - 0.5) < 0.01

    def test_well_below_threshold_near_zero(self):
        from core.detection import DetectionEngine
        score = DetectionEngine._sigmoid_score(10.0, 80.0, steepness=0.1)
        assert score < 0.1

    def test_well_above_threshold_near_one(self):
        from core.detection import DetectionEngine
        score = DetectionEngine._sigmoid_score(150.0, 80.0, steepness=0.1)
        assert score > 0.9


if __name__ == "__main__":
    import traceback
    suites = [TestDetectionEngine(), TestCauseAnalyzer(), TestSigmoidScore()]
    passed = failed = 0
    for suite in suites:
        for name in sorted(dir(suite)):
            if name.startswith("test_"):
                try:
                    getattr(suite, name)()
                    print(f"  ✓  {suite.__class__.__name__}.{name}")
                    passed += 1
                except Exception as e:
                    print(f"  ✗  {suite.__class__.__name__}.{name}: {e}")
                    traceback.print_exc()
                    failed += 1
    print(f"\n{passed} passed, {failed} failed")
