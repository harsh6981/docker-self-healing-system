"""Unit tests for the sample Flask application."""
import pytest

import app as app_module


@pytest.fixture()
def client():
    app_module._state.update(failed=False, failed_since=None, requests=0)
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def test_homepage_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Simulate failure" in resp.data


def test_health_ok_by_default(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "healthy"


def test_fail_makes_health_return_503(client):
    assert client.post("/fail").status_code == 200
    resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.get_json()["status"] == "failed"


def test_restore_makes_health_return_200(client):
    client.post("/fail")
    assert client.get("/health").status_code == 503
    client.post("/restore")
    assert client.get("/health").status_code == 200


def test_fail_and_restore_accept_get(client):
    assert client.get("/fail").status_code == 200
    assert client.get("/restore").status_code == 200


def test_api_status_reports_failure(client):
    client.post("/fail")
    data = client.get("/api/status").get_json()
    assert data["healthy"] is False
    assert data["failed_since"] is not None
    assert "hostname" in data and "uptime_seconds" in data


def test_crash_schedules_process_exit(client, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "_schedule_crash", lambda *a, **k: calls.append(1))
    resp = client.post("/crash")
    assert resp.status_code == 202
    assert calls == [1]          # the real os._exit is never executed in tests


def test_start_failed_env_boots_in_failed_state(monkeypatch):
    import importlib
    monkeypatch.setenv("START_FAILED", "true")
    reloaded = importlib.reload(app_module)
    try:
        assert reloaded.app.test_client().get("/health").status_code == 503
    finally:
        monkeypatch.delenv("START_FAILED")
        importlib.reload(app_module)
