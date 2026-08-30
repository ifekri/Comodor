"""Summary statistics for a run of measurements."""


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def spread(values: list[float]) -> float:
    """The distance between the largest and smallest value."""
    return max(values) - min(values)


def summary(values: list[float]) -> dict[str, float]:
    """Mean and spread together, for a report line."""
    return {"mean": mean(values), "spread": spread(values),
            "count": len(values)}
