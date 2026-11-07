"""Tests the Docker-facing layer with a fake Docker client (no daemon needed)."""
import json

import pytest

import monitor as monitor_module
from dashboard import create_dashboard
from recovery import Policy, RecoveryManager
from storage import EventLog, load_state, save_state


class FakeContainer:
    def __init__(self, name, status="running", health="healthy", restart_count=0, exit_code=0):
        self.name = name
        self.restarted = 0
        self.started = 0
        self.attrs = {"RestartCount": restart_count,
                      "State": {"Status": status, "ExitCode": exit_code,
                                "Health": {"Status": health} if health else {}}}

    def restart(self, timeout=10):
        self.restarted += 1
        self.attrs["State"].update(Status="running", Health={"Status": "starting"})

    def start(self):
        self.started += 1
        self.attrs["State"].update(Status="running", Health={"Status": "starting"})


class FakeClient:
    def __init__(self, *containers):
        self.c = {c.name: c for c in containers}
        self.containers = self

    def list(self, all=True, filters=None):
        return list(self.c.values())

    def get(self, name):
        return self.c[name]


def make(tmp_path, *containers, clock=None, **policy):
    client = FakeClient(*containers)
    events = EventLog(str(tmp_path))
    pol = dict(unhealthy_polls=1, cooldown_seconds=0, stopped_grace_seconds=0)
    pol.update(policy)
    mgr = RecoveryManager(monitor_module.make_action_fn(client, events), Policy(**pol), events,
                          **({"clock": clock} if clock else {}))
    return client, mgr, events


def test_unhealthy_container_gets_restarted_and_recovers(tmp_path):
    web = FakeContainer("sh-web", health="unhealthy")
    other = FakeContainer("sh-web2")
    client, mgr, events = make(tmp_path, web, other)
    assert monitor_module.poll_once(client, mgr) == 2
    assert web.restarted == 1 and other.restarted == 0          # only the sick one is touched
    web.attrs["State"]["Health"]["Status"] = "healthy"
    monitor_module.poll_once(client, mgr)
    rows = {r["name"]: r for r in mgr.snapshot()}
    assert rows["sh-web"]["failures"] == 1 and rows["sh-web"]["recoveries"] == 1
    assert rows["sh-web"]["state"] == "healthy" and rows["sh-web2"]["failures"] == 0


def test_stopped_container_is_started(tmp_path):
    web = FakeContainer("sh-web", status="exited", health=None, exit_code=137)
    client, mgr, _ = make(tmp_path, web)
    monitor_module.poll_once(client, mgr)
    assert web.started == 1


def test_removed_container_is_marked_missing(tmp_path):
    web = FakeContainer("sh-web")
    client, mgr, _ = make(tmp_path, web)
    monitor_module.poll_once(client, mgr)
    client.c.clear()
    monitor_module.poll_once(client, mgr)
    assert mgr.snapshot()[0]["state"] == "missing"


def test_event_log_writes_text_and_json_files(tmp_path):
    events = EventLog(str(tmp_path))
    events("WARNING", "sh-web", "FAILURE_DETECTED", "demo")
    assert "FAILURE_DETECTED" in (tmp_path / "recovery.log").read_text()
    line = (tmp_path / "events.jsonl").read_text().strip()
    assert json.loads(line)["container"] == "sh-web"
    assert EventLog(str(tmp_path)).recent(5)[0]["event"] == "FAILURE_DETECTED"   # reloaded


def test_state_file_round_trip(tmp_path):
    path = str(tmp_path / "state.json")
    assert load_state(path) is None
    save_state(path, {"containers": {"a": {"failures": 2}}})
    assert load_state(path)["containers"]["a"]["failures"] == 2


@pytest.fixture()
def dash(tmp_path):
    web = FakeContainer("sh-web", health="unhealthy")
    client, mgr, events = make(tmp_path, web)
    monitor_module.poll_once(client, mgr)
    app = create_dashboard(mgr, events, {"docker_ok": True, "poll_interval": 3})
    app.config["TESTING"] = True
    return app.test_client()


def test_dashboard_api_status(dash):
    data = dash.get("/api/status").get_json()
    assert data["containers"][0]["name"] == "sh-web"
    assert data["containers"][0]["failures"] == 1
    assert any(e["event"] == "FAILURE_DETECTED" for e in data["events"])
    assert data["policy"]["max_restarts"] == 3


def test_dashboard_pages_and_report(dash):
    assert dash.get("/").status_code == 200
    assert dash.get("/health").status_code == 200
    assert dash.get("/api/report").get_json()["totals"]["failures"] == 1
    csv_resp = dash.get("/report.csv")
    assert csv_resp.mimetype == "text/csv" and b"sh-web" in csv_resp.data


def test_dashboard_rejects_unknown_targets(dash):
    assert dash.post("/api/simulate/fail", json={"target": "evil.example.com"}).status_code == 404
    assert dash.post("/api/simulate/explode", json={"target": "sh-web"}).status_code == 400
    assert dash.post("/api/reset/unknown").status_code == 404
    assert dash.post("/api/reset/sh-web").status_code == 200
