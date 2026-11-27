"""TradeLang command line interface."""

import json
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import typer
from pydantic import ValidationError
from typer.exceptions import TyperException

from .application import inspect_source
from .compiler import is_portfolio_source
from .data import load_dataset, unique_json_members
from .model import ParameterValue, Problem
from .portfolio_report import portfolio_command
from .report import publish
from .run_config import (
    Origin,
    PortableRunConfig,
    RunSettings,
    configured_strategy,
    merge_settings,
)

app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)
COMMANDS = ("validate", "explain", "backtest")


def envelope(command):
    return dict(
        schema_version=1, command=command, ok=False, diagnostics=[], result=None
    )


def emit_json(response):
    typer.echo(json.dumps(response, ensure_ascii=False, allow_nan=False))


def parse_parameters(entries):
    overrides: dict[str, ParameterValue] = {}
    for entry in entries or ():
        name, delimiter, raw = entry.partition("=")
        if not delimiter or not name or name in overrides:
            raise Problem("E208_PARAMETER", "Use --param NAME=VALUE once per parameter")
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise Problem(
                "E208_PARAMETER", f"Parameter {name} requires a JSON number or Boolean"
            ) from exc
        if type(value) not in (int, float, bool):
            raise Problem(
                "E208_PARAMETER", f"Parameter {name} requires a JSON number or Boolean"
            )
        overrides[name] = value
    return overrides


