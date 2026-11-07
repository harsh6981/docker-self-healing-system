"""Unit tests for the self-healing decision logic (no Docker needed)."""
import pytest

from recovery import Policy, RecoveryManager


class Harness:
    """RecoveryManager with a fake clock and a fake Docker action."""

    def __init__(self, **policy):
        self.t = 1000.0
        self.actions = []
        self.events = []
        self.action_ok = True
        defaults = dict(unhealthy_polls=2, cooldown_seconds=20, max_restarts=3,
                        window_seconds=120, stopped_grace_seconds=10, circuit_reset_seconds=300)
        defaults.update(policy)
        self.mgr = RecoveryManager(self._act, Policy(**defaults),
                                   lambda *e: self.events.append(e), clock=lambda: self.t)

    def _act(self, name, action):
        self.actions.append((name, action))
        return self.action_ok

    def obs(self, status="running", health="healthy", restarts=0, code=None, dt=3, name="web"):
        self.t += dt
        return self.mgr.observe(name, status, health, restarts, code)

    def rec(self, name="web"):
        return self.mgr.records[name]

    def kinds(self):
        return [e[2] for e in self.events]


def test_healthy_container_needs_no_action():
    h = Harness()
    assert h.obs() == "ok"
    assert h.actions == [] and h.rec().failures == 0 and h.rec().state == "healthy"


def test_container_without_healthcheck_counts_as_healthy_when_running():
    h = Harness()
    assert h.obs(health="none") == "ok"


def test_starting_container_is_not_a_failure():
    h = Harness()
    assert h.obs(health="starting") == "wait"
    assert h.rec().failures == 0 and h.rec().state == "starting"


def test_unhealthy_is_restarted_only_after_threshold():
    h = Harness(unhealthy_polls=2)
    h.obs()
    assert h.obs(health="unhealthy") == "wait"       # 1st unhealthy poll: just record failure
    assert h.rec().failures == 1 and h.actions == []
    assert h.obs(health="unhealthy") == "restart"    # 2nd poll: act
    assert h.actions == [("web", "restart")]
    assert h.rec().monitor_restarts == 1


def test_full_recovery_cycle_records_durations():
    h = Harness()
    h.obs()
    h.obs(health="unhealthy")                         # failure detected at t0
    h.obs(health="unhealthy")                         # restart issued
    h.obs(health="starting")
    assert h.rec().state == "recovering"
    h.obs(health="healthy")                           # recovered 9 s after detection
    r = h.rec()
    assert r.failures == 1 and r.recoveries == 1
    assert r.last_recovery_duration == pytest.approx(9.0)
    assert r.total_recovery_seconds == pytest.approx(9.0)
    assert r.state == "healthy" and r.last_recovery_time is not None
    assert h.kinds() == ["FAILURE_DETECTED", "RESTART_ISSUED", "RECOVERED"]


def test_cooldown_prevents_rapid_restarts():
    h = Harness(cooldown_seconds=20, unhealthy_polls=1)
    h.obs()
    assert h.obs(health="unhealthy") == "restart"
    assert h.obs(health="unhealthy") == "cooldown"    # 3 s later, still cooling down
    assert h.obs(health="unhealthy") == "cooldown"
    assert len(h.actions) == 1


def test_circuit_breaker_stops_restart_loop():
    h = Harness(cooldown_seconds=5, max_restarts=3, window_seconds=120, unhealthy_polls=1)
    h.obs()
    results = [h.obs(health="unhealthy", dt=6) for _ in range(6)]
    assert results[:3] == ["restart"] * 3
    assert results[3] == "circuit_open"
    assert results[4:] == ["circuit_open"] * 2
    assert len(h.actions) == 3                       # never more than max_restarts
    assert h.rec().state == "circuit_open"
    assert "CIRCUIT_OPEN" in h.kinds()


def test_circuit_closes_when_container_gets_healthy():
    h = Harness(cooldown_seconds=5, max_restarts=1, unhealthy_polls=1)
    h.obs()
    h.obs(health="unhealthy", dt=6)
    assert h.obs(health="unhealthy", dt=6) == "circuit_open"
    assert h.obs(health="healthy") == "ok"
    snap = h.mgr.snapshot()[0]
    assert snap["circuit_open"] is False and snap["state"] == "healthy"


