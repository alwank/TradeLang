"""Compact storage for full-resolution marks, materializing rows only on export."""

from collections.abc import Sequence

import numpy as np

from .data import instant

FIELDS = (
    "cash",
    "quantity",
    "equity",
    "peak_equity",
    "drawdown",
    "cumulative_return",
    "benchmark_cash",
    "benchmark_quantity",
    "benchmark_equity",
    "benchmark_peak_equity",
    "benchmark_drawdown",
)


class EquityCurve(Sequence):
    def __init__(self, dataset, first, last, interval):
        self.dataset = dataset
        self.first = first
        self.dt = interval
        self.closes = (
            dataset.session_rows.close if dataset.session_rows is not None else None
        )
        self.data = np.empty((last - first + 2, len(FIELDS)))
        self.exposure = np.empty(last - first + 2, dtype=bool)
        self.size = 0

    def record(self, *values, exposed):
        self.data[self.size] = values
        self.exposure[self.size] = exposed
        self.size += 1

    def exposed_bars(self):
        return int(np.count_nonzero(self.exposure[1 : self.size]))

    def column(self, name):
        return self.data[: self.size, FIELDS.index(name)]

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.size))]
        if index < 0:
            index += self.size
        if not 0 <= index < self.size:
            raise IndexError(index)
        bar = self.first + max(0, index - 1)
        ts = self.dataset.times[bar]
        if index:
            ts = self.closes[bar] if self.closes is not None else ts + self.dt
        return dict(
            index=index,
            timestamp=instant(ts),
            phase="close" if index else "initial",
            bar_index=bar if index else None,
            mark_price=float(self.dataset.values[bar, 3]) if index else None,
            exposed=bool(self.exposure[index]),
            **dict(zip(FIELDS, self.data[index].tolist())),
        )
