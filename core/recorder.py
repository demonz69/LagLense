"""
core/recorder.py — Snapshot recorder.

Maintains a rolling buffer of recent SystemSamples so that when a lag event
fires, we can look BACKWARD (pre-lag context) as well as capture the peak.

This is the key differentiator from Task Manager — we capture what led up
to the lag, not just what's happening at the moment of pain.
"""
from collections import deque
from datetime import datetime

from core.models import SystemSample, LagSnapshot, LagEvent
from core.analyzer import CauseAnalyzer

# How many seconds of pre-lag history to keep
PRE_LAG_BUFFER_SECONDS = 5


class SnapshotRecorder:
    """
    Usage:
        recorder = SnapshotRecorder()
        # Feed it samples every second:
        recorder.record_sample(sample)
        # When a lag event occurs, capture a snapshot:
        snapshot = recorder.capture(lag_event)
    """

    def __init__(self, pre_lag_seconds: int = PRE_LAG_BUFFER_SECONDS):
        self._buffer: deque[SystemSample] = deque(maxlen=pre_lag_seconds)
        self._analyzer = CauseAnalyzer()
        self._peak_sample: SystemSample | None = None
        self._peak_composite: float = 0.0

    def record_sample(self, sample: SystemSample, composite_score: float = 0.0):
        """Call every second to keep the rolling buffer fresh."""
        self._buffer.append(sample)
        if composite_score > self._peak_composite:
            self._peak_composite = composite_score
            self._peak_sample = sample

    def capture(self, event: LagEvent) -> LagSnapshot:
        """
        Called when a lag event ends.
        Returns a fully-populated LagSnapshot including pre-lag context.
        """
        pre_samples = list(self._buffer)
        peak = self._peak_sample or (pre_samples[-1] if pre_samples else None)

        if peak is None:
            # Shouldn't happen in practice, but guard defensively
            from datetime import datetime
            from core.models import ProcessSample
            peak = SystemSample(
                timestamp=datetime.now(),
                cpu_percent=0, cpu_per_core=[], ram_percent=0,
                ram_used_mb=0, ram_total_mb=0, swap_percent=0,
                responsiveness_ms=0, top_processes=[],
            )

        snapshot = LagSnapshot(
            id=None,
            event_id=event.id,
            captured_at=datetime.now(),
            pre_lag_samples=pre_samples,
            peak_sample=peak,
            top_processes=peak.top_processes,
            peak_cpu=peak.cpu_percent,
            peak_ram=peak.ram_percent,
            peak_responsiveness_ms=peak.responsiveness_ms,
        )
        self._reset_peak()
        return snapshot

    def _reset_peak(self):
        self._peak_sample = None
        self._peak_composite = 0.0
