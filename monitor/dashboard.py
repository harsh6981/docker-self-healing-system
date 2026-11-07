"""Web dashboard + JSON API (Flask). Runs inside the monitor container."""
import csv
import io
import time

import requests
from flask import Flask, Response, jsonify, render_template, request


def create_dashboard(manager, events, runtime, app_port=5000):
    """``runtime`` is a dict shared with the polling loop (docker_ok, last_poll...)."""
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template("dashboard.html")

    @app.route("/health")
    def health():
        return jsonify(status="ok")

    @app.route("/api/status")
    def api_status():
        pol = manager.policy
        return jsonify({
            "now": time.time(),
            "monitor": dict(runtime),
            "policy": {
                "poll_interval": runtime.get("poll_interval"),
                "unhealthy_polls": pol.unhealthy_polls,
                "cooldown_seconds": pol.cooldown_seconds,
                "max_restarts": pol.max_restarts,
                "window_seconds": pol.window_seconds,
            },
            "containers": manager.snapshot(),
            "events": events.recent(60),
        })

    @app.route("/api/report")
    def api_report():
        return jsonify(manager.report())

    @app.route("/report.csv")
    def report_csv():
        rep = manager.report()
        buf = io.StringIO()
        cols = ["name", "uptime_percent", "monitored_seconds", "failures", "recoveries",
                "monitor_restarts", "docker_restarts", "total_recovery_seconds",
                "avg_recovery_seconds", "last_failure_reason"]
        writer = csv.DictWriter(buf, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rep["containers"])
        return Response(buf.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=monitoring_report.csv"})

    @app.route("/api/simulate/<action>", methods=["POST"])
    def simulate(action):
        """Trigger /fail, /restore or /crash on a monitored app (demo helper)."""
        if action not in ("fail", "restore", "crash"):
            return jsonify(error="unknown action"), 400
        target = (request.get_json(silent=True) or {}).get("target", "")
        if target not in manager.known_names():          # also prevents SSRF
            return jsonify(error="unknown container"), 404
        url = f"http://{target}:{app_port}/{action}"
        events("INFO", target, "SIMULATION", f"Dashboard requested '{action}'")
        try:
            requests.post(url, timeout=3)
        except requests.RequestException:
            if action != "crash":                          # a crash may drop the connection
                return jsonify(error=f"could not reach {url}"), 502
        return jsonify(ok=True)

    @app.route("/api/reset/<name>", methods=["POST"])
    def reset(name):
        if manager.reset_circuit(name):
            return jsonify(ok=True)
        return jsonify(error="unknown container"), 404

    return app
