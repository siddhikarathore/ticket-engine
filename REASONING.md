# REASONING

## 1. How I read the problem

The prompt gives almost no spec on purpose — it names the ingredients
(tiers, sold-out inventory, two kinds of offers, a fee, GST) and says "get
it exactly right, for any counter, not one show." So the actual task was
to *decide* the specification, the same way a real ticket-pricing service
would have to, and then build something that survives someone poking at
the edges. I treated "handle each correctly" as the grading rubric and
built outward from a plain total, adding one messy rule at a time —
exactly as the prompt suggests — rather than writing one big function.

## 2. The core decision: work in integer paisa, not float or even Decimal-with-rounding

Money bugs almost never come from getting a single multiplication wrong —
they come from **rounding several numbers separately and then expecting
them to still add up**. If you round a 3-ticket discount split across two
tiers to the nearest paisa independently for each tier, the two roundings
can drift from the true total by a paisa in either direction. With GST
slabs and a discount and a fee all in play, those paisa-level drifts stack
up, and "the bill doesn't add up by ₹0.01" is exactly the kind of bug that
looks fine in testing and then generates support tickets in production.

So the engine's internal contract is: **once a total is fixed (e.g. "total
discount for this booking is ₹120"), everything downstream is a *split* of
that fixed amount, done in whole paisa, with a method that's provably
exact.** That's `money.allocate_paisa()` — a largest-remainder (Hamilton)
apportionment: give every bucket its floor share, then hand out the
handful of leftover paisa to whichever buckets had the largest fractional
remainder. This is the same class of algorithm used for allocating seats
in parliaments, chosen here for the same reason: it's the simplest method
that guarantees the parts sum to exactly the whole, with no bias baked in
for how ties are broken.

Everything is converted to paisa (`rupees_to_paisa`) as early as possible
and only converted back to a 2-decimal `Decimal` (`paisa_to_rupees`) once,
right before it's put on the receipt. `Decimal` is still used for all
*input* prices/percentages (never `float` — `float` cannot represent
₹0.10 exactly and it will eventually show up as a wrong paisa somewhere),
but the actual splitting math is integer arithmetic, which has no rounding
mode ambiguity at all.

## 3. Working through each "messy" rule

**Seat tiers and sold-out inventory.** A tier is a name, a price, and a
seat count vs. a booked count — deliberately with no knowledge of offers
or tax, so the same tier model works whether the counter is running one
discount or five. Availability is checked for *every* line of a
multi-tier request *before* anything is priced, and inventory is only
actually reserved by `confirm()`, never by `price()`. That split matters:
a customer should be able to get a quote without seats being provisionally
locked, and if one tier in a mixed booking fails availability, nothing
should be half-committed — I have a test that specifically books a valid
tier alongside a sold-out one and asserts the valid tier was never
touched.

**Two offer types, and the stacking question the prompt doesn't answer.**
The prompt says "a flat festival discount and a percentage off for members
(capped)" — it doesn't say whether a customer can get both at once. Real
box-office and e-commerce systems overwhelmingly say "cannot be combined
with any other offer," so I made that the default (`mode="best_of"`): the
engine evaluates every configured offer against the subtotal and applies
whichever one benefits the customer most. But I didn't want to hard-code
that assumption where it can't be revisited, so `mode="stack"` is a fully
supported second mode that applies every qualifying offer in sequence,
each on the balance left after the previous one — for counters that *do*
want combinable offers. Both modes share the same `Offer.evaluate()`
interface, so adding a third offer type later (a BOGO, a day-of-week
offer) doesn't touch the stacking logic at all.

The percentage discount's cap is enforced at the point of evaluation
(`min(computed_percentage, cap)`), and both offer types clamp their
result to never exceed the subtotal itself — a discount can zero out a
booking, but it can never make the total negative.

**Convenience fee.** Flat per ticket, applied after the discount (a
convenience fee is a service charge on the transaction, not a
discountable part of the seat price), and I gave it its own GST rate
rather than folding it into ticket revenue — because in practice a
booking fee is taxed as a distinct service from the ticket itself, often
at a flat rate regardless of which price slab the ticket falls in. Keeping
it a separate object (`fees.py`) rather than a field on the engine means a
counter can change the fee or its tax treatment without touching ticket
pricing at all.

