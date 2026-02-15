from warrant_scanner.util.fx import FxProvider


def test_fx_same_currency():
    fx = FxProvider(ttl_sec=1)
    assert fx.convert(10.0, "EUR", "EUR") == 10.0
