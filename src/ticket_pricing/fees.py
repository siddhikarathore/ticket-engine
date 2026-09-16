"""
Convenience fee: a small flat charge per ticket (regardless of tier), added
after discounts. In real booking systems this fee is itself a taxable
service and carries its own flat GST rate (typically 18%), separate from
the ticket-price GST slabs in tax.py - that's why it's modelled separately
rather than folded into the ticket price before GST is calculated.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ConvenienceFee:
    per_ticket: Decimal          # flat rupee fee per ticket
    gst_rate: Decimal = Decimal("18")  # GST % applied to the fee itself
