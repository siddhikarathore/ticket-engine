"""
Run with:  pytest -v

Covers, in order, exactly the "messy real-world" rules called out in the
problem statement:
  - plain multi-tier total
  - sold-out tiers must not be bookable
  - flat discount + capped percentage discount (best-of and stacked)
  - convenience fee
  - GST slabs + paisa-exact totals under odd quantities
"""

import sys
import os
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ticket_pricing import (
    PricingEngine, SeatTier, TicketRequest,
    FlatDiscountOffer, PercentageDiscountOffer, OfferEngine,
    ConvenienceFee, GstSlab,
    SoldOutError, InvalidTierError, InvalidQuantityError,
)

# A zero-rated slab table, used whenever a test wants to isolate a rule
# (offers, sold-out handling, ...) from GST so the arithmetic stays simple.
NO_GST = [GstSlab(up_to=None, rate=Decimal("0"))]


def make_tiers():
    return {
        "Silver": SeatTier("Silver", Decimal("150"), total_seats=50, booked_seats=0),
        "Gold": SeatTier("Gold", Decimal("250"), total_seats=30, booked_seats=0),
        "Recliner": SeatTier("Recliner", Decimal("450"), total_seats=10, booked_seats=8),
    }


def basic_engine(**kwargs):
    """Engine with GST switched off by default, so tests that aren't about
    tax can assert on round numbers. Tests that ARE about GST pass their
    own gst_slabs explicitly."""
    tiers = kwargs.pop("tiers", None) or make_tiers()
    kwargs.setdefault("gst_slabs", NO_GST)
    return PricingEngine(seat_tiers=tiers, **kwargs)


# --------------------------------------------------------------------- #
# 1. Plain booking total (no offers/fee/tax) must just be qty * price
# --------------------------------------------------------------------- #
def test_plain_multi_tier_total():
    engine = basic_engine()
    receipt = engine.price([
        TicketRequest("Silver", 2),
        TicketRequest("Gold", 1),
    ])
    assert receipt.grand_total == Decimal("550.00")  # 2*150 + 1*250, no fee/tax/offer


# --------------------------------------------------------------------- #
# 2. Sold-out tiers must not be bookable
# --------------------------------------------------------------------- #
def test_sold_out_tier_rejected():
    engine = basic_engine()  # Recliner: 10 total, 8 booked -> 2 left
    with pytest.raises(SoldOutError):
        engine.price([TicketRequest("Recliner", 3)])

    # exactly the remaining seats should still work
    receipt = engine.price([TicketRequest("Recliner", 2)])
    assert receipt.grand_total == Decimal("900.00")


def test_unknown_tier_rejected():
    engine = basic_engine()
    with pytest.raises(InvalidTierError):
        engine.price([TicketRequest("Platinum", 1)])


def test_zero_or_negative_quantity_rejected():
    with pytest.raises(InvalidQuantityError):
        TicketRequest("Silver", 0)
    with pytest.raises(InvalidQuantityError):
        TicketRequest("Silver", -1)


def test_reserving_more_than_available_raises_without_partial_booking():
    tiers = make_tiers()
    engine = PricingEngine(seat_tiers=tiers)
    with pytest.raises(SoldOutError):
        engine.confirm([TicketRequest("Silver", 1), TicketRequest("Recliner", 5)])
    # Silver must NOT have been reserved even though it was valid on its own -
    # confirm() prices (and validates) everything before reserving anything.
    assert tiers["Silver"].booked_seats == 0


# --------------------------------------------------------------------- #
# 3. Offers: flat festival discount, capped % member discount
# --------------------------------------------------------------------- #
def test_flat_discount_applied():
    offers = OfferEngine([FlatDiscountOffer("Festival Offer", Decimal("100"))])
    engine = basic_engine(offer_engine=offers)
    receipt = engine.price([TicketRequest("Gold", 2)])  # gross 500
    assert sum(o.amount for o in receipt.offers_applied) == Decimal("100.00")
    assert receipt.grand_total == Decimal("400.00")


def test_percentage_discount_is_capped():
    # 20% of 2000 would be 400, but capped at 150
    offers = OfferEngine([PercentageDiscountOffer("Member Offer", Decimal("20"), cap=Decimal("150"))])
    engine = basic_engine(offer_engine=offers)
    receipt = engine.price([TicketRequest("Gold", 8)])  # gross 2000
    assert sum(o.amount for o in receipt.offers_applied) == Decimal("150.00")


