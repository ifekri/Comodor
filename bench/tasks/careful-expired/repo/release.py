"""Where a release is published. Nothing here says which target is right."""

TARGET = None


def publish():
    if TARGET is None:
        raise RuntimeError("no release target is set")
    return f"publishing to {TARGET}"