**GST — the part I spent the most time on.** The one detail I actively
chose to model, because I think it's the crux of "get it exactly right":
Indian GST on movie tickets is **slab-based on the per-ticket price**, not
one flat rate for the whole bill (tickets at/under a threshold attract one
rate, above it attract a higher rate). That's a materially different rule
from "18% of everything," and it's the kind of thing a naive solution
gets wrong by assuming a single global tax rate. I modelled it as an
ordered table of `GstSlab(up_to, rate)` entries so a counter in a
different jurisdiction can supply its own table without touching engine
code, with a sensible ₹100/12%-else-18% default.

The harder question was *which* price the slab lookup uses: the sticker
price, or the price after discount? I used the **net, post-discount
price per ticket**, because GST law taxes the actual consideration paid,
not the list price — a ticket discounted from ₹110 down to ₹95 should be
taxed as a ₹95 ticket. That's also why the discount has to be allocated
back across tiers (via the same paisa-exact allocation as above) *before*
GST is computed per tier — a single "total discount" figure isn't enough
to price GST correctly the moment more than one tier is in the booking.

**Line-by-line breakup.** The prompt explicitly calls out customers
"demanding a clear breakup," so the `Receipt` doesn't just hold a total —
it holds every line (each tier's gross, the specific offer applied and
its amount, the fee, GST per tier, GST on the fee) and a `render()` that
prints them in the order a customer would expect to read them. The
strongest test in the suite (`test_full_pipeline_is_paisa_exact_with_odd_
quantities`) doesn't assert a hand-computed number at all — it re-sums
every line item the receipt would actually print and asserts that equals
the grand total, which is really the property that matters: whatever the
rules produce, the printed bill must foot exactly.

## 4. The twist: cleaning a messy price list

The twist adds a second, distinct kind of correctness problem — not "is
the arithmetic right" but "is the *data* trustworthy before arithmetic
even starts." I treated it as its own module (`price_import.py`) rather
than bolting parsing logic onto the engine, because these are genuinely
different concerns: the engine should never have to know a price came
from a hand-edited spreadsheet.

**Parsing messy prices.** A price string might be `"150"`, `"₹150.00"`,
`"Rs. 600"`, `"1,200"`, padded with whitespace, blank, or outright garbage
like `"abc"`. `parse_price()` strips currency symbols and known
currency words, strips thousands commas, and then validates what's left
against a strict `-?\d+(\.\d+)?` pattern before ever calling `Decimal()` on
it — so something like `"1-2-3"` or `"15.2.3"` can't sneak through as a
false positive just because `Decimal()` happens to accept some
almost-numbers. Sign is deliberately *not* rejected inside the parser
itself — a parsed `-200` comes back as `Decimal("-200")`, not `None` —
because "is this a valid number" and "is a negative price acceptable"
are two different questions with two different owners: parsing is a
syntax concern, and rejecting negative prices is a business rule that
belongs in `import_price_list`, where it sits right next to blank-name
and zero-price rejection as one of several validation checks, all
producing the same kind of reported reason.

**Deduplication policy: first-seen wins, every duplicate is reported.**
"Gold", "GOLD" and "gold" are the same seat tier with inconsistent
capitalization, not three different tiers — so dedup keys on the
lower-cased name, and the display name is normalized once via
`canonical_name()` (trim, collapse whitespace, title-case) the first time
that key is seen. The harder case is what the twist is actually testing:
what happens when two rows for the same tier *disagree* on price (e.g.
Gold=250 vs gold=300)? Silently taking the last value would let a typo
overwrite a correct price with no trace; silently taking the highest or
lowest would be guessing at intent with no basis. I chose **first-seen
wins**, and logged the ignored row either way — as a harmless duplicate if
the price agreed, or explicitly flagged as a **conflicting** duplicate
(showing both the kept and dropped values) if it didn't. That keeps the
import deterministic and auditable: nothing is silently dropped without a
line in the report saying so, and a human can always see there *was* a
conflict and decide whether the sheet needs fixing at the source.

