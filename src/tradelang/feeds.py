"""Index completed secondary candles on the primary close clock."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .model import Problem

if TYPE_CHECKING:
    from .data import Dataset

ALIGNMENT_POLICY = "completed_close_v1"
MISSING, STALE, GAP = 1, 2, 3


@dataclass(frozen=True)
class FeedAlignment:
    dataset: "Dataset"
    indices: np.ndarray
    status: np.ndarray

    @property
    def rows(self) -> int:
        return int(self.indices[-1]) + 1 if len(self.indices) else 0

    def reason(self, row):
        return {
            MISSING: "feed_no_completed_candle",
            STALE: "feed_stale",
            GAP: "feed_gap",
        }.get(self.status[row])


def prepare_feeds(strategy, primary, inputs, end):
    mapping = inputs or {}
    feed = strategy.feed
    required = {feed.name} if strategy.requires_feed else set()
    if missing := required - mapping.keys():
        name = min(missing)
        raise Problem(
            "E402_WINDOW",
            f"Select candles for secondary feed {name}",
            details={"feed": name},
        )
    if extra := mapping.keys() - required:
        name = min(extra)
        raise Problem(
            "E402_WINDOW",
            f"Secondary feed {name} is not required by this strategy",
            details={"feed": name},
        )
    if not required:
        return {}
    secondary = mapping[feed.name]
    if secondary.timeframe_seconds != feed.seconds:
        raise Problem(
            "E402_WINDOW",
            f"Feed {feed.name} requires {feed.seconds}-second candles",
            details={"feed": feed.name},
        )
    if feed.seconds <= primary.timeframe_seconds or (
        feed.seconds % primary.timeframe_seconds
        and not (primary.grid is not None and feed.seconds == 86400)
    ):
        raise Problem(
            "E402_WINDOW",
            f"Feed {feed.name} must use a larger exact multiple of the primary timeframe",
            details={"feed": feed.name},
        )
    for field in (
        "symbol",
        "quote_currency",
        "calendar",
        "timestamp_convention",
        "price_basis",
        "volume_unit",
        "session_schedule",
        "splits",
    ):
        if getattr(secondary.meta, field) != getattr(primary.meta, field):
            raise Problem(
                "E402_WINDOW",
                f"Feed {feed.name} must match the primary dataset's {field}",
                details={"feed": feed.name, "field": field},
            )
    if any(call.type.clock == feed.name for call in strategy.calls("VWAP")) and (
        feed.seconds >= 86400 or (secondary.grid is None and 86400 % feed.seconds)
    ):
        raise Problem(
            "E402_WINDOW",
            f"Feed {feed.name}: VWAP requires an intraday timeframe dividing a UTC day",
            details={"feed": feed.name},
        )

    primary_closes = primary.close_at(slice(0, end + 1))
    interval = feed.seconds * 1_000_000
    secondary_closes = secondary.close_at(slice(None))
    indices = secondary_closes.searchsorted(primary_closes, side="right") - 1
    age = primary_closes - secondary_closes[np.maximum(indices, 0)]
    status = np.zeros(len(indices), dtype=np.uint8)
    missing = (
        age >= interval
        if secondary.session_rows is None
        else primary_closes >= secondary.session_rows.next_close[np.maximum(indices, 0)]
    )
    status[missing] = GAP
    status[age >= feed.max_age_seconds * 1_000_000] = STALE
    status[indices < 0] = MISSING
    return {feed.name: FeedAlignment(secondary, indices, status)}
