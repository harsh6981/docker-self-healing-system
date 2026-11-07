"""Sample Flask application used as the *target* of the self-healing system.

Endpoints
---------
GET  /            Status page (HTML)
GET  /health      200 when healthy, 503 when failure has been simulated
GET  /api/status  JSON status used by the status page
*    /fail        Simulate an application failure (health check starts failing)
*    /restore     Restore the application after a simulated failure
*    /crash       Kill the Python process (container exits with code 1)

/fail, /restore and /crash accept both GET and POST so they can be triggered
from a browser address bar or curl during a demo. A production service would
never expose such endpoints without authentication.
"""
import os
import socket
import threading
import time

from flask import Flask, jsonify, render_template

app = Flask(__name__)

APP_NAME = os.getenv("APP_NAME", "Demo Service")
PORT = int(os.getenv("PORT", "5000"))
START_TIME = time.time()
# START_FAILED=true makes the app boot already broken, so restarting never helps.
# Used to demonstrate the restart-loop protection (see docker-compose.broken.yml).
START_FAILED = os.getenv("START_FAILED", "false").strip().lower() in ("1", "true", "yes")

_lock = threading.Lock()
_state = {"failed": START_FAILED,
          "failed_since": START_TIME if START_FAILED else None,
          "requests": 0}


def _terminate():
    """Hard-kill the process (simulates a crash). Exit code 1 => failure."""
    os._exit(1)


def _schedule_crash(delay=0.3):
    """Exit shortly *after* the HTTP response has been sent."""
    timer = threading.Timer(delay, _terminate)
    timer.daemon = True
    timer.start()


def _status_payload():
    with _lock:
        failed = _state["failed"]
        failed_since = _state["failed_since"]
        requests_served = _state["requests"]
    return {
        "app_name": APP_NAME,
        "hostname": socket.gethostname(),
        "status": "failed" if failed else "healthy",
        "healthy": not failed,
        "failed_since": failed_since,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "started_at": START_TIME,
        "requests_served": requests_served,
    }


@app.before_request
def _count_request():
    with _lock:
        _state["requests"] += 1


@app.route("/")
def index():
    return render_template("index.html", app_name=APP_NAME)


@app.route("/health")
def health():
    payload = _status_payload()
    code = 200 if payload["healthy"] else 503
    return jsonify(status=payload["status"], app=APP_NAME), code


@app.route("/api/status")
def api_status():
    return jsonify(_status_payload())


@app.route("/fail", methods=["GET", "POST"])
def fail():
    with _lock:
        if not _state["failed"]:
            _state["failed"] = True
            _state["failed_since"] = time.time()
    return jsonify(message="Failure simulated: /health now returns 503"), 200


@app.route("/restore", methods=["GET", "POST"])
def restore():
    with _lock:
        _state["failed"] = False
        _state["failed_since"] = None
    return jsonify(message="Application restored: /health returns 200"), 200


@app.route("/crash", methods=["GET", "POST"])
def crash():
    _schedule_crash()
    return jsonify(message="Process will exit with code 1 in 0.3s"), 202


if __name__ == "__main__":
    # threaded=True so /health still answers while another request is running.
    app.run(host="0.0.0.0", port=PORT, threaded=True)
