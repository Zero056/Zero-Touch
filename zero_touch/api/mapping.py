"""Lists the fields of a target DocType, and of its line-item tables, for the Document Field Mapping form."""

import frappe
from frappe import _

from zero_touch.mapping.compat import AUTO_FILLED_FIELDS, LAYOUT_FIELDTYPES, MAPPABLE_FIELDTYPES
from zero_touch.mapping.line_fields import (
	AMOUNT_FIELDS,
	NAME_FIELDS,
	QTY_FIELDS,
	RATE_FIELDS,
	canonical,
	field_for,
	is_line_item,
)
from zero_touch.targets import validate_target_doctype

FILLED_BY_SYSTEM = frozenset({"company", "naming_series"})
# Kept empty on purpose: the document fields are now decided by DOCUMENT_DEFAULT_FIELDS,
# GENERIC_LABELS and the target doctype's own metadata, not by a hard-coded doctype list.
FROM_DOCUMENT = frozenset()
MONEY_TYPES = ("Currency", "Float", "Percent", "Int")
DATE_TYPES = ("Date", "Datetime")
# A child table is a line-item table when its rows carry a quantity and a price/amount.
# This is what makes "items" on a Quotation, Sales Order, Delivery Note, ... behave like
# the invoice item table without naming any doctype here. The aliases live in line_fields.
# Header fields that documents normally print and that should be offered even when the
# doctype gives them a default (Quotation.transaction_date defaults to today).
DOCUMENT_DEFAULT_FIELDS = frozenset(
	{
		"transaction_date",
		"posting_date",
		"bill_date",
		"due_date",
		"valid_till",
		"delivery_date",
		"party_name",
		"customer",
		"supplier",
		"item_name",
		"tax_id",
		"email_id",
		"mobile_no",
		"phone",
		"website",
		"grand_total",
		"total",
		"total_taxes_and_charges",
		"tax_amount",
		"po_no",
		"project",
	}
)
# Fields that must not silently disappear: the party and the date identify the transaction,
# and item_name is the value an Item is built around even when the schema does not mark it reqd.
ESSENTIAL_DOCUMENT_FIELDS = frozenset(
	{"party_name", "customer", "supplier", "transaction_date", "posting_date", "bill_date", "item_name"}
)


def child_tables_for(target_doctype: str) -> tuple[str, ...]:
	"""Every table field on the doctype, in form order. No per-doctype list."""
	meta = frappe.get_meta(target_doctype)
	return tuple(
		df.fieldname
		for df in meta.fields
		if df.fieldtype in ("Table", "Table MultiSelect") and df.options and df.fieldname
	)


def _is_line_item_table(child_doctype: str) -> bool:
	return is_line_item(df.fieldname for df in frappe.get_meta(child_doctype).fields)


def _column_info(meta, fieldnames=None, extra_required=()):
	fields, mandatory = [], []
	for df in meta.fields:
		if not df.fieldname or df.fieldtype in LAYOUT_FIELDTYPES or df.fieldtype not in MAPPABLE_FIELDTYPES:
			continue
		fields.append(
			{"fieldname": df.fieldname, "label": df.label or df.fieldname, "fieldtype": df.fieldtype, "options": df.options}
		)
		if (df.reqd and not df.default or df.fieldname in extra_required) and df.fieldname not in FILLED_BY_SYSTEM:
			mandatory.append(df.fieldname)
	return fields, mandatory


@frappe.whitelist()
def get_target_fields(target_doctype: str) -> dict:
	validate_target_doctype(target_doctype)
	if not frappe.has_permission("Document Field Mapping", "write"):
		frappe.throw(_("You do not have permission to configure mappings"), frappe.PermissionError)

	meta = frappe.get_meta(target_doctype)
	fields, mandatory = _column_info(meta)

	tables = {}
	for table in child_tables_for(target_doctype):
		df = meta.get_field(table)
		child_meta = frappe.get_meta(df.options)
		line_item = _is_line_item_table(df.options)
		child_names = {field.fieldname for field in child_meta.fields}
		extra = (
			tuple(
				found
				for found in (
					field_for(child_names, NAME_FIELDS),
					field_for(child_names, QTY_FIELDS),
					field_for(child_names, RATE_FIELDS),
					field_for(child_names, AMOUNT_FIELDS),
				)
				if found
			)
			if line_item
			else ()
		)
		child_fields, child_mandatory = _column_info(child_meta, extra_required=extra)
		tables[table] = {
			"label": df.label or table,
			"doctype": df.options,
			"line_item": line_item,
			"fields": child_fields,
			"mandatory": child_mandatory,
		}

	return {
		"fields": fields,
		"mandatory": mandatory,
		"tables": tables,
	}


