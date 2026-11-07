# Viva Preparation: 25 Questions and Answers

## Docker fundamentals

**1. What is Docker and why use containers?**
Docker packages an application with its dependencies into a container that runs the same everywhere.
Containers share the host kernel, so they start fast and use fewer resources than virtual machines.

**2. What is the difference between an image and a container?**
An image is a read-only template (layers: OS files, Python, our code). A container is a running (or stopped)
instance of an image with a writable layer and its own process, network and filesystem view. One image can
start many containers: here `sh-web` and `sh-web2` use the same image.

**3. What is a Dockerfile and what does ours do?**
A text recipe for building an image. Ours starts from `python:3.12-slim`, installs Flask, copies the code,
switches to a non-root user, defines the `HEALTHCHECK` and starts `app.py`.

**4. What is a bind mount and why do we use one?**
It maps a host folder into a container. `./logs:/logs` keeps recovery logs on the host so they survive
container restarts and removal.

## Docker Compose

**5. What is Docker Compose?**
A tool to define and run multi-container applications from one YAML file: services, ports, volumes,
environment, restart policy and dependencies. `docker compose up` creates the network and all containers.

**6. How do the containers talk to each other?**
Compose creates a private network where each container is reachable by its service/container name.
The dashboard calls `http://sh-web:5000/fail` using that DNS name.

**7. What does `depends_on` guarantee?**
Only start order, not readiness. We therefore do not rely on it; the monitor simply retries until Docker answers
and treats containers that are still starting as "starting", not failed.

## Health checks

**8. How does a Docker health check work?**
Docker runs a command inside the container at an interval. Exit code 0 is healthy, 1 is unhealthy.
After `retries` consecutive failures the status becomes `unhealthy`. Statuses: `starting`, `healthy`, `unhealthy`.

**9. Explain our HEALTHCHECK parameters.**
`interval=5s` check every 5 s; `timeout=3s` a slow check counts as failed; `start-period=5s` failures while booting are
ignored; `retries=2` two consecutive failures mean unhealthy. Detection time is roughly interval × retries (about 10 s).

**10. Why is the health check written in Python instead of curl?**
The slim image has no curl/wget; installing them adds size. `healthcheck.py` uses the standard library.

**11. What are the limitations of health checks?**
They only report status; they do not act. They are only as good as the endpoint (a `/health` that always says 200 hides
problems), and detection is delayed by interval × retries.

## Restart policies

**12. What restart policies exist?**
`no`, `on-failure[:max]`, `always`, `unless-stopped`. We use `unless-stopped`: always restart unless the user stopped
the container manually.

**13. Do restart policies restart unhealthy containers?**
No. They act only when the main process exits. A running container with a failing health check stays as it is.
This is why the project needs its own recovery mechanism.

**14. Difference between a crashed, an unhealthy and a stopped container?**
Crashed: the process exited abnormally (e.g. exit code 1); the restart policy handles it. Unhealthy: the process runs but
the health check fails; needs an explicit controller. Stopped: deliberately stopped or removed from running; `unless-stopped`
will not bring it back, so our monitor starts it after a grace period.

## Self-healing architecture

**15. Describe the architecture.**
Two Flask containers with health checks and restart policy, a monitor container with access to the Docker socket,
persistent logs on a bind mount, and a dashboard. The monitor polls Docker, decides with `recovery.py`, acts through the
Docker API and records events.

**16. How do you prevent infinite restart loops?**
Three mechanisms: a minimum cooldown between attempts (20 s), a budget of 3 attempts per 120 s, and a circuit breaker that
pauses recovery and logs an error when the budget is exhausted. It resumes when the container becomes healthy, on a manual
reset, or after 5 minutes.

**17. How do you make sure only the failed container restarts?**
Decisions and actions are per container name. We restart with `container.restart()` on that one container, never
`docker compose restart`. The integration test verifies that `sh-web2`'s start time did not change.

**18. Why does the monitor wait before starting a stopped container?**
To let Docker's own restart policy act first (`STOPPED_GRACE_SECONDS`, 10 s) and avoid both fighting over the container.

**19. How is recovery time measured and what does it not include?**
From the moment the monitor first sees the failure until the container reports healthy. Detection delay
(health check interval × retries) is not included.

**20. What are the security implications of mounting `docker.sock`?**
Whoever controls the socket controls Docker and effectively the host. Acceptable in a controlled demo; in production
use a socket proxy with limited permissions, or an orchestrator.

## Python monitoring logic

**21. How does the monitor read container state?**
Through the Docker SDK for Python: `containers.list(filters={"label": ...})`, then `attrs["State"]["Status"]`,
`attrs["State"]["Health"]["Status"]` and `attrs["RestartCount"]`, which are the same data as `docker inspect`.

**22. How does the monitor tell its own restarts from Docker's restarts?**
`RestartCount` increases only for automatic restarts by the restart policy; a restart through the API does not change it.
We track both separately: "recovery logic" and "Docker policy".

**23. Why is `recovery.py` separate from `monitor.py` and how is it tested?**
`recovery.py` has no Docker dependency: it gets observations and returns actions, so we test it with a fake clock and a fake
action function (cooldown, circuit breaker, recovery timing, uptime). `test_monitor.py` uses a fake Docker client for the
glue code. Result: 36 unit tests without Docker.

## GitHub Actions and CI/CD

**24. What does the GitHub Actions workflow do, and is it monitoring your containers?**
On each push to `main` it checks out code, validates Python, runs unit tests, builds both images, validates the Compose
file and runs an integration test that starts the stack on the runner, injects failures and checks recovery. It does
**not** monitor local containers: it is CI on GitHub's servers. Runtime monitoring is the monitor container.

**25. What are CI and CD, and what is covered here?**
Continuous Integration: automatically build and test every change so errors are found early. Continuous Delivery/Deployment:
automatically release the tested build to an environment. We implement CI fully; CD (deploying to a server) is future scope.

## Extra questions you may get

* *Why not Kubernetes?* It has liveness probes that restart unhealthy pods, but is heavy for a single-host project; our design shows the underlying concept.
* *Why poll instead of Docker events?* Simplicity; events would give instant detection and is listed as future work.
* *What if the monitor crashes?* Docker restarts it (`unless-stopped`); state is restored from `logs/state.json`.
* *What if the app has a real bug?* Restarting will not help; the circuit breaker stops after 3 attempts and raises an error.
