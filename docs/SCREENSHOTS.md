# Screenshots to Capture for Submission

Name files as shown so they sort in the order of your report. Use `Win + Shift + S`.

| # | File name | What it must show |
|---|---|---|
| 1 | `01-docker-version.png` | `docker --version`, `docker compose version` in PowerShell |
| 2 | `02-project-structure.png` | VS Code Explorer or `tree /f` showing the folder structure |
| 3 | `03-compose-up.png` | Output of `docker compose up -d --build` finishing with 3 containers started |
| 4 | `04-compose-ps-healthy.png` | `docker compose ps` with `(healthy)` on `sh-web` and `sh-web2` |
| 5 | `05-app-healthy.png` | Browser at `localhost:5000` with green **Healthy** badge |
| 6 | `06-dashboard-healthy.png` | Dashboard at `localhost:8080`, all containers Healthy, counters 0 |
| 7 | `07-app-failed.png` | App page showing **Failed** after pressing Simulate failure (and `/health` returning 503) |
| 8 | `08-docker-unhealthy.png` | `docker ps` showing `(unhealthy)` |
| 9 | `09-dashboard-unhealthy.png` | Dashboard with an amber **Unhealthy** row and the failure event in the log |
| 10 | `10-recovery-log.png` | `recovery.log` showing FAILURE_DETECTED, RESTART_ISSUED, RECOVERED |
| 11 | `11-dashboard-recovered.png` | Dashboard after recovery: failures 1, restarts 1, recovery time filled |
| 12 | `12-uptime-comparison.png` | `docker ps` showing different uptimes (only the failed container restarted) |
| 13 | `13-crash-restartcount.png` | `docker inspect` showing `RestartCount=1` after `/crash`, plus dashboard "Docker policy 1" |
| 14 | `14-circuit-breaker.png` | Dashboard with **Recovery paused** and the CIRCUIT_OPEN log line (Test 6) |
| 15 | `15-report.png` | `localhost:8080/api/report` or the downloaded CSV opened in Excel |
| 16 | `16-unit-tests.png` | `python -m pytest -v` showing `36 passed` |
| 17 | `17-github-repo.png` | GitHub repository page with files and description |
| 18 | `18-actions-success.png` | Actions run with all steps green |
| 19 | `19-actions-integration-step.png` | Expanded "Integration test" step with `INTEGRATION TEST PASSED` |
| 20 | `20-logs-folder.png` | File Explorer showing `logs\` with `recovery.log`, `events.jsonl`, `state.json` (proves persistence) |

Tip: for 9 to 11 take screenshots in sequence during one failure, so the timestamps match across images.