def _default_row(
	target_field: str,
	fieldtype: str,
	label: str,
	table: str | None,
	from_document: bool = False,
	required: bool = True,
) -> dict:
	from zero_touch.mapping.compat import default_transform, default_value_type

	if fieldtype in DATE_TYPES:
		transform = "date_iso"
	elif fieldtype in MONEY_TYPES:
		transform = "money"
	else:
		transform = default_transform(fieldtype)
	return {
		"target_field": target_field,
		"target_table": table or "",
		"target_label": label,
		"target_type": fieldtype,
		"value_type": default_value_type(fieldtype) or "text",
		"transform": transform,
		"required": 1 if required else 0,
		"source": "From document" if from_document else "ERPNext fills automatically",
	}


def _read_from_document(target_doctype: str, fieldname: str) -> bool:
	if fieldname in FROM_DOCUMENT:
		return True
	if target_doctype in ("Sales Invoice", "Purchase Invoice"):
		return False
	# For a non-invoice doctype every standard named field (customer_name, tax_id, ...)
	# comes from the document; ERPNext fills the rest.
	from zero_touch.extraction.specs import GENERIC_LABELS

	return fieldname in GENERIC_LABELS or fieldname.endswith("_name")


def _can_autofill(meta, field) -> bool:
	"""True when ERPNext itself can supply this mandatory field on insert."""
	name = field["fieldname"]
	if name in FILLED_BY_SYSTEM or name in AUTO_FILLED_FIELDS:
		return True
	df = meta.get_field(name)
	if df and df.default not in (None, ""):
		return True
	if name in ("item_group", "stock_uom", "uom") or field.get("options") in ("Item Group", "UOM"):
		return True
	# Item.item_code and other "field:<name>" namings are derived from the document's main name.
	return bool(df) and meta.autoname == f"field:{name}"


@frappe.whitelist()
def get_default_rows(target_doctype: str) -> list[dict]:
	"""Ready-to-fill rows: the mandatory header fields plus the line-item columns.

	Other child tables stay available in the Target Field dropdown, but are not added
	automatically: a document normally has exactly one line-item table.
	"""
	info = get_target_fields(target_doctype)
	meta = frappe.get_meta(target_doctype)
	types = {f["fieldname"]: (f["fieldtype"], f["label"]) for f in info["fields"]}
	field_info = {f["fieldname"]: f for f in info["fields"]}
	header = list(info["mandatory"])
	for field in info["fields"]:
		name = field["fieldname"]
		if name in header or name not in DOCUMENT_DEFAULT_FIELDS:
			continue
		if name in ("customer", "supplier") and not meta.has_field("company"):
			# Item has an optional customer field, but it is not the item's party; adding it
			# to an Item mapping only creates an empty required row.
			continue
		header.append(name)
	rows = [
		_default_row(
			name,
			*types.get(name, ("Data", name)),
			None,
			name in DOCUMENT_DEFAULT_FIELDS
			or _read_from_document(target_doctype, name)
			or not _can_autofill(meta, field_info.get(name, {"fieldname": name})),
			required=name in info["mandatory"] or name in ESSENTIAL_DOCUMENT_FIELDS,
		)
		for name in header
	]
	for table, data in info["tables"].items():
		if not data["line_item"]:
			continue
		# Only the first line-item table is the document's item grid (Quotation Item,
		# not Bundle Items). Other tables remain selectable in the dropdown.
		child_types = {f["fieldname"]: (f["fieldtype"], f["label"]) for f in data["fields"]}
		for name in data["mandatory"]:
			fieldtype, label = child_types.get(name, ("Data", name))
			rows.append(
				_default_row(
					f"{table}.{name}",
					fieldtype,
					f"{label} ({data['label']})",
					table,
					canonical(name) is not None,
					required=name in data["mandatory"],
				)
			)
		break
	return rows
