class PricingError(Exception):
    """Base class for all pricing-engine errors."""


class InvalidTierError(PricingError):
    """Raised when a booking references a seat tier that doesn't exist."""


class InvalidQuantityError(PricingError):
    """Raised when a requested quantity is invalid (zero/negative)."""


class SoldOutError(PricingError):
    """Raised when a tier doesn't have enough seats left for the request."""
