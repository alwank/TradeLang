"""Execute durable backtests in an isolated child of the supervised worker."""

import multiprocessing as mp
import os
import subprocess
import sys
import threading
import time
from uuid import UUID

from .model import Problem
from .persistence import Library
from .persistence.runs import RUN_SECONDS, Runs, run_error
from .portfolio import compile_portfolio, prepare_portfolio
from .portfolio_library import resolve_portfolio_assets
from .portfolio_report import publish_portfolio
from .report import publish
from .run_config import RunSettings, configured_strategy
from .workload import MEMORY_LIMIT_BYTES

CANCEL_SECONDS = 2


class RunCancelled(Exception):
    pass


def publish_job(library, row, destination, progress):
    snapshot = row["snapshot"]
    if "portfolio_assets" in snapshot:
        spec = compile_portfolio(snapshot["source"])
        assets, _ = resolve_portfolio_assets(
            library, spec, snapshot["portfolio_assets"]
        )
        return publish_portfolio(
            prepare_portfolio(spec, assets),
            destination,
            progress=progress,
            expected_fingerprint=snapshot["run_fingerprint"],
            run_id=row["id"],
        )
    primary = library.resolve_dataset(UUID(row["dataset_id"]))
    profile = (
        library.resolve_dataset(UUID(row["profile_dataset_id"]))
        if row["profile_dataset_id"] is not None
        else None
    )
    if primary is None or (row["profile_dataset_id"] is not None and profile is None):
        raise Problem("E_RUN_DATA", "A dataset from the run snapshot is unavailable")
    feeds = {}
    for name, ident in snapshot.get("feed_ids", {}).items():
        dataset = library.resolve_dataset(UUID(ident))
        if dataset is None:
            raise Problem("E_RUN_DATA", f"The dataset from feed {name} is unavailable")
        feeds[name] = dataset
    return publish(
        configured_strategy(
            snapshot["source"],
            RunSettings.model_validate(snapshot["run_settings"])
            if "run_settings" in snapshot
            else None,
            parameters=snapshot.get("parameter_overrides")
            if "run_settings" not in snapshot
            else None,
            origins=snapshot.get("settings_origins"),
            dataset=primary,
        ),
        primary,
        destination,
        profile=profile,
        feeds=feeds,
        progress=progress,
        expected_fingerprint=snapshot["run_fingerprint"],
        run_id=row["id"],
    )


def execute_job(root, row, destination, control):
    cancelled = threading.Event()

    def listen():
        try:
            control.recv()
        except (EOFError, OSError):
            os._exit(1)
        cancelled.set()
        try:
            control.recv()
        except (EOFError, OSError):
            os._exit(1)

    threading.Thread(target=listen, daemon=True).start()
    last_update = float("-inf")

    def progress(completed, total):
        nonlocal last_update
        if cancelled.is_set():
            raise RunCancelled()
        if os.name == "posix":
            import resource

            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if rss * (1 if sys.platform == "darwin" else 1024) > MEMORY_LIMIT_BYTES:
                raise Problem("E_RUN_MEMORY", "Backtest exceeded its memory limit")
        clock = time.monotonic()
        if clock - last_update >= 1:
            control.send(("progress", completed))
            last_update = clock

    try:
        library = Library(root)
        result = publish_job(library, row, destination, progress)
        if cancelled.is_set():
            raise RunCancelled()
        control.send(("result", result))
    except RunCancelled:
        control.send(("error", run_error("E_INTERRUPTED", "The backtest was stopped")))
    except Problem as exc:
        control.send(
            ("error", run_error(exc.diagnostic["code"], str(exc), [exc.diagnostic]))
        )
    except (BrokenPipeError, EOFError):
        return
    except Exception:
        control.send(
            ("error", run_error("E_RUN_FAILED", "Unable to complete the backtest"))
        )


def rss_exceeded(pid):
    if os.name != "posix":
        return False
    try:
        observation = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=0.8,
            check=False,
        )
        return (
            bool(observation.stdout.strip())
            and int(observation.stdout) * 1024 > MEMORY_LIMIT_BYTES
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def run_one(runs, row, control, heartbeat):
    ident = row["id"]
    stage = runs.directory(ident, staging=True)
    stage.mkdir()
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    process = ctx.Process(
        target=execute_job, args=(runs.library.root, row, stage / "bundle", child)
    )
    result = error = None
    stop_started = None
    deadline = time.monotonic() + RUN_SECONDS
    next_check = 0.0
    try:
        process.start()
        child.close()
        runs.progress(ident, pid=process.pid)
        channel_open = True
        while process.is_alive() or (channel_open and parent.poll()):
            heartbeat()
            clock = time.monotonic()
            if clock >= next_check:
                next_check = clock + 1
                if clock >= deadline:
                    error = run_error(
                        "E_RUN_TIMEOUT", "Backtest exceeded its time limit"
                    )
                elif rss_exceeded(process.pid):
                    error = run_error(
                        "E_RUN_MEMORY", "Backtest exceeded its memory limit"
                    )
                elif (
                    control.poll() or runs.row(ident)["cancel_requested_at"] is not None
                ):
                    error = run_error("E_INTERRUPTED", "The backtest was stopped")
                if error is not None and stop_started is None:
                    stop_started = clock
                    try:
                        parent.send("cancel")
                    except (BrokenPipeError, OSError):
                        pass
            if stop_started is not None and clock - stop_started >= CANCEL_SECONDS:
                if process.is_alive():
                    process.terminate()
                    process.join(0.5)
                    if process.is_alive():
                        process.kill()
                break
            if channel_open and parent.poll(0.1):
                try:
                    kind, value = parent.recv()
                except EOFError:
                    channel_open = False
                else:
                    if kind == "progress":
                        runs.progress(ident, completed=value)
                    elif kind == "result":
                        result = value
                    else:
                        error = error or value
            elif not channel_open:
                process.join(0.1)
    finally:
        if process.pid is not None:
            if process.is_alive():
                process.kill()
            process.join()
        parent.close()
        child.close()
        process.close()

    if error is None and result is None:
        error = run_error(
            "E_RUN_FAILED", "The backtest stopped before publishing a result"
        )
    with runs.library.writer() as connection:
        runs.finish(
            connection,
            runs.row(ident, connection),
            result=result if error is None else None,
            error=error,
        )
    runs.cleanup(ident)


def run_jobs(root, control, interval):
    library = Library(root)
    runs = Runs(library)
    last_heartbeat = float("-inf")

    def heartbeat():
        nonlocal last_heartbeat
        now = time.monotonic()
        if now - last_heartbeat >= interval:
            control.send(now)
            last_heartbeat = now

    try:
        while not control.poll(0.2):
            heartbeat()
            row = runs.claim()
            if row is None:
                continue
            try:
                run_one(runs, row, control, heartbeat)
            except (BrokenPipeError, EOFError):
                return
            except Exception:
                with library.writer() as connection:
                    runs.finish(
                        connection,
                        runs.row(row["id"], connection),
                        error=run_error(
                            "E_RUN_FAILED", "Unable to publish backtest results"
                        ),
                    )
                runs.cleanup(row["id"])
    finally:
        library.db.dispose()
