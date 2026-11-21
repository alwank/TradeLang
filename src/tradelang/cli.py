"""TradeLang command line interface."""

import json
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer
from typer.exceptions import TyperException

from .application import inspect_source
from .compiler import compile_source
from .data import load_dataset
from .model import Problem
from .report import publish

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
COMMANDS = ("validate", "explain", "backtest")


def envelope(command):
    return dict(
        schema_version=1, command=command, ok=False, diagnostics=[], result=None
    )


def emit_json(response):
    typer.echo(json.dumps(response, ensure_ascii=False, allow_nan=False))


def show_version(requested: bool):
    if requested:
        typer.echo(version("tradelang"))
        raise typer.Exit()


@app.callback()
def root(
    version_requested: bool = typer.Option(
        False, "--version", callback=show_version, is_eager=True
    ),
):
    """Validate strategies and run local backtests."""


def register(command):
    def run(
        strategy: Path,
        data: Path | None = None,
        metadata: Path | None = None,
        profile_data: Path | None = None,
        profile_metadata: Path | None = None,
        symbol: str | None = None,
        quote_currency: str | None = None,
        timeframe: str | None = None,
        calendar: str | None = None,
        timestamp_convention: str | None = None,
        volume_unit: str | None = None,
        price_basis: str | None = None,
        gap_policy: str | None = None,
        out: Path | None = None,
        json_output: bool = typer.Option(False, "--json"),
    ):
        response = envelope(command)
        code = 0
        try:
            with strategy.open("rb") as f:
                source = f.read(65537)
            flags = dict(
                symbol=symbol,
                quote_currency=quote_currency,
                timeframe=timeframe,
                calendar=calendar,
                timestamp_convention=timestamp_convention,
                volume_unit=volume_unit,
                price_basis=price_basis,
                gap_policy=gap_policy,
            )
            flags = {k: v for k, v in flags.items() if v is not None}
            if metadata and flags:
                raise typer.BadParameter("Use metadata file or explicit metadata flags")
            if (metadata or flags) and data is None:
                raise typer.BadParameter("Metadata requires --data")
            if (profile_data is None) != (profile_metadata is None):
                raise typer.BadParameter(
                    "Supply --profile-data with --profile-metadata"
                )
            if profile_data is not None and data is None:
                raise Problem(
                    "E402_WINDOW", "A profile dataset requires a primary dataset"
                )
            if out and command != "backtest":
                raise typer.BadParameter("--out applies to backtest")
            as_of = datetime.now(UTC) if profile_data is not None else None
            d = (
                load_dataset(
                    data,
                    json.loads(metadata.read_text()) if metadata else flags,
                    as_of_utc=as_of,
                )
                if data
                else None
            )
            profile = (
                load_dataset(
                    profile_data,
                    json.loads(profile_metadata.read_text()),
                    as_of_utc=as_of,
                )
                if profile_data is not None and profile_metadata is not None
                else None
            )
            if command in ("validate", "explain"):
                analysis = inspect_source(source, command, d, profile=profile)
                response["diagnostics"] = analysis["diagnostics"]
                if analysis["valid"]:
                    fields = (
                        (
                            "source_hash",
                            "spec_hash",
                            "spec",
                            "warmup_index",
                            "data_compatible",
                        )
                        if command == "validate"
                        else (
                            "source_hash",
                            "spec_hash",
                            "text",
                            "assumptions",
                            "warmup_index",
                            "resolved_window",
                        )
                    )
                    r = {k: analysis[k] for k in fields}
                    response.update(ok=True, result=r)
                else:
                    code = 2
            else:
                if not out or not d:
                    raise typer.BadParameter("Backtest requires --out and --data")
                s = compile_source(source)
                r = publish(s, d, out, profile=profile)
                response.update(ok=True, result=r, diagnostics=r["summary"]["warnings"])
        except Problem as exc:
            response["diagnostics"] = [exc.diagnostic]
            code = 4 if exc.diagnostic["code"] == "E_NUMERIC_EXECUTION" else 2
        except (OSError, ValueError) as exc:
            response["diagnostics"] = [Problem("E_IO", str(exc)).diagnostic]
            code = 3
        except (ArithmeticError, MemoryError) as exc:
            response["diagnostics"] = [
                Problem(
                    "E_NUMERIC_EXECUTION", str(exc) or "Resource limit exceeded"
                ).diagnostic
            ]
            code = 4
        except KeyboardInterrupt:
            response["diagnostics"] = [Problem("E_INTERRUPT", "Interrupted").diagnostic]
            code = 130
        if json_output:
            emit_json(response)
        elif code:
            for dgn in response["diagnostics"]:
                sp = dgn["span"]
                where = f" at {sp['start_line']}:{sp['start_column']}" if sp else ""
                if dgn["data_row"] is not None:
                    where += f" at data row {dgn['data_row']}"
                typer.echo(f"{dgn['code']}{where} {dgn['message']}", err=True)
        elif command == "explain":
            typer.echo(r["text"])
        elif command == "validate":
            typer.echo(
                f"Valid strategy: {r['spec']['name']}. Warmup index {r['warmup_index']}."
            )
        else:
            typer.echo(
                f"Final equity {r['summary']['final_equity']:.8g} {s.config.currency}. Artifacts: {r['artifact_directory']}"
            )
        if code:
            raise typer.Exit(code)

    app.command(name=command)(run)


for command in COMMANDS:
    register(command)


def main():
    args = sys.argv[1:]
    try:
        status = app(args=args, standalone_mode=False)
    except TyperException as exc:
        message = str(exc)[:512]
        options = args[: args.index("--")] if "--" in args else args
        if args and args[0] in COMMANDS and "--json" in options:
            response = envelope(args[0])
            response["diagnostics"] = [Problem("E_USAGE", message).diagnostic]
            emit_json(response)
        else:
            typer.echo(f"E_USAGE {message}\nSee tradelang --help.", err=True)
        status = 3
    except KeyboardInterrupt:
        status = 130
    raise SystemExit(status or 0)


if __name__ == "__main__":
    main()
