"""Project settings, one dict behind a helper."""

SETTINGS = {}


def put(key, value):
    """Record one setting and hand back the value."""
    SETTINGS[key] = value
    return value
