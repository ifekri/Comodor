from pricing import total


def test_a_small_order_pays_shipping():
    assert total(5.0, 2) == 14.95


def test_exactly_ten_items_earns_the_bulk_discount():
    # BULK_FROM is 10 and the docstring says "at or above".
    assert total(2.0, 10) == 22.95


def test_eleven_items_earns_it_too():
    assert total(2.0, 11) == 24.75


def test_a_member_gets_five_percent():
    assert total(10.0, 4, member=True) == 42.95


def test_both_discounts_come_off_the_same_subtotal():
    assert total(10.0, 20, member=True) == 170.0


def test_exactly_fifty_ships_free():
    # FREE_SHIPPING_FROM is 50.0 and the comment says "at or above".
    assert total(50.0, 1) == 50.0
