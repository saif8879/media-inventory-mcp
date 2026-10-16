from __future__ import annotations

import math


def resolve_radius(radius_km: float | None, default: float) -> float:
    value = default if radius_km is None else radius_km
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("radius_km must be a number greater than 0 and at most 100")
    number = float(value)
    if not math.isfinite(number) or number <= 0 or number > 100:
        raise ValueError("radius_km must be a number greater than 0 and at most 100")
    return number


def resolve_bounded_int(
    value: int | None,
    default: int,
    *,
    minimum: int,
    maximum: int,
    name: str,
) -> int:
    chosen = default if value is None else value
    if isinstance(chosen, bool) or not isinstance(chosen, int) or chosen < minimum or chosen > maximum:
        raise ValueError(f"{name} must be an integer from {minimum} to {maximum}")
    return chosen


def resolve_budget(budget: float) -> float:
    if isinstance(budget, bool) or not isinstance(budget, (int, float)):
        raise ValueError("budget must be a positive amount in INR")
    number = float(budget)
    if not math.isfinite(number) or number <= 0:
        raise ValueError("budget must be a positive amount in INR")
    return number
