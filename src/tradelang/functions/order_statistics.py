"""A bounded online multiset for wide mean-absolute-deviation windows."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite

import numpy as np

from .rolling import binary64_units


@dataclass(slots=True)
class _Node:
    value: int
    weight: int = 1
    left: _Node | None = None
    right: _Node | None = None
    height: int = 1
    count: int = 1
    total: int = 0

    def refresh(self):
        self.count = (
            self.weight
            + (self.left.count if self.left else 0)
            + (self.right.count if self.right else 0)
        )
        self.total = (
            self.value * self.weight
            + (self.left.total if self.left else 0)
            + (self.right.total if self.right else 0)
        )
        self.height = 1 + max(_height(self.left), _height(self.right))


def _height(node):
    return node.height if node is not None else 0


def _rotate_left(node):
    pivot = node.right
    node.right = pivot.left
    pivot.left = node
    node.refresh()
    pivot.refresh()
    return pivot


def _rotate_right(node):
    pivot = node.left
    node.left = pivot.right
    pivot.right = node
    node.refresh()
    pivot.refresh()
    return pivot


def _balance(node):
    node.refresh()
    spread = _height(node.left) - _height(node.right)
    if spread > 1:
        if _height(node.left.right) > _height(node.left.left):
            node.left = _rotate_left(node.left)
        return _rotate_right(node)
    if spread < -1:
        if _height(node.right.left) > _height(node.right.right):
            node.right = _rotate_right(node.right)
        return _rotate_left(node)
    return node


def _remove_first(node):
    if node.left is None:
        return node, node.right
    first, node.left = _remove_first(node.left)
    return first, _balance(node)


def _change(node, value, change):
    if node is None:
        return _Node(value, total=value)
    if value < node.value:
        node.left = _change(node.left, value, change)
    elif value > node.value:
        node.right = _change(node.right, value, change)
    else:
        node.weight += change
        if not node.weight:
            if node.left is None:
                return node.right
            if node.right is None:
                return node.left
            replacement, node.right = _remove_first(node.right)
            replacement.left, replacement.right = node.left, node.right
            node = replacement
    return _balance(node)


def _through_mean(node, total, count):
    seen = subtotal = 0
    while node is not None:
        if node.value * count <= total:
            seen += node.weight + (node.left.count if node.left else 0)
            subtotal += node.value * node.weight + (node.left.total if node.left else 0)
            node = node.right
        else:
            node = node.left
    return seen, subtotal


def cci_wide(typical, period):
    result = np.full(len(typical), np.nan)
    values: deque[int] = deque()
    root: _Node | None = None
    for index, price in enumerate(typical):
        if not isfinite(price):
            root = None
            values.clear()
            continue
        price_units = binary64_units(price)
        if len(values) == period:
            root = _change(root, values.popleft(), -1)
        values.append(price_units)
        root = _change(root, price_units, 1)
        if len(values) == period:
            total = root.total
            count, below_total = _through_mean(root, total, period)
            # Count each deviation in units of 1/period of a binary64 subnormal.
            deviation_sum = 2 * (total * count - below_total * period)
            result[index] = (
                (price_units * period - total) * period / deviation_sum / 0.015
                if deviation_sum
                else 0
            )
    return result
