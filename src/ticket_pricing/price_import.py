"""
Cleans a messy seat-class price list (as handed to a counter by, say, a
finance/pricing team) into a validated {tier_name: Decimal price} map, and
produces a full report of what happened to every row: imported,
de-duplicated (and why), or rejected (and why).

Deliberately kept independent of PricingEngine/SeatTier: this module's job
ends at "here is a clean price list and a report" - what a counter does
with that list (build fresh tiers, update existing ones, ...) is the
caller's decision. See `apply_price_list` at the bottom for one such use.

Messiness this is built to survive, because the brief calls it out
explicitly:
  - duplicate tier names in different cases ("Gold", "GOLD", "gold")
  - prices in inconsistent formats (currency symbols, "Rs.", thousands
    commas, stray whitespace, plain numbers)
  - blank/missing prices
  - negative prices
  - unparsable garbage prices
  - blank/missing tier names
"""

import csv
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Tuple

TWO_PLACES = Decimal("0.01")

# Recognised currency words/prefixes to strip before parsing a price, e.g.
# "Rs. 150", "Rs150", "INR 150", "150 rupees". Case-insensitive.
_CURRENCY_WORDS = re.compile(r"(?i)(rs\.?|inr|rupees?)")
_CURRENCY_SYMBOLS = str.maketrans("", "", "₹$")
_VALID_NUMBER = re.compile(r"-?\d+(\.\d+)?")


