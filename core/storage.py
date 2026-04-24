"""
core/storage.py — SQLite persistence via SQLAlchemy.

Tables:
  lag_events     — one row per confirmed lag event
  lag_snapshots  — one row per snapshot (linked to an event)
  process_logs   — top processes at peak of each event

No external server needed; the .db file lives in the data/ folder.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (
    Column, Integer, Float, String, DateTime, Text, ForeignKey,
    create_engine, select
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship

from core.models import LagEvent, LagSnapshot

# ---------------------------------------------------------------------------
# Database path
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent.parent / "data" / "lag_history.db"


def _ensure_data_dir():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class LagEventRow(Base):
    __tablename__ = "lag_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    peak_composite_score = Column(Float, default=0.0)
    cause = Column(Text, default="")
    cause_code = Column(String(64), default="UNKNOWN")
    duration_seconds = Column(Float, default=0.0)

    snapshots = relationship("LagSnapshotRow", back_populates="event", cascade="all, delete-orphan")


class LagSnapshotRow(Base):
    __tablename__ = "lag_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("lag_events.id"), nullable=True)
    captured_at = Column(DateTime, nullable=False)
    peak_cpu = Column(Float, default=0.0)
    peak_ram = Column(Float, default=0.0)
    peak_responsiveness_ms = Column(Float, default=0.0)
    top_processes_json = Column(Text, default="[]")    # JSON list of {name, pid, cpu, mem}
    pre_lag_summary_json = Column(Text, default="[]")  # JSON list of {ts, cpu, ram, resp}

    event = relationship("LagEventRow", back_populates="snapshots")


# ---------------------------------------------------------------------------
# Storage class
# ---------------------------------------------------------------------------

class Storage:

    def __init__(self, db_path: Path = DB_PATH):
        _ensure_data_dir()
        self._engine = create_engine(f"sqlite:///{db_path}", echo=False)
        Base.metadata.create_all(self._engine)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def save_event(self, event: LagEvent) -> int:
        """Inserts or updates a LagEvent. Returns the row id."""
        with Session(self._engine) as session:
            if event.id:
                row = session.get(LagEventRow, event.id)
                if row is None:
                    row = LagEventRow()
                    session.add(row)
            else:
                row = LagEventRow()
                session.add(row)

            row.started_at = event.started_at
            row.ended_at = event.ended_at
            row.peak_composite_score = event.peak_composite_score
            row.cause = event.cause
            row.cause_code = event.cause_code
            row.duration_seconds = event.duration_seconds

            session.commit()
            session.refresh(row)
            return row.id

    def save_snapshot(self, snapshot: LagSnapshot) -> int:
        """Persists a LagSnapshot. Returns row id."""
        with Session(self._engine) as session:
            procs_json = json.dumps([
                {
                    "name": p.name,
                    "pid": p.pid,
                    "cpu_percent": round(p.cpu_percent, 1),
                    "memory_mb": round(p.memory_mb, 1),
                }
                for p in snapshot.top_processes
            ])

            pre_json = json.dumps([
                {
                    "ts": s.timestamp.isoformat(),
                    "cpu": round(s.cpu_percent, 1),
                    "ram": round(s.ram_percent, 1),
                    "resp": round(s.responsiveness_ms, 1),
                }
                for s in snapshot.pre_lag_samples
            ])

            row = LagSnapshotRow(
                event_id=snapshot.event_id,
                captured_at=snapshot.captured_at,
                peak_cpu=snapshot.peak_cpu,
                peak_ram=snapshot.peak_ram,
                peak_responsiveness_ms=snapshot.peak_responsiveness_ms,
                top_processes_json=procs_json,
                pre_lag_summary_json=pre_json,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_recent_events(self, limit: int = 100) -> list[LagEvent]:
        with Session(self._engine) as session:
            stmt = (
                select(LagEventRow)
                .order_by(LagEventRow.started_at.desc())
                .limit(limit)
            )
            rows = session.scalars(stmt).all()
            return [self._row_to_event(r) for r in rows]

    def get_snapshot_for_event(self, event_id: int) -> LagSnapshot | None:
        with Session(self._engine) as session:
            stmt = (
                select(LagSnapshotRow)
                .where(LagSnapshotRow.event_id == event_id)
                .order_by(LagSnapshotRow.captured_at.desc())
                .limit(1)
            )
            row = session.scalars(stmt).first()
            if row is None:
                return None
            return self._row_to_snapshot(row)

    def event_count(self) -> int:
        with Session(self._engine) as session:
            from sqlalchemy import func
            return session.scalar(select(func.count()).select_from(LagEventRow)) or 0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_event(row: LagEventRow) -> LagEvent:
        return LagEvent(
            id=row.id,
            started_at=row.started_at,
            ended_at=row.ended_at,
            peak_composite_score=row.peak_composite_score,
            cause=row.cause,
            cause_code=row.cause_code,
            duration_seconds=row.duration_seconds,
        )

    @staticmethod
    def _row_to_snapshot(row: LagSnapshotRow) -> LagSnapshot:
        from core.models import ProcessSample, SystemSample
        procs = [
            ProcessSample(
                pid=p["pid"],
                name=p["name"],
                cpu_percent=p["cpu_percent"],
                memory_mb=p["memory_mb"],
            )
            for p in json.loads(row.top_processes_json)
        ]
        # Reconstruct minimal SystemSamples for the timeline chart
        pre_samples = []
        for s in json.loads(row.pre_lag_summary_json):
            pre_samples.append(SystemSample(
                timestamp=datetime.fromisoformat(s["ts"]),
                cpu_percent=s["cpu"],
                cpu_per_core=[],
                ram_percent=s["ram"],
                ram_used_mb=0,
                ram_total_mb=0,
                swap_percent=0,
                responsiveness_ms=s["resp"],
                top_processes=[],
            ))

        return LagSnapshot(
            id=row.id,
            event_id=row.event_id,
            captured_at=row.captured_at,
            pre_lag_samples=pre_samples,
            peak_sample=pre_samples[-1] if pre_samples else SystemSample(
                timestamp=row.captured_at,
                cpu_percent=row.peak_cpu,
                cpu_per_core=[],
                ram_percent=row.peak_ram,
                ram_used_mb=0,
                ram_total_mb=0,
                swap_percent=0,
                responsiveness_ms=row.peak_responsiveness_ms,
                top_processes=procs,
            ),
            top_processes=procs,
            peak_cpu=row.peak_cpu,
            peak_ram=row.peak_ram,
            peak_responsiveness_ms=row.peak_responsiveness_ms,
        )
