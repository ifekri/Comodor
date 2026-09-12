"""What the command-line side of Comodor needs from a terminal.

Not an interface. The interface is the OpenTUI renderer in `comodor.tui`,
driven over the protocol. This is the smaller set of things the *commands*
need — `comodor setup`, `doctor`, `help`, the channel commands — when they
print to a terminal or ask one question in it:

- `console` — a Rich console built for the configured theme, and the UTF-8
  and colour decisions that go with it.
- `theme` — the named palettes those commands print in.
- `chooser` — one interactive picker, used by setup and the workspace prompt,
  with a numbered fallback where keys cannot be read.
- `keys`, `reader` — raw key decoding for that picker.
- `banner` — the wordmark.
- `clipboard` — copying a link on the platforms that can.

Everything here used to live under `comodor.ui` beside the previous
interface. That interface is gone; these are what it left behind because
something other than it was using them.
"""
