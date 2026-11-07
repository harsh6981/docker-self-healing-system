
#!/usr/bin/env python3
"""End-to-end test of the Docker self-healing system.

Usage:
    python scripts/integration_test.py
    python scripts/integration_test.py --down
    python scripts/integration_test.py --no-build

Tests:
1. Docker containers start and become healthy.
2. Application health-check failure is detected.
3. Monitor restarts only the unhealthy container.
4. Docker restart policy handles a process crash.
5. Dashboard API and recovery reports contain real data.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

WEB = "http://localhost:5000"
WEB2 = "http://localhost:5001"
MON = "http://localhost:8080"


def run(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=False)


def inspect(name, fmt):
    result = subprocess.run(
        ["docker", "inspect", "-f", fmt, name],
        capture_output=True,
        text=True
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def http(url, timeout=5):
    """Return HTTP status and response body."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode()

    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()

    except Exception:
        return None, ""


def wait_for(description, condition, timeout=120, interval=2):
    """Wait until a condition becomes true."""
    start = time.time()

    while time.time() - start < timeout:
        try:
            if condition():
                print(
                    f"  ok   {description} "
                    f"({time.time() - start:.1f}s)",
                    flush=True
                )
                return
        except Exception:
            pass

        time.sleep(interval)

    raise AssertionError(
        f"Timed out after {timeout}s waiting for: {description}"
    )


def health(name):
    return inspect(name, "{{.State.Health.Status}}")


def stats():
    code, body = http(MON + "/api/status")

    if code != 200:
        return {}

    try:
        data = json.loads(body)
        return {
            container["name"]: container
            for container in data["containers"]
        }
    except (ValueError, KeyError, TypeError):
        return {}


