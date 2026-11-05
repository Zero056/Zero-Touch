import frappe

from zero_touch.extraction.parse import FALLBACK_ALIASES, FALLBACK_FIELDS, SALES_INVOICE_FIELDS, FieldSpec


def load_mapping(name: str, company: str | None = None):
	"""The Document Field Mapping is the document type: one record holds the target and rows."""
	if not name or not frappe.db.exists("Document Field Mapping", name):
		return None
	return frappe.get_doc("Document Field Mapping", name)


def _header_rows(mapping):
	"""Line-item (table) columns are read by the line-item reader. ERPNext-filled rows are not read from the document."""
	return [
		row
		for row in mapping.rows
		if "." not in (row.target_field or "") and row.source != "ERPNext fills automatically"
	]


GENERIC_LABELS = {
	"customer_name": (("Customer Name", "Name", "Customer", "Bill To"), ("اسم العميل", "الاسم", "اسم الشركة")),
	"supplier_name": (("Supplier Name", "Name", "Supplier", "Vendor"), ("اسم المورد", "الاسم", "اسم الشركة")),
	"tax_id": (
		("Tax No", "VAT No", "Tax ID", "TRN", "Tax Registration", "CR Number", "CR No", "Commercial Register"),
		("الرقم الضريبي", "السجل التجاري"),
	),
	"email_id": (("Email", "E-mail", "Email Address"), ("البريد الإلكتروني", "البريد")),
	"mobile_no": (("Mobile", "Mobile No", "Mobile Number"), ("الجوال", "رقم الجوال")),
	"phone": (("Phone", "Telephone", "Tel"), ("الهاتف", "رقم الهاتف")),
	"website": (("Website",), ("الموقع الإلكتروني",)),
	"customer_group": (("Customer Group",), ("مجموعة العملاء",)),
	"territory": (("Territory",), ("المنطقة",)),
	"customer_type": (("Customer Type",), ("نوع العميل",)),
	"supplier_group": (("Supplier Group",), ("مجموعة الموردين",)),
	"supplier_type": (("Supplier Type",), ("نوع المورد",)),
}
LAYOUT_TYPES = frozenset(
	{"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Heading", "Fold", "Image"}
)
# Link, Select and table fields cannot be filled from free text without a mapping that
# resolves them, so the generic fallback leaves them to defaults.
NON_TEXT_TYPES = frozenset(
	{"Link", "Select", "Table", "Table MultiSelect", "Dynamic Link", "Attach", "Attach Image", "Check"}
)


def generic_specs(target_doctype: str) -> tuple[FieldSpec, ...]:
	"""Specs for a doctype the mapping has not covered yet, from its own standard fields."""
	meta = frappe.get_meta(target_doctype)
	specs = []
	for df in meta.fields:
		labels = GENERIC_LABELS.get(df.fieldname)
		if not labels or df.fieldtype in LAYOUT_TYPES or df.fieldtype in NON_TEXT_TYPES:
			continue
		if df.fieldname == "tax_id" or df.fieldname.endswith("_tax_id"):
			kind = "tax_id"
		elif df.fieldname in ("email_id", "email", "contact_email"):
			kind = "email"
		elif df.fieldname in ("customer_name", "supplier_name"):
			kind = "name"
		elif df.fieldtype in ("Date", "Datetime"):
			kind = "date"
		elif df.fieldtype in ("Currency", "Float"):
			kind = "money"
		else:
			kind = "text"
		specs.append(
			FieldSpec(
				key=df.fieldname,
				label=df.label or df.fieldname,
				kind=kind,
				labels_en=labels[0],
				labels_ar=labels[1],
				required=bool(df.reqd),
			)
		)
	return tuple(specs)


