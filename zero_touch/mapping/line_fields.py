"""Names that a child table commonly uses for its item columns.

A mapping is not tied to Quotation Item or Sales Invoice Item. Any doctype whose child table
carries a quantity and a price/amount is a line-item table, even when the columns are called
"quantity" and "unit_price" instead of "qty" and "rate".
"""

NAME_FIELDS = ("item_name", "description", "product_name", "particulars", "service")
CODE_FIELDS = ("item_code", "code", "sku")
QTY_FIELDS = ("qty", "quantity", "qty_in")
RATE_FIELDS = ("rate", "price", "unit_price", "selling_price", "valuation_rate")
AMOUNT_FIELDS = ("amount", "total", "line_total", "net_amount")

CANONICAL = {
	**{name: "item_name" for name in NAME_FIELDS},
	**{name: "item_code" for name in CODE_FIELDS},
	**{name: "qty" for name in QTY_FIELDS},
	**{name: "rate" for name in RATE_FIELDS},
	**{name: "amount" for name in AMOUNT_FIELDS},
}


def field_for(fieldnames, aliases) -> str | None:
	"""The first alias that is present in this child table."""
	return next((name for name in aliases if name in fieldnames), None)


def canonical(fieldname: str) -> str | None:
	"""Maps "quantity"/"unit_price"/"line_total" to qty/rate/amount."""
	return CANONICAL.get(fieldname)


def is_line_item(fieldnames) -> bool:
	"""A table is the document's item grid when it has a quantity and a price or amount."""
	names = set(fieldnames)
	quantity = field_for(names, QTY_FIELDS)
	return bool(quantity) and bool(field_for(names, RATE_FIELDS) or field_for(names, AMOUNT_FIELDS))
