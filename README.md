# Automated Docker Container Health Checks and Self-Healing System

*Docker, Docker Compose, Python/Flask, GitHub Actions*

A multi-container system that **monitors container health, detects failures, restarts the
failed container automatically, logs every recovery event, and reports uptime and recovery
time on a live dashboard**. GitHub Actions tests and validates every push.

| What | Where |
|---|---|
| Sample app A / B | http://localhost:5000 / http://localhost:5001 |
| **Monitoring dashboard** | **http://localhost:8080** |
| Recovery log (persistent) | `logs/recovery.log`, `logs/events.jsonl`, `logs/state.json` |

## Quick start (Windows, Docker Desktop running)

```powershell
cd docker-self-healing-system
docker compose up -d --build
start http://localhost:8080
```

Then press **Fail** on a container in the dashboard and watch it go
Healthy → Unhealthy → Recovering → Healthy without any manual action.
Full walkthrough: [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md).

| Document | Purpose |
|---|---|
| [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) | Windows setup, Git and GitHub, troubleshooting |
| [docs/TEST_SCENARIOS.md](docs/TEST_SCENARIOS.md) | Six practical tests with commands, expected output, what to show |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 8 to 10 minute demonstration sequence |
| [docs/VIVA_QA.md](docs/VIVA_QA.md) | 25 viva questions and answers |
| [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) | Screenshots to capture for submission |

---

## 1. Abstract

Containers fail in different ways: the process crashes, the container is stopped, or the
process keeps running but no longer works. Docker's restart policy handles the first two
but **does not restart a container that is running and merely reported "unhealthy"**.
This project closes that gap. A Python monitor reads Docker's health status through the
Docker Engine API, restarts unhealthy containers, guards against restart loops with a
cooldown and a circuit breaker, stores recovery events persistently, and shows live
statistics on a web dashboard. GitHub Actions runs unit tests, builds the images,
validates the Compose file and runs an end-to-end failure-injection test on every push.

## 2. Problem statement

Applications deployed in containers can fail silently. A web server may stay alive while
returning errors, so the container still looks "Up". Without automatic detection and
recovery, someone must notice and restart it manually, which reduces availability. A naive
automatic restart can also make things worse by restarting a permanently broken container
forever. A safe, observable self-healing mechanism is needed.

## 3. Objectives

1. Deploy a multi-container application with Docker Compose.
2. Monitor container health continuously with Docker `HEALTHCHECK`.
3. Detect unhealthy, crashed and stopped containers.
4. Automatically recover failed containers, restarting only the affected one.
5. Prevent infinite restart loops.
6. Record failures, restarts and recovery times persistently.
7. Display live status, failures, restarts and recovery statistics on a dashboard.
8. Automate testing, image building and validation with GitHub Actions.
9. Generate a monitoring report (uptime, failures, recovery time).

## 4. Existing system

* Plain `docker run` / Compose with `restart: always|unless-stopped|on-failure`:
  restarts only when the **main process exits**.
* `HEALTHCHECK` marks a container `unhealthy` but **takes no action**; Docker Engine (outside Swarm)
  never restarts a container just because it is unhealthy.
* Manual inspection with `docker ps` and `docker logs`.
* Full orchestrators (Kubernetes liveness probes) or paid monitoring tools solve this but are heavy for small projects.

## 5. Proposed system

Three layers working together:

1. **Detection:** `HEALTHCHECK` in the Dockerfile probes `/health` every 5 s.
2. **Crash handling:** `restart: unless-stopped` lets Docker restart exited processes.
3. **Self-healing monitor:** polls Docker every 3 s, restarts *unhealthy* containers, starts
   *stopped* containers that Docker did not bring back, records everything, and pauses
   recovery when a container keeps failing (restart-loop protection).

### The three failure types

| Situation | What it means | Who fixes it here |
|---|---|---|
| **Crashed process** | Main process exits (e.g. exit code 1). Container goes to `exited`. | Docker **restart policy** |
| **Unhealthy container** | Process is alive but `/health` fails. Status is `Up ... (unhealthy)`. | **Monitor** (restart policies ignore this) |
| **Stopped container** | Stopped on purpose (`docker stop`) or by the OS. `unless-stopped` will *not* restart it. | **Monitor** starts it after a grace period |

## 6. Technology stack

Docker, Docker Compose v2, Python 3.12, Flask 3, Docker SDK for Python, HTML/CSS/JavaScript
(dashboard, no frameworks), pytest, flake8, Git, GitHub Actions. No Kubernetes, cloud or paid tools.

## 7. System architecture

