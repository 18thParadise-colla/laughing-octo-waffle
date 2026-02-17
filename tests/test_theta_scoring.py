from warrant_scanner.scoring.option_scoring import _score_theta


def test_theta_scoring_matches_documented_percent_bands():
    assert _score_theta(4.9) == 15
    assert _score_theta(6.5) == 12
    assert _score_theta(9.9) == 8
    assert _score_theta(12.0) == 3
