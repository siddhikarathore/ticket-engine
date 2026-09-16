# ticket_pricing

A paisa-exact pricing engine for a multiplex booking counter — Silver / Gold /
Recliner seat tiers, sold-out enforcement, a flat festival discount, a capped
percentage member discount, a per-ticket convenience fee, and slab-based GST —
all reduced to a clean, line-by-line bill that always adds up exactly. Includes
a messy price-list import/cleaning module and a themed Streamlit counter UI.

## 1. Requirements

- Python 3.9+ (the engine itself uses only the standard library, `decimal`
  in particular — no external runtime dependencies)
- `pytest` — to run the test suite
- `streamlit` — to run the UI (see `requirements.txt`)

## 2. Setup

```bash
git clone <this-repo-url>
cd ticket_pricing
python3 -m venv .venv          # optional but recommended
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 3. The messy price-list import

`data/seat_price_list.csv` is a deliberately messy sample sheet — duplicate
tier names in different cases, currency symbols and "Rs." prefixes,
thousands-comma formatting, blank prices, negative prices, a zero price,
and a blank tier name. Both `main.py` and `app.py` import and clean it
before building the engine, and print/show the full report of what
happened to every row.

Run just the import on its own to see it in isolation:

```bash
python3 -c "
import sys; sys.path.insert(0, 'src')
from ticket_pricing import load_price_list_csv, import_price_list
rows = load_price_list_csv('data/seat_price_list.csv')
clean, report = import_price_list(rows)
print(report.render())
"
```

To try your own messy sheet, edit `data/seat_price_list.csv` (same two
columns: `name,price`) and re-run `main.py` or reload the Streamlit app.

## 4. Running the UI

```bash
streamlit run app.py
```

This opens an interactive booking-counter screen styled as a cinema
box-office at night (dark marquee background, gold accent, the bill
rendered as an actual printed receipt):

- Live seat availability per tier as a card with a status badge — open
  (gold), low stock (red-tinted), or **SOLD OUT** (disabled entirely,
  not just rejected on submit)
- Pick a quantity per tier and the bill breakup on the right updates
  instantly — every line item (gross per tier, the offer actually applied,
  convenience fee, GST per tier, GST on the fee) plus the grand total,
  laid out like a printed receipt with dashed rules
- Two toggles ("Customer is a member" / "Festival period is on") that
  control which offers are even eligible to compete for "best of" on this
  quote — turn both on to see the engine pick whichever one actually saves
  the customer more
- **Confirm & Reserve Seats** actually books the seats against the shared
  in-session inventory (via `engine.confirm()`), so the live inventory
  bars at the bottom update immediately, and quantities reset for the
  next customer
- The price-import report is shown in a collapsible section at the top

**Running it in a GitHub Codespace:** once `streamlit run app.py` starts,
Codespaces will show a notification / a "Ports" tab prompt for port
`8501` — click **Open in Browser** (set the port's visibility to
"Public" if you want to share the link). Stop it with `Ctrl+C` in the
terminal.

The UI is a thin layer over the same `PricingEngine` used by `main.py` and
the tests — no pricing logic lives in `app.py` itself, so anything the
tests guarantee about correctness applies here unchanged. All CSS/HTML on
the page is rendered through a single `raw_html()` helper that flattens
multi-line markup to one line before handing it to `st.markdown()` — see
the Debugging tips section below for why that matters.

## 5. Running the demo (CLI)

```bash
python3 main.py
```

This runs four scenarios end to end and prints a formatted receipt for each:

1. A normal multi-tier booking where the engine picks whichever offer
   (flat vs. percentage) saves the customer more money.
2. Attempting to book a **sold-out** tier — rejected cleanly.
3. Attempting to book a **tier that doesn't exist** — rejected cleanly.
4. A booking that's actually **confirmed** (`engine.confirm(...)`), which
   reserves the seats against inventory only after pricing succeeds.

## 6. Running the tests

```bash
pytest -v
```

34 tests across two files:

**`test_engine.py`** — pricing rules:
- a plain multi-tier total with no offers/fee/tax
- sold-out tiers being rejected, and *not* partially reserved when one tier
  in a multi-tier request fails
- unknown tier / invalid (zero or negative) quantity handling
- the flat discount, the capped percentage discount, "best of the two"
  selection, and "stack both" mode
- a discount that would exceed the subtotal being clamped to the subtotal
  (never a negative total)
- the convenience fee scaling with ticket count, and carrying its own GST
- GST slab selection at the exact price boundary (₹100 vs ₹101)
- a stress case with an odd per-seat price, an odd quantity, a capped
  discount and GST all at once — asserting the sum of every single printed
  line item equals the grand total, to the paisa

**`test_price_import.py`** — messy price-list cleaning:
- every price format (plain number, ₹ symbol, "Rs." prefix, thousands
  comma, stray whitespace) parses to the correct `Decimal`
- blank and garbage prices both parse to `None` (and are rejected upstream)
- case-insensitive duplicate names: same price is a harmless duplicate,
  conflicting price keeps the first-seen value and is flagged, not silently
  dropped or silently overwritten
- blank tier names, negative prices, and zero prices are all rejected with
  a specific reason
- every row in a batch ends up in exactly one of imported/duplicate/rejected
  (nothing silently disappears)
- applying a cleaned price list onto real `SeatTier`s updates only matching
  tiers, leaves seat inventory untouched, and reports tiers on the sheet
  that this counter doesn't actually sell

## 7. Project layout