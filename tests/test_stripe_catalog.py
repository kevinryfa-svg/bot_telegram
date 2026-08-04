import stripe_catalog


def test_to_stripe_unit_amount_two_decimal_currencies():
    # EUR/USD: la unidad mínima son céntimos (x100).
    assert stripe_catalog.to_stripe_unit_amount(10, "EUR") == 1000
    assert stripe_catalog.to_stripe_unit_amount(10, "usd") == 1000
    assert stripe_catalog.to_stripe_unit_amount(9.99, "EUR") == 999
    assert stripe_catalog.to_stripe_unit_amount(0, "EUR") == 0


def test_to_stripe_unit_amount_zero_decimal_currencies():
    # JPY no tiene decimales: el importe va tal cual.
    assert stripe_catalog.to_stripe_unit_amount(1000, "JPY") == 1000
    assert stripe_catalog.to_stripe_unit_amount(500, "krw") == 500


def test_to_stripe_unit_amount_defaults_to_eur():
    assert stripe_catalog.to_stripe_unit_amount(5, None) == 500
