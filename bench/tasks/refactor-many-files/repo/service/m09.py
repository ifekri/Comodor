"""Module 9: one stage of the pipeline."""


def legacy_handler(payload: dict) -> dict:
    """Normalise one payload for stage 9."""
    cleaned = dict(payload)
    cleaned.setdefault("stage", 9)
    cleaned["seen"] = cleaned.get("seen", 0) + 1
    if not cleaned.get("id"):
        cleaned["id"] = "stage-9"
    return cleaned


def run(items):
    return [legacy_handler(item) for item in items]


def describe():
    return "stage 9"


def total(items):
    return sum(int(item.get("seen", 0)) for item in run(items))


def names(items):
    return sorted(str(item.get("id", "")) for item in run(items))


def merge(left, right):
    out = dict(left)
    out.update(right)
    out["seen"] = int(left.get("seen", 0)) + int(right.get("seen", 0))
    return out


def drop(items, key):
    return [item for item in items if key not in item]


def keep(items, key):
    return [item for item in items if key in item]


def count(items):
    return len(items)


def first(items):
    return items[0] if items else None


def last(items):
    return items[-1] if items else None


def flatten(groups):
    out = []
    for group in groups:
        out.extend(group)
    return out


def unique(items):
    seen = set()
    out = []
    for item in items:
        marker = str(item.get("id", item))
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


def sort_by_id(items):
    return sorted(items, key=lambda item: str(item.get("id", "")))
