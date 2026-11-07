"""Docker health monitor + self-healing loop.

Every POLL_INTERVAL seconds:
  1. list containers labelled  selfheal.monitor=true
  2. read State.Status, State.Health.Status and RestartCount (docker inspect)
  3. pass the observation to RecoveryManager, which decides whether to restart
  4. persist statistics (logs/state.json) and serve them on the dashboard (:8080)

Docker's own restart policy handles crashed processes; this loop adds what the
policy cannot do: restart a container that is running but *unhealthy*.
"""
import os
import signal
import sys
import threading
import time

import docker
from docker.errors import DockerException

from dashboard import create_dashboard
from recovery import Policy, RecoveryManager
from storage import EventLog, load_state, save_state

LABEL = os.getenv("MONITOR_LABEL", "selfheal.monitor=true")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3"))
LOG_DIR = os.getenv("LOG_DIR", "/logs")
APP_PORT = int(os.getenv("APP_PORT", "5000"))
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
STATE_PATH = os.path.join(LOG_DIR, "state.json")


def poll_once(client, manager, label=LABEL):
    """One monitoring cycle. Returns the number of containers observed."""
    containers = client.containers.list(all=True, filters={"label": label})
    seen = set()
    for container in containers:
        state = container.attrs.get("State", {})
        health = (state.get("Health") or {}).get("Status", "none")
        manager.observe(
            container.name,
            state.get("Status", "unknown"),
            health,
            container.attrs.get("RestartCount", 0),
            state.get("ExitCode"),
        )
        seen.add(container.name)
    manager.mark_missing(seen)
    return len(seen)


def make_action_fn(client, log):
    """Build the function the RecoveryManager calls to act on a container."""
    def act(name, action):
        try:
            container = client.containers.get(name)
            if action == "restart":
                container.restart(timeout=5)      # SIGTERM, wait 5 s, then SIGKILL
            elif action == "start":
                container.start()
            else:
                return False
            return True
        except DockerException as exc:
            log("ERROR", name, "ACTION_ERROR", f"{action} failed: {exc}")
            return False
    return act


def connect(stop, log):
    """Wait until the Docker daemon is reachable through /var/run/docker.sock."""
    while not stop.is_set():
        try:
            client = docker.from_env()
            client.ping()
            return client
        except DockerException as exc:
            log("ERROR", "monitor", "DOCKER_UNAVAILABLE", f"{exc}; retrying in 5s")
            stop.wait(5)
    return None


def main():
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    events = EventLog(LOG_DIR)
    client = connect(stop, events)
    if client is None:
        return 0

    policy = Policy.from_env()
    manager = RecoveryManager(make_action_fn(client, events), policy, events)
    manager.load(load_state(STATE_PATH))

    runtime = {"docker_ok": True, "last_poll": None, "last_error": "",
               "poll_interval": POLL_INTERVAL, "started_at": time.time(), "label": LABEL}
    dashboard = create_dashboard(manager, events, runtime, APP_PORT)
    threading.Thread(
        target=lambda: dashboard.run(host="0.0.0.0", port=DASHBOARD_PORT,
                                     threaded=True, use_reloader=False),
        daemon=True).start()

    events("INFO", "monitor", "MONITOR_STARTED",
           f"Watching label '{LABEL}' every {POLL_INTERVAL:g}s | policy: {policy}")

    while not stop.is_set():
        try:
            count = poll_once(client, manager)
            runtime.update(docker_ok=True, last_poll=time.time(), last_error="", watched=count)
        except Exception as exc:    # never let the monitor die because of one bad poll
            if runtime.get("docker_ok", True):
                events("ERROR", "monitor", "POLL_ERROR", str(exc))
            runtime.update(docker_ok=False, last_error=str(exc))
        save_state(STATE_PATH, manager.to_state())
        stop.wait(POLL_INTERVAL)

    events("INFO", "monitor", "MONITOR_STOPPED", "Shutting down")
    save_state(STATE_PATH, manager.to_state())
    return 0


if __name__ == "__main__":
    sys.exit(main())
