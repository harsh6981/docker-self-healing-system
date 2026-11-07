"""Self-healing decision logic.

This module is pure Python (no Docker import) so it can be unit-tested without
Docker. The monitor feeds it one observation per container per poll via
``RecoveryManager.observe`` and the manager decides what to do:

* ``ok``           container is running and healthy
* ``wait``         nothing to do yet (starting, or waiting for threshold/grace)
* ``restart``      container was unhealthy  -> restart issued
* ``start``        container was stopped    -> start issued
* ``cooldown``     recovery needed but a recent attempt is still being given time
* ``circuit_open`` too many recovery attempts -> auto-recovery paused (loop guard)
* ``failed``       the Docker action itself failed

Restart-loop protection (circuit breaker)
-----------------------------------------
* Cooldown: at least COOLDOWN_SECONDS between two recovery attempts.
* Budget  : at most MAX_RESTARTS attempts inside a WINDOW_SECONDS window.
  When the budget is exhausted the circuit "opens" and the monitor stops
  touching the container until it becomes healthy on its own, an operator
  presses "Reset" on the dashboard, or CIRCUIT_RESET_SECONDS have passed.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field, fields
from typing import Callable, Deque, Dict, Iterable, List, Optional

MAX_ACCOUNTING_GAP = 60.0   # seconds; larger gaps (monitor was down) are ignored
TIMELINE_LENGTH = 60        # polls kept for the dashboard health strip


@dataclass
class Policy:
    unhealthy_polls: int = 2          # consecutive "unhealthy" polls before restarting
    cooldown_seconds: float = 20.0    # minimum gap between two recovery attempts
    max_restarts: int = 3             # attempts allowed inside the window
    window_seconds: float = 120.0     # sliding window for max_restarts
    stopped_grace_seconds: float = 10.0   # give Docker's restart policy time first
    circuit_reset_seconds: float = 300.0  # auto-close an open circuit after this long

    @classmethod
    def from_env(cls) -> "Policy":
        return cls(
            unhealthy_polls=int(os.getenv("UNHEALTHY_POLLS", cls.unhealthy_polls)),
            cooldown_seconds=float(os.getenv("COOLDOWN_SECONDS", cls.cooldown_seconds)),
            max_restarts=int(os.getenv("MAX_RESTARTS", cls.max_restarts)),
            window_seconds=float(os.getenv("WINDOW_SECONDS", cls.window_seconds)),
            stopped_grace_seconds=float(os.getenv("STOPPED_GRACE_SECONDS", cls.stopped_grace_seconds)),
            circuit_reset_seconds=float(os.getenv("CIRCUIT_RESET_SECONDS", cls.circuit_reset_seconds)),
        )


@dataclass
class ContainerRecord:
    """Statistics persisted to logs/state.json."""
    name: str
    state: str = "unknown"      # healthy|starting|unhealthy|stopped|recovering|circuit_open|missing
    status: str = "unknown"     # raw Docker state: running, exited, restarting ...
    health: str = "none"        # raw Docker health: healthy, unhealthy, starting, none
    failures: int = 0
    monitor_restarts: int = 0   # restarts/starts performed by *our* recovery logic
    docker_restarts: int = 0    # restarts performed by Docker's restart policy
    recoveries: int = 0
    last_failure_time: Optional[float] = None
    last_failure_reason: str = ""
    last_recovery_time: Optional[float] = None
    last_recovery_duration: Optional[float] = None
    total_recovery_seconds: float = 0.0
    monitored_seconds: float = 0.0
    up_seconds: float = 0.0


@dataclass
class _Runtime:
    """Per-container working data that does not need to survive a monitor restart."""
    last_poll: Optional[float] = None
    last_up: bool = False
    failing_since: Optional[float] = None
    bad_polls: int = 0
    docker_count: Optional[int] = None
    last_action: Optional[float] = None
    circuit_opened_at: Optional[float] = None
    history: Deque[float] = field(default_factory=deque)
    timeline: Deque[str] = field(default_factory=lambda: deque(maxlen=TIMELINE_LENGTH))


ActionFn = Callable[[str, str], bool]
EventFn = Callable[[str, str, str, str], None]


class RecoveryManager:
    def __init__(self, action_fn: ActionFn, policy: Optional[Policy] = None,
                 event_fn: Optional[EventFn] = None, clock: Callable[[], float] = time.time):
        self.action_fn = action_fn
        self.policy = policy or Policy()
        self.event_fn = event_fn or (lambda level, name, kind, message: None)
        self.clock = clock
        self.records: Dict[str, ContainerRecord] = {}
        self._rt: Dict[str, _Runtime] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ helpers
    def _record(self, name: str) -> ContainerRecord:
        if name not in self.records:
            self.records[name] = ContainerRecord(name=name)
        return self.records[name]

    def _runtime(self, name: str) -> _Runtime:
        if name not in self._rt:
            self._rt[name] = _Runtime()
        return self._rt[name]

    def _event(self, level: str, name: str, kind: str, message: str) -> None:
        self.event_fn(level, name, kind, message)

    def known_names(self) -> List[str]:
        with self._lock:
            return sorted(self.records)

    # ------------------------------------------------------------- persistence
    def to_state(self) -> dict:
        with self._lock:
            return {"saved_at": self.clock(),
                    "containers": {n: asdict(r) for n, r in self.records.items()}}

    def load(self, data: Optional[dict]) -> None:
        if not data:
            return
        allowed = {f.name for f in fields(ContainerRecord)}
        with self._lock:
            for name, raw in (data.get("containers") or {}).items():
                clean = {k: v for k, v in raw.items() if k in allowed and k != "name"}
                self.records[name] = ContainerRecord(name=name, **clean)

    # ----------------------------------------------------------------- observe
    def observe(self, name: str, status: str, health: str = "none",
                docker_restart_count: int = 0, exit_code: Optional[int] = None) -> str:
        """Feed one observation and return the action taken."""
        with self._lock:
            now = self.clock()
            rec, rt = self._record(name), self._runtime(name)

            # --- uptime accounting: attribute the elapsed interval to the previous state
            if rt.last_poll is not None:
                gap = min(now - rt.last_poll, MAX_ACCOUNTING_GAP)
                rec.monitored_seconds += gap
                if rt.last_up:
                    rec.up_seconds += gap
            rt.last_poll = now
            rec.status, rec.health = status, health
            up = status == "running" and health in ("healthy", "none")
            rt.last_up = up

            # --- detect restarts performed by Docker's restart policy
            if rt.docker_count is None or docker_restart_count < rt.docker_count:
                rt.docker_count = docker_restart_count          # baseline / container re-created
            elif docker_restart_count > rt.docker_count:
                n = docker_restart_count - rt.docker_count
                rt.docker_count = docker_restart_count
                rec.docker_restarts += n
                self._event("INFO", name, "DOCKER_RESTART",
                            f"Docker restart policy restarted the container "
                            f"(RestartCount={docker_restart_count})")
                if rt.failing_since is None:   # crash was so quick we never saw 'exited'
                    reason = "process crashed" + (f" (exit code {exit_code})" if exit_code not in (None, 0) else "")
                    self._begin_failure(rec, rt, now, name, reason + "; restarted by Docker")

            # --- healthy
            if up:
                if rt.failing_since is not None:
                    self._complete_recovery(rec, rt, now, name)
                rt.circuit_opened_at = None
                rt.bad_polls = 0
                return self._finish(rec, rt, "healthy", "ok")

            # --- still starting up
            if status == "running" and health == "starting":
                state = "recovering" if rt.failing_since is not None else "starting"
                return self._finish(rec, rt, state, "wait")

            # --- running but unhealthy
            if status == "running" and health == "unhealthy":
                rt.bad_polls += 1
                if rt.failing_since is None:
                    self._begin_failure(rec, rt, now, name, "health check reports unhealthy")
                if rt.bad_polls < self.policy.unhealthy_polls:
                    return self._finish(rec, rt, "unhealthy", "wait")
                action = self._recover(rec, rt, now, name, "restart")
                state = "recovering" if action in ("restart", "cooldown") else "unhealthy"
                return self._finish(rec, rt, state, action)

            # --- stopped
            if status in ("exited", "dead"):
                rt.bad_polls += 1
                if rt.failing_since is None:
                    code = f" (exit code {exit_code})" if exit_code is not None else ""
                    self._begin_failure(rec, rt, now, name, f"container stopped{code}")
                if now - rt.failing_since < self.policy.stopped_grace_seconds:
                    return self._finish(rec, rt, "stopped", "wait")
                action = self._recover(rec, rt, now, name, "start")
                state = "recovering" if action in ("start", "cooldown") else "stopped"
                return self._finish(rec, rt, state, action)

            # --- restarting / paused / created / removing ...
            state = "recovering" if rt.failing_since is not None else status
            return self._finish(rec, rt, state, "wait")

    def _finish(self, rec: ContainerRecord, rt: _Runtime, state: str, action: str) -> str:
        if rt.circuit_opened_at is not None and state != "healthy":
            state = "circuit_open"
        rec.state = state
        rt.timeline.append(state)
        return action

    def mark_missing(self, present: Iterable[str]) -> None:
        """Containers we know about that Docker no longer lists (e.g. after `compose down`)."""
        present = set(present)
        with self._lock:
            for name, rec in self.records.items():
                if name not in present and rec.state != "missing":
                    rec.state, rec.status, rec.health = "missing", "not found", "none"
                    rt = self._runtime(name)
                    rt.last_up, rt.last_poll = False, None
                    rt.timeline.append("missing")

    # --------------------------------------------------------- failure / recovery
    def _begin_failure(self, rec, rt, now, name, reason) -> None:
        rt.failing_since = now
        rec.failures += 1
        rec.last_failure_time = now
        rec.last_failure_reason = reason
        self._event("WARNING", name, "FAILURE_DETECTED", f"Failure #{rec.failures}: {reason}")

    def _complete_recovery(self, rec, rt, now, name) -> None:
        duration = now - rt.failing_since
        rec.recoveries += 1
        rec.last_recovery_time = now
        rec.last_recovery_duration = duration
        rec.total_recovery_seconds += duration
        rt.failing_since = None
        self._event("SUCCESS", name, "RECOVERED", f"Healthy again after {duration:.1f}s")

    def _recover(self, rec, rt, now, name, action) -> str:
        policy = self.policy

        if rt.circuit_opened_at is not None:
            if now - rt.circuit_opened_at < policy.circuit_reset_seconds:
                return "circuit_open"
            rt.circuit_opened_at = None
            rt.history.clear()
            self._event("INFO", name, "CIRCUIT_RESET", "Circuit auto-reset; recovery resumes")

        if rt.last_action is not None and now - rt.last_action < policy.cooldown_seconds:
            return "cooldown"

        while rt.history and now - rt.history[0] > policy.window_seconds:
            rt.history.popleft()
        if len(rt.history) >= policy.max_restarts:
            rt.circuit_opened_at = now
            self._event("ERROR", name, "CIRCUIT_OPEN",
                        f"{policy.max_restarts} recovery attempts in {policy.window_seconds:.0f}s did not "
                        f"fix the container. Automatic recovery paused to avoid a restart loop.")
            return "circuit_open"

        ok = self.action_fn(name, action)
        rt.last_action = now
        rt.history.append(now)
        if ok:
            rec.monitor_restarts += 1
            rt.bad_polls = 0
            verb = "Restarted" if action == "restart" else "Started"
            self._event("INFO", name, "RESTART_ISSUED",
                        f"{verb} container (attempt {len(rt.history)}/{policy.max_restarts} "
                        f"in the last {policy.window_seconds:.0f}s)")
            return action
        self._event("ERROR", name, "RESTART_FAILED", f"Docker refused to {action} the container")
        return "failed"

    def reset_circuit(self, name: str) -> bool:
        with self._lock:
            if name not in self.records:
                return False
            rt = self._runtime(name)
            rt.circuit_opened_at, rt.last_action = None, None
            rt.history.clear()
            self._event("INFO", name, "CIRCUIT_RESET", "Circuit reset manually from the dashboard")
            return True

    # ------------------------------------------------------------------ reports
    def snapshot(self) -> List[dict]:
        with self._lock:
            now, rows = self.clock(), []
            for name in sorted(self.records):
                rec, rt = self.records[name], self._runtime(name)
                row = asdict(rec)
                row["restarts_total"] = rec.monitor_restarts + rec.docker_restarts
                row["uptime_percent"] = (round(100.0 * rec.up_seconds / rec.monitored_seconds, 2)
                                         if rec.monitored_seconds > 0 else None)
                row["avg_recovery_seconds"] = (round(rec.total_recovery_seconds / rec.recoveries, 2)
                                               if rec.recoveries else None)
                row["current_downtime_seconds"] = (round(now - rt.failing_since, 1)
                                                   if rt.failing_since is not None else 0.0)
                row["circuit_open"] = rt.circuit_opened_at is not None
                row["timeline"] = list(rt.timeline)
                rows.append(row)
            return rows

    def report(self) -> dict:
        rows = self.snapshot()
        total_fail = sum(r["failures"] for r in rows)
        total_rec = sum(r["recoveries"] for r in rows)
        total_time = sum(r["total_recovery_seconds"] for r in rows)
        return {
            "generated_at": self.clock(),
            "containers": [{
                "name": r["name"],
                "uptime_percent": r["uptime_percent"],
                "monitored_seconds": round(r["monitored_seconds"], 1),
                "failures": r["failures"],
                "recoveries": r["recoveries"],
                "monitor_restarts": r["monitor_restarts"],
                "docker_restarts": r["docker_restarts"],
                "total_recovery_seconds": round(r["total_recovery_seconds"], 1),
                "avg_recovery_seconds": r["avg_recovery_seconds"],
                "last_failure_reason": r["last_failure_reason"],
            } for r in rows],
            "totals": {
                "failures": total_fail,
                "recoveries": total_rec,
                "total_recovery_seconds": round(total_time, 1),
                "avg_recovery_seconds": round(total_time / total_rec, 2) if total_rec else None,
            },
        }
