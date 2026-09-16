"""
Offers applied to the gross ticket subtotal (before convenience fee / GST).

Two concrete offer types are asked for in the problem statement:

  * FlatDiscountOffer        - flat rupee amount off ("festival discount")
  * PercentageDiscountOffer  - % off, capped at a max rupee amount
                                ("member discount, capped")

Both share a tiny interface (`evaluate(subtotal_paisa) -> int`) so adding a
new offer type later (BOGO, day-of-week offer, ...) doesn't touch the engine.

Stacking policy is the messy real-world bit: real box-office systems
almost always say "offers cannot be combined with any other offer", i.e.
best-of-N, not all-of-N stacked on top of each other. That is the default
here (OfferEngine.mode = "best_of"), but "stack" is supported too for
counters that *do* want to combine them - it's a one-line switch, not a
rewrite.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

from .money import rupees_to_paisa


class Offer:
    """Base class. `evaluate` receives the gross subtotal in paisa and
    returns the discount it grants, in paisa (never more than the subtotal)."""

    name: str

    def evaluate(self, subtotal_paisa: int) -> int:
        raise NotImplementedError


@dataclass
class FlatDiscountOffer(Offer):
    """e.g. "Flat ₹75 off (Festival Offer)", optionally gated behind a
    minimum spend so a ₹75 flat discount can't wipe out a ₹100 booking."""

    name: str
    amount: Decimal
    min_subtotal: Decimal = Decimal("0")

    def evaluate(self, subtotal_paisa: int) -> int:
        min_paisa = rupees_to_paisa(self.min_subtotal)
        if subtotal_paisa < min_paisa:
            return 0
        discount_paisa = rupees_to_paisa(self.amount)
        return min(discount_paisa, subtotal_paisa)


@dataclass
class PercentageDiscountOffer(Offer):
    """e.g. "20% off for members, capped at ₹150"."""

    name: str
    percent: Decimal                 # e.g. Decimal("20") means 20%
    cap: Optional[Decimal] = None    # max rupee discount, None = uncapped
    min_subtotal: Decimal = Decimal("0")

    def evaluate(self, subtotal_paisa: int) -> int:
        min_paisa = rupees_to_paisa(self.min_subtotal)
        if subtotal_paisa < min_paisa:
            return 0
        raw = (subtotal_paisa * self.percent) / Decimal("100")
        discount_paisa = int(raw.to_integral_value(rounding="ROUND_HALF_UP"))
        if self.cap is not None:
            discount_paisa = min(discount_paisa, rupees_to_paisa(self.cap))
        return min(discount_paisa, subtotal_paisa)


class OfferEngine:
    """
    Applies a set of offers to a gross subtotal (in paisa) and returns the
    total discount plus a breakdown of which offer(s) fired.

    mode="best_of" (default): only the single best-performing offer is
        applied - matches "cannot be combined with other offers".
    mode="stack": every offer that clears its minimum is applied in the
        order given, each computed on the *remaining* balance after prior
        offers - so a flat discount doesn't get percentage-discounted too.
    """

    def __init__(self, offers: List[Offer], mode: str = "best_of"):
        if mode not in ("best_of", "stack"):
            raise ValueError("mode must be 'best_of' or 'stack'")
        self.offers = offers
        self.mode = mode

    def compute(self, subtotal_paisa: int) -> Tuple[int, List[Tuple[str, int]]]:
        if not self.offers or subtotal_paisa <= 0:
            return 0, []

        if self.mode == "best_of":
            best_name, best_amount = None, 0
            for offer in self.offers:
                amount = offer.evaluate(subtotal_paisa)
                if amount > best_amount:
                    best_name, best_amount = offer.name, amount
            applied = [(best_name, best_amount)] if best_amount > 0 else []
            return best_amount, applied

        # mode == "stack"
        remaining = subtotal_paisa
        applied = []
        total_discount = 0
        for offer in self.offers:
            amount = offer.evaluate(remaining)
            if amount > 0:
                applied.append((offer.name, amount))
                total_discount += amount
                remaining -= amount
        return total_discount, applied
