"""
core/analyzer.py — Rules engine that turns raw lag data into human-readable explanations.

Rule priority (first match wins):
  1. Single process >60% CPU          → CPU_SPIKE
  2. RAM >90% + swap active           → RAM_EXHAUSTION
  3. Many small processes (cluster)   → BACKGROUND_CLUSTER
  4. Responsiveness delay, CPU normal → DISK_IO (disk I/O bottleneck)
  5. Fallback                         → SCHEDULER_CONTENTION

Each rule returns a (cause_code, explanation) tuple.
Adding new rules is easy — just add a method prefixed with _rule_ and
register it in RULE_PRIORITY.  The engine tries them in order.
"""
from core.models import SystemSample, ProcessSample

# Thresholds used by rules
SINGLE_PROC_CPU_THRESHOLD = 40.0    # % — a single process eating this much is suspicious
RAM_EXHAUSTION_THRESHOLD = 88.0     # % RAM used
SWAP_ACTIVE_THRESHOLD = 5.0         # % swap used
BACKGROUND_CLUSTER_COUNT = 5        # number of processes each contributing ≥5% CPU
CPU_NORMAL_FOR_DISK = 55.0          # if CPU below this but lag detected → disk
RESP_HIGH_THRESHOLD_MS = 40.0       # ms — above this is "high responsiveness delay"


class CauseAnalyzer:

    def analyze(self, peak_sample: SystemSample, pre_lag_samples: list[SystemSample]) -> tuple[str, str]:
        """
        Returns (cause_code, human_readable_explanation).

        peak_sample     — the SystemSample at peak lag
        pre_lag_samples — the 5 samples leading up to the lag event
        """
        for rule_fn in self._rules():
            result = rule_fn(peak_sample, pre_lag_samples)
            if result:
                return result

        return "UNKNOWN", "No clear cause identified. System may be under general stress."

    # ------------------------------------------------------------------
    # Rules (tried in order — first match wins)
    # ------------------------------------------------------------------

    def _rules(self):
        return [
            self._rule_single_cpu_spike,
            self._rule_ram_exhaustion,
            self._rule_background_cluster,
            self._rule_disk_io,
            self._rule_scheduler_contention,
        ]

    def _rule_single_cpu_spike(
        self, sample: SystemSample, _pre: list[SystemSample]
    ) -> tuple[str, str] | None:
        """One process is hogging the CPU."""
        if not sample.top_processes:
            return None
        top = sample.top_processes[0]
        if top.cpu_percent >= SINGLE_PROC_CPU_THRESHOLD:
            pct = round(top.cpu_percent, 1)
            return (
                "CPU_SPIKE",
                f'"{top.name}" (PID {top.pid}) was consuming {pct}% CPU, '
                f"causing the system to become unresponsive. "
                f"Try closing or restarting this application.",
            )
        return None

    def _rule_ram_exhaustion(
        self, sample: SystemSample, _pre: list[SystemSample]
    ) -> tuple[str, str] | None:
        """RAM is nearly full and the OS is paging to disk."""
        if sample.ram_percent >= RAM_EXHAUSTION_THRESHOLD and sample.swap_percent >= SWAP_ACTIVE_THRESHOLD:
            used_gb = round(sample.ram_used_mb / 1024, 1)
            total_gb = round(sample.ram_total_mb / 1024, 1)
            swap = round(sample.swap_percent, 1)
            return (
                "RAM_EXHAUSTION",
                f"System RAM is critically full ({used_gb} GB / {total_gb} GB used, "
                f"{swap}% swap active). The OS is writing memory to disk (paging), "
                f"which is much slower than RAM. Close unused applications or browser tabs.",
            )
        if sample.ram_percent >= RAM_EXHAUSTION_THRESHOLD:
            used_gb = round(sample.ram_used_mb / 1024, 1)
            total_gb = round(sample.ram_total_mb / 1024, 1)
            return (
                "RAM_PRESSURE",
                f"RAM usage is very high ({used_gb} GB / {total_gb} GB). "
                f"The system is running out of memory headroom. "
                f"Close unused applications to free memory.",
            )
        return None

    def _rule_background_cluster(
        self, sample: SystemSample, _pre: list[SystemSample]
    ) -> tuple[str, str] | None:
        """Many small background processes adding up to a lot of CPU."""
        contributors = [p for p in sample.top_processes if p.cpu_percent >= 5.0]
        if len(contributors) >= BACKGROUND_CLUSTER_COUNT:
            names = ", ".join(f'"{p.name}"' for p in contributors[:5])
            total = round(sum(p.cpu_percent for p in contributors), 1)
            return (
                "BACKGROUND_CLUSTER",
                f"{len(contributors)} background processes ({names}) are each consuming CPU, "
                f"totalling ~{total}% combined. No single villain, but the crowd is the problem. "
                f"Consider disabling startup applications.",
            )
        return None

    def _rule_disk_io(
        self, sample: SystemSample, _pre: list[SystemSample]
    ) -> tuple[str, str] | None:
        """High responsiveness delay but CPU is normal → likely disk I/O bottleneck."""
        if (
            sample.responsiveness_ms >= RESP_HIGH_THRESHOLD_MS
            and sample.cpu_percent < CPU_NORMAL_FOR_DISK
        ):
            resp = round(sample.responsiveness_ms, 1)
            return (
                "DISK_IO",
                f"CPU usage was normal ({round(sample.cpu_percent, 1)}%) but system responsiveness "
                f"was severely degraded ({resp} ms delay). This typically means a disk I/O bottleneck — "
                f"something is reading/writing heavily to storage (antivirus scan, updates, backup, "
                f"or a failing drive).",
            )
        return None

    def _rule_scheduler_contention(
        self, sample: SystemSample, _pre: list[SystemSample]
    ) -> tuple[str, str] | None:
        """Fallback — general system stress, no single root cause."""
        resp = round(sample.responsiveness_ms, 1)
        cpu = round(sample.cpu_percent, 1)
        return (
            "SCHEDULER_CONTENTION",
            f"System was under general stress (CPU: {cpu}%, responsiveness: {resp} ms) "
            f"but no single clear cause was identified. This may be OS scheduler contention — "
            f"many processes competing for CPU time simultaneously.",
        )

    # ------------------------------------------------------------------
    # Pre-lag trend helpers (used for richer explanations in future phases)
    # ------------------------------------------------------------------

    @staticmethod
    def pre_lag_trend(pre_samples: list[SystemSample], attribute: str) -> str:
        """Returns 'rising', 'falling', or 'stable' for a given attribute over pre-lag samples."""
        if len(pre_samples) < 2:
            return "stable"
        values = [getattr(s, attribute) for s in pre_samples]
        delta = values[-1] - values[0]
        if delta > 10:
            return "rising"
        if delta < -10:
            return "falling"
        return "stable"
