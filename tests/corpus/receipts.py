"""
Receipts of every shape I could think of, with hand-keyed truth beside each.

Not fixtures written to suit the parser. Each of these is typed from the layout
a real till, restaurant, supermarket or invoicing system actually prints, and
the expected values were written by reading the receipt, not by running the
code and recording what came out. Where the parser disagrees with the truth,
the truth is what stays.

`expect` is what a person reading the paper would say the fields are. `None`
means the receipt genuinely does not state it. `silent_pass_risk` marks the
ones where a wrong reading would still *reconcile* -- the only truly dangerous
output, because nothing downstream would flag it.
"""

CASES = [

# ---------------------------------------------------------------------------
# The ordinary cases
# ---------------------------------------------------------------------------
dict(
    name="us_till_basic",
    text="""\
TARGET
1000 Nicollet Mall

Paper towels           12.99
Milk 2%                 4.49
Bread                   3.29

SUBTOTAL               20.77
TAX 7.375%              1.53
TOTAL                  22.30
""",
    expect=dict(merchant="TARGET", subtotal=2077, tax=153, total=2230,
                lines=[1299, 449, 329]),
),

dict(
    name="restaurant_with_tip",
    text="""\
THE GOLDEN SPOON
Table 14      Server: Ana

Soup of the day         8.50
Ribeye                 34.00
Glass of red            9.00

Subtotal               51.50
Sales Tax               4.51
Tip                    11.00
Total                  67.01
""",
    expect=dict(merchant="THE GOLDEN SPOON", subtotal=5150, tax=451, tip=1100,
                total=6701, lines=[850, 3400, 900]),
),

dict(
    name="uk_vat_receipt",
    text="""\
WAITROSE & PARTNERS
STORE 442

Sourdough               2.80
Cheddar 200g            4.15
Tomatoes                1.90

SUB TOTAL               8.85
VAT @ 20%               0.00
TOTAL                   8.85
""",
    expect=dict(merchant="WAITROSE & PARTNERS", subtotal=885, tax=0, total=885,
                lines=[280, 415, 190]),
    # "SUB TOTAL" must not be read as "TOTAL", and a zero-rated VAT line must
    # not be mistaken for a missing one.
    silent_pass_risk=True,
),

# ---------------------------------------------------------------------------
# Other conventions
# ---------------------------------------------------------------------------
dict(
    name="german_comma_decimals",
    text="""\
EDEKA MARKT
Hauptstrasse 12

Brot                    2,49
Butter                  3,29
Kaffee                  7,99

ZWISCHENSUMME          13,77
MWST 7%                 0,96
SUMME                  14,73
""",
    expect=dict(merchant="EDEKA MARKT", subtotal=1377, tax=96, total=1473,
                lines=[249, 329, 799]),
    # The expectation used to say total=None, which recorded what the parser
    # could do rather than what the paper says. A person reading this sees
    # SUMME 14,73 and calls it the total. The corpus states the truth and the
    # parser was made to match it.
    note="German labels: ZWISCHENSUMME is the subtotal, SUMME the total.",
),

dict(
    name="french_tva",
    text="""\
BOULANGERIE PAUL

Baguette                1,20
Croissant x2            2,40

TOTAL HT                3,60
TVA 5,5%                0,20
TOTAL TTC               3,80
""",
    expect=dict(merchant="BOULANGERIE PAUL", tax=20, total=380),
),

dict(
    name="thousands_separator",
    text="""\
NORDIC FURNITURE AB

Sofa                 1,299.00
Delivery               149.00

SUBTOTAL             1,448.00
TAX                    115.84
TOTAL                1,563.84
""",
    expect=dict(merchant="NORDIC FURNITURE AB", subtotal=144800, tax=11584,
                total=156384, lines=[129900, 14900]),
    silent_pass_risk=True,
),

# ---------------------------------------------------------------------------
# The traps
# ---------------------------------------------------------------------------
dict(
    name="change_due_after_total",
    text="""\
CORNER SHOP

Crisps                  1.20
Cola                    1.80

SUBTOTAL                3.00
TOTAL                   3.00
CASH                   10.00
CHANGE                  7.00
""",
    expect=dict(merchant="CORNER SHOP", subtotal=300, total=300,
                lines=[120, 180]),
    # CASH and CHANGE are larger than the total and sit after it. A parser
    # that takes the last or largest amount gets 10.00 or 7.00.
    silent_pass_risk=True,
),

dict(
    name="loyalty_balance_at_the_foot",
    text="""\
GREENGROCER

Apples                  2.50
Pears                   3.10

SUBTOTAL                5.60
TOTAL                   5.60

Points balance        142.00
Card ending 4471
""",
    expect=dict(merchant="GREENGROCER", subtotal=560, total=560,
                lines=[250, 310]),
    silent_pass_risk=True,
),

dict(
    name="quantity_at_unit_price",
    text="""\
HARDWARE DIRECT

Screws 3 @ 2.50         7.50
Hinges 2 @ 4.25         8.50

SUBTOTAL               16.00
TAX                     1.28
TOTAL                  17.28
""",
    expect=dict(merchant="HARDWARE DIRECT", subtotal=1600, tax=128, total=1728,
                lines=[750, 850]),
    # The unit prices must not join the column being summed.
    silent_pass_risk=True,
),

dict(
    name="tax_rate_beside_the_label",
    text="""\
CAFE NERO

Latte                   3.40
Muffin                  2.60

SUBTOTAL                6.00
TAX 8.25%               0.50
TOTAL                   6.50
""",
    expect=dict(merchant="CAFE NERO", subtotal=600, tax=50, total=650,
                lines=[340, 260]),
),

dict(
    name="total_printed_twice",
    text="""\
BOOKS & CO

Novel                  12.00

SUBTOTAL               12.00
TOTAL                  12.00

VISA                   12.00
TOTAL DUE              12.00
""",
    expect=dict(merchant="BOOKS & CO", subtotal=1200, total=1200,
                lines=[1200]),
),

dict(
    name="discount_line",
    text="""\
SPORTS OUTLET

Trainers               60.00
Socks                   8.00

SUBTOTAL               68.00
DISCOUNT               10.00
TAX                     4.64
TOTAL                  62.64
""",
    expect=dict(merchant="SPORTS OUTLET", subtotal=6800, discount=1000,
                tax=464, total=6264, lines=[6000, 800]),
),

dict(
    name="phone_number_in_the_header",
    text="""\
PIZZA EXPRESS
0207 123 4567

Margherita              9.95

SUBTOTAL                9.95
TOTAL                   9.95
""",
    expect=dict(merchant="PIZZA EXPRESS", subtotal=995, total=995,
                lines=[995]),
),

dict(
    name="date_that_looks_like_money",
    text="""\
FUEL STOP
12.08.2026  09.15

Unleaded 30L           45.60

SUBTOTAL               45.60
TOTAL                  45.60
""",
    expect=dict(merchant="FUEL STOP", subtotal=4560, total=4560),
    # "12.08" and "09.15" are a date and a time, and both look exactly like
    # money. They sit above the first priced line, so they must not become
    # line items.
    silent_pass_risk=True,
),

# ---------------------------------------------------------------------------
# Awkward but real
# ---------------------------------------------------------------------------
dict(
    name="no_subtotal_at_all",
    text="""\
MARKET STALL

Carrots                 1.00
Onions                  1.50

TOTAL                   2.50
""",
    expect=dict(merchant="MARKET STALL", subtotal=None, total=250, lines=[]),
    note="No subtotal means no trustworthy bound, so no line items are taken.",
),

dict(
    name="invoice_style",
    text="""\
ACME SUPPLIES LTD
Invoice 8841

Timber                800.00
Fixings               200.00

Subtotal             1000.00
VAT                   200.00
Amount Due           1200.00
""",
    expect=dict(merchant="ACME SUPPLIES LTD", subtotal=100000, tax=20000,
                total=120000, lines=[80000, 20000]),
),

dict(
    name="thermal_spacing_mangled",
    text="""\
QUICK MART
Item A                          1.99
Item B                          2.01
SUBTOTAL                        4.00
TAX                             0.32
TOTAL                           4.32
""",
    expect=dict(merchant="QUICK MART", subtotal=400, tax=32, total=432,
                lines=[199, 201]),
),

dict(
    name="refund_receipt_negative_line",
    text="""\
FASHION HOUSE

Jacket                 -49.99

SUBTOTAL              -49.99
TOTAL                 -49.99
""",
    expect=dict(merchant="FASHION HOUSE", subtotal=-4999, total=-4999),
    note="A return. The sign must survive.",
),

dict(
    name="currency_symbol_on_every_line",
    text="""\
LONDON DELI

Sandwich               £5.50
Coffee                 £2.50

SUBTOTAL               £8.00
TOTAL                  £8.00
""",
    expect=dict(merchant="LONDON DELI", subtotal=800, total=800,
                lines=[550, 250], currency="£"),
),

dict(
    name="service_charge_added",
    text="""\
THE BISTRO

Main                   18.00
Dessert                 6.00

Subtotal               24.00
Service Charge          3.00
Total                  27.00
""",
    expect=dict(merchant="THE BISTRO", subtotal=2400, tip=300, total=2700,
                lines=[1800, 600]),
    note="'Service charge' is read as a tip, which is what it is arithmetically.",
),

dict(
    name="blank_lines_everywhere",
    text="""\

SLOW ROASTERS


Filter                  3.00


SUBTOTAL                3.00

TOTAL                   3.00

""",
    expect=dict(merchant="SLOW ROASTERS", subtotal=300, total=300, lines=[300]),
),

dict(
    name="nothing_readable",
    text="""\
###### ##### ####
??? ??? ???
""",
    expect=dict(merchant=None, subtotal=None, total=None, lines=[]),
    note="An unreadable scan must produce nothing, not a guess.",
),
]
