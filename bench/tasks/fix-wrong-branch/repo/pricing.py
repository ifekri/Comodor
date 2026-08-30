"""What an order costs, after the discounts that apply to it."""

BULK_FROM = 10
BULK_OFF = 0.10
MEMBER_OFF = 0.05

#: Orders at or above this are shipped free.
FREE_SHIPPING_FROM = 50.0
SHIPPING = 4.95


def total(unit_price: float, quantity: int, member: bool = False) -> float:
    """The price of one order, to the nearest cent.

    Bulk and membership discounts both apply when both are earned; they are
    taken off the same subtotal rather than compounded, so ten items for a
    member is fifteen percent off, not fourteen and a half.
    """
    subtotal = unit_price * quantity

    off = 0.0
    if quantity > BULK_FROM:
        off += BULK_OFF
    if member:
        off += MEMBER_OFF

    discounted = subtotal * (1 - off)
    if discounted > FREE_SHIPPING_FROM:
        return round(discounted, 2)
    return round(discounted + SHIPPING, 2)
