"""
Run with: pytest -v

Covers every messiness the twist calls out explicitly:
  - duplicate names in different cases (same price -> harmless; different
    price -> conflict, first-seen kept, reported)
  - inconsistent price formats (currency symbol, "Rs.", thousands comma,
    stray whitespace, plain number) all parsing correctly
  - blank prices, negative prices, zero, and unparsable garbage all
    rejected with a specific reason
  - blank tier names rejected
  - applying a cleaned list onto real SeatTiers: matched tiers get updated,
    unrecognised tier names are reported rather than silently created
"""

import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ticket_pricing import SeatTier
from ticket_pricing.price_import import (
    parse_price, canonical_name, import_price_list, apply_price_list,
)


# --------------------------------------------------------------------- #
# parse_price - the messy-format parser in isolation
# --------------------------------------------------------------------- #
def test_parse_plain_number():
    assert parse_price("150") == Decimal("150")


def test_parse_rupee_symbol():
    assert parse_price("₹150.00") == Decimal("150.00")


def test_parse_rs_prefix():
    assert parse_price("Rs. 600") == Decimal("600")
    assert parse_price("Rs600") == Decimal("600")


def test_parse_thousands_comma():
    assert parse_price("1,200") == Decimal("1200")


def test_parse_surrounding_whitespace():
    assert parse_price("  450.00  ") == Decimal("450.00")


def test_parse_blank_is_none():
    assert parse_price("") is None
    assert parse_price("   ") is None
    assert parse_price(None) is None


def test_parse_garbage_is_none():
    assert parse_price("abc") is None
    assert parse_price("free!") is None


def test_parse_negative_still_parses_sign_is_a_business_rule_not_a_parse_error():
    # parse_price itself doesn't reject negatives - import_price_list does.
    assert parse_price("-200") == Decimal("-200")


# --------------------------------------------------------------------- #
# canonical_name
# --------------------------------------------------------------------- #
def test_canonical_name_normalises_case_and_whitespace():
    assert canonical_name("GOLD") == "Gold"
    assert canonical_name("gold") == "Gold"
    assert canonical_name("  Gold  ") == "Gold"
    assert canonical_name("recliner deluxe") == "Recliner Deluxe"


# --------------------------------------------------------------------- #
# import_price_list - the full cleaning pipeline
# --------------------------------------------------------------------- #
def test_clean_rows_are_imported():
    rows = [{"name": "Silver", "price": "150"}, {"name": "Gold", "price": "250"}]
    clean, report = import_price_list(rows)
    assert clean == {"Silver": Decimal("150.00"), "Gold": Decimal("250.00")}
    assert len(report.imported) == 2
    assert not report.duplicates and not report.rejected


def test_duplicate_same_price_is_harmless_and_reported():
    rows = [
        {"name": "Gold", "price": "250"},
        {"name": "GOLD", "price": "250.00"},
        {"name": " gold ", "price": "₹250"},
    ]
    clean, report = import_price_list(rows)
    assert clean == {"Gold": Decimal("250.00")}
    assert len(report.duplicates) == 2
    assert all("same price" in d.reason for d in report.duplicates)


def test_duplicate_conflicting_price_keeps_first_seen_and_flags_conflict():
    rows = [
        {"name": "Gold", "price": "250"},
        {"name": "gold", "price": "300"},
    ]
    clean, report = import_price_list(rows)
    assert clean == {"Gold": Decimal("250.00")}  # first-seen wins
    assert len(report.duplicates) == 1
    assert "CONFLICTING" in report.duplicates[0].reason
    assert report.duplicates[0].kept_price == Decimal("250.00")


def test_blank_price_rejected():
    clean, report = import_price_list([{"name": "Recliner", "price": ""}])
    assert clean == {}
    assert len(report.rejected) == 1
    assert "blank or unparsable" in report.rejected[0].reason


def test_unparsable_price_rejected():
    clean, report = import_price_list([{"name": "Balcony", "price": "abc"}])
    assert clean == {}
    assert "blank or unparsable" in report.rejected[0].reason


def test_negative_price_rejected():
    clean, report = import_price_list([{"name": "VIP", "price": "-200"}])
    assert clean == {}
    assert "non-positive" in report.rejected[0].reason


def test_zero_price_rejected():
    clean, report = import_price_list([{"name": "Balcony", "price": "0"}])
    assert clean == {}
    assert "non-positive" in report.rejected[0].reason


def test_blank_name_rejected():
    clean, report = import_price_list([{"name": "", "price": "300"}])
    assert clean == {}
    assert report.rejected[0].reason == "missing seat-tier name"


def test_report_accounts_for_every_row_exactly_once():
    rows = [
        {"name": "Silver", "price": "150"},
        {"name": "SILVER", "price": "150"},       # duplicate
        {"name": "Gold", "price": "abc"},          # rejected
        {"name": "", "price": "300"},              # rejected
    ]
    clean, report = import_price_list(rows)
    assert report.total_rows == len(rows)
    assert len(report.imported) + len(report.duplicates) + len(report.rejected) == len(rows)


# --------------------------------------------------------------------- #
# apply_price_list - wiring the cleaned data onto real seat tiers
# --------------------------------------------------------------------- #
def test_apply_price_list_updates_matching_tiers_only():
    tiers = {
        "Silver": SeatTier("Silver", Decimal("100"), total_seats=50),
        "Gold": SeatTier("Gold", Decimal("200"), total_seats=30),
    }
    clean = {"Silver": Decimal("150.00"), "Premium": Decimal("1200.00")}
    updated, unmatched = apply_price_list(tiers, clean)

    assert tiers["Silver"].price == Decimal("150.00")
    assert tiers["Gold"].price == Decimal("200")           # untouched - not in the sheet
    assert unmatched == ["Premium"]                        # no configured "Premium" tier
    assert updated == [("Silver", Decimal("100"), Decimal("150.00"))]


def test_apply_price_list_does_not_touch_inventory():
    tiers = {"Silver": SeatTier("Silver", Decimal("100"), total_seats=50, booked_seats=10)}
    apply_price_list(tiers, {"Silver": Decimal("999.00")})
    assert tiers["Silver"].total_seats == 50
    assert tiers["Silver"].booked_seats == 10


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