```
                         Windows PC (Docker Desktop, Linux containers)
 ┌────────────────────────────────────────────────────────────────────────────┐
 │  docker compose network                                                    │
 │                                                                            │
 │   ┌──────────────┐   /health    ┌─────────────────────────────────────┐    │
 │   │ sh-web       │◄──(5 s)──────│ Docker Engine                       │    │
 │   │ Flask  :5000 │  HEALTHCHECK │  - runs HEALTHCHECK, stores status  │    │
 │   └──────────────┘              │  - restart policy: unless-stopped   │    │
 │   ┌──────────────┐              └──────────────▲──────────────────────┘    │
 │   │ sh-web2      │                             │ Docker API via            │
 │   │ Flask  :5001 │                             │ /var/run/docker.sock      │
 │   └──────────────┘                             │                           │
 │                                  ┌─────────────┴───────────────────────┐   │
 │   browser :8080 ───────────────► │ sh-monitor                          │   │
 │   (dashboard)                    │  monitor.py   poll + act            │   │
 │                                  │  recovery.py  decisions, loop guard │   │
 │                                  │  dashboard.py Flask UI + API        │   │
 │                                  └─────────────┬───────────────────────┘   │
 └────────────────────────────────────────────────┼───────────────────────────┘
                                                  ▼
                                   ./logs  (bind mount, survives restarts)
                                   recovery.log  events.jsonl  state.json

 GitHub push ──► GitHub Actions (cloud): lint, unit tests, build, compose validate,
                 integration test.   CI only: it does NOT watch your local containers.
```

Only containers labelled `selfheal.monitor=true` are watched, so the monitor never touches itself.

### Project structure

```
docker-self-healing-system/
├── app/                      Sample Flask application (the thing being protected)
│   ├── app.py                /, /health, /fail, /restore, /crash
│   ├── healthcheck.py        script run by Docker HEALTHCHECK
│   ├── templates/index.html
│   ├── requirements.txt
│   └── Dockerfile            contains the HEALTHCHECK instruction
├── monitor/                  Self-healing monitor
│   ├── monitor.py            Docker polling loop, performs restarts
│   ├── recovery.py           decision logic, restart-loop guard, statistics (Docker-free)
│   ├── dashboard.py          dashboard + JSON/CSV API
│   ├── storage.py            persistent logs and state
│   ├── templates/dashboard.html
│   ├── requirements.txt
│   └── Dockerfile
├── tests/                    36 unit tests (app, recovery logic, monitor with fake Docker)
├── scripts/
│   ├── integration_test.py   end-to-end test used locally and in CI
│   └── demo.ps1              PowerShell helper for the demonstration
├── docs/                     setup, tests, demo, viva, screenshots
├── logs/                     persistent logs (git-ignored)
├── .github/workflows/docker-ci.yml
├── docker-compose.yml
├── docker-compose.broken.yml demo override: permanently broken service
├── .dockerignore  .gitignore  .gitattributes
└── requirements.txt          dev/CI dependencies
```

## 8. Project workflow

1. `docker compose up` starts `sh-web`, `sh-web2` and `sh-monitor`.
2. Docker runs the `HEALTHCHECK` for each app every 5 s. Two failures in a row ⇒ `unhealthy`.
3. Every 3 s the monitor reads each container's `State.Status`, `State.Health.Status` and `RestartCount`.
4. **Unhealthy:** after 2 consecutive unhealthy polls the monitor restarts that container only.
5. **Crashed:** Docker restarts it; the monitor notices `RestartCount` increased and records a crash and its recovery time.
6. **Stopped for more than 10 s:** the monitor starts it.
7. **Loop guard:** at most 3 recovery attempts per 120 s with 20 s between attempts. If that does not
   fix it, automatic recovery pauses ("Recovery paused" on the dashboard) until the container
   becomes healthy, someone presses *Resume recovery*, or 5 minutes pass.
8. Every event goes to `logs/recovery.log`, `logs/events.jsonl` and `docker compose logs monitor`;
   statistics persist in `logs/state.json`.

**How recovery time is measured:** from the moment the monitor first sees the failure until
the container reports `healthy` again. Detection itself takes up to about 10 s (health-check
interval × retries) and is not included.

## 9. Installation

Requirements: Windows 10/11, **Docker Desktop** (WSL 2 backend, Linux containers), Git, Python 3.12
(only if you want to run the tests outside Docker). See [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md).

```powershell
docker --version
docker compose version
```

## 10. Execution

```powershell
docker compose up -d --build        # start everything
docker compose ps                   # status, shows (healthy) / (unhealthy)
docker compose logs -f monitor      # live recovery events
docker compose down                 # stop and remove containers (logs/ is kept)
```

Helper commands (optional):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1 status
powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1 fail A
```

Run the tests on your machine:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -v
python scripts/integration_test.py --down    # needs Docker running
```

## 11. Testing scenarios

| # | Scenario | Proves |
|---|---|---|
| 1 | Normal operation | stack starts, both containers `healthy` |
| 2 | Application failure | `/health` returns 503, Docker marks `unhealthy`, monitor logs the failure |
| 3 | Automatic recovery | monitor restarts only the failed container, it becomes healthy again |
| 4 | Container crash | Docker's restart policy restarts it, `RestartCount` increases, monitor records it |
| 5 | GitHub Actions | push triggers tests, image builds and integration test |
| 6 | Restart-loop protection | a permanently broken container is *not* restarted forever |

