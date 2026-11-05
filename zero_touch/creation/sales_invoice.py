"""Builds a Sales Invoice payload from reviewed values and the document's field mapping.

Returns the payload and a list of blockers. Nothing is created here; the caller creates the draft only
when there are no blockers.
"""

from dataclasses import dataclass, field

import frappe
from frappe import _

from zero_touch.mapping.compat import AUTO_FILLED_FIELDS
from zero_touch.mapping.line_fields import (
	AMOUNT_FIELDS,
	CODE_FIELDS,
	NAME_FIELDS,
	QTY_FIELDS,
	RATE_FIELDS,
	canonical,
	field_for,
	is_line_item,
)
from zero_touch.mapping.transforms import apply_transform

ITEM_FIELD_DEFAULT_TRANSFORM = {"qty": "none", "rate": "money", "amount": "money"}
SYSTEM_FIELDS = frozenset(
	{"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx", "amended_from"}
)



@dataclass
class Build:
	payload: dict
	blockers: list[str] = field(default_factory=list)


def _effective(row) -> str | None:
	if row.reviewed_value is not None:
		return row.reviewed_value or None
	return row.value or None


def _transform(name: str, value: str) -> str:
	return apply_transform(name or "none", value)


def _line_tables(meta) -> dict:
	"""Table fields whose rows carry a quantity and a price/amount."""
	tables = {}
	for df in meta.fields:
		if df.fieldtype not in ("Table", "Table MultiSelect") or not df.options:
			continue
		child = frappe.get_meta(df.options)
		if is_line_item(f.fieldname for f in child.fields):
			tables[df.fieldname] = child
	return tables


def _number(value) -> float:
	return float(_transform("money", str(value)))


def _unique_record_name(doctype: str, base: str) -> str:
	name = (base or "Untitled").strip()[:140]
	if not frappe.db.exists(doctype, name):
		return name
	for number in range(2, 100):
		suffix = f"-{number}"
		candidate = name[: 140 - len(suffix)] + suffix
		if not frappe.db.exists(doctype, candidate):
			return candidate
	return f"{name[:130]}-{frappe.generate_hash(length=8)}"


def _setup_link_default(fieldname: str, options: str | None) -> str | None:
	"""ERPNext's own default for common setup links (Item Group, UOM). No per-document guess."""
	if fieldname == "item_group" or options == "Item Group":
		return frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="lft asc")
	if fieldname in ("stock_uom", "uom") or options == "UOM":
		return (
			frappe.db.get_single_value("Stock Settings", "stock_uom")
			or frappe.db.get_value("UOM", {"name": "Nos"}, "name")
			or frappe.db.get_value("UOM", {"enabled": 1}, "name", order_by="name asc")
		)
	return None


def _fill_required_defaults(payload, meta, blockers) -> None:
	"""Fills what ERPNext would fill on its own form, and reports what only the mapping can supply."""
	for df in meta.fields:
		if not df.reqd or df.fieldname in SYSTEM_FIELDS or payload.get(df.fieldname):
			continue
		if df.fieldname in AUTO_FILLED_FIELDS:
			continue
		if df.default not in (None, ""):
			payload[df.fieldname] = df.default
			continue
		if df.fieldtype in ("Link", "Dynamic Link"):
			default = _setup_link_default(df.fieldname, df.options)
			if default:
				payload[df.fieldname] = default
				continue
		# A doctype whose name is a field (Item.item_code) can derive that name from the
		# document's main name. Otherwise a blank naming field fails only at insert time.
		if meta.autoname == f"field:{df.fieldname}":
			base = (
				payload.get("item_name")
				or payload.get("title")
				or payload.get("customer_name")
				or payload.get("supplier_name")
				or ""
			)
			if base:
				payload[df.fieldname] = _unique_record_name(meta.name, base)
				continue
		blockers.append(
			_("{0} is required. Map it to a document label, or fill it on the review page.").format(
				df.label or df.fieldname
			)
		)


def _fill_child_defaults(child: dict, child_meta) -> None:
	code_field = field_for({df.fieldname for df in child_meta.fields}, CODE_FIELDS)
	for df in child_meta.fields:
		if df.fieldname in child or not df.reqd:
			continue
		if df.default not in (None, ""):
			child[df.fieldname] = df.default
		elif df.fieldname == "conversion_factor":
			child[df.fieldname] = 1
		elif df.fieldname == "uom":
			code = child.get(code_field) if code_field else None
			uom = (
				frappe.db.get_value("Item", code, "stock_uom")
				if code
				else None
			) or frappe.db.get_value("UOM", {"name": "Nos"}, "name") or frappe.db.get_value(
				"UOM", {"enabled": 1}, "name", order_by="name asc"
			)
			if uom:
				child[df.fieldname] = uom


