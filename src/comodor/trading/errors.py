"""What goes wrong in the trading domain, and what kind of wrong it is.

Three exceptions, not thirty. A caller catches on the category — is this input
I can fix, or a boundary I am not allowed to cross — and reads the message for
the specifics. One class per rule would give every rule a name nobody imports
and no caller a way to handle a group of them.

They follow the repository's convention: each subsystem has one base error that
subclasses whichever builtin fits its meaning, so that code which does not know
about trading still handles it sensibly.
"""

from __future__ import annotations


class TradingError(Exception):
    """Anything the trading domain refuses to do."""


class TradingValidationError(TradingError, ValueError):
    """A value that cannot describe a real trade.

    A `ValueError` as well, because that is what it is: the caller passed
    something the domain cannot represent. Silent correction is not an option
    here — a quantity rounded down without saying so is a position that does
    not match the exchange's, discovered at reconciliation.
    """


class LiveTradingDisabledError(TradingError):
    """Something asked for live execution, which does not exist.

    Deliberately not a `ValueError`: the input was well-formed and the answer
    is still no. Live trading is off by default and there is no gateway behind
    it, so this is the wall rather than a complaint about an argument.
    """
