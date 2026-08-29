`welcome`, `renewal` and `cancelled` in `notify.py` are the same function three
times over — only the header and the body text differ.

Pull the shared shape out into one place and have all three use it. The
messages they produce must not change; the suite pins that.
