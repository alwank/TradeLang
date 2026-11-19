import json
import os
import re
import signal
import subprocess
import time
from contextlib import contextmanager
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from tradelang.api import create_app
from tradelang.supervisor import is_fresh


def test_health_contract_and_stale_heartbeat():
    now = 100.0
    client = TestClient(
        create_app(worker_available=lambda: is_fresh(86.0, clock=lambda: now)),
        base_url="http://127.0.0.1:8000",
        client=("127.0.0.1", 1234),
    )
    ready = client.get("/health")
    assert ready.status_code == 200
    assert ready.json() == dict(
        schema_version=1, status="ok", worker_available=True, queue_depth=0
    )
    now = 102.0
    stale = client.get("/health")
    assert stale.status_code == 503
    assert stale.json() == dict(
        schema_version=1, status="degraded", worker_available=False, queue_depth=0
    )
    assert client.get("/health", headers={"Host": "localhost:8000"}).status_code == 403
    public = TestClient(
        create_app(), base_url="http://127.0.0.1:8000", client=("192.0.2.1", 1234)
    )
    assert public.get("/health").status_code == 403
    standalone = TestClient(
        create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 1234)
    )
    assert standalone.get("/health").status_code == 503
    response_schema = client.get("/openapi.json").json()["paths"]["/health"]["get"][
        "responses"
    ]
    assert {"200", "403", "503"} == set(response_schema)


def poll_health(status, process):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and process.poll() is None:
        try:
            with urlopen("http://127.0.0.1:8000/health", timeout=1) as response:
                if response.status == status:
                    return json.load(response)
        except HTTPError as exc:
            with exc:
                if exc.code == status:
                    return json.load(exc)
        except (URLError, TimeoutError):
            pass
        time.sleep(0.05)
    pytest.fail(f"Expected local health status {status}, process exit {process.poll()}")


@contextmanager
def local_app(root, output):
    with output.open("w") as log:
        process = subprocess.Popen(
            ["tradelang-local", "--data-root", str(root)], stdout=log, stderr=log
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=9)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise


@pytest.mark.skipif(os.name == "nt", reason="POSIX child signal assertions")
def test_installed_supervisor_lifecycle(tmp_path):
    root = tmp_path / "data"
    log = tmp_path / "supervisor.log"
    with local_app(root, log) as process:
        assert poll_health(200, process)["worker_available"]
        duplicate = subprocess.run(
            ["tradelang-local", "--data-root", str(root)],
            capture_output=True,
            text=True,
            timeout=4,
        )
        assert duplicate.returncode != 0 and "active runner" in duplicate.stderr
        busy_port = subprocess.run(
            ["tradelang-local", "--data-root", str(tmp_path / "other")],
            capture_output=True,
            text=True,
            timeout=4,
        )
        assert busy_port.returncode != 0 and "startup failed" in busy_port.stderr
        worker = int(re.search(r"worker started \(PID (\d+)\)", log.read_text())[1])
        api = int(re.search(r"Started server process \[(\d+)\]", log.read_text())[1])
        os.kill(worker, signal.SIGTERM)
        assert not poll_health(503, process)["worker_available"]
        with open("docs/fixtures/core.trade") as strategy:
            source = strategy.read()
        request = Request(
            "http://127.0.0.1:8000/api/v1/strategies/validate",
            data=json.dumps({"source": source}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:3000",
            },
        )
        with urlopen(request, timeout=2) as response:
            assert json.load(response)["valid"]
    assert process.returncode == 0
    for pid in (worker, api):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    with local_app(root, tmp_path / "restart.log") as restarted:
        assert poll_health(200, restarted)["worker_available"]
