"""Resolve reusable run settings without rewriting strategy source."""

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .compiler import compile_source
from .model import ParameterValue, Problem, Strategy

Gap = Literal["reject", "allow"]
Origin = Literal["source", "preset", "override", "dataset"]
ParameterOverrides = Annotated[dict[str, ParameterValue], Field(max_length=128)]
CONFIG_FIELDS = ("from_date", "to_date", "capital", "fee_bps", "slippage_bps")


class RunSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    from_date: str | None = None
    to_date: str | None = None
    capital: float | None = None
    fee_bps: float | None = None
    slippage_bps: float | None = None
    gap_policy: Gap | None = None
    parameters: ParameterOverrides = Field(default_factory=dict)


class FeedFiles(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    data: str
    metadata: str


class PortableRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    name: str | None = None
    settings: RunSettings = Field(default_factory=RunSettings)
    data: str | None = None
    metadata: str | None = None
    profile_data: str | None = None
    profile_metadata: str | None = None
    feeds: Annotated[dict[str, FeedFiles], Field(max_length=1)] = Field(
        default_factory=dict
    )


def merge_settings(preset=None, overrides=None):
    values: dict[str, Any] = {}
    origins: dict[str, Origin] = {}
    layers: tuple[tuple[RunSettings | None, Origin], ...] = (
        (preset, "preset"),
        (overrides, "override"),
    )
    for layer, origin in layers:
        if layer is None:
            continue
        fields = layer.model_dump(exclude_none=True, exclude_defaults=True)
        for name, val in fields.items():
            if name == "parameters":
                values.setdefault(name, {}).update(val)
                origins.update((f"parameters.{key}", origin) for key in val)
            else:
                values[name] = val
                origins[name] = origin
    if len(values.get("parameters", {})) > 128:
        raise Problem(
            "E208_PARAMETER", "Run settings may override at most 128 parameters"
        )
    return RunSettings.model_validate(values), origins


def configured_strategy(
    source,
    settings: RunSettings | None = None,
    *,
    parameters: Mapping[str, ParameterValue] | None = None,
    origins: dict[str, Origin] | None = None,
    dataset=None,
):
    apply_settings = settings is not None or bool(parameters)
    if settings is None:
        settings = RunSettings()
    overrides = {**settings.parameters, **(parameters or {})}
    strategy = compile_source(source, parameters=overrides)
    if not isinstance(strategy, Strategy):
        raise Problem("E305_PORTFOLIO", "Bind a portfolio's datasets by asset alias")
    if not apply_settings:
        return strategy
    config = strategy.config
    from_date = (
        settings.from_date if settings.from_date is not None else config.from_date
    )
    to_date = settings.to_date if settings.to_date is not None else config.to_date
    try:
        start, end = date.fromisoformat(from_date), date.fromisoformat(to_date)
        if (
            from_date != start.isoformat()
            or to_date != end.isoformat()
            or start > end
            or end == date.max
        ):
            raise ValueError
    except ValueError as exc:
        raise Problem(
            "E209_RUN_CONFIG",
            "Run dates must use YYYY-MM-DD and cover an ordered window",
            details={"from_date": from_date, "to_date": to_date},
        ) from exc
    if settings.capital is not None and settings.capital <= 0:
        raise Problem(
            "E209_RUN_CONFIG",
            "Starting capital must be greater than zero",
            details={"field": "capital"},
        )
    for field in ("fee_bps", "slippage_bps"):
        value = getattr(settings, field)
        if value is not None and not 0 <= value < 10_000:
            raise Problem(
                "E209_RUN_CONFIG",
                f"{field} must be in [0, 10000)",
                details={"field": field},
            )
    if (
        dataset is not None
        and settings.gap_policy is not None
        and settings.gap_policy != dataset.meta.gap_policy
    ):
        raise Problem("E402_WINDOW", "Run gap policy must match the selected import")

    applied = settings.model_copy(
        update={"parameters": dict(strategy.parameter_overrides)}
    )
    origin_map: dict[str, Origin] = {key: "source" for key in CONFIG_FIELDS}
    origin_map.update((f"parameters.{p.name}", "source") for p in strategy.parameters)
    if dataset is not None:
        origin_map.update(dataset_id="dataset", gap_policy="dataset")
    origin_map.update(origins or {})
    origin_map.update((f"parameters.{key}", "override") for key in parameters or {})
    return replace(
        strategy,
        config=replace(
            config,
            from_date=from_date,
            to_date=to_date,
            capital=config.capital if settings.capital is None else settings.capital,
            fee_rate=config.fee_rate
            if settings.fee_bps is None
            else settings.fee_bps / 10000,
            slippage_rate=config.slippage_rate
            if settings.slippage_bps is None
            else settings.slippage_bps / 10000,
        ),
        declared_config=config,
        run_settings=applied.model_dump(exclude_none=True, exclude_defaults=True),
        settings_origins=origin_map,
    )


def configuration_view(strategy, dataset=None, profile=None):
    config = strategy.config
    return dict(
        schema_version=1,
        from_date=config.from_date,
        to_date=config.to_date,
        capital=config.capital,
        currency=config.currency,
        fee_rate=config.fee_rate,
        slippage_rate=config.slippage_rate,
        dataset_hash=dataset.dataset_hash if dataset is not None else None,
        profile_dataset_hash=profile.dataset_hash if profile is not None else None,
        gap_policy=dataset.meta.gap_policy
        if dataset is not None
        else (strategy.run_settings or {}).get("gap_policy"),
        parameters={
            parameter.name: parameter.value for parameter in strategy.parameters
        },
        origins=strategy.settings_origins or {},
    )
