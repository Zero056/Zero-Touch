"""Which value types and transforms make sense for each ERPNext field type. No Frappe imports."""

COMPATIBILITY: dict[str, dict[str, tuple[str, ...]]] = {
	"Data": {"types": ("text", "id", "tax_id", "name"), "transforms": ("none", "strip", "upper", "digits_only")},
	"Link": {"types": ("id", "tax_id", "name", "text"), "transforms": ("none", "strip", "upper")},
	"Dynamic Link": {"types": ("id", "name", "text"), "transforms": ("none", "strip", "upper")},
	"Small Text": {"types": ("text", "name"), "transforms": ("none", "strip")},
	"Text": {"types": ("text", "name"), "transforms": ("none", "strip")},
	"Long Text": {"types": ("text", "name"), "transforms": ("none", "strip")},
	"Select": {"types": ("text", "id"), "transforms": ("none", "strip", "upper")},
	"Date": {"types": ("date",), "transforms": ("none", "date_iso")},
	"Datetime": {"types": ("date",), "transforms": ("none", "date_iso")},
	"Currency": {"types": ("money",), "transforms": ("none", "money")},
	"Float": {"types": ("money",), "transforms": ("none", "money")},
	"Percent": {"types": ("money",), "transforms": ("none", "money")},
	"Int": {"types": ("money",), "transforms": ("none", "money", "digits_only")},
}

MAPPABLE_FIELDTYPES = frozenset(COMPATIBILITY)

# Mandatory fields that ERPNext's validate/insert fills from the company, price list or
# naming series. They must not become mapping blockers or "from document" defaults.
AUTO_FILLED_FIELDS = frozenset(
	{
		"naming_series",
		"company",
		"currency",
		"conversion_rate",
		"price_list",
		"price_list_currency",
		"plc_conversion_rate",
		"selling_price_list",
		"buying_price_list",
		"default_price_list",
		"taxes_and_charges",
		"shipping_rule",
		"incoterm",
		"tax_category",
		"status",
		"order_type",
		"quotation_to",
		"customer_group",
		"territory",
		"set_posting_time",
		"is_internal_customer",
		"is_internal_supplier",
	}
)

LAYOUT_FIELDTYPES = frozenset({"Section Break", "Column Break", "Tab Break", "Table", "Table MultiSelect", "Button", "HTML", "Fold", "Heading", "Image", "Attach", "Attach Image", "Signature", "Check", "Geolocation", "JSON", "Code"})


def allowed_value_types(fieldtype: str) -> tuple[str, ...]:
	return COMPATIBILITY.get(fieldtype, {}).get("types", ())


def allowed_transforms(fieldtype: str) -> tuple[str, ...]:
	return COMPATIBILITY.get(fieldtype, {}).get("transforms", ())


def default_value_type(fieldtype: str) -> str | None:
	# A Link is printed as the linked record's name, not as an internal ID. Treating it as
	# "id" made a Party field borrow a date or a CR number from the next line.
	if fieldtype in ("Link", "Dynamic Link"):
		return "name"
	types = allowed_value_types(fieldtype)
	return types[0] if types else None


def default_transform(fieldtype: str) -> str:
	transforms = allowed_transforms(fieldtype)
	return "none" if "none" in transforms else (transforms[0] if transforms else "none")