def check(condition, message):
    if not condition:
        raise AssertionError(message)

    print(f"  ok   {message}", flush=True)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--down",
        action="store_true",
        help="Remove containers and volumes after testing"
    )

    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip Docker image building"
    )

    args = parser.parse_args()

    success = False

    try:
        # -------------------------------------------------
        # STEP 1: START THE DOCKER STACK
        # -------------------------------------------------

        print("\n[1/5] Start the stack", flush=True)

        run(
            "docker",
            "compose",
            "up",
            "-d",
            *([] if args.no_build else ["--build"])
        )

        wait_for(
            "sh-web is healthy",
            lambda: health("sh-web") == "healthy"
        )

        wait_for(
            "sh-web2 is healthy",
            lambda: health("sh-web2") == "healthy"
        )

        wait_for(
            "monitor dashboard answers",
            lambda: http(MON + "/health")[0] == 200
        )

        wait_for(
            "monitor sees both containers healthy",
            lambda: {"sh-web", "sh-web2"} <= set(stats())
            and all(
                stats()[name]["state"] == "healthy"
                for name in ("sh-web", "sh-web2")
            )
        )

        check(
            http(WEB + "/")[0] == 200,
            "app homepage reachable on :5000"
        )

        check(
            http(WEB + "/health")[0] == 200,
            "/health returns 200"
        )

        # -------------------------------------------------
        # STEP 2: SIMULATE APPLICATION FAILURE
        # -------------------------------------------------

        print(
            "\n[2/5] Simulate application failure on sh-web",
            flush=True
        )

        web_started = inspect(
            "sh-web",
            "{{.State.StartedAt}}"
        )

        web2_started = inspect(
            "sh-web2",
            "{{.State.StartedAt}}"
        )

        http(WEB + "/fail")

        check(
            http(WEB + "/health")[0] == 503,
            "/health now returns 503"
        )

        wait_for(
            "Docker marks sh-web unhealthy",
            lambda: health("sh-web") == "unhealthy",
            timeout=60,
            interval=1
        )

        wait_for(
            "monitor records the failure",
            lambda: stats().get("sh-web", {}).get("failures", 0) >= 1
        )

        # -------------------------------------------------
        # STEP 3: VERIFY AUTOMATIC RECOVERY
        # -------------------------------------------------

        print("\n[3/5] Automatic recovery", flush=True)

        wait_for(
            "monitor restarted sh-web",
            lambda: stats().get("sh-web", {}).get(
                "monitor_restarts", 0
            ) >= 1
        )

        wait_for(
            "sh-web healthy again",
            lambda: health("sh-web") == "healthy"
        )

        wait_for(
            "monitor records the recovery",
            lambda: stats().get("sh-web", {}).get(
                "recoveries", 0
            ) >= 1
        )

        check(
            http(WEB + "/health")[0] == 200,
            "/health returns 200 again"
        )

        check(
            inspect("sh-web", "{{.State.StartedAt}}") != web_started,
            "sh-web was really restarted"
        )

        check(
            inspect("sh-web2", "{{.State.StartedAt}}") == web2_started,
            "sh-web2 was NOT restarted"
        )

        check(
            stats().get("sh-web2", {}).get("failures", 0) == 0,
            "sh-web2 has no failures recorded"
        )

        # -------------------------------------------------
        # STEP 4: VERIFY DOCKER PROCESS-CRASH RECOVERY
        # -------------------------------------------------

        print(
            "\n[4/5] Process crash handled by Docker restart policy",
            flush=True
        )

        initial_restarts = int(
            inspect("sh-web2", "{{.RestartCount}}") or "0"
        )

        http(WEB2 + "/crash")

        wait_for(
            "Docker restart policy restarted sh-web2",
            lambda: int(
                inspect("sh-web2", "{{.RestartCount}}") or "0"
            ) > initial_restarts,
            timeout=60,
            interval=1
        )

        wait_for(
            "sh-web2 healthy again",
            lambda: health("sh-web2") == "healthy",
            timeout=60,
            interval=1
        )

        wait_for(
            "monitor counted the Docker restart",
            lambda: stats().get("sh-web2", {}).get(
                "docker_restarts", 0
            ) >= 1,
            timeout=60,
            interval=2
        )

        # IMPORTANT FIX:
        # Wait until the monitoring service records the
        # recovery before checking the final report.

        wait_for(
            "monitor records Docker crash recovery",
            lambda: stats().get("sh-web2", {}).get(
                "recoveries", 0
            ) >= 1,
            timeout=60,
            interval=2
        )

        check(
            stats().get("sh-web2", {}).get(
                "monitor_restarts", 0
            ) == 0,
            "monitor did not interfere with the crash restart"
        )

        # -------------------------------------------------
        # STEP 5: VERIFY REPORTS
        # -------------------------------------------------

        print("\n[5/5] Reports", flush=True)

        # Wait for the final API report to include both
        # failure and recovery events.

        def report_ready():
            code, body = http(MON + "/api/report")

            if code != 200:
                return False

            try:
                report = json.loads(body)
                totals = report["totals"]

                return (
                    totals["failures"] >= 2
                    and totals["recoveries"] >= 2
                )

            except (ValueError, KeyError, TypeError):
                return False

        wait_for(
            "report includes all failures and recoveries",
            report_ready,
            timeout=60,
            interval=2
        )

        code, body = http(MON + "/api/report")

        check(
            code == 200,
            "report endpoint returns HTTP 200"
        )

        report = json.loads(body)

        check(
            report["totals"]["failures"] >= 2,
            "report shows the failures"
        )

        check(
            report["totals"]["recoveries"] >= 2,
            "report shows the recoveries"
        )

        success = True

        print("\n========================================")
        print("       INTEGRATION TEST PASSED")
        print("========================================")

    except Exception as exc:
        print(
            f"\nINTEGRATION TEST FAILED: {exc}",
            file=sys.stderr,
            flush=True
        )

    finally:
        if not success:
            print("\nCollecting Docker diagnostics...", flush=True)

            run(
                "docker",
                "compose",
                "ps",
                "-a",
                check=False
            )

            run(
                "docker",
                "compose",
                "logs",
                "--tail",
                "100",
                check=False
            )

        if args.down:
            print("\nCleaning up Docker resources...", flush=True)

            run(
                "docker",
                "compose",
                "down",
                "-v",
                check=False
            )

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
