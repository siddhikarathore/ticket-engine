"""
ticket_pricing
~~~~~~~~~~~~~~
A paisa-exact pricing engine for a multiplex booking counter.

Public entry point: PricingEngine (see engine.py)
"""

from .engine import PricingEngine
from .models import SeatTier, TicketRequest
from .offers import FlatDiscountOffer, PercentageDiscountOffer, OfferEngine
from .fees import ConvenienceFee
from .tax import GstSlab
from .exceptions import SoldOutError, InvalidTierError, InvalidQuantityError
from .price_import import (
    parse_price,
    canonical_name,
    import_price_list,
    load_price_list_csv,
    apply_price_list,
    ImportReport,
    RejectedRow,
    DuplicateRow,
)

__all__ = [
    "PricingEngine",
    "SeatTier",
    "TicketRequest",
    "FlatDiscountOffer",
    "PercentageDiscountOffer",
    "OfferEngine",
    "ConvenienceFee",
    "GstSlab",
    "SoldOutError",
    "InvalidTierError",
    "InvalidQuantityError",
    "parse_price",
    "canonical_name",
    "import_price_list",
    "load_price_list_csv",
    "apply_price_list",
    "ImportReport",
    "RejectedRow",
    "DuplicateRow",
]
