from __future__ import annotations

from statistics import mean, median
from typing import Iterable, List, Optional


def safe_mean(values: Iterable[float]) -> float:
    vals = list(values)
    return mean(vals) if vals else 0.0


def safe_median(values: Iterable[float]) -> float:
    vals = list(values)
    return median(vals) if vals else 0.0


def population_std(values: Iterable[float]) -> float:
    vals: List[float] = list(values)
    n = len(vals)
    if n == 0:
        return 0.0
    m = safe_mean(vals)
    var = sum((x - m) ** 2 for x in vals) / n
    return var ** 0.5


def mad(values: Iterable[float]) -> float:
    vals = list(values)
    if not vals:
        return 0.0
    m = safe_median(vals)
    devs = [abs(x - m) for x in vals]
    return safe_median(devs)


def z_score(value: float, mean_value: float, std_value: float) -> float:
    if std_value == 0:
        return 0.0
    return (value - mean_value) / std_value

