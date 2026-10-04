"""Tests for src.interest.compound_interest.

Reference values computed with the weekly-compound formula:
    principal * (1 + annual_rate/52) ** (52 * years)

These tests are the contract — the brief explicitly says WEEKLY
compounding. If a test fails, the implementation is using the wrong
formula (simple, monthly, or annual compounding instead).
"""

import math

from src.interest import compound_interest


def test_one_year_five_percent() -> None:
    # 1000 * (1 + 0.05/52) ** 52 ≈ 1051.246
    result = compound_interest(1000.0, 0.05, 1)
    assert math.isclose(result, 1051.25, abs_tol=0.01)


def test_three_years_seven_percent() -> None:
    # 5000 * (1 + 0.07/52) ** (52*3) ≈ 6166.13
    result = compound_interest(5000.0, 0.07, 3)
    assert math.isclose(result, 6166.13, abs_tol=0.05)
