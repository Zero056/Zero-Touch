"""Matches extracted link values (Customer, Supplier) to ERPNext records, and creates missing ones when allowed.

Runs on Save Review as the user who saved, so ERPNext permissions apply to any record created.
"""

import difflib
import re
import unicodedata

import frappe
from frappe import _

from zero_touch.audit.log import write_event

NAME_FIELD = {"Customer": "customer_name", "Supplier": "supplier_name"}
TYPE_FIELD = {"Customer": "customer_type", "Supplier": "supplier_type"}
GROUP_SETTING = {
	"Customer": ("Selling Settings", "customer_group"),
	"Supplier": ("Buying Settings", "supplier_group"),
}
TERRITORY_SETTING = ("Selling Settings", "territory")


def _tax_for(rows, doctype: str) -> str | None:
	prefix = doctype.lower() + "_"
	for row in rows:
		if row.value_type == "tax_id" and (row.field_key or "").startswith(prefix):
			value = row.reviewed_value if row.reviewed_value is not None else row.value
			return value or None
	return None


def _norm_name(value: str | None) -> str:
	"""Compares names the way people write them: alef forms, ta marbuta, diacritics and spaces ignored."""
	text = unicodedata.normalize("NFKC", value or "")
	text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\u0640\u064b-\u0652\u0670]", "", text)
	for source, target in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ؤ", "و"), ("ئ", "ي")):
		text = text.replace(source, target)
	return re.sub(r"[^\w\u0600-\u06FF]+", "", text).casefold()


def _name_field(meta) -> str:
	"""The human name column of any linked DocType, without a hard-coded table.

	Item/Customer/Supplier use title_field; Item Group/UOM/Warehouse expose
	item_group_name/uom_name/warehouse_name. Anything else falls back to the record name.
	"""
	if meta.title_field and meta.has_field(meta.title_field):
		return meta.title_field
	candidate = f"{meta.name.lower().replace(' ', '_')}_name"
	if meta.has_field(candidate):
		return candidate
	return "name"


def _active_filters(meta) -> dict:
	"""Only link to enabled/not-disabled records, when the DocType has such a flag."""
	if meta.has_field("disabled"):
		return {"disabled": 0}
	if meta.has_field("enabled"):
		return {"enabled": 1}
	return {}


def _find(doctype: str, value: str, tax: str | None):
	meta = frappe.get_meta(doctype)
	label = _name_field(meta)
	filters = _active_filters(meta)

	def exact(field: str):
		query = dict(filters)
		query[field] = value
		return frappe.get_all(doctype, filters=query, pluck="name", limit=2)

	hits = exact(label)
	if not hits and label != "name":
		hits = exact("name")
	if len(hits) > 1:
		return "ambiguous", None
	if len(hits) == 1:
		return "matched", hits[0]

	# Exact match failed. Try the same name written with a different alef, ta marbuta,
	# diacritics or spacing, which is common in Arabic invoices.
	wanted = _norm_name(value)
	if wanted:
		fields = ["name"] if label == "name" else ["name", label]
		records = frappe.get_all(doctype, filters=filters, fields=fields, limit_page_length=0)
		matched = []
		for record in records:
			names = {_norm_name(record.get("name"))}
			if label != "name":
				names.add(_norm_name(record.get(label)))
			if wanted in names:
				matched.append(record.name)
				if len(matched) > 1:
					return "ambiguous", None
		if len(matched) == 1:
			return "matched", matched[0]
		# OCR can turn one Arabic letter into another ("الامريكية" / "الامربكية"). Accept a
		# near-identical name only when one record is clearly the best, never a guess between two.
		scored = []
		for record in records:
			for name in (record.get("name"), record.get(label) if label != "name" else None):
				normalized = _norm_name(name)
				if normalized:
					scored.append((difflib.SequenceMatcher(None, wanted, normalized).ratio(), record.name))
		scored.sort(reverse=True)
		if scored and scored[0][0] >= 0.9 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.03):
			return "matched", scored[0][1]

	if tax and meta.has_field("tax_id"):
		query = dict(filters)
		query["tax_id"] = tax
		by_tax = frappe.get_all(doctype, filters=query, pluck="name", limit=2)
		if len(by_tax) == 1:
			return "matched", by_tax[0]
		if len(by_tax) > 1:
			return "ambiguous", None
	return "not_found", None


def _create(doctype: str, value: str, tax: str | None) -> str:
	name_field = NAME_FIELD.get(doctype)
	if not name_field:
		frappe.throw(_("Creating {0} records from a document is not supported").format(doctype))
	values = {"doctype": doctype, name_field: value}
	type_field = TYPE_FIELD.get(doctype)
	if type_field:
		values[type_field] = "Company"
	if tax and frappe.get_meta(doctype).has_field("tax_id"):
		values["tax_id"] = tax
	group_setting = GROUP_SETTING.get(doctype)
	if group_setting:
		group_doctype, group_field = group_setting
		group = frappe.db.get_single_value(group_doctype, group_field)
		if group:
			values[group_field] = group
	if doctype == "Customer":
		territory = frappe.db.get_single_value(*TERRITORY_SETTING)
		if territory:
			values["territory"] = territory
	record = frappe.get_doc(values)
	record.insert()
	return record.name


def resolve_links(extraction_name: str, *, allow_create: bool = True) -> list[dict]:
	extraction = frappe.get_doc("Document Extraction", extraction_name)
	results = []
	for row in extraction.fields:
		if not row.link_doctype:
			continue
		value = row.reviewed_value if row.reviewed_value is not None else row.value
		value = (value or "").strip()
		if not value:
			frappe.db.set_value("Extracted Field", row.name, {"link_status": "", "link_name": None}, update_modified=False)
			continue

		doctype = row.link_doctype
		tax = _tax_for(extraction.fields, doctype)
		status, name = _find(doctype, value, tax)
		message = ""
		if status == "not_found" and row.link_create and allow_create:
			try:
				name = _create(doctype, value, tax)
				status = "created"
				write_event(
					"master_created",
					intake=extraction.intake,
					stage="review",
					message=f"{doctype} {name} created from extracted value",
				)
			except frappe.PermissionError:
				status, message = "error", _("You do not have permission to create a {0}").format(doctype)
			except frappe.ValidationError as exc:
				status, message = "error", frappe.utils.strip_html(str(exc))[:200]
		frappe.db.set_value(
			"Extracted Field",
			row.name,
			{"link_status": status, "link_name": name},
			update_modified=False,
		)
		results.append({"field_key": row.field_key, "doctype": doctype, "value": value, "status": status, "name": name, "message": message})
	return results
