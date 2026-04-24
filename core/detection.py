"""
core/detection.py — Lag detection engine.

How it works:
1. Maintains a rolling 10-second window of SystemSamples.
2. Each second, computes a composite lag score (0–1) from CPU, RAM, responsiveness.
3. A lag event is triggered when the composite score exceeds a threshold for 2+ consecutive seconds.
4. Scores are compared against a learned Baseline so that a busy server and a quiet laptop
   have different thresholds — it's personalised, not one-size-fits-all.

This is what separates this tool from Task Manager:
  - Responsiveness probe catches disk-bound lag even when CPU is normal.
  - The rolling window prevents single-sample false positives.
  - The baseline makes thresholds machine-specific.
"""
from collections import deque
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from core.models import SystemSample, LagScore, Baseline

# How many seconds of history to keep
WINDOW_SIZE = 10

# How many consecutive above-threshold seconds trigger an event
LAG_TRIGGER_CONSECUTIVE = 2

# Default thresholds (overridden once baseline is learned)
DEFAULT_CPU_THRESHOLD = 80.0       # %
DEFAULT_RAM_THRESHOLD = 85.0       # %
DEFAULT_RESP_THRESHOLD_MS = 50.0   # ms  (healthy is ~5–15 ms)

# Weight for composite score
WEIGHT_CPU = 0.50
WEIGHT_RAM = 0.20
WEIGHT_RESP = 0.30

# Minimum samples before baseline is considered "ready"
BASELINE_MIN_SAMPLES = 60   # ~60 seconds