Commands, expected output and what to show faculty: [docs/TEST_SCENARIOS.md](docs/TEST_SCENARIOS.md).

## 12. Expected results

* Application failure is detected as `unhealthy` about 10 s after `/fail`.
* The monitor restarts the container about 3 to 6 s later; it is healthy again about 5 to 10 s after that.
  Typical total: **20 to 40 s with no manual action**.
* `sh-web2` is untouched while `sh-web` is recovering.
* Crash: Docker restarts the process within a couple of seconds; `RestartCount` increments.
* The dashboard shows failures, restarts, last failure/recovery time, recovery durations and uptime %.
* A broken container gets at most 3 restarts, then recovery pauses.
* GitHub Actions turns green after the integration test passes.

## 13. Advantages

* Closes the gap Docker leaves: unhealthy containers are actually restarted.
* Only the affected container restarts.
* Safe by design: cooldown, restart budget, circuit breaker, grace period for Docker's own policy.
* Persistent logs and statistics survive monitor restarts.
* Only Docker, Python and Flask; runs on a laptop.
* The decision logic is Docker-independent and unit tested (36 tests).
* CI verifies the whole behaviour automatically with failure injection.

## 14. Limitations

* **Docker health checks** only report status. They detect what `/health` tests; a health endpoint that
  always returns 200 hides real problems. Detection is delayed by `interval × retries`.
* **Restart policies** act only on process exit, ignore `unhealthy`, and have an exponential back-off between restarts.
  `unless-stopped` will not restart a container you stopped manually (the monitor will start it after the grace period).
* **Polling:** the monitor checks every 3 s, so very short events are inferred from `RestartCount`
  rather than observed. Docker's events API would be more immediate.
* Restarting fixes transient faults, not bugs, bad configuration or missing dependencies (hence the loop guard).
* Single host only: no failover to another machine and no state migration.
* **Security:** mounting `/var/run/docker.sock` gives the monitor control over all containers on the host
  (root-equivalent). Acceptable for a lab or demo, not for production without hardening.
  The `/fail`, `/restore`, `/crash` endpoints and dashboard buttons exist for demonstration only and must not be exposed publicly.
* The Flask development server is used for simplicity; production should use gunicorn or waitress.
* If the monitor container itself dies, Docker restarts it (`unless-stopped`), but nobody watches the monitor.
* GitHub Actions is **CI**, not runtime monitoring: it cannot see containers on your PC.

## 15. Future scope

* Use the Docker events stream for instant detection.
* Alerts by e-mail, Telegram or Slack when the circuit opens.
* Prometheus metrics and a Grafana dashboard; historical charts.
* Dependency-aware recovery (restart a database before its clients).
* Kubernetes liveness/readiness probes or Docker Swarm for multi-host self-healing.
* Authentication on the dashboard, a socket proxy with least privilege, and a production WSGI server.
* Deploy the stack from GitHub Actions to a server (CD).

## 16. Conclusion

The project demonstrates that reliable container operation needs three cooperating pieces:
health checks for detection, restart policies for crashes, and an explicit recovery controller
for unhealthy containers. Together with persistent logging, loop protection, a live dashboard
and automated CI testing, the result is a small but complete self-healing system that
shortens downtime from "until someone notices" to a few seconds, while being explicit about
where Docker's built-in mechanisms stop.

## 17. Configuration reference

Set in `docker-compose.yml` under the `monitor` service.

| Variable | Default | Meaning |
|---|---|---|
| `POLL_INTERVAL` | 3 | seconds between checks |
| `UNHEALTHY_POLLS` | 2 | consecutive unhealthy polls before restart |
| `COOLDOWN_SECONDS` | 20 | minimum time between two recovery attempts |
| `MAX_RESTARTS` / `WINDOW_SECONDS` | 3 / 120 | restart budget in a sliding window |
| `STOPPED_GRACE_SECONDS` | 10 | time given to Docker's restart policy before the monitor starts a stopped container |
| `CIRCUIT_RESET_SECONDS` | 300 | automatic resume after recovery was paused |
| `MONITOR_LABEL` | `selfheal.monitor=true` | which containers to watch |

Health check parameters (in `app/Dockerfile`): `--interval=5s --timeout=3s --start-period=5s --retries=2`.

### API

| Endpoint | Description |
|---|---|
| `GET :8080/api/status` | live statistics and recent events (JSON) |
| `GET :8080/api/report` | monitoring report (JSON) |
| `GET :8080/report.csv` | monitoring report (CSV download) |
| `GET :5000/health` | 200 healthy / 503 failed |
| `/fail`, `/restore`, `/crash` | demo controls on each app |