def test_manual_circuit_reset_allows_recovery_again():
    h = Harness(cooldown_seconds=5, max_restarts=1, unhealthy_polls=1)
    h.obs()
    h.obs(health="unhealthy", dt=6)
    assert h.obs(health="unhealthy", dt=6) == "circuit_open"
    assert h.mgr.reset_circuit("web") is True
    assert h.obs(health="unhealthy", dt=6) == "restart"
    assert h.mgr.reset_circuit("nope") is False


def test_circuit_auto_resets_after_timeout():
    h = Harness(cooldown_seconds=5, max_restarts=1, unhealthy_polls=1, circuit_reset_seconds=60)
    h.obs()
    h.obs(health="unhealthy", dt=6)
    assert h.obs(health="unhealthy", dt=6) == "circuit_open"
    assert h.obs(health="unhealthy", dt=61) == "restart"


def test_stopped_container_waits_for_docker_policy_then_is_started():
    h = Harness(stopped_grace_seconds=10)
    h.obs()
    assert h.obs(status="exited", health="none", code=1) == "wait"
    assert h.rec().failures == 1 and "exit code 1" in h.rec().last_failure_reason
    assert h.obs(status="exited", health="none", code=1) == "wait"
    assert h.obs(status="exited", health="none", code=1) == "wait"      # 6 s down
    assert h.obs(status="exited", health="none", code=1) == "wait"      # 9 s down
    assert h.obs(status="exited", health="none", code=1) == "start"     # 12 s down (> 10 s grace)
    assert h.actions == [("web", "start")]


def test_docker_restart_policy_is_counted_and_recovery_timed():
    h = Harness()
    h.obs(restarts=0)
    h.obs(status="exited", health="none", code=1, restarts=0)   # crash seen
    h.obs(status="running", health="starting", restarts=1)      # Docker restarted it
    h.obs(status="running", health="healthy", restarts=1)
    r = h.rec()
    assert r.docker_restarts == 1 and r.monitor_restarts == 0
    assert r.failures == 1 and r.recoveries == 1
    assert h.actions == []                                       # we did NOT interfere


def test_crash_restarted_between_polls_is_still_detected():
    h = Harness()
    h.obs(restarts=0)
    h.obs(status="running", health="starting", restarts=1)       # exited state was never observed
    h.obs(status="running", health="healthy", restarts=1)
    r = h.rec()
    assert r.failures == 1 and r.docker_restarts == 1 and r.recoveries == 1


def test_baseline_restart_count_is_not_counted_as_new_restart():
    h = Harness()
    h.obs(restarts=7)       # container already had 7 restarts before the monitor started
    h.obs(restarts=7)
    assert h.rec().docker_restarts == 0 and h.rec().failures == 0


def test_failed_docker_action_is_reported_and_not_counted():
    h = Harness(unhealthy_polls=1)
    h.action_ok = False
    h.obs()
    assert h.obs(health="unhealthy") == "failed"
    assert h.rec().monitor_restarts == 0 and "RESTART_FAILED" in h.kinds()


def test_containers_are_independent():
    h = Harness(unhealthy_polls=1)
    h.obs(name="web")
    h.obs(name="web2")
    h.obs(name="web", health="unhealthy")
    assert h.actions == [("web", "restart")]
    assert h.rec("web2").failures == 0


def test_uptime_percentage():
    h = Harness()
    h.obs()                         # first poll: no interval yet
    h.obs(dt=10)                    # 10 s healthy
    h.obs(health="unhealthy", dt=10)  # interval attributed to previous (healthy) state
    h.obs(health="unhealthy", dt=10)  # 10 s down
    snap = h.mgr.snapshot()[0]
    assert snap["monitored_seconds"] == pytest.approx(30)
    assert snap["uptime_percent"] == pytest.approx(66.67, abs=0.01)


def test_missing_container_is_marked_missing():
    h = Harness()
    h.obs()
    h.mgr.mark_missing([])
    assert h.rec().state == "missing"


def test_state_round_trip():
    h = Harness(unhealthy_polls=1)
    h.obs()
    h.obs(health="unhealthy")
    state = h.mgr.to_state()
    h2 = Harness()
    h2.mgr.load(state)
    assert h2.rec().failures == 1 and h2.rec().monitor_restarts == 1


def test_report_totals():
    h = Harness(unhealthy_polls=1)
    h.obs()
    h.obs(health="unhealthy")
    h.obs(health="healthy")
    rep = h.mgr.report()
    assert rep["totals"]["failures"] == 1 and rep["totals"]["recoveries"] == 1
    assert rep["containers"][0]["name"] == "web"
