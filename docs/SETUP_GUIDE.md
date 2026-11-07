# Setup Guide (Windows + Docker Desktop)

Do this later at your own pace. Total time: about 20 minutes plus downloads.

## Step 1. Environment verification

1. Install **Docker Desktop** (https://www.docker.com/products/docker-desktop/). Keep the default
   "Use WSL 2 instead of Hyper-V" option. Restart Windows if asked.
2. Start Docker Desktop and wait until the whale icon says *Engine running*.
3. Install **Git for Windows** (https://git-scm.com/download/win).
4. *(Optional, only to run tests outside Docker)* install **Python 3.12** from python.org and tick "Add python.exe to PATH".
5. Open **PowerShell** and check:

```powershell
docker --version
docker compose version
docker run --rm hello-world
git --version
python --version
```

Expected: version numbers, and `hello-world` prints "Hello from Docker!".
Docker Desktop must be in **Linux containers** mode (default). If `docker` is not found, restart PowerShell or Windows.

## Step 2. Get the project

Unzip `docker-self-healing-system.zip` somewhere simple, e.g. `C:\Projects\`, then:

```powershell
cd C:\Projects\docker-self-healing-system
dir
```

You should see `app`, `monitor`, `tests`, `docker-compose.yml`, `README.md` and more.

## Step 3. Run the system

```powershell
docker compose up -d --build
```

The first build downloads the Python image and takes 1 to 3 minutes. Expected end of output:

```
 ✔ Container sh-web      Started
 ✔ Container sh-web2     Started
 ✔ Container sh-monitor  Started
```

Wait about 15 seconds, then:

```powershell
docker compose ps
```

Expected: `sh-web`, `sh-web2` show `Up ... (healthy)`; `sh-monitor` shows `Up`.
(Right after start you may briefly see `(health: starting)`; that is normal.)

Open in the browser:

* http://localhost:8080 monitoring dashboard (both containers should be **Healthy**)
* http://localhost:5000 Service A, http://localhost:5001 Service B

Verify the monitor works:

```powershell
docker compose logs monitor
Get-Content .\logs\recovery.log
```

You should see a `MONITOR_STARTED` line, and the files `recovery.log`, `events.jsonl`, `state.json` appear in the `logs` folder.

## Step 4. Run the automated tests (optional but recommended)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -v
```

Expected: `36 passed`. If activation is blocked: `Set-ExecutionPolicy -Scope Process Bypass`, then activate again.

Full end-to-end test (restarts the stack and injects failures; takes about 1 to 2 minutes):

```powershell
python scripts/integration_test.py --down
```

Expected last line: `INTEGRATION TEST PASSED`.

## Step 5. Create the GitHub repository

1. Sign in at https://github.com and click **New repository**.
2. **Repository name:** `docker-self-healing-system`
3. **Description:** `Automated Docker container health checks and self-healing system using Docker Compose, Python/Flask and GitHub Actions`
4. Public or Private, as you prefer. **Do not** tick "Add README / .gitignore / license" (the project already has them).
5. Click **Create repository**, then run in PowerShell (replace `YOUR-USERNAME`):

```powershell
cd C:\Projects\docker-self-healing-system
git init -b main
git config user.name  "Your Name"
git config user.email "you@example.com"
git add .
git status
git commit -m "Initial commit: Docker self-healing system"
git remote add origin https://github.com/YOUR-USERNAME/docker-self-healing-system.git
git push -u origin main
```

A browser window may ask you to sign in to GitHub (Git Credential Manager). After the push, refresh the repository page.

`git status` before committing should **not** list `logs/recovery.log` or `.venv` (they are in `.gitignore`).

## Step 6. Check GitHub Actions

1. Open your repository, click the **Actions** tab.
2. The workflow **Docker CI** starts automatically on each push to `main`. Click the run.
3. Steps 1 to 9 should all show green checkmarks (about 3 to 5 minutes). Click the job summary to see the recovery log
   produced by the integration test. Under the run, **Artifacts** contains `recovery-logs`.
4. Optional badge for your README (replace `YOUR-USERNAME`):

```markdown
![Docker CI](https://github.com/YOUR-USERNAME/docker-self-healing-system/actions/workflows/docker-ci.yml/badge.svg)
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `error during connect ... docker_engine` | Docker Desktop is not running. Start it and retry. |
| `port is already allocated` (5000, 5001 or 8080) | Another program uses it. Stop it, or change the left number in `ports:` of `docker-compose.yml`, e.g. `"5050:5000"`. |
| Dashboard says **Docker unreachable** | Docker Desktop > Settings > Advanced: enable "Allow the default Docker socket to be used" (if present), then `docker compose up -d --force-recreate monitor`. |
| Dashboard empty | Containers need the label `selfheal.monitor=true`; run `docker compose up -d`. |
| `logs` files not created | Docker Desktop > Settings > Resources > File sharing: make sure the project drive is shared (WSL 2 does this automatically). |
| Container stuck at `(health: starting)` | Wait 15 s. If it stays, run `docker compose logs web`. |
| `Set-ExecutionPolicy` / script blocked | Use `powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1 status`. |
| `curl` behaves strangely in PowerShell | `curl` is an alias for `Invoke-WebRequest`. Use `Invoke-RestMethod` or `curl.exe`. |
| GitHub push rejected / auth error | Sign in via the browser prompt, or create a Personal Access Token and use it as the password. |
| Actions fails at step 8 | Open the step log; the job prints `docker compose logs` on failure. Re-run the job once (cold runners can be slow). |
| Start fresh | `docker compose down -v` and delete the contents of `logs\` (keep `.gitkeep`). |

## Cleaning up

```powershell
docker compose down          # remove containers (logs\ stays)
docker image prune -f        # optional: remove unused images
```
