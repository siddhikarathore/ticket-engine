"""
Streamlit front end for the multiplex booking counter.

This is a thin UI layer only - every pricing rule (offers, fee, GST,
paisa-exact rounding) lives in src/ticket_pricing/ and is untouched by this
file. The UI just: shows live seat availability, lets the counter staff
pick tiers/quantities, recomputes the bill breakup on every change, and
lets them confirm a booking (which actually reserves seats).

Visual design: a cinema box-office counter at night - dark marquee
background, gold accent, ticket-stub cards for seat selection, and the
bill rendered as an actual printed receipt (dashed rules, monospaced
figures, a torn-edge bottom).

Run:
    streamlit run app.py
"""

import os
import sys
from decimal import Decimal

import streamlit as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ticket_pricing import (
    PricingEngine, SeatTier, TicketRequest,
    FlatDiscountOffer, PercentageDiscountOffer, OfferEngine,
    ConvenienceFee, SoldOutError, InvalidTierError, InvalidQuantityError,
    load_price_list_csv, import_price_list, apply_price_list,
)


# ======================================================================= #
# Engine setup - unchanged logic, just persisted across reruns
# ======================================================================= #
def build_engine():
    seat_tiers = {
        "Silver": SeatTier("Silver", price=Decimal("100"), total_seats=80, booked_seats=20),
        "Gold": SeatTier("Gold", price=Decimal("200"), total_seats=60, booked_seats=55),
        "Recliner": SeatTier("Recliner", price=Decimal("400"), total_seats=20, booked_seats=18),
    }

    csv_path = os.path.join(os.path.dirname(__file__), "data", "seat_price_list.csv")
    raw_rows = load_price_list_csv(csv_path)
    clean_prices, import_report = import_price_list(raw_rows)
    updated, unmatched = apply_price_list(seat_tiers, clean_prices)

    offer_engine = OfferEngine(
        offers=[
            FlatDiscountOffer("Festival Offer", amount=Decimal("75"), min_subtotal=Decimal("300")),
            PercentageDiscountOffer("Member Offer", percent=Decimal("15"), cap=Decimal("120")),
        ],
        mode="best_of",
    )
    convenience_fee = ConvenienceFee(per_ticket=Decimal("29"), gst_rate=Decimal("18"))
    engine = PricingEngine(seat_tiers=seat_tiers, offer_engine=offer_engine, convenience_fee=convenience_fee)
    return engine, import_report, updated, unmatched


if "engine" not in st.session_state:
    engine, import_report, price_updates, unmatched_names = build_engine()
    st.session_state.engine = engine
    st.session_state.import_report = import_report
    st.session_state.price_updates = price_updates
    st.session_state.unmatched_names = unmatched_names
if "last_confirmed" not in st.session_state:
    st.session_state.last_confirmed = None
if "confirm_error" not in st.session_state:
    st.session_state.confirm_error = None

engine: PricingEngine = st.session_state.engine


def raw_html(html: str):
    """Render an HTML snippet via st.markdown without letting Streamlit's
    Markdown pre-parser touch it. Streamlit runs st.markdown() content
    through a Markdown parser before rendering the HTML; multi-line,
    indented HTML can get its line breaks/indentation or stray characters
    (like a leading '*') misread as Markdown syntax and dumped onto the
    page as literal text instead of being rendered. Flattening to a single
    line removes every line-start character the parser could misinterpret."""
    st.markdown(" ".join(line.strip() for line in html.strip().splitlines()), unsafe_allow_html=True)


def confirm_booking():
    """Button callback - reads quantities from widget state, confirms
    against the real engine, resets quantity widgets for the next
    customer. See README for why this has to be a callback, not inline
    code after the button."""
    reqs = [
        TicketRequest(name, st.session_state.get(f"qty_{name}", 0))
        for name in engine.seat_tiers
        if st.session_state.get(f"qty_{name}", 0) > 0
    ]
    if not reqs:
        st.session_state.confirm_error = "Select at least one seat before confirming."
        return
    try:
        confirmed = engine.confirm(reqs)
    except (SoldOutError, InvalidTierError, InvalidQuantityError) as e:
        st.session_state.confirm_error = str(e)
        return

    st.session_state.last_confirmed = confirmed
    st.session_state.confirm_error = None
    for req in reqs:
        st.session_state[f"qty_{req.tier_name}"] = 0


