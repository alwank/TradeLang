"""Own the loopback API and its worker for a single local session."""

import argparse
import json
import multiprocessing as mp
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

HEARTBEAT_SECONDS = 2.0
STALE_SECONDS = 15.0
STARTUP_SECONDS = 20.0
SHUTDOWN_SECONDS = 5.0
LOOPBACK = "127.0.0.1"
API_PORT = 8000
WEB_PORT = 3000


def is_fresh(last: float, clock: Callable[[], float] = time.monotonic) -> bool:
    return last >= 0 and clock() - last <= STALE_SECONDS


@contextmanager
def runner_lock(root: Path) -> Iterator[None]:
    """Keep an OS-held lock open until every supervised child is stopped."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".runner.lock").open("a+b") as file:
        try:
            if sys.platform == "win32":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "The application data directory already has an active runner"
            ) from exc
        yield


def worker_main(control: Connection, ready, root: Path):
    with control:
        try:
            while not ready.wait(0.1):
                if control.poll():
                    return
            from .run_worker import run_jobs

            run_jobs(root, control, HEARTBEAT_SECONDS)
        except (BrokenPipeError, EOFError, OSError):
            return


def api_main(
    listener: socket.socket,
    heartbeat: Any,
    parent_control: Connection,
    root: Path,
    ready,
    web_port: int,
    instance_id: str,
):
    import uvicorn

    from .api import create_app
    from .persistence import Library

    library = Library(root)
    library.recover()
    ready.set()
    api_port = listener.getsockname()[1]

    class SupervisedServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            if self.started:
                try:
                    parent_control.send("ready")
                except OSError:
                    self.should_exit = True

    server = SupervisedServer(
        uvicorn.Config(
            create_app(
                worker_available=lambda: is_fresh(heartbeat.value),
                library=library,
                host=f"{LOOPBACK}:{api_port}",
                origin=f"http://{LOOPBACK}:{web_port}",
                instance_id=instance_id,
            ),
            host=LOOPBACK,
            port=api_port,
            proxy_headers=False,
        )
    )

    def watch_supervisor():
        with parent_control:
            try:
                parent_control.recv()
            except EOFError:
                pass
            finally:
                server.should_exit = True

    threading.Thread(target=watch_supervisor, daemon=True).start()
    with listener:
        server.run(sockets=[listener])
    if not server.started:
        raise SystemExit(1)


def reap(children: Sequence[BaseProcess], frontend: subprocess.Popen | None):
    deadline = time.monotonic() + SHUTDOWN_SECONDS
    if frontend is not None and frontend.poll() is None:
        frontend.terminate()
    for child in children:
        child.join(max(0, deadline - time.monotonic()))
    for child in children:
        if child.is_alive():
            child.terminate()
    for child in children:
        child.join(1)
        if child.is_alive():
            child.kill()
            child.join()
        child.close()
    if frontend is not None:
        try:
            frontend.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            frontend.kill()
            frontend.wait()


def write_readiness(path: Path, root: Path, port: int, instance_id: str) -> None:
    handle = NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(
                {
                    "url": f"http://{LOOPBACK}:{port}",
                    "instance_id": instance_id,
                    "data_root": str(root),
                    "pid": os.getpid(),
                },
                handle,
            )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def supervise(
    root: Path,
    *,
    frontend_command: Sequence[str] | None = None,
    api_port: int = API_PORT,
    web_port: int = WEB_PORT,
    ready_file: Path | None = None,
) -> int:
    ctx = mp.get_context("spawn")
    root = root.resolve()
    with runner_lock(root), socket.create_server((LOOPBACK, api_port)) as listener:
        port = listener.getsockname()[1]
        instance_id = uuid4().hex
        heartbeat = ctx.Value("d", -1.0)
        ready = ctx.Event()
        worker_control, worker_child = ctx.Pipe()
        api_control, api_child = ctx.Pipe()
        worker = ctx.Process(
            name="TradeLang worker",
            target=worker_main,
            args=(worker_child, ready, root),
        )
        api = ctx.Process(
            name="TradeLang API",
            target=api_main,
            args=(listener, heartbeat, api_child, root, ready, web_port, instance_id),
        )
        children: list[BaseProcess] = []
        frontend = None
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        handlers = {
            sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
        }
        try:
            worker.start()
            children.append(worker)
            worker_child.close()
            api.start()
            children.append(api)
            api_child.close()
            listener.close()
            if frontend_command:
                frontend = subprocess.Popen(
                    frontend_command,
                    env={
                        **os.environ,
                        "TRADELANG_API_PORT": str(port),
                        "TRADELANG_WEB_PORT": str(web_port),
                    },
                )
            print(
                f"TradeLang worker started (PID {worker.pid})",
                file=sys.stderr,
                flush=True,
            )
            worker_connected = True
            started = False
            startup_deadline = time.monotonic() + STARTUP_SECONDS
            while not stopping:
                if not api.is_alive():
                    print("TradeLang API stopped unexpectedly", file=sys.stderr)
                    return 1
                if frontend is not None and frontend.poll() is not None:
                    print("TradeLang frontend stopped unexpectedly", file=sys.stderr)
                    return 1
                if worker_connected and worker_control.poll(0.1):
                    try:
                        heartbeat.value = worker_control.recv()
                    except EOFError:
                        worker_connected = False
                if not worker.is_alive():
                    worker_connected = False
                if not worker_connected:
                    heartbeat.value = -1.0
                    time.sleep(0.1)
                if not started and api_control.poll():
                    try:
                        started = api_control.recv() == "ready"
                        if started and ready_file is not None:
                            write_readiness(ready_file, root, port, instance_id)
                    except EOFError:
                        print(
                            "TradeLang API closed its startup channel", file=sys.stderr
                        )
                        return 1
                if not started and time.monotonic() >= startup_deadline:
                    print(
                        "TradeLang API did not become ready before the startup deadline",
                        file=sys.stderr,
                    )
                    return 1
            return 0
        finally:
            for connection in (worker_control, worker_child, api_control, api_child):
                connection.close()
            try:
                reap(children, frontend)
            finally:
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument(
        "--web", type=Path, help="Start the built Next.js app from this directory"
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=API_PORT,
        help="Loopback API port (0 selects a free port)",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=WEB_PORT,
        help="Loopback browser port and allowed origin",
    )
    parser.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not (0 <= args.api_port <= 65535 and 1 <= args.web_port <= 65535):
        parser.error("API port must be 0..65535 and browser port must be 1..65535")
    if args.api_port == args.web_port:
        parser.error("API and browser ports must differ")
    try:
        import uvicorn  # noqa: F401

        frontend = None
        if args.web is not None:
            web = args.web.resolve()
            node = shutil.which("node")
            launcher = web / "node_modules" / "next" / "dist" / "bin" / "next"
            if (
                node is None
                or not launcher.is_file()
                or not (web / ".next" / "BUILD_ID").is_file()
            ):
                raise RuntimeError(
                    "Build the web app with Node.js and npm before starting --web"
                )
            frontend = [
                node,
                str(launcher),
                "start",
                str(web),
                "--hostname",
                LOOPBACK,
                "--port",
                str(args.web_port),
            ]
        status = supervise(
            args.data_root,
            frontend_command=frontend,
            api_port=args.api_port,
            web_port=args.web_port,
            ready_file=args.ready_file,
        )
    except ImportError:
        print(
            "Install TradeLang with the api extra to start the local supervisor.",
            file=sys.stderr,
        )
        status = 1
    except (OSError, RuntimeError) as exc:
        print(f"TradeLang startup failed: {exc}", file=sys.stderr)
        status = 1
    raise SystemExit(status)