def _build_line_rows(payload, rows, extraction_doc, meta, blockers) -> None:
	"""Fills the mapped line-item table of any doctype from the rows read out of the document."""
	mapped: dict[str, list] = {}
	for row in rows:
		if row.target_table:
			mapped.setdefault(row.target_table, []).append(row)
	if not mapped:
		return

	line_tables = _line_tables(meta)
	lines = sorted(extraction_doc.lines, key=lambda line: line.line_no or 0)
	for table, table_rows in mapped.items():
		child_meta = line_tables.get(table)
		if child_meta is None:
			blockers.append(
				_("{0}: only line-item tables (with quantity and price) can be filled from a document").format(
					meta.get_field(table).label or table
				)
			)
			continue
		if not lines:
			blockers.append(_("No item rows were read from the document"))
			continue
		by_field = {row.target_field.split(".", 1)[-1]: row for row in table_rows}
		child_fields = {df.fieldname for df in child_meta.fields}
		name_field = field_for(child_fields, NAME_FIELDS)
		code_field = field_for(child_fields, CODE_FIELDS)
		qty_field = field_for(child_fields, QTY_FIELDS)
		rate_field = field_for(child_fields, RATE_FIELDS)
		amount_field = field_for(child_fields, AMOUNT_FIELDS)
		built = []
		for line in lines:
			name = (line.item_name or "").strip()
			if not name:
				blockers.append(_("Item row {0} has no name").format(line.line_no))
				continue
			child = {}
			if code_field:
				code = (
					line.item_code
					or frappe.db.get_value("Item", {"item_name": name, "disabled": 0}, "name")
					or frappe.db.get_value("Item", {"name": name, "disabled": 0}, "name")
				)
				if code:
					child[code_field] = code
				elif code_field in by_field and by_field[code_field].required:
					blockers.append(
						_("Item {0} does not exist in ERPNext. Create the item or correct its name").format(name)
					)
					continue
			for field, row in by_field.items():
				item_field = canonical(field)
				if item_field is None or field in child:
					continue
				if item_field == "item_name":
					value = name
				elif item_field == "item_code":
					continue
				else:
					value = getattr(line, item_field, None)
				if value in (None, ""):
					continue
				try:
					child[field] = (
						_number(value)
						if item_field in ("qty", "rate", "amount")
						else _transform(row.transform, value)
					)
				except ValueError as exc:
					blockers.append(_("Item {0}: {1}").format(name, str(exc)))
			if name_field and not child.get(name_field):
				child[name_field] = name
			if (
				amount_field
				and not child.get(amount_field)
				and child.get(qty_field)
				and child.get(rate_field)
			):
				child[amount_field] = float(child[qty_field]) * float(child[rate_field])
			_fill_child_defaults(child, child_meta)
			built.append(child)
		payload[table] = built


