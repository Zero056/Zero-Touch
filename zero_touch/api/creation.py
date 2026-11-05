"""Whitelisted methods: preview and create the draft ERPNext document, and fill item masters."""

import frappe
from frappe import _

from zero_touch.audit.log import write_event
from zero_touch.creation.service import create_draft as _create_draft
from zero_touch.creation.service import preview_draft as _preview_draft
from zero_touch.pipeline import states


@frappe.whitelist(methods=["POST"])
def create_draft(intake: str):
	return _create_draft(intake)


@frappe.whitelist()
def preview_draft(intake: str):
	return _preview_draft(intake)


def _default_item_group() -> str:
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name", order_by="lft asc")
	if not group:
		frappe.throw(_("Create an Item Group before items can be created"))
	return group


def _default_uom() -> str:
	for uom in ("Nos", "Unit", "Units"):
		if frappe.db.exists("UOM", uom):
			return uom
	uom = frappe.db.get_value("UOM", {"enabled": 1}, "name")
	if not uom:
		frappe.throw(_("Create a Unit of Measure before items can be created"))
	return uom


def _unique_code(name: str) -> str:
	code = name[:140]
	if not frappe.db.exists("Item", code):
		return code
	for number in range(2, 100):
		suffix = f"-{number}"
		candidate = name[: 140 - len(suffix)] + suffix
		if not frappe.db.exists("Item", candidate):
			return candidate
	frappe.throw(_("Could not make a unique item code for {0}").format(name))


@frappe.whitelist(methods=["POST"])
def create_missing_items(intake: str):
	"""Creates a service item for each item row whose name is not an ERPNext item yet.

	Only runs when the user clicks the button; nothing is created automatically while reading.
	"""
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("write")
	if intake_doc.status not in (states.STATUS_PENDING_REVIEW, states.STATUS_READY):
		frappe.throw(_("This document is {0} and its items can no longer be created").format(_(intake_doc.status)))
	if not frappe.has_permission("Item", "create"):
		frappe.throw(_("You do not have permission to create items"), frappe.PermissionError)

	name = intake_doc.current_extraction
	if not name:
		frappe.throw(_("This document has not been read yet"))

	extraction = frappe.get_doc("Document Extraction", name)
	created, matched, skipped = [], [], []
	group = uom = None
	for row in extraction.lines:
		value = (row.item_name or "").strip()
		if not value:
			continue
		if row.item_code and frappe.db.exists("Item", row.item_code):
			skipped.append(row.item_code)
			continue
		existing = frappe.db.get_value("Item", {"item_name": value}, "name") or frappe.db.get_value(
			"Item", {"item_code": value}, "name"
		)
		if existing:
			frappe.db.set_value("Extracted Line Item", row.name, "item_code", existing, update_modified=False)
			row.item_code = existing
			matched.append(existing)
			continue
		group = group or _default_item_group()
		uom = uom or _default_uom()
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": _unique_code(value),
				"item_name": value[:140],
				"description": value[:1000],
				"item_group": group,
				"stock_uom": uom,
				"is_stock_item": 0,
				"is_sales_item": 1,
			}
		)
		item.insert()
		frappe.db.set_value("Extracted Line Item", row.name, "item_code", item.name, update_modified=False)
		row.item_code = item.name
		created.append(item.name)
		write_event(
			"master_created",
			intake=intake,
			stage="review",
			message=f"Item {item.name} created from the document",
		)
	return {"created": created, "matched": matched, "skipped": skipped}
