"""
Money handling utilities.

Everything user-facing is a Decimal number of rupees (e.g. Decimal("149.00")).
Internally, once we start splitting/allocating amounts (discounts across
tiers, GST per tier, etc.) we switch to integer PAISA so that:

  1. There is zero floating-point error.
  2. Every allocation step provably sums back to the exact input amount
     (the "largest remainder" method below never loses or invents a paisa).

Rule of thumb used throughout the engine: convert to paisa as early as
possible, do all splitting/rounding in integers, convert back to Decimal
only when producing the final receipt.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import List

TWO_PLACES = Decimal("0.01")


def rupees_to_paisa(amount: Decimal) -> int:
    """Convert a Decimal rupee amount to an integer number of paisa,
    rounding half-up at the paisa boundary."""
    return int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))


def paisa_to_rupees(paisa: int) -> Decimal:
    """Convert an integer paisa amount back to a 2-decimal-place Decimal."""
    return (Decimal(paisa) / 100).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def allocate_paisa(total_paisa: int, weights: List[int]) -> List[int]:
    """
    Split `total_paisa` across len(weights) buckets in proportion to
    `weights`, guaranteeing:

      - sum(result) == total_paisa   (exact, no drift)
      - each result[i] is an integer >= 0
      - the split follows the weights as closely as integer paisa allows

    Uses the "largest remainder" (Hamilton) method: give everyone their
    floor share first, then hand out the few leftover paisa one-by-one to
    whichever buckets had the largest fractional remainder.

    If every weight is 0 (e.g. a subtotal of zero), the amount is split as
    evenly as possible instead (remainder to the first buckets).
    """
    n = len(weights)
    if n == 0:
        if total_paisa != 0:
            raise ValueError("Cannot allocate a non-zero amount across zero buckets")
        return []

    total_weight = sum(weights)

    if total_weight == 0:
        base, rem = divmod(total_paisa, n)
        result = [base] * n
        for i in range(rem):
            result[i] += 1
        return result

    floors = []
    remainders = []
    for w in weights:
        numerator = total_paisa * w
        floors.append(numerator // total_weight)
        remainders.append(numerator % total_weight)

    distributed = sum(floors)
    leftover = total_paisa - distributed

    # Largest-remainder-first order (stable tie-break: earlier index wins)
    order = sorted(range(n), key=lambda i: (-remainders[i], i))
    for i in range(leftover):
        floors[order[i]] += 1

    return floors
