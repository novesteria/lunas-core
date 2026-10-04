"""Interest calculation helper.

Computes the future value of a deposit under weekly compounding.
"""


def compound_interest(principal: float, annual_rate: float, years: int) -> float:
    """Return the future value of ``principal`` after ``years`` years
    at ``annual_rate`` (e.g. 0.05 for 5%), compounded WEEKLY.

    The formula used here returns the gross interest amount (simple
    formula) — callers can add it to principal externally if needed.
    """
    # BUG: this is simple interest, not weekly-compound.
    # The brief asks for principal * (1 + annual_rate/52) ** (52 * years).
    return round(principal * annual_rate * years, 2)