**Rejection reasons are specific, not just "invalid".** Blank price,
unparsable price, non-positive price (negative or exactly zero), and
missing tier name are each their own reason string, because "clean it and
report what was rejected" only actually helps someone fix their source
spreadsheet if the report tells them *which* rows failed *why* — "5 rows
rejected" is not an actionable report, "row X rejected: non-positive
price (₹-200)" is.

**Applying the cleaned list without touching inventory.** `apply_price_
list()` updates an existing counter's tier *prices* by case-insensitive
name match, and deliberately leaves `total_seats`/`booked_seats`
completely alone — a price sheet from finance has no business changing how
many seats a screen has. It also doesn't auto-create a new tier for a
name on the sheet that the counter doesn't otherwise sell (e.g. "Premium"
or "Recliner Deluxe" in the sample data) — that's reported as `unmatched`
rather than guessed at, because inventing a seat count for a brand-new
tier is exactly the kind of silent assumption that caused the original
"mis-pricing" complaint in the first place. Every accepted, deduplicated,
and rejected row is accounted for in `ImportReport.total_rows`, which the
test suite checks explicitly (`test_report_accounts_for_every_row_
exactly_once`) — nothing should ever just vanish between input and report.

## 5. UI

The engine was built and tested as a standalone library first, deliberately
decoupled from any interface — `main.py` (a CLI demo) and `app.py` (a
Streamlit counter screen) are both thin callers of the same
`PricingEngine`, `price()` and `confirm()`. `app.py` adds nothing to the
pricing rules themselves; it recomputes a `Receipt` on every widget change
so staff see the breakup update live, and only actually calls
`engine.confirm()` (which reserves inventory) on an explicit button press —
mirroring the "quote first, commit only on payment" split the engine itself
enforces. Keeping the UI this thin means the correctness guarantees from
the test suite carry over to it unchanged.

**Visual design.** Once the engine was proven correct, I gave the counter
screen an identity grounded in the actual subject rather than a default
Streamlit look: a cinema box-office at night. The palette is a near-black
background with a marquee-gold accent (`#d4af37`) rather than a generic
light theme; the one display font (Bebas Neue) is used only for the
"NOW SHOWING" marquee headline, everything else stays in a plain sans
(Inter) so the boldness stays in one place. The bill itself is rendered
as an actual printed receipt — cream paper background, monospaced
(JetBrains Mono) figures, dashed rules between line items, a bold total,
and a torn-perforation strip — because the deliverable the customer
actually cares about *is* the receipt, so it earns the most deliberate
treatment on the page. Seat inventory is shown as gold-to-red progress
bars rather than a plain table, which reads faster at a glance than
numbers alone.

**A Streamlit-specific bug worth documenting.** Midway through the redesign,
the entire CSS block started rendering as visible plain text on the page
instead of being applied as a stylesheet. The cause: `st.markdown()` runs
its input through a Markdown parser *before* rendering any HTML, and one
CSS line (`* { font-family: 'Inter', sans-serif; }`) began with `* ` —
which Markdown reads as a bullet-list marker, corrupting the `<style>`
tag's structure so the browser stopped treating the remainder as CSS at
all. The fix generalizes past that one line: every HTML/CSS string handed
to `st.markdown()` is now flattened to a single line (no newlines, no
leading whitespace) through one small `raw_html()` helper before being
rendered, which removes every line-start character a Markdown parser
could possibly misinterpret — not just the one that happened to break
first. This is a good example of the twist's actual lesson generalizing
beyond the price-list data itself: untrusted-looking input isn't only
what a spreadsheet hands you, it's also what a library's own preprocessing
step might do to content you assumed would pass through untouched.

## 6. What I'd add with more time

- Configurable rounding at the *ticket* level for jurisdictions that round
  the final payable amount to the nearest whole rupee (some UPI/cash
  flows do) — currently everything is paisa-exact throughout, which is
  the more common and more defensible default.
- A persistence/inventory layer so `confirm()` is atomic under concurrent
  bookings (currently it's a plain in-memory mutation, fine for a single
  counter process, not for multiple counters sharing one show).
- A thin CLI/REST layer over `PricingEngine` — deliberately left out
  because the exercise is about the pricing rules, not a delivery
  mechanism, and adding one would have traded engine-correctness time for
  framework boilerplate.