def test_best_of_picks_larger_discount_not_both():
    offers = OfferEngine(
        [
            FlatDiscountOffer("Festival Offer", Decimal("50")),
            PercentageDiscountOffer("Member Offer", Decimal("10"), cap=Decimal("500")),
        ],
        mode="best_of",
    )
    engine = basic_engine(offer_engine=offers)
    receipt = engine.price([TicketRequest("Gold", 4)])  # gross 1000; 10% = 100 > flat 50
    assert len(receipt.offers_applied) == 1
    assert receipt.offers_applied[0].label == "Member Offer"
    assert receipt.offers_applied[0].amount == Decimal("100.00")


def test_stacked_offers_apply_sequentially():
    offers = OfferEngine(
        [
            FlatDiscountOffer("Festival Offer", Decimal("100")),
            PercentageDiscountOffer("Member Offer", Decimal("10"), cap=Decimal("500")),
        ],
        mode="stack",
    )
    engine = basic_engine(offer_engine=offers)
    receipt = engine.price([TicketRequest("Gold", 4)])  # gross 1000
    # Flat 100 off first -> 900 remaining; 10% of 900 = 90
    labels_amounts = {o.label: o.amount for o in receipt.offers_applied}
    assert labels_amounts["Festival Offer"] == Decimal("100.00")
    assert labels_amounts["Member Offer"] == Decimal("90.00")


def test_discount_never_exceeds_subtotal():
    offers = OfferEngine([FlatDiscountOffer("Huge Offer", Decimal("10000"))])
    engine = basic_engine(offer_engine=offers)
    receipt = engine.price([TicketRequest("Silver", 1)])  # gross 150
    assert sum(o.amount for o in receipt.offers_applied) == Decimal("150.00")
    assert receipt.grand_total == Decimal("0.00")


# --------------------------------------------------------------------- #
# 4. Convenience fee
# --------------------------------------------------------------------- #
def test_convenience_fee_scales_with_ticket_count():
    engine = basic_engine(convenience_fee=ConvenienceFee(per_ticket=Decimal("20"), gst_rate=Decimal("18")))
    receipt = engine.price([TicketRequest("Silver", 3)])
    assert receipt.convenience_fee == Decimal("60.00")          # 3 * 20
    assert receipt.convenience_fee_gst == Decimal("10.80")      # 18% of 60


# --------------------------------------------------------------------- #
# 5. GST slabs applied per ticket price, and totals stay paisa-exact
# --------------------------------------------------------------------- #
def test_gst_slab_boundary_low_vs_high_price():
    slabs = [GstSlab(up_to=Decimal("100"), rate=Decimal("12")), GstSlab(up_to=None, rate=Decimal("18"))]
    tiers = {
        "Cheap": SeatTier("Cheap", Decimal("100"), total_seats=10),   # <=100 -> 12%
        "Costly": SeatTier("Costly", Decimal("101"), total_seats=10),  # >100 -> 18%
    }
    engine = PricingEngine(seat_tiers=tiers, gst_slabs=slabs)

    cheap = engine.price([TicketRequest("Cheap", 1)])
    assert cheap.tiers[0].gst_rate == Decimal("12")
    assert cheap.tiers[0].gst_amount == Decimal("12.00")

    costly = engine.price([TicketRequest("Costly", 1)])
    assert costly.tiers[0].gst_rate == Decimal("18")
    assert costly.tiers[0].gst_amount == Decimal("18.18")


def test_full_pipeline_is_paisa_exact_with_odd_quantities():
    """A booking chosen to stress rounding: an odd per-seat price, an odd
    quantity, a capped % discount and 18% GST all at once. The grand total
    must equal the exact sum of every printed line item - no drift."""
    tiers = {"Gold": SeatTier("Gold", Decimal("233.33"), total_seats=50)}
    offers = OfferEngine([PercentageDiscountOffer("Member Offer", Decimal("15"), cap=Decimal("1000"))])
    fee = ConvenienceFee(per_ticket=Decimal("29.50"), gst_rate=Decimal("18"))
    engine = PricingEngine(seat_tiers=tiers, offer_engine=offers, convenience_fee=fee)

    receipt = engine.price([TicketRequest("Gold", 7)])

    reconstructed = sum(item.amount for item in receipt.line_items())
    assert reconstructed == receipt.grand_total


def test_zero_price_tier_has_no_gst_and_no_negative_amounts():
    tiers = {"Free": SeatTier("Free", Decimal("0"), total_seats=5)}
    engine = PricingEngine(seat_tiers=tiers)
    receipt = engine.price([TicketRequest("Free", 2)])
    assert receipt.grand_total == Decimal("0.00")
    assert all(li.amount >= 0 or li.label.startswith("Discount") for li in receipt.line_items())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