def feed_paths(entries):
    paths: dict[str, Path] = {}
    for entry in entries or ():
        name, delimiter, value = entry.partition("=")
        if not delimiter or not name or not value or name in paths or paths:
            raise Problem(
                "E402_WINDOW", "Supply one named secondary input with NAME=FILE"
            )
        paths[name] = Path(value)
    return paths


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
        feed: list[str] | None = typer.Option(
            None, "--feed", help="Bind secondary candles as NAME=FILE"
        ),
        feed_metadata: list[str] | None = typer.Option(
            None, "--feed-metadata", help="Bind secondary metadata as NAME=FILE"
        ),
        symbol: str | None = None,
        quote_currency: str | None = None,
        timeframe: str | None = None,
        calendar: str | None = None,
        timestamp_convention: str | None = None,
        volume_unit: str | None = None,
        price_basis: str | None = None,
        gap_policy: str | None = None,
        out: Path | None = None,
        run_config: Path | None = typer.Option(
            None, "--run-config", help="Read a reusable run configuration JSON file"
        ),
        from_date: str | None = typer.Option(
            None,
            "--from-date",
            help="Override the inclusive start date in the strategy calendar",
        ),
        to_date: str | None = typer.Option(
            None,
            "--to-date",
            help="Override the inclusive end date in the strategy calendar",
        ),
        capital: float | None = typer.Option(
            None, "--capital", help="Override starting capital in the declared currency"
        ),
        fee_bps: float | None = typer.Option(
            None, "--fee-bps", help="Override fee basis points per side"
        ),
        slippage_bps: float | None = typer.Option(
            None, "--slippage-bps", help="Override slippage basis points per side"
        ),
        run_gap_policy: str | None = typer.Option(
            None, "--run-gap-policy", help="Require the selected input's gap policy"
        ),
        params: list[str] | None = typer.Option(
            None, "--param", help="Override a DSL 2 parameter as NAME=VALUE"
        ),
        json_output: bool = typer.Option(False, "--json"),
    ):
        response = envelope(command)
        code = 0
        try:
            with strategy.open("rb") as f:
                source = f.read(65537)
            portfolio = is_portfolio_source(source)
            if portfolio:
                if any(
                    value is not None
                    for value in (
                        data,
                        metadata,
                        profile_data,
                        profile_metadata,
                        feed,
                        feed_metadata,
                        symbol,
                        quote_currency,
                        timeframe,
                        calendar,
                        timestamp_convention,
                        volume_unit,
                        price_basis,
                        gap_policy,
                        from_date,
                        to_date,
                        capital,
                        fee_bps,
                        slippage_bps,
                        run_gap_policy,
                        params,
                    )
                ):
                    raise Problem(
                        "E305_PORTFOLIO",
                        "Set asset inputs and overrides in --run-config",
                    )
                r = portfolio_command(source, command, run_config, out)
                response.update(
                    ok=True,
                    result=r,
                    diagnostics=r["summary"]["warnings"]
                    if command == "backtest"
                    else [],
                )
            else:
                overrides = parse_parameters(params)
                feed_data, feed_meta = feed_paths(feed), feed_paths(feed_metadata)
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
                origins: dict[str, Origin] = {}
                for key, value in (
                    ("dataset_id", data),
                    ("profile_dataset_id", profile_data),
                ):
                    if value is not None:
                        origins[key] = "override"
                try:
                    explicit = RunSettings.model_validate(
                        dict(
                            from_date=from_date,
                            to_date=to_date,
                            capital=capital,
                            fee_bps=fee_bps,
                            slippage_bps=slippage_bps,
                            gap_policy=run_gap_policy,
                        )
                    )
                    preset = (
                        PortableRunConfig.model_validate(
                            json.loads(
                                run_config.read_text(encoding="utf-8"),
                                object_pairs_hook=unique_json_members,
                            )
                        )
                        if run_config is not None
                        else None
                    )
                except ValidationError as error:
                    first = error.errors()[0]
                    field = ".".join(map(str, first["loc"])) or "run configuration"
                    raise Problem(
                        "E209_RUN_CONFIG", f"{field}: {first['msg']}"
                    ) from error
                except (ValueError, RecursionError) as error:
                    raise Problem(
                        "E209_RUN_CONFIG", f"Invalid run configuration JSON: {error}"
                    ) from error
                settings, settings_origins = merge_settings(
                    preset.settings if preset else None, explicit
                )
                origins.update(settings_origins)
                configure = preset is not None or bool(settings_origins)
                if preset is not None and run_config is not None:

                    def from_preset(filename):
                        return run_config.parent / filename if filename else None

                    if data is None and preset.data is not None:
                        data = from_preset(preset.data)
                        origins["dataset_id"] = "preset"
                    if metadata is None and not flags:
                        metadata = from_preset(preset.metadata)
                    if profile_data is None and preset.profile_data is not None:
                        profile_data = from_preset(preset.profile_data)
                        origins["profile_dataset_id"] = "preset"
                    if profile_metadata is None:
                        profile_metadata = from_preset(preset.profile_metadata)
                    for name, item in preset.feeds.items():
                        if not feed_data or name in feed_data:
                            feed_data.setdefault(name, run_config.parent / item.data)
                        if not feed_meta or name in feed_meta:
                            feed_meta.setdefault(
                                name, run_config.parent / item.metadata
                            )
                if feed_data.keys() != feed_meta.keys():
                    raise Problem(
                        "E402_WINDOW", "Each --feed requires matching --feed-metadata"
                    )
                if feed_data and data is None:
                    raise Problem(
                        "E402_WINDOW", "A secondary feed requires a primary dataset"
                    )
                if metadata and flags:
                    raise typer.BadParameter(
                        "Use metadata file or explicit metadata flags"
                    )
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
                as_of = (
                    datetime.now(UTC) if profile_data is not None or feed_data else None
                )
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
                feeds = {
                    name: load_dataset(
                        path, json.loads(feed_meta[name].read_text()), as_of_utc=as_of
                    )
                    for name, path in feed_data.items()
                }
                if command in ("validate", "explain"):
                    analysis = inspect_source(
                        source,
                        command,
                        d,
                        profile=profile,
                        parameters=overrides,
                        settings=settings if configure else None,
                        origins=origins,
                        feeds=feeds,
                    )
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
                        r = {k: analysis[k] for k in (*fields, "workload")}
                        if "run_configuration" in analysis:
                            r["run_configuration"] = analysis["run_configuration"]
                        response.update(ok=True, result=r)
                    else:
                        code = 2
                else:
                    if not out or not d:
                        raise typer.BadParameter("Backtest requires --out and --data")
                    s = configured_strategy(
                        source,
                        settings if configure else None,
                        parameters=overrides,
                        origins=origins,
                        dataset=d,
                    )
                    r = publish(s, d, out, profile=profile, feeds=feeds)
                    response.update(
                        ok=True, result=r, diagnostics=r["summary"]["warnings"]
                    )
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
        else:
            for dgn in response["diagnostics"]:
                if not code and (command == "backtest" or dgn["severity"] != "warning"):
                    continue
                sp = dgn["span"]
                where = f" at {sp['start_line']}:{sp['start_column']}" if sp else ""
                if dgn["data_row"] is not None:
                    where += f" at data row {dgn['data_row']}"
                typer.echo(f"{dgn['code']}{where} {dgn['message']}", err=True)
                if dgn["suggestion"]:
                    typer.echo(f"  {dgn['suggestion']}", err=True)
            if not code:
                if command == "explain":
                    typer.echo(r["text"])
                elif command == "validate":
                    if portfolio:
                        typer.echo(
                            f"Valid portfolio: {r['spec']['name']}. Assets: {', '.join(r['spec']['assets'])}."
                        )
                    else:
                        typer.echo(
                            f"Valid strategy: {r['spec']['name']}. Warmup index {r['warmup_index']}."
                        )
                else:
                    typer.echo(
                        f"Final equity {r['summary']['final_equity']:.8g} {r['summary']['quote_currency']}. Artifacts: {r['artifact_directory']}"
                    )
                if command != "backtest" and (work := r["workload"]) is not None:
                    typer.echo(
                        f"Workload: {work['evaluated_rows']:,} evaluated candles, "
                        f"{work['retained_series']:,} retained series, "
                        f"at least {work['minimum_resident_bytes']:,} resident bytes "
                        f"of {work['memory_limit_bytes']:,} allowed."
                    )
                if (
                    command == "validate"
                    and (effective := r.get("run_configuration")) is not None
                ):
                    typer.echo(
                        f"Run window {effective['from_date']} to {effective['to_date']}. "
                        f"Capital {effective['capital']:g} {effective['currency']}. "
                        f"Fee {effective['fee_rate'] * 10000:g} bps and slippage "
                        f"{effective['slippage_rate'] * 10000:g} bps per side."
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
