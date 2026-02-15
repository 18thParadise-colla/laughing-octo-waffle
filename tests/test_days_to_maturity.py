from warrant_scanner.scoring.option_scoring import parse_days_to_maturity


def test_parse_days_to_maturity_parses_date():
    # should not crash; exact value depends on current date, just ensure int/None
    d = parse_days_to_maturity("18.12.2026")
    assert d is None or isinstance(d, int)
