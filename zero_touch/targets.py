"""Which DocTypes a Document Field Mapping may target.

The list is no longer hard-coded: any normal DocType can be chosen on a mapping, which then
decides which fields are read. Only tables,
single documents, virtual doctypes and ERPNext's own setup doctypes are refused.
"""

import frappe
from frappe import _

SYSTEM_DOCTYPES = frozenset(
	{
		"DocType",
		"DocField",
		"DocPerm",
		"Role",
		"User",
		"File",
		"Report",
		"Print Format",
		"Custom Field",
		"Property Setter",
		"Module Def",
		"Client Script",
		"Server Script",
		"Workspace",
		"Document Field Mapping",
		"Document Intake",
	}
)


def target_problem(doctype: str | None) -> str | None:
	"""Returns why the doctype cannot be a profile target, or None when it can."""
	if not doctype:
		return _("Choose a target DocType")
	if doctype in SYSTEM_DOCTYPES:
		return _("{0} is an ERPNext setup doctype and cannot be a target").format(doctype)
	if not frappe.db.exists("DocType", doctype):
		return _("{0} does not exist").format(doctype)
	meta = frappe.get_meta(doctype)
	if meta.istable:
		return _("{0} is a child table, not a document").format(doctype)
	if meta.issingle:
		return _("{0} is a single document and cannot be created per upload").format(doctype)
	if getattr(meta, "is_virtual", False):
		return _("{0} is a virtual doctype and cannot be created here").format(doctype)
	return None


def validate_target_doctype(doctype: str | None) -> None:
	problem = target_problem(doctype)
	if problem:
		frappe.throw(problem)
