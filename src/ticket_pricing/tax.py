"""
GST on movie tickets in India is slab-based on the *transaction value per
ticket* (not a flat rate for the whole bill) - e.g. tickets priced at ₹100
or below attract one rate, tickets above ₹100 attract a higher rate. That
slab-by-ticket-price rule is modelled here as a small, ordered table so a
counter in a state/city with different slabs can just pass its own table in.

The "transaction value" used for slab lookup is the *net, post-discount*
price per ticket - i.e. what the customer actually pays for the seat -
which is the correct base per GST law (tax is on consideration actually
paid), not the sticker price before any offer.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from .money import rupees_to_paisa


@dataclass
class GstSlab:
    """A slab rule: if net price-per-ticket <= `up_to` rupees, `rate` % GST
    applies. Use `up_to=None` for the catch-all top slab and put it last."""

    up_to: Optional[Decimal]   # None = no upper bound
    rate: Decimal              # percent, e.g. Decimal("18")


DEFAULT_GST_SLABS: List[GstSlab] = [
    GstSlab(up_to=Decimal("100"), rate=Decimal("12")),
    GstSlab(up_to=None, rate=Decimal("18")),
]


def rate_for_ticket_price(price_per_ticket: Decimal, slabs: List[GstSlab]) -> Decimal:
    """Return the GST % that applies to a single ticket priced at
    `price_per_ticket`, per the given ordered slab table."""
    for slab in slabs:
        if slab.up_to is None or price_per_ticket <= slab.up_to:
            return slab.rate
    # Should be unreachable if the table has a catch-all (up_to=None) slab.
    raise ValueError("GST slab table has no catch-all slab for high prices")


def gst_paisa(amount_paisa: int, rate_percent: Decimal) -> int:
    """GST amount (in paisa) on `amount_paisa` at `rate_percent` percent."""
    raw = (Decimal(amount_paisa) * rate_percent) / Decimal("100")
    return int(raw.to_integral_value(rounding="ROUND_HALF_UP"))
