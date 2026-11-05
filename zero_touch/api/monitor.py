"""Read APIs for the Processing Monitor and Review Center. Permission-aware: lists use frappe.get_list."""

import frappe
from frappe import _

from zero_touch.pipeline import states

LIST_FIELDS = [
	"name",
	"company",
	"document_profile",
	"status",
	"stage",
	"status_reason",
	"original_filename",
	"submitted_by",
	"attempt_count",
	"retry_count",
	"next_retry_at",
	"modified",
]
MAX_PAGE = 200


@frappe.whitelist()
def get_status_counts(company: str | None = None) -> dict:
	filters = {"company": company} if company else {}
	rows = frappe.get_list(
		"Document Intake",
		filters=filters,
		fields=["status", "count(name) as count"],
		group_by="status",
	)
	counts = {status: 0 for status in states.STATUSES}
	for row in rows:
		counts[row.status] = row.count
	return {"counts": counts, "total": sum(counts.values())}


@frappe.whitelist()
def get_intakes(status: str | None = None, company: str | None = None, start: int = 0, page_length: int = 50):
	filters = {}
	if status:
		filters["status"] = status
	if company:
		filters["company"] = company
	page_length = min(int(page_length or 50), MAX_PAGE)
	rows = frappe.get_list(
		"Document Intake",
		filters=filters,
		fields=LIST_FIELDS,
		order_by="modified desc",
		start=int(start or 0),
		page_length=page_length,
	)
	return rows


@frappe.whitelist()
def get_intake_detail(intake: str) -> dict:
	doc = frappe.get_doc("Document Intake", intake)
	doc.check_permission("read")

	duplicate_of = None
	if doc.duplicate_of and frappe.has_permission("Document Intake", "read", doc.duplicate_of):
		duplicate_of = doc.duplicate_of

	can_write = doc.has_permission("write")
	logs = frappe.get_list(
		"Document Processing Log",
		filters={"intake": intake},
		fields=["event_type", "from_status", "to_status", "stage", "actor", "message", "creation"],
		order_by="creation asc",
		page_length=500,
	)

	created = frappe.db.get_value(
		"Document Transaction Link",
		{"intake": intake},
		["target_doctype", "target_name"],
		as_dict=True,
	)

	mapping_label = frappe.db.get_value("Document Field Mapping", doc.document_profile, "label")
	return {
		"created": {"doctype": created.target_doctype, "name": created.target_name} if created else None,
		"name": doc.name,
		"company": doc.company,
		"document_profile": doc.document_profile,
		"document_type": mapping_label or doc.document_profile,
		"target_doctype": doc.target_doctype,
		"status": doc.status,
		"stage": doc.stage,
		"status_reason": doc.status_reason,
		"original_filename": doc.original_filename,
		"file_size": doc.file_size,
		"mime_type": doc.mime_type,
		"file_sha256": doc.file_sha256,
		"channel": doc.channel,
		"submitted_by": doc.submitted_by,
		"creation": doc.creation,
		"attempt_count": doc.attempt_count,
		"retry_count": doc.retry_count,
		"next_retry_at": doc.next_retry_at,
		"duplicate_of": duplicate_of,
		"has_original": bool(doc.original_file),
		"can_retry": can_write and doc.status == states.STATUS_FAILED,
		"can_cancel": can_write
		and doc.status in (states.STATUS_QUEUED, states.STATUS_PENDING_REVIEW, states.STATUS_FAILED),
		"logs": logs,
		"extraction_available": False,
		"extraction_message": _("Field extraction is not part of this release. Fields appear here once extraction is enabled."),
	}
