"""Resolve a portfolio's pinned library revisions and candle imports."""

from uuid import UUID

from .model import Problem
from .persistence import Library, LibraryError
from .portfolio import AssetInputs, PortfolioSpec
from .run_config import RunSettings, configured_strategy


def require_portfolio_selection(body):
    if (
        any(
            getattr(body, name, None)
            for name in (
                "dataset_id",
                "profile_dataset_id",
                "feed_ids",
                "parameters",
                "preset_id",
                "preset_revision",
                "settings",
            )
        )
        or "policy" in body.model_fields_set
    ):
        raise Problem(
            "E305_PORTFOLIO",
            "Set datasets, costs, and overrides on each portfolio asset",
        )


def resolve_portfolio_assets(
    library: Library, spec: PortfolioSpec, selected: dict
) -> tuple[dict[str, AssetInputs], dict]:
    if selected.keys() != set(spec.assets):
        raise Problem("E305_PORTFOLIO", "Bind each declared asset alias exactly once")

    def candles(ident):
        dataset = library.resolve_dataset(UUID(ident))
        if dataset is None:
            raise Problem(
                "E_DATASET_NOT_FOUND", "A selected candle import is unavailable"
            )
        return dataset

    inputs, descriptions = {}, {}
    for name in spec.assets:
        selection = selected[name]
        try:
            revision = library.revision(
                selection["strategy_id"], selection["strategy_revision"]
            )
            settings = (
                RunSettings.model_validate(selection["settings"])
                if selection.get("settings") is not None
                else None
            )
            if settings is not None and settings.capital is not None:
                raise Problem(
                    "E305_PORTFOLIO", "Set shared capital in the portfolio declaration"
                )
            primary = candles(selection["dataset_id"])
            strategy = configured_strategy(
                revision["source"], settings, dataset=primary
            )
            profile = (
                candles(selection["profile_dataset_id"])
                if selection.get("profile_dataset_id")
                else None
            )
            feeds = {
                feed: candles(ident)
                for feed, ident in selection.get("feed_ids", {}).items()
            }
            inputs[name] = AssetInputs(strategy, primary, profile, feeds)
            descriptions[name] = {
                "asset": name,
                "strategy_id": selection["strategy_id"],
                "strategy_revision": revision["revision"],
                "source_hash": revision["source_hash"],
                "dataset_id": selection["dataset_id"],
                "dataset_hash": primary.dataset_hash,
                "market": primary.meta.symbol,
                "timeframe": primary.meta.timeframe,
            }
        except Problem as error:
            diagnostic = error.diagnostic
            raise Problem(
                diagnostic["code"],
                f"{name}: {diagnostic['message']}",
                suggestion=diagnostic["suggestion"],
                row=diagnostic["data_row"],
                details={**diagnostic["details"], "asset": name},
            ) from error
        except LibraryError as error:
            if error.status != 404:
                raise
            raise Problem(
                "E_REVISION_NOT_FOUND",
                f"{name}: The selected strategy revision is unavailable",
            ) from error
    return inputs, descriptions
