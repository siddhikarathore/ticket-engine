from dataclasses import dataclass
from decimal import Decimal

from .exceptions import SoldOutError, InvalidQuantityError


@dataclass
class SeatTier:
    """
    One category of seating for a show (Silver / Gold / Recliner / ...).

    A tier is deliberately dumb: it knows its price and its inventory, and
    nothing about offers, fees or tax. That keeps pricing rules reusable
    across any cinema/any show, which is the whole point of the exercise.
    """

    name: str
    price: Decimal          # price per single seat, in rupees
    total_seats: int
    booked_seats: int = 0

    def __post_init__(self):
        if self.price < 0:
            raise ValueError(f"Tier '{self.name}' cannot have a negative price")
        if self.total_seats < 0:
            raise ValueError(f"Tier '{self.name}' cannot have negative total_seats")
        if self.booked_seats < 0:
            raise ValueError(f"Tier '{self.name}' cannot have negative booked_seats")

    @property
    def available_seats(self) -> int:
        return self.total_seats - self.booked_seats

    @property
    def is_sold_out(self) -> bool:
        return self.available_seats <= 0

    def reserve(self, quantity: int) -> None:
        """Commit `quantity` seats as booked. Raises SoldOutError if not enough
        are left. Call this only after pricing succeeds, so a failed price
        calculation never partially reserves seats."""
        if quantity <= 0:
            raise InvalidQuantityError("Quantity to reserve must be positive")
        if quantity > self.available_seats:
            raise SoldOutError(
                f"'{self.name}' has only {self.available_seats} seat(s) left "
                f"(requested {quantity})"
            )
        self.booked_seats += quantity


@dataclass
class TicketRequest:
    """One line of a customer's booking: N seats of a given tier."""

    tier_name: str
    quantity: int

    def __post_init__(self):
        if self.quantity <= 0:
            raise InvalidQuantityError(
                f"Quantity for tier '{self.tier_name}' must be a positive integer"
            )
