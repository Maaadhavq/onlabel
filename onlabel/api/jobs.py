"""Document reviews as background jobs with replayable events.

One worker thread runs reviews one at a time (the instance has a tenth of a CPU and the
model quotas are per minute). Every event a job emits is kept, numbered, so the page's
stream can drop and reconnect with Last-Event-ID without losing a claim.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections.abc import Callable

TERMINAL = ("done", "error")


class Job:
    def __init__(self, text: str, labels: list[str] | None, audience: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.text, self.labels, self.audience = text, labels, audience
        self.created = time.time()
        self.events: list[dict] = []
        self.done = False
        self._lock = threading.Lock()

    def emit(self, event: str, data: dict) -> None:
        with self._lock:
            if self.done:
                return
            self.events.append({"id": len(self.events), "event": event, "data": data})
            self.done = event in TERMINAL

    def since(self, index: int) -> tuple[list[dict], bool]:
        with self._lock:
            return list(self.events[index:]), self.done

    def claim_kind(self, n: int) -> str | None:
        with self._lock:
            for ev in self.events:
                if ev["event"] == "claims":
                    return next((c.get("kind") for c in ev["data"]["claims"] if c["n"] == n), None)
        return None

    def claim_review(self, n: int) -> dict | None:
        with self._lock:
            for ev in self.events:
                if ev["event"] == "claim" and ev["data"]["n"] == n:
                    return ev["data"]["review"]
        return None


class JobRunner:
    def __init__(self, run: Callable[[Job], None], keep: int = 200, ttl_s: float = 3600) -> None:
        self._run, self.keep, self.ttl_s = run, keep, ttl_s
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[Job] = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._work, daemon=True, name="document-reviews").start()

    def submit(self, job: Job) -> Job:
        with self._lock:
            self._prune()
            self.jobs[job.id] = job
        ahead = self._queue.qsize()
        if ahead:
            job.emit("queued", {"ahead": ahead})
        self._queue.put(job)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self.jobs.get(job_id)

    def _prune(self) -> None:
        now = time.time()
        stale = [k for k, j in self.jobs.items() if j.done and now - j.created > self.ttl_s]
        for k in stale:
            del self.jobs[k]
        while len(self.jobs) >= self.keep:
            oldest = min(self.jobs.values(), key=lambda j: j.created)
            del self.jobs[oldest.id]

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            try:
                self._run(job)
            except Exception as exc:  # noqa: BLE001 - reported to the page, never swallowed
                job.emit("error", {"message": f"The review stopped: {type(exc).__name__}.", "code": "internal"})
            finally:
                if not job.done:
                    job.emit("done", {})