def field_specs(mapping, target_doctype: str | None = None) -> tuple[FieldSpec, ...]:
	rows = _header_rows(mapping) if mapping else []
	if not rows:
		# A document type may be uploaded before its fields are configured. Use the target's
		# own fields instead of borrowing Sales Invoice fields for a Customer or custom doctype.
		target = mapping.target_doctype if mapping else target_doctype
		if target and target != "Sales Invoice":
			return generic_specs(target)
		return SALES_INVOICE_FIELDS
	meta = frappe.get_meta(mapping.target_doctype)
	specs = []
	for row in rows:
		kind = row.value_type
		df = meta.get_field(row.target_field)
		if df and df.fieldtype in ("Link", "Dynamic Link") and kind == "id":
			# Existing mappings were saved with "id" before Link fields defaulted to names.
			kind = "name"
		specs.append(
			FieldSpec(
				key=row.target_field,
				label=meta.get_label(row.target_field) or row.target_field,
				kind=kind,
				labels_en=(row.pdf_label_en,) if row.pdf_label_en else (),
				labels_ar=(row.pdf_label_ar,) if row.pdf_label_ar else (),
				required=bool(row.required),
			)
		)
	return tuple(specs)


def fallback_specs(specs) -> tuple[FieldSpec, ...]:
	"""For each mapped field that may not match this supplier's wording, its common wording."""
	out = []
	for spec in specs:
		fallback = FALLBACK_FIELDS.get(FALLBACK_ALIASES.get(spec.key, ""))
		if fallback is None:
			continue
		out.append(
			FieldSpec(
				key=spec.key,
				label=spec.label,
				kind=spec.kind,
				labels_en=fallback.labels_en,
				labels_ar=fallback.labels_ar,
				exclude=fallback.exclude,
				required=spec.required,
			)
		)
	return tuple(out)


def link_rules(mapping) -> dict[str, dict]:
	"""For each mapped link field: the linked DocType and whether a missing record may be created."""
	if mapping is None:
		return {}
	meta = frappe.get_meta(mapping.target_doctype)
	rules = {}
	for row in _header_rows(mapping):
		df = meta.get_field(row.target_field)
		if not df or df.fieldtype not in ("Link", "Dynamic Link"):
			continue
		doctype = df.options
		if df.fieldtype == "Dynamic Link":
			# A Dynamic Link points at a fieldname that holds the DocType, e.g. Quotation
			# party_name <- quotation_to (default Customer).
			link_field = meta.get_field(df.options) if df.options else None
			doctype = (link_field.default if link_field else None) or None
		if doctype and frappe.db.exists("DocType", doctype):
			rules[row.target_field] = {"doctype": doctype, "create": bool(row.create_if_missing)}
	return rules


def load_field_specs(profile: str, company: str | None) -> tuple[FieldSpec, ...]:
	return field_specs(load_mapping(profile, company))


def _line_tables(target_doctype: str) -> set[str]:
	"""Table fields whose rows carry a quantity and a price/amount (Quotation Item, ...)."""
	from zero_touch.mapping.line_fields import is_line_item

	meta = frappe.get_meta(target_doctype)
	found = set()
	for df in meta.fields:
		if df.fieldtype not in ("Table", "Table MultiSelect") or not df.options:
			continue
		names = {f.fieldname for f in frappe.get_meta(df.options).fields}
		if is_line_item(names):
			found.add(df.fieldname)
	return found


def item_label_map(mapping) -> dict[str, list[str]]:
	"""Labels typed on the mapping for line columns, keyed by item field, e.g. {'qty': [...]}."""
	from zero_touch.mapping.line_fields import canonical

	if mapping is None:
		return {}
	tables = _line_tables(mapping.target_doctype)
	labels: dict[str, list[str]] = {}
	for row in mapping.rows:
		if (row.target_table or "") not in tables:
			continue
		raw = (row.target_field or "").split(".", 1)[-1]
		# An item-code column on a document is still the name the line reader can supply.
		field = "item_name" if raw == "item_code" else canonical(raw)
		if field not in ("item_name", "qty", "rate", "amount"):
			continue
		names = [name for name in (row.pdf_label_en, row.pdf_label_ar) if name]
		if not names:
			continue
		labels.setdefault(field, [])
		labels[field].extend(name for name in names if name not in labels[field])
	return labels


def has_item_rows(mapping) -> bool:
	if mapping is None:
		return False
	tables = _line_tables(mapping.target_doctype)
	return any((row.target_table or "") in tables for row in mapping.rows)