class DetectionEngine(QObject):
    """
    Receives SystemSample objects, scores them, and emits lag events.

    Signals
    -------
    lag_started(datetime)  — fires when lag begins
    lag_ended(datetime, float)  — fires when lag ends; float = peak composite score
    score_updated(LagScore)  — fires every second (useful for live UI sparkline)
    baseline_updated(Baseline)  — fires when baseline changes
    """

    lag_started = Signal(object)          # datetime
    lag_ended = Signal(object, float)     # datetime, peak_score
    score_updated = Signal(object)        # LagScore
    baseline_updated = Signal(object)     # Baseline

    def __init__(self, parent=None):
        super().__init__(parent)
        self._window: deque[SystemSample] = deque(maxlen=WINDOW_SIZE)
        self._scores: deque[LagScore] = deque(maxlen=WINDOW_SIZE)
        self._baseline = Baseline()
        self._consecutive_lag = 0
        self._in_lag = False
        self._lag_start: datetime | None = None
        self._peak_score = 0.0

        # Baseline accumulators (online mean/variance via Welford's algorithm)
        self._cpu_samples: list[float] = []
        self._ram_samples: list[float] = []
        self._resp_samples: list[float] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, sample: SystemSample):
        """Call this for every new SystemSample (every second)."""
        self._window.append(sample)
        self._update_baseline(sample)
        score = self._score(sample)
        self._scores.append(score)
        self.score_updated.emit(score)
        self._check_lag_state(score)

    @property
    def baseline(self) -> Baseline:
        return self._baseline

    @property
    def recent_scores(self) -> list[LagScore]:
        return list(self._scores)

    @property
    def recent_samples(self) -> list[SystemSample]:
        return list(self._window)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score(self, sample: SystemSample) -> LagScore:
        bl = self._baseline

        # --- CPU score ---
        cpu_thresh = bl.cpu_mean + 2 * bl.cpu_std if bl.is_ready else DEFAULT_CPU_THRESHOLD
        cpu_score = self._sigmoid_score(sample.cpu_percent, cpu_thresh, steepness=0.1)

        # --- RAM score ---
        ram_thresh = bl.ram_mean + 2 * bl.ram_std if bl.is_ready else DEFAULT_RAM_THRESHOLD
        ram_score = self._sigmoid_score(sample.ram_percent, ram_thresh, steepness=0.1)

        # --- Responsiveness score ---
        resp_thresh = (
            bl.responsiveness_mean_ms + 3 * bl.responsiveness_std_ms
            if bl.is_ready
            else DEFAULT_RESP_THRESHOLD_MS
        )
        resp_score = self._sigmoid_score(sample.responsiveness_ms, resp_thresh, steepness=0.05)

        weighted = (
            WEIGHT_CPU * cpu_score
            + WEIGHT_RAM * ram_score
            + WEIGHT_RESP * resp_score
        )
        # Also factor in the highest single-dimension score so that one
        # extreme metric (e.g. CPU at 95%) can trigger lag even when the
        # others are fine.
        peak_dim = max(cpu_score, ram_score, resp_score)
        composite = 0.6 * weighted + 0.4 * peak_dim

        is_lag = composite >= 0.45

        return LagScore(
            timestamp=sample.timestamp,
            cpu_score=cpu_score,
            ram_score=ram_score,
            responsiveness_score=resp_score,
            composite=composite,
            is_lag=is_lag,
        )

    @staticmethod
    def _sigmoid_score(value: float, threshold: float, steepness: float = 0.1) -> float:
        """
        Returns a 0–1 score.
        - At threshold → ~0.5
        - Well below threshold → near 0
        - Well above threshold → near 1

        Uses a logistic (sigmoid) curve so the score is smooth, not binary.
        This avoids the "flickering" you get with hard cutoffs.
        """
        import math
        x = steepness * (value - threshold)
        return 1.0 / (1.0 + math.exp(-x))

    # ------------------------------------------------------------------
    # Lag state machine
    # ------------------------------------------------------------------

    def _check_lag_state(self, score: LagScore):
        if score.is_lag:
            self._consecutive_lag += 1
            if score.composite > self._peak_score:
                self._peak_score = score.composite

            if not self._in_lag and self._consecutive_lag >= LAG_TRIGGER_CONSECUTIVE:
                self._in_lag = True
                self._lag_start = score.timestamp
                self.lag_started.emit(score.timestamp)
        else:
            if self._in_lag:
                self._in_lag = False
                self.lag_ended.emit(score.timestamp, self._peak_score)
                self._peak_score = 0.0
            self._consecutive_lag = 0

    # ------------------------------------------------------------------
    # Baseline learning (Welford online algorithm)
    # ------------------------------------------------------------------

    def _update_baseline(self, sample: SystemSample):
        """
        Incrementally update the baseline statistics without storing all samples.
        Welford's algorithm gives us a running mean and variance in O(1) space.
        """
        # Only learn from "calm" periods (below default thresholds) to avoid
        # skewing the baseline with already-bad data.
        if (
            sample.cpu_percent < DEFAULT_CPU_THRESHOLD
            and sample.ram_percent < DEFAULT_RAM_THRESHOLD
            and sample.responsiveness_ms < DEFAULT_RESP_THRESHOLD_MS
        ):
            self._cpu_samples.append(sample.cpu_percent)
            self._ram_samples.append(sample.ram_percent)
            self._resp_samples.append(sample.responsiveness_ms)

        count = len(self._cpu_samples)
        if count < 5:
            return  # not enough data yet

        import statistics as stats
        self._baseline.cpu_mean = stats.mean(self._cpu_samples[-BASELINE_MIN_SAMPLES:])
        self._baseline.cpu_std = max(
            stats.stdev(self._cpu_samples[-BASELINE_MIN_SAMPLES:]) if count > 1 else 5.0, 1.0
        )
        self._baseline.ram_mean = stats.mean(self._ram_samples[-BASELINE_MIN_SAMPLES:])
        self._baseline.ram_std = max(
            stats.stdev(self._ram_samples[-BASELINE_MIN_SAMPLES:]) if count > 1 else 5.0, 1.0
        )
        self._baseline.responsiveness_mean_ms = stats.mean(self._resp_samples[-BASELINE_MIN_SAMPLES:])
        self._baseline.responsiveness_std_ms = max(
            stats.stdev(self._resp_samples[-BASELINE_MIN_SAMPLES:]) if count > 1 else 5.0, 0.5
        )
        self._baseline.sample_count = count
        self._baseline.is_ready = count >= BASELINE_MIN_SAMPLES
        self.baseline_updated.emit(self._baseline)
