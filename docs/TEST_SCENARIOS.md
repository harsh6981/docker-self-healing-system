# Practical Test Scenarios

Assumes `docker compose up -d --build` has been run and everything is healthy.
Timings are typical; allow a few seconds either way.

Useful windows to keep open during all tests:

* Browser: http://localhost:8080 (dashboard)
* PowerShell A: `docker compose logs -f monitor`  or  `Get-Content .\logs\recovery.log -Tail 20 -Wait`
* PowerShell B: for the commands below

---

## Test 1: Normal operation

**Objective.** Show that the stack starts, the apps are reachable and Docker reports them healthy.

**Commands**
```powershell
docker compose up -d --build
docker compose ps
Invoke-RestMethod http://localhost:5000/health
Invoke-RestMethod http://localhost:5001/health
```

**Expected output**
```
NAME         ...  STATUS                    PORTS
sh-monitor   ...  Up 20 seconds             0.0.0.0:8080->8080/tcp
sh-web       ...  Up 20 seconds (healthy)   0.0.0.0:5000->5000/tcp
sh-web2      ...  Up 20 seconds (healthy)   0.0.0.0:5001->5000/tcp

status  app
------  ---
healthy Service A
```

**Actual result to verify**
- [ ] `sh-web` and `sh-web2` show `(healthy)`
- [ ] http://localhost:5000 shows a green **Healthy** badge
- [ ] Dashboard shows 2 containers monitored, 2 healthy, 0 failures, 0 restarts

**Show faculty.** `docker compose ps`, the app page, and the dashboard with two Healthy rows.
Point out the `(healthy)` text: it comes from the Dockerfile `HEALTHCHECK`.

---

## Test 2: Application failure detection

**Objective.** Simulate a failure where the process stays alive but the application is broken, and show that it is detected.

**Commands** (run these straight after each other and watch)
```powershell
Invoke-RestMethod http://localhost:5000/fail
docker ps --filter name=sh-web --format "table {{.Names}}\t{{.Status}}"
```
Run the `docker ps` command again every few seconds.

**Expected output**
1. `/fail` returns `Failure simulated: /health now returns 503`.
2. Immediately, `sh-web` still says `Up ... (healthy)` (Docker has not noticed yet).
3. After about 5 to 10 s the status becomes `Up ... (unhealthy)`. The container is still **running**.
4. Monitor log / `recovery.log`:
```
[WARNING] sh-web FAILURE_DETECTED - Failure #1: health check reports unhealthy
```
5. Dashboard: `sh-web` badge turns amber **Unhealthy**, Failures = 1.

**Actual result to verify**
- [ ] `/health` returns 503: `curl.exe -i http://localhost:5000/health`
- [ ] Docker status changes to `(unhealthy)`
- [ ] `FAILURE_DETECTED` line exists in `logs\recovery.log`
- [ ] `sh-web2` is still healthy

**Show faculty.** That Docker alone only *labels* the container unhealthy. Do not expect it to restart by itself:
this is exactly the gap the monitor fills.

---

## Test 3: Automatic recovery

**Objective.** Show that the monitor restarts the unhealthy container and the application becomes healthy again, without touching `sh-web2`.

**Commands.** Continue directly from Test 2 (or run `/fail` again) and just watch:
```powershell
docker ps --filter name=sh- --format "table {{.Names}}\t{{.Status}}"
Get-Content .\logs\recovery.log -Tail 10
Invoke-RestMethod http://localhost:5000/health
```

**Expected output** (within about 20 to 40 s of `/fail`)
```
[WARNING] sh-web FAILURE_DETECTED - Failure #1: health check reports unhealthy
[INFO]    sh-web RESTART_ISSUED   - Restarted container (attempt 1/3 in the last 120s)
[SUCCESS] sh-web RECOVERED        - Healthy again after 9.4s
```
(the number of seconds will differ). `sh-web` returns to `(healthy)`; `/health` returns `healthy`
because the restart reset the simulated failure.

Dashboard row for `sh-web`: Failures 1, Restarts 1 ("recovery logic 1, Docker policy 0"),
Last failure and Last recovery timestamps filled, Recovery time about 9 s.

**Actual result to verify**
- [ ] Log shows FAILURE_DETECTED, RESTART_ISSUED, RECOVERED in this order
- [ ] `docker ps` shows `sh-web` with a *small* uptime (it was restarted) and `sh-web2` with a *long* uptime (it was not)
- [ ] Dashboard shows the recovery duration and restart counters

**Show faculty.** The log lines, the uptime difference between the two containers
(proves only the failed one restarted), and the dashboard counters.
The same can be triggered from the dashboard with the **Fail** button.

