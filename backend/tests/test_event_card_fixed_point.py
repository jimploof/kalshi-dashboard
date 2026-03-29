from app.services.catalog.fixed_point import parse_fp, sum_fp


def test_parse_fp_none_returns_zero() -> None:
    assert str(parse_fp(None)) == "0"


def test_sum_fp_quantizes_to_two_decimals() -> None:
    assert sum_fp(["1.005", "2.004"]) == "3.01"


def test_sum_fp_malformed_values_normalize_to_zero() -> None:
    assert sum_fp(["5.25", "bad", None]) == "5.25"