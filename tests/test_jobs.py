import threading

from onlabel.api.jobs import Job, JobRunner


def test_events_are_numbered_and_stop_at_a_terminal_event():
    job = Job("text", None, "consumer")
    job.emit("start", {})
    job.emit("claim", {"n": 1, "review": {"status": "supported"}})
    job.emit("done", {})
    job.emit("claim", {"n": 2})  # ignored after done
    events, done = job.since(0)
    assert [e["id"] for e in events] == [0, 1, 2] and done
    assert job.since(2)[0][0]["event"] == "done"
    assert job.claim_review(1) == {"status": "supported"} and job.claim_review(2) is None


def _wait(job: Job, timeout: float = 5.0) -> None:
    ev = threading.Event()

    def poll():
        while not job.since(0)[1]:
            ev.wait(0.01)
        ev.set()

    threading.Thread(target=poll, daemon=True).start()
    assert ev.wait(timeout), "job did not finish"


def test_runner_runs_jobs_and_reports_crashes():
    def run(job):
        if job.text == "boom":
            raise RuntimeError("secret detail")
        job.emit("claims", {"claims": []})

    runner = JobRunner(run)
    ok, bad = runner.submit(Job("fine", None, "hcp")), runner.submit(Job("boom", None, "hcp"))
    _wait(ok), _wait(bad)
    assert [e["event"] for e in ok.since(0)[0]][-1] == "done"
    err = bad.since(0)[0][-1]
    assert err["event"] == "error" and "secret detail" not in err["data"]["message"]
    assert runner.get(ok.id) is ok and runner.get("nope") is None


def test_a_job_remembers_the_labels_its_review_detected():
    job = Job("Ozempic copy", None, "consumer")
    job.emit("start", {"labels": [{"key": "ozempic"}, {"key": "rybelsus"}]})
    assert job.labels is None and job.checked_labels == ["ozempic", "rybelsus"]


def test_a_new_check_counts_the_review_that_is_running():
    gate = threading.Event()

    def run(job):
        if job.text == "first":
            gate.wait(5)
        job.emit("claims", {"claims": []})

    runner = JobRunner(run)
    first = runner.submit(Job("first", None, "consumer"))
    while not runner._busy:  # the worker has picked the first job up
        threading.Event().wait(0.01)
    second = runner.submit(Job("second", None, "consumer"))
    gate.set()
    _wait(first), _wait(second)
    assert second.since(0)[0][0] == {"id": 0, "event": "queued", "data": {"ahead": 1}}