# ======================================================================= #
# Page config + theme
# ======================================================================= #
st.set_page_config(page_title="Multiplex Booking Counter", page_icon="🎟️", layout="wide")

_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap');
:root {
    --bg: #12080c;
    --panel: #1c1116;
    --panel-border: #3a2530;
    --paper: #f3ead8;
    --paper-ink: #2b2118;
    --gold: #d4af37;
    --gold-soft: rgba(212, 175, 55, 0.15);
    --red: #b23a48;
    --red-soft: rgba(178, 58, 72, 0.18);
    --text: #f1e9dd;
    --muted: #b9a89c;
}
html, body, [data-testid="stAppViewContainer"], .main { background-color: var(--bg) !important; color: var(--text); }
[data-testid="stHeader"] { background: transparent; }
html, body, p, div, span, label { font-family: 'Inter', sans-serif; }
.marquee { background: linear-gradient(180deg, #1c1116 0%, #150c10 100%); border: 1px solid var(--panel-border); border-radius: 14px; padding: 28px 32px 22px 32px; margin-bottom: 22px; position: relative; overflow: hidden; }
.marquee::before { content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 15% 20%, var(--gold-soft), transparent 45%); pointer-events: none; }
.marquee-title { font-family: 'Bebas Neue', sans-serif; font-size: 3rem; letter-spacing: 0.04em; color: var(--gold); line-height: 1; margin: 0; text-shadow: 0 0 18px rgba(212,175,55,0.35); }
.marquee-sub { color: var(--muted); font-size: 0.95rem; margin-top: 6px; }
.section-label { font-size: 0.78rem; letter-spacing: 0.08em; color: var(--gold); font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
.section-label::after { content: ""; flex: 1; height: 1px; background: var(--panel-border); }
div[data-testid="stVerticalBlockBorderWrapper"] { background: var(--panel); border: 1px solid var(--panel-border) !important; border-radius: 14px !important; padding: 6px 4px; }
.tier-card { display: flex; justify-content: space-between; align-items: center; padding: 10px 4px 2px 4px; }
.tier-name { font-weight: 600; font-size: 1.05rem; color: var(--text); }
.tier-price { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }
.badge { padding: 3px 11px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; letter-spacing: 0.02em; white-space: nowrap; }
.badge-open { background: var(--gold-soft); color: var(--gold); }
.badge-low { background: var(--red-soft); color: #e2919c; }
.badge-sold { background: var(--red); color: #fff; }
div[data-testid="stNumberInput"] input { background: #241720 !important; color: var(--text) !important; border: 1px solid var(--panel-border) !important; border-radius: 8px !important; }
div[data-testid="stNumberInput"] button { background: #241720 !important; border: 1px solid var(--panel-border) !important; color: var(--gold) !important; }
[data-testid="stCheckbox"] label p { color: var(--text) !important; }
input[type="checkbox"] { accent-color: var(--gold); }
.stButton > button { background: linear-gradient(180deg, var(--gold), #b8912a) !important; color: #1c1116 !important; border: none !important; border-radius: 10px !important; font-weight: 700 !important; letter-spacing: 0.01em; padding: 0.6rem 1rem !important; transition: transform 0.12s ease, box-shadow 0.12s ease; box-shadow: 0 2px 0 rgba(0,0,0,0.25); }
.stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 10px rgba(212,175,55,0.35); }
.stButton > button:active { transform: translateY(0); }
.receipt { background: var(--paper); color: var(--paper-ink); border-radius: 6px; padding: 22px 24px 18px 24px; font-family: 'JetBrains Mono', monospace; box-shadow: 0 10px 24px rgba(0,0,0,0.35); background-image: repeating-linear-gradient(0deg, transparent, transparent 27px, rgba(0,0,0,0.03) 28px); }
.receipt-title { font-family: 'Inter', sans-serif; font-weight: 700; font-size: 0.75rem; letter-spacing: 0.1em; color: #7a6a55; margin-bottom: 10px; }
.receipt-row { display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; font-size: 0.92rem; border-bottom: 1px dashed rgba(43,33,24,0.18); }
.receipt-row .label { color: #4a3c2c; }
.receipt-row .amt { font-weight: 600; white-space: nowrap; }
.receipt-row.discount .amt { color: var(--red); }
.receipt-total { display: flex; justify-content: space-between; margin-top: 12px; padding-top: 12px; border-top: 2px solid var(--paper-ink); font-family: 'Inter', sans-serif; font-weight: 700; font-size: 1.25rem; color: var(--paper-ink); }
.receipt-total .amt { color: #7a3b1f; }
.receipt-perforation { height: 14px; background: radial-gradient(circle at 6px 0, transparent 6px, var(--bg) 6.5px) 0 -7px / 16px 14px repeat-x; margin-top: -2px; }
.inv-row { padding: 8px 2px; }
.inv-head { display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--text); margin-bottom: 5px; }
.inv-head .n { color: var(--muted); }
.inv-track { background: rgba(255,255,255,0.08); border-radius: 6px; height: 9px; overflow: hidden; }
.inv-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, var(--gold), #f0d67a); transition: width 0.4s ease; }
.inv-fill.hot { background: linear-gradient(90deg, var(--red), #e2919c); }
[data-testid="stExpander"] { background: var(--panel); border: 1px solid var(--panel-border) !important; border-radius: 12px !important; }
[data-testid="stExpander"] summary { color: var(--text) !important; }
"""

# Streamlit runs st.markdown() content through a Markdown parser before
# rendering the HTML, so a raw multi-line <style> block can get its
# indentation or a stray leading "*" (bullet syntax) misread as Markdown
# and dumped onto the page as visible text instead of being applied as
# CSS. Collapsing it to a single line sidesteps that entirely - there is
# no line-start character left for the Markdown parser to misinterpret.
_CSS_FLAT = " ".join(line.strip() for line in _CSS.strip().splitlines())
st.markdown(f"<style>{_CSS_FLAT}</style>", unsafe_allow_html=True)


# ======================================================================= #
# Header
# ======================================================================= #
raw_html("""
<div class="marquee">
    <p class="marquee-title">🎟️ NOW SHOWING &nbsp;&mdash;&nbsp; BOX OFFICE</p>
    <div class="marquee-sub">Friday night pricing, worked out to the paisa — seats, offers, fee &amp; GST, all on one receipt.</div>
</div>
""")

with st.expander("📋 Seat price list import report — data/seat_price_list.csv"):
    r = st.session_state.import_report
    c1, c2, c3 = st.columns(3)
    c1.metric("Imported", len(r.imported))
    c2.metric("De-duplicated", len(r.duplicates))
    c3.metric("Rejected", len(r.rejected))

    if r.imported:
        st.markdown("**Imported**")
        st.table([{"Tier": n, "Price": f"₹{p}"} for n, p in r.imported])
    if r.duplicates:
        st.markdown("**De-duplicated** (first-seen value kept)")
        st.table([
            {"Raw name": d.raw_name, "Raw price": d.raw_price, "Reason": d.reason}
            for d in r.duplicates
        ])
    if r.rejected:
        st.markdown("**Rejected**")
        st.table([
            {"Raw name": x.raw_name, "Raw price": x.raw_price, "Reason": x.reason}
            for x in r.rejected
        ])
    if st.session_state.unmatched_names:
        st.warning(
            "Sheet also listed tiers this counter doesn't sell (ignored): "
            + ", ".join(st.session_state.unmatched_names)
        )

col_left, col_right = st.columns([1, 1.25], gap="large")


# ======================================================================= #
# Left: seat selection
# ======================================================================= #
with col_left:
    raw_html('<div class="section-label">SELECT SEATS</div>')
    with st.container(border=True):
        for name, tier in engine.seat_tiers.items():
            if tier.is_sold_out:
                badge_html = '<span class="badge badge-sold">SOLD OUT</span>'
            elif tier.available_seats <= max(3, tier.total_seats * 0.1):
                badge_html = f'<span class="badge badge-low">{tier.available_seats} left</span>'
            else:
                badge_html = f'<span class="badge badge-open">{tier.available_seats} left</span>'

            raw_html(f"""
            <div class="tier-card">
                <div>
                    <div class="tier-name">{name}</div>
                    <div class="tier-price">₹{tier.price} per seat</div>
                </div>
                {badge_html}
            </div>
            """)

            if tier.is_sold_out:
                st.session_state.setdefault(f"qty_{name}", 0)
            else:
                st.number_input(
                    f"Quantity — {name}",
                    min_value=0,
                    max_value=tier.available_seats,
                    step=1,
                    key=f"qty_{name}",
                    label_visibility="collapsed",
                )
            raw_html("<div style='height:6px'></div>")

    raw_html('<div class="section-label" style="margin-top:18px">OFFERS</div>')
    with st.container(border=True):
        is_member = st.checkbox("Customer is a member (member discount eligible)", value=True)
        apply_festival = st.checkbox("Festival period is on (festival discount eligible)", value=True)

    raw_html("<div style='height:14px'></div>")
    st.button("✅  Confirm & Reserve Seats", type="primary", on_click=confirm_booking, use_container_width=True)

    if st.session_state.confirm_error:
        st.error(st.session_state.confirm_error)
        st.session_state.confirm_error = None

# Build the current requested booking from the widgets above.
requests = [
    TicketRequest(name, st.session_state.get(f"qty_{name}", 0))
    for name in engine.seat_tiers
    if st.session_state.get(f"qty_{name}", 0) > 0
]

active_offers = [
    offer for offer in engine.offer_engine.offers
    if not (offer.name == "Member Offer" and not is_member)
    and not (offer.name == "Festival Offer" and not apply_festival)
]
quote_engine = PricingEngine(
    seat_tiers=engine.seat_tiers,
    offer_engine=OfferEngine(offers=active_offers, mode=engine.offer_engine.mode),
    convenience_fee=engine.convenience_fee,
    gst_slabs=engine.gst_slabs,
)


# ======================================================================= #
# Right: bill breakup, rendered as a printed receipt
# ======================================================================= #
def render_receipt_html(receipt, title="BILL BREAKUP"):
    rows_html = ""
    for item in receipt.line_items():
        css_class = "discount" if item.amount < 0 else ""
        sign = "-" if item.amount < 0 else ""
        rows_html += f"""
        <div class="receipt-row {css_class}">
            <span class="label">{item.label}</span>
            <span class="amt">{sign}₹{abs(item.amount):,.2f}</span>
        </div>
        """
    return f"""
    <div class="receipt">
        <div class="receipt-title">{title}</div>
        {rows_html}
        <div class="receipt-total">
            <span>Grand Total</span>
            <span class="amt">₹{receipt.grand_total:,.2f}</span>
        </div>
    </div>
    <div class="receipt-perforation"></div>
    """


with col_right:
    raw_html('<div class="section-label">BILL BREAKUP</div>')
    if not requests:
        st.info("Pick at least one seat on the left to see a live breakup.")
    else:
        try:
            receipt = quote_engine.price(requests)
        except (SoldOutError, InvalidTierError, InvalidQuantityError) as e:
            st.error(str(e))
        else:
            raw_html(render_receipt_html(receipt))

    if st.session_state.last_confirmed:
        raw_html('<div class="section-label" style="margin-top:18px">LAST CONFIRMED BOOKING</div>')
        raw_html(render_receipt_html(st.session_state.last_confirmed, title="CONFIRMED RECEIPT"))


# ======================================================================= #
# Footer: live seat inventory, as progress bars rather than a plain table
# ======================================================================= #
raw_html('<div class="section-label" style="margin-top:22px">LIVE SEAT INVENTORY</div>')
inv_cols = st.columns(len(engine.seat_tiers))
for col, (name, tier) in zip(inv_cols, engine.seat_tiers.items()):
    pct = 0 if tier.total_seats == 0 else int(100 * tier.booked_seats / tier.total_seats)
    fill_class = "hot" if pct >= 90 else ""
    with col:
        raw_html(f"""
        <div class="inv-row">
            <div class="inv-head">
                <span>{name}</span>
                <span class="n">{tier.booked_seats}/{tier.total_seats} booked</span>
            </div>
            <div class="inv-track"><div class="inv-fill {fill_class}" style="width:{pct}%"></div></div>
        </div>
        """)