"""
Demo runner - simulates the Friday-night multiplex counter from the
problem statement: import + clean a messy seat-class price sheet, three
seating tiers (one close to sold out), a festival flat discount, a capped
member percentage discount, a convenience fee, and slab-based GST - printed
as a clean line-by-line bill.

Run:  python main.py
"""

import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ticket_pricing import (
    PricingEngine, SeatTier, TicketRequest,
    FlatDiscountOffer, PercentageDiscountOffer, OfferEngine,
    ConvenienceFee, SoldOutError, InvalidTierError,
    load_price_list_csv, import_price_list, apply_price_list,
)


def build_engine() -> PricingEngine:
    seat_tiers = {
        "Silver": SeatTier("Silver", price=Decimal("100"), total_seats=80, booked_seats=20),
        "Gold": SeatTier("Gold", price=Decimal("200"), total_seats=60, booked_seats=55),
        "Recliner": SeatTier("Recliner", price=Decimal("400"), total_seats=20, booked_seats=20),  # sold out
    }

    # -- Import + clean the messy price sheet before anything else runs --
    csv_path = os.path.join(os.path.dirname(__file__), "data", "seat_price_list.csv")
    raw_rows = load_price_list_csv(csv_path)
    clean_prices, report = import_price_list(raw_rows)
    print(report.render())
    updated, unmatched = apply_price_list(seat_tiers, clean_prices)
    print(f"\nApplied {len(updated)} price update(s) to configured tiers.")
    if unmatched:
        print(f"Ignored (no matching configured tier): {', '.join(unmatched)}")
    print()

    offer_engine = OfferEngine(
        offers=[
            FlatDiscountOffer("Festival Offer", amount=Decimal("75"), min_subtotal=Decimal("300")),
            PercentageDiscountOffer("Member Offer", percent=Decimal("15"), cap=Decimal("120")),
        ],
        mode="best_of",   # counters typically don't let offers stack
    )

    convenience_fee = ConvenienceFee(per_ticket=Decimal("29"), gst_rate=Decimal("18"))

    return PricingEngine(seat_tiers=seat_tiers, offer_engine=offer_engine, convenience_fee=convenience_fee)


def main():
    engine = build_engine()

    print("Scenario 1: 2 Silver + 2 Gold, member offer beats festival offer\n")
    receipt = engine.price([TicketRequest("Silver", 2), TicketRequest("Gold", 2)])
    print(receipt.render())

    print("\nScenario 2: trying to book a sold-out Recliner seat\n")
    try:
        engine.price([TicketRequest("Recliner", 1)])
    except SoldOutError as e:
        print(f"Booking rejected: {e}")

    print("\nScenario 3: booking an unknown tier\n")
    try:
        engine.price([TicketRequest("VIP-Lounge", 1)])
    except InvalidTierError as e:
        print(f"Booking rejected: {e}")

    print("\nScenario 4: confirming a real booking commits the seats\n")
    receipt = engine.confirm([TicketRequest("Silver", 3)])
    print(receipt.render())
    print(f"\nSilver seats now booked: {engine.seat_tiers['Silver'].booked_seats}"
          f"/{engine.seat_tiers['Silver'].total_seats}")


if __name__ == "__main__":
    main()
