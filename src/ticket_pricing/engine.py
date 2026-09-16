"""
PricingEngine: the single object a booking counter talks to.

price() runs the full pipeline and returns a paisa-exact Receipt. It never
mutates seat inventory - call engine.confirm(receipt) (or tier.reserve()
directly) only after the customer has actually paid, so a quote that's
never bought doesn't burn seats.

Pipeline (each step is intentionally its own module so any one rule can
change without touching the others):

    1. Validate tiers exist and have enough inventory available (models.py)
    2. Gross subtotal = sum(price_per_seat * qty) per tier
    3. Offers evaluated on the gross subtotal, best-of or stacked (offers.py)
    4. Discount allocated back across tiers proportionally, paisa-exact
       (money.py: largest-remainder allocation - see its docstring)
    5. Convenience fee = flat amount x total ticket count (fees.py)
    6. GST on tickets: slab-based per tier, on the *net* (post-discount)
       price per ticket (tax.py)
       GST on the convenience fee: flat rate, separate from ticket slabs
    7. Grand total = sum of every one of the above, already paisa-exact
       because every intermediate figure was computed in whole paisa.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from .exceptions import InvalidTierError, SoldOutError
from .fees import ConvenienceFee
from .models import SeatTier, TicketRequest
from .money import allocate_paisa, paisa_to_rupees, rupees_to_paisa
from .offers import OfferEngine
from .tax import DEFAULT_GST_SLABS, GstSlab, gst_paisa, rate_for_ticket_price


@dataclass
class LineItem:
    label: str
    amount: Decimal   # rupees, 2dp - always paisa-exact, never re-rounded


@dataclass
class TierBreakup:
    tier_name: str
    quantity: int
    list_price: Decimal        # price per seat before discount
    gross_amount: Decimal      # list_price * quantity
    discount: Decimal          # this tier's share of the discount
    net_amount: Decimal        # gross - discount
    gst_rate: Decimal          # % applied to this tier, from the slab table
    gst_amount: Decimal


@dataclass
class Receipt:
    tiers: List[TierBreakup]
    offers_applied: List[LineItem]
    convenience_fee: Decimal
    convenience_fee_gst: Decimal
    ticket_gst_total: Decimal
    grand_total: Decimal
    total_tickets: int

    def line_items(self) -> List[LineItem]:
        """Flat, ordered, human-readable breakup - what the counter prints
        on the receipt / shows the customer."""
        items: List[LineItem] = []
        for t in self.tiers:
            items.append(LineItem(
                f"{t.tier_name} x{t.quantity} @ ₹{t.list_price}", t.gross_amount
            ))
        for offer in self.offers_applied:
            items.append(LineItem(f"Discount - {offer.label}", -offer.amount))
        items.append(LineItem(
            f"Convenience fee ({self.total_tickets} ticket(s))", self.convenience_fee
        ))
        for t in self.tiers:
            if t.gst_amount > 0:
                items.append(LineItem(
                    f"GST on {t.tier_name} @ {t.gst_rate}%", t.gst_amount
                ))
        if self.convenience_fee_gst > 0:
            items.append(LineItem("GST on convenience fee", self.convenience_fee_gst))
        return items

    def render(self) -> str:
        lines = ["=" * 46, " BOOKING RECEIPT", "=" * 46]
        for item in self.line_items():
            sign = "-" if item.amount < 0 else " "
            lines.append(f"{item.label:<32}{sign}₹{abs(item.amount):>8}")
        lines.append("-" * 46)
        lines.append(f"{'GRAND TOTAL':<32}  ₹{self.grand_total:>8}")
        lines.append("=" * 46)
        return "\n".join(lines)


class PricingEngine:
    def __init__(
        self,
        seat_tiers: Dict[str, SeatTier],
        offer_engine: Optional[OfferEngine] = None,
        convenience_fee: Optional[ConvenienceFee] = None,
        gst_slabs: Optional[List[GstSlab]] = None,
    ):
        self.seat_tiers = seat_tiers
        self.offer_engine = offer_engine or OfferEngine(offers=[])
        self.convenience_fee = convenience_fee or ConvenienceFee(per_ticket=Decimal("0"))
        self.gst_slabs = gst_slabs or DEFAULT_GST_SLABS

    # ------------------------------------------------------------------ #
    def price(self, requests: List[TicketRequest]) -> Receipt:
        if not requests:
            raise ValueError("A booking needs at least one ticket request")

        # 1. Validate tiers + availability up front, so pricing either
        #    fully succeeds or fails with nothing half-applied.
        resolved: List[SeatTier] = []
        for req in requests:
            tier = self.seat_tiers.get(req.tier_name)
            if tier is None:
                raise InvalidTierError(f"No such seat tier: '{req.tier_name}'")
            if req.quantity > tier.available_seats:
                raise SoldOutError(
                    f"'{tier.name}' has only {tier.available_seats} seat(s) left "
                    f"(requested {req.quantity})"
                )
            resolved.append(tier)

        # 2. Gross subtotal per tier and overall (in paisa throughout).
        gross_paisa_per_tier = [
            rupees_to_paisa(tier.price) * req.quantity
            for tier, req in zip(resolved, requests)
        ]
        gross_subtotal_paisa = sum(gross_paisa_per_tier)

        # 3. Offers, evaluated on the whole booking's subtotal.
        discount_paisa, applied_offers = self.offer_engine.compute(gross_subtotal_paisa)

        # 4. Allocate that single discount figure back across tiers,
        #    proportional to each tier's share of the gross subtotal, so
        #    every tier's own GST slab is computed on its true net price.
        discount_per_tier = allocate_paisa(discount_paisa, gross_paisa_per_tier)

        # 5. Convenience fee - flat per ticket, independent of tier/price.
        total_tickets = sum(req.quantity for req in requests)
        fee_paisa = rupees_to_paisa(self.convenience_fee.per_ticket) * total_tickets
        fee_gst_paisa = gst_paisa(fee_paisa, self.convenience_fee.gst_rate)

        # 6. Per-tier net amount, GST slab lookup, GST amount.
        tier_breakups: List[TierBreakup] = []
        ticket_gst_total_paisa = 0
        for tier, req, gross_paisa, disc_paisa in zip(
            resolved, requests, gross_paisa_per_tier, discount_per_tier
        ):
            net_paisa = gross_paisa - disc_paisa
            net_per_seat = paisa_to_rupees(net_paisa) / req.quantity if req.quantity else Decimal("0")
            rate = rate_for_ticket_price(net_per_seat, self.gst_slabs)
            tier_gst_paisa = gst_paisa(net_paisa, rate)
            ticket_gst_total_paisa += tier_gst_paisa

            tier_breakups.append(TierBreakup(
                tier_name=tier.name,
                quantity=req.quantity,
                list_price=tier.price,
                gross_amount=paisa_to_rupees(gross_paisa),
                discount=paisa_to_rupees(disc_paisa),
                net_amount=paisa_to_rupees(net_paisa),
                gst_rate=rate,
                gst_amount=paisa_to_rupees(tier_gst_paisa),
            ))

        # 7. Grand total - a straight sum of already-exact paisa figures.
        net_subtotal_paisa = gross_subtotal_paisa - discount_paisa
        grand_total_paisa = (
            net_subtotal_paisa + fee_paisa + ticket_gst_total_paisa + fee_gst_paisa
        )

        offer_line_items = [
            LineItem(label=name, amount=paisa_to_rupees(amount))
            for name, amount in applied_offers
        ]

        return Receipt(
            tiers=tier_breakups,
            offers_applied=offer_line_items,
            convenience_fee=paisa_to_rupees(fee_paisa),
            convenience_fee_gst=paisa_to_rupees(fee_gst_paisa),
            ticket_gst_total=paisa_to_rupees(ticket_gst_total_paisa),
            grand_total=paisa_to_rupees(grand_total_paisa),
            total_tickets=total_tickets,
        )

    # ------------------------------------------------------------------ #
    def confirm(self, requests: List[TicketRequest]) -> Receipt:
        """Price the booking, then - only if pricing succeeds - actually
        reserve the seats. Use this (not price()) once payment is taken."""
        receipt = self.price(requests)
        for req in requests:
            self.seat_tiers[req.tier_name].reserve(req.quantity)
        return receipt
