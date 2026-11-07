# Final Demonstration (about 9 minutes)

## Before you walk in (5 minutes of preparation)

* Docker Desktop running; `docker compose down` run once so you start from zero.
* Project already pushed to GitHub, with at least one green workflow run (as a fallback).
* Browser tabs ready: dashboard `localhost:8080`, GitHub **Actions** tab. Do not open the app pages yet.
* Two PowerShell windows in the project folder: **Window 1** for commands, **Window 2** for the live log.
* Run `docker compose build` once beforehand so the live start takes seconds, not minutes.
* Clear old logs for a clean story: `Remove-Item .\logs\*.log, .\logs\*.jsonl, .\logs\state.json -ErrorAction SilentlyContinue`

## Sequence

| Time | Do | Say |
|---|---|---|
| 0:00 | Show the README architecture diagram. | "Docker restart policies only react when a process exits. A container that is running but broken is just labelled *unhealthy*, and nobody restarts it. My project adds the missing piece: a monitor that detects and heals it, safely." |
| 0:45 | **Window 1:** `docker compose up -d --build` | "One command starts two sample apps and the monitor." |
| 1:15 | `docker compose ps` | "Docker's own HEALTHCHECK reports `healthy` for both apps; it probes `/health` every 5 seconds." |
| 1:30 | **Window 2:** `Get-Content .\logs\recovery.log -Tail 20 -Wait`<br>Browser: open `localhost:8080`. | "This is the live dashboard. Everything is read from the Docker engine. Both containers are healthy, zero failures, zero restarts. Logs are stored on disk, not inside the container." |
| 2:15 | Click **Fail** on `sh-web` (or `.\scripts\demo.ps1 fail A`). | "I now simulate a real-world fault: the process is alive, but the application returns HTTP 503." |
| 2:30 | **Window 1:** `docker ps --filter name=sh- --format "table {{.Names}}\t{{.Status}}"` (repeat) | "Within seconds Docker marks it `unhealthy`. Note it is still *running*. Docker will not fix this on its own." |
| 3:00 | Point to dashboard (amber **Unhealthy**) and Window 2 (`FAILURE_DETECTED`). | "Failure detected and logged." |
| 3:30 | Wait for `RESTART_ISSUED`, then `RECOVERED`. | "The monitor restarted only this container after two consecutive unhealthy checks. Now it is healthy again, and the application works." |
| 4:30 | Dashboard: failures 1, restarts 1, recovery time. `docker ps`: compare uptimes. | "Counters, last failure and recovery times, and recovery duration. `sh-web2` kept running, so only the faulty container was restarted." |
| 5:00 | Click **Crash** on `sh-web2` (or `.\scripts\demo.ps1 crash B`). Then `docker inspect -f "RestartCount={{.RestartCount}}" sh-web2` | "Now the process itself dies. This case Docker's restart policy handles. See `RestartCount` is 1 and the dashboard credits it to the *Docker policy*, not to my monitor. Two failure types, two mechanisms." |
| 6:00 | Click **Download report (CSV)** or open `localhost:8080/api/report`. | "The system also produces a report: uptime percentage, failures, recoveries, average recovery time." |
| 6:30 | *(Optional, 1 min)* `docker compose -f docker-compose.yml -f docker-compose.broken.yml up -d` and show the dashboard after about a minute. Skip if short on time; mention it instead. | "What if restarting never helps? The monitor allows 3 attempts, then pauses recovery and raises an error instead of looping forever." |
| 7:00 | Edit README (or `Add-Content README.md "`nDemo run"`), then `git add .`, `git commit -m "Demo change"`, `git push` | "Now the CI side. Pushing to `main` triggers GitHub Actions." |
| 7:30 | Browser: GitHub **Actions** tab, open the running workflow. | "This runs in GitHub's cloud: validates the Python code, runs 36 unit tests, builds the Docker images, validates the Compose file, and runs an end-to-end failure-injection test. It tests my *code*. It does not monitor my laptop. Runtime monitoring is the monitor container." |
| 8:30 | Show a previous green run if the current one is still running. Expand "Integration test". | "Same self-healing behaviour proven automatically in the cloud." |
| 9:00 | Summarise and mention limitations: polling, Docker socket security, single host. | "Limitations are documented; future work is events API, alerts and Kubernetes." |

## Cleanup after the demo

```powershell
docker compose down
```

## If something goes wrong

| Problem | Quick recovery |
|---|---|
| Dashboard shows nothing | `docker compose up -d --force-recreate monitor`, refresh. |
| Recovery seems slow | Detection plus restart takes up to about 40 s; talk through the architecture while waiting. |
| Workflow still running | Show the previous green run and the live step log. |
| Port conflict | Change the left side of the `ports:` mapping and mention it. |
