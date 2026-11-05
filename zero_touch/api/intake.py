"""Whitelisted methods for Document Intake. Every method checks permissions on the target record."""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit

from zero_touch.audit.log import write_event
from zero_touch.intake.service import create_intake_from_upload
from zero_touch.pipeline import machine, states
from zero_touch.pipeline.jobs import queue_intake

MB = 1024 * 1024


@frappe.whitelist(methods=["POST"])
@rate_limit(limit=60, seconds=60 * 60)
def upload_document(company: str, document_profile: str):
	upload = frappe.request.files.get("file") if frappe.request else None
	if not upload:
		frappe.throw(_("No file was uploaded"))

	settings = frappe.get_single("Zero Touch Settings")
	limit = int(settings.max_file_size_mb or 20) * MB
	content = upload.stream.read(limit + 1)
	return create_intake_from_upload(company, document_profile, upload.filename or "", content)


@frappe.whitelist()
def download_original(intake: str):
	doc = frappe.get_doc("Document Intake", intake)
	try:
		doc.check_permission("read")
	except frappe.PermissionError:
		write_event("access_denied", intake=intake, message=f"download refused for {frappe.session.user}")
		frappe.db.commit()
		raise

	file_name = frappe.db.get_value(
		"File",
		{"file_url": doc.original_file, "attached_to_doctype": "Document Intake", "attached_to_name": doc.name},
		"name",
	)
	if not file_name:
		frappe.throw(_("The original file is not available"))

	write_event("original_downloaded", intake=intake, message=doc.original_filename)
	frappe.db.commit()
	frappe.local.response.filename = doc.original_filename
	frappe.local.response.filecontent = frappe.get_doc("File", file_name).get_content()
	frappe.local.response.type = "download"


@frappe.whitelist(methods=["POST"])
def cancel_intake(intake: str, reason: str | None = None):
	doc = frappe.get_doc("Document Intake", intake)
	doc.check_permission("write")
	if not reason:
		frappe.throw(_("A reason is required to cancel a document"))
	machine.transition(intake, states.STATUS_CANCELLED, reason=f"Cancelled: {reason}", actor=frappe.session.user)
	return {"name": intake, "status": states.STATUS_CANCELLED}


@frappe.whitelist(methods=["POST"])
def retry_intake(intake: str):
	doc = frappe.get_doc("Document Intake", intake)
	doc.check_permission("write")
	if doc.status != states.STATUS_FAILED:
		frappe.throw(_("Only failed documents can be retried"))
	queue_intake(intake, reason="Manual retry", extra={"next_retry_at": None}, actor=frappe.session.user)
	return {"name": intake, "status": states.STATUS_QUEUED}


@frappe.whitelist(methods=["POST"])
def reprocess_intake(intake: str):
	doc = frappe.get_doc("Document Intake", intake)
	doc.check_permission("write")
	if doc.status not in (states.STATUS_PENDING_REVIEW, states.STATUS_READY):
		frappe.throw(_("Only documents in Pending Review or Ready to Create can be processed again"))
	if doc.status == states.STATUS_READY:
		# The mapping may have gained a field after the review was saved. Move back to review
		# first; Pending Review is the state allowed to queue a new extraction.
		machine.transition(
			intake,
			states.STATUS_PENDING_REVIEW,
			reason="The document is read again after a mapping change",
			actor=frappe.session.user,
		)
		frappe.db.commit()
	queue_intake(intake, reason="Processing started again by a reviewer", actor=frappe.session.user)
	return {"name": intake, "status": states.STATUS_QUEUED}
