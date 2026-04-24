"""
core/models.py — Data models for lag events, snapshots, and process samples.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ProcessSample:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    status: str = "running"


@dataclass
class SystemSample:
    """A single 1-second snapshot of system state."""
    timestamp: datetime
    cpu_percent: float          # overall CPU %
    cpu_per_core: list[float]   # per-core %
    ram_percent: float          # RAM usage %
    ram_used_mb: float
    ram_total_mb: float
    swap_percent: float
    responsiveness_ms: float    # how long a simple OS op took (ms)
    top_processes: list[ProcessSample] = field(default_factory=list)


@dataclass
class LagScore:
    """Composite score for a single sample."""
    timestamp: datetime
    cpu_score: float        # 0–1
    ram_score: float        # 0–1
    responsiveness_score: float  # 0–1
    composite: float        # weighted average
    is_lag: bool = False


@dataclass
class LagEvent:
    """A confirmed lag event — persisted to SQLite."""
    id: Optional[int]
    started_at: datetime
    ended_at: Optional[datetime]
    peak_composite_score: float
    cause: str                  # human-readable explanation
    cause_code: str             # machine tag: CPU_SPIKE, RAM_EXHAUSTION, etc.
    duration_seconds: float = 0.0
    snapshot_id: Optional[int] = None


@dataclass
class LagSnapshot:
    """Full capture of system state around a lag event."""
    id: Optional[int]
    event_id: Optional[int]
    captured_at: datetime
    pre_lag_samples: list[SystemSample]  # 5s before
    peak_sample: SystemSample
    top_processes: list[ProcessSample]
    peak_cpu: float
    peak_ram: float
    peak_responsiveness_ms: float


@dataclass
class Baseline:
    """Learned normal behaviour for this machine."""
    cpu_mean: float = 10.0
    cpu_std: float = 5.0
    ram_mean: float = 40.0
    ram_std: float = 10.0
    responsiveness_mean_ms: float = 15.0
    responsiveness_std_ms: float = 5.0
    sample_count: int = 0
    is_ready: bool = False          # True after enough samples collected
