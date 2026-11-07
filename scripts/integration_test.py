#!/usr/bin/env python3
"""End-to-end test of the whole system. Needs Docker. Works on Windows, Linux, macOS.

    python scripts/integration_test.py            # build, start, test, leave running
    python scripts/integration_test.py --down     # ... and tear everything down afterwards

What it proves
  1. all containers start and become healthy
  2. a simulated application failure is detected as 'unhealthy'
  3. the monitor restarts ONLY the failed container and it becomes healthy again
  4. a process crash is handled by Docker's restart policy and counted
  5. the dashboard API and the report endpoint return real data
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request

WEB, WEB2, MON = "http://localhost:5000", "http://localhost:5001", "http://localhost:8080"


def run(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=False)


def inspect(name, fmt):
    out = subprocess.run(["docker", "inspect", "-f", fmt, name], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def http(url, timeout=5):
    """Return (status_code, body) or (None, '') if unreachable."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
    except Exception:
        return None, ""


def wait_for(description, condition, timeout=120, interval=2):
    start = time.time()
    while time.time() - start < timeout:
        if condition():
            print(f"  ok   {description} ({time.time() - start:.0f}s)", flush=True)
            return
        time.sleep(interval)
    raise AssertionError(f"timed out after {timeout}s waiting for: {description}")


def health(name):
    return inspect(name, "{{.State.Health.Status}}")


def stats():
    code, body = http(MON + "/api/status")
    if code != 200:
        return {}
    return {c["name"]: c for c in json.loads(body)["containers"]}


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  ok   {message}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--down", action="store_true", help="docker compose down -v when finished")
    parser.add_argument("--no-build", action="store_true", help="skip --build")
    args = parser.parse_args()

    ok = False
    try:
        print("\n[1/5] Start the stack")
        run("docker", "compose", "up", "-d", *([] if args.no_build else ["--build"]))
        wait_for("sh-web is healthy", lambda: health("sh-web") == "healthy")
        wait_for("sh-web2 is healthy", lambda: health("sh-web2") == "healthy")
        wait_for("monitor dashboard answers", lambda: http(MON + "/health")[0] == 200)
        wait_for("monitor sees both containers healthy",
                 lambda: {"sh-web", "sh-web2"} <= set(stats()) and
                 all(c["state"] == "healthy" for c in stats().values()))
        check(http(WEB + "/")[0] == 200, "app homepage reachable on :5000")
        check(http(WEB + "/health")[0] == 200, "/health returns 200")

        print("\n[2/5] Simulate application failure on sh-web")
        web2_started = inspect("sh-web2", "{{.State.StartedAt}}")
        web_started = inspect("sh-web", "{{.State.StartedAt}}")
        http(WEB + "/fail")
        check(http(WEB + "/health")[0] == 503, "/health now returns 503")
        wait_for("Docker marks sh-web unhealthy", lambda: health("sh-web") == "unhealthy", timeout=60, interval=1)
        wait_for("monitor records the failure", lambda: stats().get("sh-web", {}).get("failures", 0) >= 1)

        print("\n[3/5] Automatic recovery")
        wait_for("monitor restarted sh-web", lambda: stats().get("sh-web", {}).get("monitor_restarts", 0) >= 1)
        wait_for("sh-web healthy again", lambda: health("sh-web") == "healthy")
        wait_for("monitor records the recovery", lambda: stats().get("sh-web", {}).get("recoveries", 0) >= 1)
        check(http(WEB + "/health")[0] == 200, "/health returns 200 again (restart cleared the failure)")
        check(inspect("sh-web", "{{.State.StartedAt}}") != web_started, "sh-web was really restarted")
        check(inspect("sh-web2", "{{.State.StartedAt}}") == web2_started, "sh-web2 was NOT restarted")
        check(stats()["sh-web2"]["failures"] == 0, "sh-web2 has no failures recorded")

        print("\n[4/5] Process crash handled by Docker's restart policy")
        http(WEB2 + "/crash")
        wait_for("Docker restart policy restarted sh-web2",
                 lambda: inspect("sh-web2", "{{.RestartCount}}") not in ("", "0"), timeout=60, interval=1)
        wait_for("sh-web2 healthy again", lambda: health("sh-web2") == "healthy")
        wait_for("monitor counted the Docker restart",
                 lambda: stats().get("sh-web2", {}).get("docker_restarts", 0) >= 1)
        check(stats()["sh-web2"]["monitor_restarts"] == 0, "monitor did not interfere with the crash restart")

        print("\n[5/5] Reports")
        code, body = http(MON + "/api/report")
        report = json.loads(body)
        check(code == 200 and report["totals"]["failures"] >= 2, "report shows the failures")
        check(report["totals"]["recoveries"] >= 2, "report shows the recoveries")
        ok = True
        print("\nINTEGRATION TEST PASSED")
    except AssertionError as exc:
        print(f"\nINTEGRATION TEST FAILED: {exc}", file=sys.stderr)
    finally:
        if not ok:
            run("docker", "compose", "ps", "-a", check=False)
            run("docker", "compose", "logs", "--tail", "60", check=False)
        if args.down:
            run("docker", "compose", "down", "-v", check=False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