---

## Test 4: Container crash (Docker restart policy)

**Objective.** Kill the process and show that Docker's restart policy (not the monitor) restarts it, and that the restart is counted.

**Commands**
```powershell
docker inspect -f "RestartCount={{.RestartCount}}" sh-web2
Invoke-RestMethod -Method Post http://localhost:5001/crash
Start-Sleep -Seconds 5
docker ps -a --filter name=sh-web2 --format "table {{.Names}}\t{{.Status}}"
docker inspect -f "RestartCount={{.RestartCount}}  ExitCode={{.State.ExitCode}}" sh-web2
```

**Expected output**
```
RestartCount=0
...
sh-web2   Up 4 seconds (health: starting)      (or briefly: Restarting / Exited (1))
RestartCount=1  ExitCode=...
```
Log:
```
[INFO]    sh-web2 DOCKER_RESTART   - Docker restart policy restarted the container (RestartCount=1)
[WARNING] sh-web2 FAILURE_DETECTED - Failure #1: process crashed ...  (or: container stopped (exit code 1))
[SUCCESS] sh-web2 RECOVERED        - Healthy again after ...s
```
There is **no** `RESTART_ISSUED` for this container: the monitor deliberately gives Docker's policy time first
(`STOPPED_GRACE_SECONDS`, 10 s).

**Actual result to verify**
- [ ] `RestartCount` increased by 1
- [ ] Dashboard: `sh-web2` Restarts shows "Docker policy 1" and "recovery logic 0"
- [ ] The container is healthy again after a few seconds

**Show faculty.** The contrast with Test 3: *crash* is handled by the restart policy, *unhealthy* needs the monitor.
Optional extra: `docker stop sh-web2` is a *manual stop*. `unless-stopped` will not restart it, but after 10 s the
monitor logs the failure and starts it (`RESTART_ISSUED - Started container`).

---

## Test 5: GitHub Actions

**Objective.** Show that every push to `main` is automatically tested, built and validated in the cloud.

**Commands** (make a small change, then push)
```powershell
Add-Content README.md "`nLast tested: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
git add .
git commit -m "Update README for CI demonstration"
git push
```
Open `https://github.com/YOUR-USERNAME/docker-self-healing-system/actions`.

**Expected output.** A new run named after your commit message appears (yellow spinner), then turns green after 3 to 5 minutes with these steps:
checkout, set up Python, install dependencies, validate Python, **36 unit tests pass**, build both Docker images,
validate Compose config, integration test (`INTEGRATION TEST PASSED`), report result.

**Actual result to verify**
- [ ] Green checkmark on the commit and on the Actions run
- [ ] Step "Run unit tests" shows `36 passed`
- [ ] Step "Integration test" prints the five numbered sections and `INTEGRATION TEST PASSED`
- [ ] The run summary shows the recovery log from the test

**Show faculty.** The run, expand "Integration test" to show failure injection happening in the cloud, and state clearly:
GitHub Actions tests the *code*; the *monitor container* does the runtime monitoring on your machine.

---

## Test 6: Restart-loop protection (bonus, recommended)

**Objective.** Show that a container that can never become healthy is not restarted forever.

**Commands**
```powershell
docker compose -f docker-compose.yml -f docker-compose.broken.yml up -d --build
Get-Content .\logs\recovery.log -Tail 20 -Wait
```
Wait about 1.5 minutes.

**Expected output**
```
[WARNING] sh-web FAILURE_DETECTED - Failure #1: health check reports unhealthy
[INFO]    sh-web RESTART_ISSUED   - Restarted container (attempt 1/3 in the last 120s)
[INFO]    sh-web RESTART_ISSUED   - Restarted container (attempt 2/3 in the last 120s)
[INFO]    sh-web RESTART_ISSUED   - Restarted container (attempt 3/3 in the last 120s)
[ERROR]   sh-web CIRCUIT_OPEN     - 3 recovery attempts in 120s did not fix the container. Automatic recovery paused ...
```
The dashboard shows `sh-web` as dark red **Recovery paused** with a *Resume recovery* button; no further restarts happen.

**Actual result to verify**
- [ ] Exactly 3 `RESTART_ISSUED` events, then `CIRCUIT_OPEN`
- [ ] No more restarts after that (`docker ps` uptime keeps growing)

**Fix and return to normal**
```powershell
docker compose up -d --force-recreate web
```
The container comes back healthy, the circuit closes automatically.

**Show faculty.** This answers "what if restarting never helps?": the system stops, logs an error and waits for a human.