def build_payload(intake_doc, extraction_doc, mapping) -> Build:
	blockers: list[str] = []
	fields = {row.field_key: row for row in extraction_doc.fields}
	target = mapping.target_doctype if mapping else intake_doc.target_doctype
	meta = frappe.get_meta(target)
	payload: dict = {"doctype": target}
	if meta.has_field("company"):
		payload["company"] = intake_doc.company
	rows = list(mapping.rows) if mapping else []

	for row in rows:
		if row.target_table or row.source == "ERPNext fills automatically":
			continue
		extracted = fields.get(row.target_field)
		value = _effective(extracted) if extracted else None
		label = row.target_label or row.target_field
		if not value:
			if row.required:
				blockers.append(_("{0} is missing").format(label))
			continue
		if extracted.link_doctype:
			if extracted.link_status not in ("matched", "created") or not extracted.link_name:
				blockers.append(_("{0}: {1} is not linked to an ERPNext record").format(label, value))
				continue
			payload[row.target_field] = extracted.link_name
			continue
		try:
			payload[row.target_field] = _transform(row.transform, value)
		except ValueError as exc:
			blockers.append(_("{0}: {1}").format(label, str(exc)))

	# Values are normally written by the mapping loop above. When the profile has no
	# mapping, the extracted fields are used directly, using the target field's own type.
	for field in extraction_doc.fields:
		key = field.field_key
		if key in payload or not meta.has_field(key):
			continue
		value = _effective(field)
		if not value:
			continue
		df = meta.get_field(key)
		try:
			if df.fieldtype in ("Date", "Datetime"):
				payload[key] = _transform("date_iso", value)
			elif df.fieldtype in ("Currency", "Float"):
				payload[key] = _transform("money", value)
			else:
				payload[key] = value
		except ValueError as exc:
			blockers.append(_("{0}: {1}").format(df.label or key, str(exc)))

	invoice = target in ("Sales Invoice", "Purchase Invoice")
	if invoice:
		payload.setdefault("items", [])
		item_rows = [row for row in rows if row.target_table == "items"]
		lines = sorted(extraction_doc.lines, key=lambda line: line.line_no or 0)
		if item_rows and not lines:
			blockers.append(_("No item rows were read from the document"))
		for line in lines:
			item = {}
			name = (line.item_name or "").strip()
			if not name:
				blockers.append(_("Item row {0} has no name").format(line.line_no))
				continue
			code = line.item_code or frappe.db.get_value("Item", {"item_name": name, "disabled": 0}, "name") or (
				frappe.db.get_value("Item", {"name": name, "disabled": 0}, "name")
			)
			if not code:
				blockers.append(_("Item {0} does not exist in ERPNext. Create the item or correct its name").format(name))
				continue
			item["item_code"] = code
			for key, source in (("qty", line.qty), ("rate", line.rate)):
				if not source:
					blockers.append(_("Item {0}: {1} is missing").format(name, key))
					continue
				try:
					item[key] = float(_transform(ITEM_FIELD_DEFAULT_TRANSFORM[key], source))
				except ValueError:
					blockers.append(_("Item {0}: {1} is not a number").format(name, key))
			payload["items"].append(item)

		if not payload.get("posting_date"):
			entered = fields.get("posting_date")
			if entered and _effective(entered):
				payload["posting_date"] = _effective(entered)
		if not payload.get("posting_date"):
			blockers.append(_("Posting date is missing. Enter it on the page, or map the invoice date to Posting Date"))
		elif meta.has_field("set_posting_time"):
			# ERPNext replaces the posting date with today unless this flag is set.
			payload["set_posting_time"] = 1
		customer_field = fields.get("customer")
		customer_value = _effective(customer_field) if customer_field else None
		if not payload.get("customer") and not customer_value:
			blockers.append(_("Customer is missing"))
		tax_template = frappe.db.get_value(
			"Sales Taxes and Charges Template", {"company": intake_doc.company, "is_default": 1}, "name"
		)
		tax_row = fields.get("total_taxes_and_charges")
		tax_value = _effective(tax_row) if tax_row else None
		if tax_template:
			payload["taxes_and_charges"] = tax_template
		elif tax_value:
			account = frappe.db.get_single_value("Zero Touch Settings", "tax_account")
			if not account:
				blockers.append(
					_("Set the tax account (VAT) in Zero Touch Settings so the tax read from the document can be posted")
				)
			else:
				payload.setdefault("taxes", []).append(
					{
						"charge_type": "Actual",
						"account_head": account,
						"description": _("VAT"),
						"tax_amount": _transform("money", tax_value),
					}
				)
	else:
		# Any other doctype (Customer, Quotation, ...): header fields from the mapping,
		# line rows into the mapped line-item table.
		_build_line_rows(payload, rows, extraction_doc, meta, blockers)
		# Quotations, Sales Orders and similar documents compute their own taxes from the
		# taxes child table. Without this row the draft silently loses the VAT that was
		# printed on the document (2,865.00 became a 2,865.00 grand total).
		taxes_field = meta.get_field("taxes") if meta.has_field("taxes") else None
		tax_row = fields.get("total_taxes_and_charges")
		tax_value = _effective(tax_row) if tax_row else None
		if taxes_field and taxes_field.options == "Sales Taxes and Charges" and tax_value:
			account = frappe.db.get_single_value("Zero Touch Settings", "tax_account")
			if not account:
				blockers.append(
					_("Set the tax account (VAT) in Zero Touch Settings so the tax read from the document can be posted")
				)
			else:
				payload["taxes"] = [
					{
						"charge_type": "Actual",
						"account_head": account,
						"description": _("VAT"),
						"tax_amount": _transform("money", tax_value),
					}
				]
		_fill_required_defaults(payload, meta, blockers)
		if target == "Customer":
			payload.setdefault("customer_type", "Company")
			if not payload.get("customer_group"):
				group = frappe.db.get_single_value("Selling Settings", "customer_group") or frappe.db.get_value(
					"Customer Group", {"is_group": 0}, "name", order_by="lft asc"
				)
				if group:
					payload["customer_group"] = group
			if not payload.get("territory"):
				territory = frappe.db.get_single_value("Selling Settings", "territory") or frappe.db.get_value(
					"Territory", {"is_group": 0}, "name", order_by="lft asc"
				)
				if territory:
					payload["territory"] = territory
			name = payload.get("customer_name")
			if name and frappe.db.exists("Customer", name):
				blockers.append(_("Customer {0} already exists").format(name))
	return Build(payload=payload, blockers=blockers)


def extracted_grand_total(extraction_doc) -> str | None:
	for row in extraction_doc.fields:
		if row.field_key == "grand_total":
			return _effective(row)
	return None
