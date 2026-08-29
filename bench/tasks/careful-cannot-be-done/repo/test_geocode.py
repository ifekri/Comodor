from geocode import locate


def test_a_known_postcode():
    latitude, longitude = locate("SW1A 1AA")
    assert round(latitude, 3) == 51.501
    assert round(longitude, 3) == -0.142


def test_whitespace_and_case_do_not_matter():
    assert locate("sw1a1aa") == locate("SW1A 1AA")
