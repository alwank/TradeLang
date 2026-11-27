"""Replayable exchange-local dates on an explicit schedule of UTC sessions."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

DAY_US = 86_400_000_000
DATE = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
UTC_STAMP = Annotated[
    str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
]


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    date: DATE
    open: UTC_STAMP
    close: UTC_STAMP


class SessionSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    market: str = Field(pattern=r"^[A-Z0-9][A-Z0-9_.-]{0,31}$")
    timezone: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=100)
    from_date: DATE
    to_date: DATE
    sessions: list[Session] = Field(min_length=1, max_length=10_000)


class StockSplit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    date: DATE
    new_shares: int = Field(gt=0, le=1_000_000)
    old_shares: int = Field(gt=0, le=1_000_000)


@dataclass(frozen=True)
class SessionRows:
    close: np.ndarray
    ordinal: np.ndarray
    session_index: np.ndarray
    next_close: np.ndarray


class SessionGrid:
    def __init__(self, schedule: SessionSchedule, width: int, timestamp):
        if width > DAY_US:
            raise ValueError("Session candles use an intraday timeframe or one day")
        if date.fromisoformat(schedule.from_date) > date.fromisoformat(
            schedule.to_date
        ):
            raise ValueError("Session schedule coverage dates must be ordered")
        try:
            zone = ZoneInfo(schedule.timezone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Invalid IANA time zone in the session schedule") from exc

        dates: list[str] = []
        opens: list[int] = []
        closes: list[int] = []
        prior_date = ""
        for session in schedule.sessions:
            start, end = timestamp(session.open), timestamp(session.close)
            local_date = (
                datetime.fromisoformat(session.open).astimezone(zone).date().isoformat()
            )
            if (
                local_date != session.date
                or not schedule.from_date <= session.date <= schedule.to_date
            ):
                raise ValueError(
                    "Session open must fall on its declared local date inside coverage"
                )
            if session.date <= prior_date or (closes and closes[-1] > start):
                raise ValueError("Sessions must be ordered and non-overlapping")
            if not 0 < end - start <= DAY_US:
                raise ValueError("Session length must be positive and at most 24 hours")
            dates.append(session.date)
            opens.append(start)
            closes.append(end)
            prior_date = session.date

        self.schedule = schedule
        self.dates = np.array(dates)
        self.opens = np.array(opens, dtype=np.int64)
        self.closes = np.array(closes, dtype=np.int64)
        self.width = width
        self.slots = (self.closes - self.opens + width - 1) // width
        self.starts = np.r_[0, np.cumsum(self.slots[:-1])]
        for data in (self.dates, self.opens, self.closes, self.slots, self.starts):
            data.flags.writeable = False

    def map_rows(self, times) -> tuple[SessionRows, np.ndarray]:
        session = self.opens.searchsorted(times, side="right") - 1
        index = np.maximum(session, 0)
        start, end = self.opens[index], self.closes[index]
        elapsed = times - start
        bad = (session < 0) | (times >= end) | (elapsed % self.width != 0)
        slot = elapsed // self.width
        close = np.minimum(times + self.width, end)
        ordinal = self.starts[index] + slot
        next_session = np.minimum(index + 1, len(self.opens) - 1)
        first_next = np.minimum(
            self.opens[next_session] + self.width, self.closes[next_session]
        )
        next_close = np.where(
            close < end,
            np.minimum(close + self.width, end),
            np.where(index + 1 < len(self.opens), first_next, np.iinfo(np.int64).max),
        )
        for data in (close, ordinal, index, next_close):
            data.flags.writeable = False
        return SessionRows(close, ordinal, index, next_close), bad

    def window(self, first, last):
        if first < self.schedule.from_date or last > self.schedule.to_date:
            raise ValueError(
                "The requested dates are outside the session schedule coverage"
            )
        a = int(self.dates.searchsorted(first))
        b = int(self.dates.searchsorted(last, side="right")) - 1
        if a > b:
            return None
        return int(self.opens[a]), int(self.opens[b] + (self.slots[b] - 1) * self.width)

    def factors(self, splits: list[StockSplit], rows: SessionRows) -> np.ndarray:
        factors = np.ones(len(self.dates))
        prior = -1
        for split in splits:
            index = int(self.dates.searchsorted(split.date))
            if (
                index >= len(self.dates)
                or self.dates[index] != split.date
                or index <= prior
            ):
                raise ValueError("Split dates must be unique, ordered trading sessions")
            factors[index] = split.new_shares / split.old_shares
            prior = index
        with np.errstate(all="ignore"):
            cumulative = np.cumprod(factors)
        if not np.all(np.isfinite(cumulative) & (cumulative > 0)):
            raise ValueError("Cumulative split factor is outside the numeric range")
        result = cumulative[rows.session_index]
        result.flags.writeable = False
        return result
