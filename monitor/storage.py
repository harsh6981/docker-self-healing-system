"""Persistent logging and state storage (files under /logs, a bind mount)."""
import json
import os
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class EventLog:
    """Callable used as ``event_fn``. Writes three places:

    * logs/recovery.log  human readable text (open in Notepad / VS Code)
    * logs/events.jsonl  one JSON object per line (machine readable)
    * stdout             visible with `docker compose logs monitor`
    Also keeps the latest events in memory for the dashboard.
    """

    def __init__(self, log_dir: str, keep: int = 200):
        self.dir = log_dir
        self.text_path = os.path.join(log_dir, "recovery.log")
        self.json_path = os.path.join(log_dir, "events.jsonl")
        self._recent = deque(maxlen=keep)
        self._lock = threading.Lock()
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as exc:
            print(f"[storage] cannot create {log_dir}: {exc}", file=sys.stderr)
        self._load_recent()

    def _load_recent(self) -> None:
        try:
            with open(self.json_path, "r", encoding="utf-8") as fh:
                for line in fh.readlines()[-self._recent.maxlen:]:
                    try:
                        self._recent.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            pass

    def __call__(self, level: str, container: str, event: str, message: str) -> None:
        now = time.time()
        entry = {"time": now, "iso": iso(now), "level": level,
                 "container": container, "event": event, "message": message}
        line = f"{entry['iso']} [{level}] {container} {event} - {message}"
        with self._lock:
            self._recent.append(entry)
            print(line, flush=True)
            try:
                with open(self.text_path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                with open(self.json_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except OSError as exc:
                print(f"[storage] cannot write logs: {exc}", file=sys.stderr, flush=True)

    def recent(self, n: int = 60):
        with self._lock:
            return list(self._recent)[-n:][::-1]   # newest first


def load_state(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def save_state(path: str, data: dict) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)
    except OSError:
        try:   # fallback for file systems that refuse rename
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
        except OSError as exc:
            print(f"[storage] cannot save state: {exc}", file=sys.stderr, flush=True)