def parse_price(raw) -> Optional[Decimal]:
    """
    Best-effort parse of a messy price value into a Decimal.

    Returns None for anything that isn't a real number once currency
    symbols/words, thousands separators and stray whitespace are stripped
    - i.e. blanks and genuine garbage both come back as None. The caller
    decides how to label that (this module does, in import_price_list,
    as "blank or unparsable"). Sign is NOT validated here - a parsed
    negative Decimal is returned as-is; rejecting negative prices is a
    business rule, not a parsing concern, so it's checked separately.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None

    s = s.translate(_CURRENCY_SYMBOLS)
    s = _CURRENCY_WORDS.sub("", s)
    s = s.replace(",", "")
    s = s.strip()
    if not s:
        return None

    if not _VALID_NUMBER.fullmatch(s):
        return None

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def canonical_name(raw_name: str) -> str:
    """Normalise a tier name for display: trim, collapse internal
    whitespace, title-case ('GOLD' / 'gold' / '  Gold ' -> 'Gold')."""
    return re.sub(r"\s+", " ", raw_name.strip()).title()


def _display(raw_price) -> str:
    if raw_price is None:
        return "<blank>"
    s = str(raw_price).strip()
    return s if s else "<blank>"


@dataclass
class RejectedRow:
    raw_name: str
    raw_price: str
    reason: str


@dataclass
class DuplicateRow:
    canonical_name: str
    raw_name: str
    raw_price: str
    kept_price: Decimal
    reason: str


@dataclass
class ImportReport:
    imported: List[Tuple[str, Decimal]] = field(default_factory=list)
    duplicates: List[DuplicateRow] = field(default_factory=list)
    rejected: List[RejectedRow] = field(default_factory=list)

    @property
    def total_rows(self) -> int:
        return len(self.imported) + len(self.duplicates) + len(self.rejected)

    def render(self) -> str:
        lines = ["=" * 60, " PRICE LIST IMPORT REPORT", "=" * 60]
        lines.append(f"Rows processed : {self.total_rows}")
        lines.append(f"Imported       : {len(self.imported)}")
        lines.append(f"De-duplicated  : {len(self.duplicates)}")
        lines.append(f"Rejected       : {len(self.rejected)}")

        if self.imported:
            lines.append("\n-- Imported --")
            for name, price in self.imported:
                lines.append(f"  {name:<15} ₹{price}")

        if self.duplicates:
            lines.append("\n-- De-duplicated (ignored, first-seen value kept) --")
            for d in self.duplicates:
                lines.append(
                    f"  '{d.raw_name}' -> price '{d.raw_price}': {d.reason}"
                )

        if self.rejected:
            lines.append("\n-- Rejected --")
            for r in self.rejected:
                lines.append(
                    f"  name='{r.raw_name}' price='{r.raw_price}': {r.reason}"
                )

        lines.append("=" * 60)
        return "\n".join(lines)


def import_price_list(rows: Iterable[Dict[str, str]]) -> Tuple[Dict[str, Decimal], ImportReport]:
    """
    Clean a raw seat-class price list into {canonical_name: Decimal price}.

    `rows` is any iterable of dict-like rows with "name" and "price" keys
    (e.g. csv.DictReader output). Every row ends up in exactly one bucket
    of the returned ImportReport:

      - imported:   a valid, first-seen (tier name, price)
      - duplicates: a tier name that's a case-insensitive repeat of one
                    already imported - kept the first-seen valid price,
                    regardless of whether the repeat's price agreed or
                    conflicted (both are logged, with the reason saying
                    which happened)
      - rejected:   missing name, or a price that's blank, unparsable, or
                    non-positive

    First-seen-wins is the dedup policy: whichever valid row for a given
    tier name (case-insensitively) appears earliest in the input keeps its
    price; every later repeat is logged as a duplicate rather than
    silently overwriting it, so a conflicting price never disappears
    without a trace.
    """
    report = ImportReport()
    clean_prices: Dict[str, Decimal] = {}
    seen_keys: Dict[str, str] = {}  # lowercase name -> canonical name already kept

    for row in rows:
        raw_name = (row.get("name") or "").strip()
        raw_price = row.get("price")

        if not raw_name:
            report.rejected.append(RejectedRow(
                raw_name="<blank>", raw_price=_display(raw_price),
                reason="missing seat-tier name",
            ))
            continue

        price = parse_price(raw_price)
        if price is None:
            report.rejected.append(RejectedRow(
                raw_name=raw_name, raw_price=_display(raw_price),
                reason="blank or unparsable price",
            ))
            continue
        if price <= 0:
            report.rejected.append(RejectedRow(
                raw_name=raw_name, raw_price=_display(raw_price),
                reason=f"non-positive price (₹{price})",
            ))
            continue

        price = price.quantize(TWO_PLACES)
        key = raw_name.lower()

        if key in seen_keys:
            kept_name = seen_keys[key]
            kept_price = clean_prices[kept_name]
            if price == kept_price:
                reason = f"duplicate of '{kept_name}' with the same price - ignored"
            else:
                reason = (
                    f"duplicate of '{kept_name}' with a CONFLICTING price "
                    f"(kept ₹{kept_price}, ignored ₹{price})"
                )
            report.duplicates.append(DuplicateRow(
                canonical_name=kept_name, raw_name=raw_name,
                raw_price=_display(raw_price), kept_price=kept_price, reason=reason,
            ))
            continue

        name = canonical_name(raw_name)
        seen_keys[key] = name
        clean_prices[name] = price
        report.imported.append((name, price))

    return clean_prices, report


def load_price_list_csv(path: str) -> List[Dict[str, str]]:
    """Read a price-list CSV (columns: name, price) into plain dict rows,
    ready to hand to import_price_list(). No cleaning happens here -
    that's the point of keeping this a separate, trivial step."""
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def apply_price_list(seat_tiers: Dict[str, "SeatTier"], clean_prices: Dict[str, Decimal]):
    """
    Update an existing counter's SeatTier prices from a cleaned price list,
    matched case-insensitively by tier name. Seat *inventory* (total/booked
    seats) is deliberately untouched - a price sheet from finance has no
    business changing how many seats exist, only what they cost.

    Returns (updated, unmatched):
      updated   - list of (tier_name, old_price, new_price) actually changed
      unmatched - list of cleaned names that don't correspond to any tier
                  this counter actually has configured (e.g. "Premium" or
                  "VIP" on the sheet, but this screen only sells
                  Silver/Gold/Recliner) - reported, not guessed at.
    """
    by_lower = {name.lower(): name for name in seat_tiers}
    updated = []
    unmatched = []

    for clean_name, price in clean_prices.items():
        key = clean_name.lower()
        if key not in by_lower:
            unmatched.append(clean_name)
            continue
        tier_name = by_lower[key]
        tier = seat_tiers[tier_name]
        if tier.price != price:
            updated.append((tier_name, tier.price, price))
            tier.price = price

    return updated, unmatched
