import json
import os
import re
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
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


@dataclass(frozen=True)
class LocalService:
    process: subprocess.Popen
    url: str
    instance_id: str


def poll_health(status, service):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and service.process.poll() is None:
        try:
            response = urlopen(service.url + "/health", timeout=1)
        except HTTPError as exc:
            response = exc
        except (URLError, TimeoutError):
            time.sleep(0.05)
            continue
        with response:
            assert response.headers.get("TradeLang-Instance") == service.instance_id
            if response.status == status:
                return json.load(response)
        time.sleep(0.05)
    pytest.fail(
        f"Expected local health status {status}, process exit {service.process.poll()}"
    )


@contextmanager
def local_app(root, output, *, api_port=0):
    ready = output.with_suffix(".ready.json")
    with output.open("w") as log:
        process = subprocess.Popen(
            [
                "tradelang-local",
                "--data-root",
                str(root),
                "--api-port",
                str(api_port),
                "--ready-file",
                str(ready),
            ],
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 20
            while (
                not ready.is_file()
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            if not ready.is_file() or process.poll() is not None:
                raise RuntimeError(
                    f"Test supervisor did not start. {output.read_text()}"
                )
            startup = json.loads(ready.read_text())
            assert startup["pid"] == process.pid
            assert startup["data_root"] == str(root.resolve())
            address = urlsplit(startup["url"])
            assert address.scheme == "http" and address.hostname == "127.0.0.1"
            assert address.port
            service = LocalService(process, startup["url"], startup["instance_id"])
            poll_health(200, service)
            yield service
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
    with local_app(root, log) as service:
        assert poll_health(200, service)["worker_available"]
        duplicate = subprocess.run(
            ["tradelang-local", "--data-root", str(root), "--api-port", "0"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        assert duplicate.returncode != 0 and "active runner" in duplicate.stderr
        busy_port = subprocess.run(
            [
                "tradelang-local",
                "--data-root",
                str(tmp_path / "other"),
                "--api-port",
                str(urlsplit(service.url).port),
            ],
            capture_output=True,
            text=True,
            timeout=4,
        )
        assert busy_port.returncode != 0 and "startup failed" in busy_port.stderr
        worker = int(re.search(r"worker started \(PID (\d+)\)", log.read_text())[1])
        api = int(re.search(r"Started server process \[(\d+)\]", log.read_text())[1])
        os.kill(worker, signal.SIGTERM)
        assert not poll_health(503, service)["worker_available"]
        with open("docs/fixtures/core.trade") as strategy:
            source = strategy.read()
        request = Request(
            service.url + "/api/v1/strategies/validate",
            data=json.dumps({"source": source}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:3000",
            },
        )
        with urlopen(request, timeout=2) as response:
            assert json.load(response)["valid"]
    assert service.process.returncode == 0
    for pid in (worker, api):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    with local_app(root, tmp_path / "restart.log") as restarted:
        assert poll_health(200, restarted)["worker_available"]
        assert restarted.instance_id != service.instance_id


def test_local_app_rejects_a_healthy_decoy_on_the_requested_port(tmp_path):
    requests = []

    class Decoy(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.command)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"worker_available":true}')

        do_POST = do_GET

    with ThreadingHTTPServer(("127.0.0.1", 0), Decoy) as decoy:
        thread = threading.Thread(target=decoy.serve_forever)
        thread.start()
        try:
            port = decoy.server_address[1]
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                assert json.load(response)["worker_available"]
            requests.clear()
            with pytest.raises(RuntimeError, match="startup failed"):
                with local_app(
                    tmp_path / "decoy", tmp_path / "decoy.log", api_port=port
                ):
                    pytest.fail("A decoy endpoint was accepted as the test supervisor")
            with (
                local_app(tmp_path / "left", tmp_path / "left.log") as left,
                local_app(tmp_path / "right", tmp_path / "right.log") as right,
            ):
                assert len({urlsplit(s.url).port for s in (left, right)} | {port}) == 3
                assert left.instance_id != right.instance_id
            assert requests == []
        finally:
            decoy.shutdown()
            thread.join()
