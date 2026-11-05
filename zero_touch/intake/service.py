import frappe
from frappe import _

from zero_touch.audit.log import write_event
from zero_touch.intake.file_checks import MIME_BY_KIND, check_upload, sanitize_filename
from zero_touch.pipeline import machine, states
from zero_touch.pipeline.jobs import queue_intake

MB = 1024 * 1024
DEFAULT_EXTENSIONS = "pdf,jpg,jpeg,png,tif,tiff,csv,xlsx,docx"
DEFAULT_MAX_FILE_SIZE_MB = 20

REJECTION_MESSAGES = {
	"EMPTY_FILE": "The file is empty.",
	"EXTENSION_NOT_ALLOWED": "This file type is not allowed.",
	"FILE_TOO_LARGE": "The file is larger than the allowed size.",
	"SIGNATURE_MISMATCH": "The file content does not match its file type.",
	"ARCHIVE_INVALID": "The Office document is damaged or not a valid archive.",
	"ARCHIVE_TOO_LARGE": "The Office document expands beyond the allowed size.",
	"ARCHIVE_TOO_MANY_MEMBERS": "The Office document contains too many parts.",
	"ARCHIVE_NESTED": "Archives inside documents are not allowed.",
	"ARCHIVE_MACRO": "Documents with macros are not allowed.",
}


def _allowed_extensions(settings) -> list[str]:
	raw = settings.allowed_extensions or DEFAULT_EXTENSIONS
	return [e.strip() for e in raw.split(",") if e.strip()]


def create_intake_from_upload(
	company: str,
	document_profile: str,
	filename: str,
	content: bytes,
	channel: str = "upload",
) -> dict:
	settings = frappe.get_single("Zero Touch Settings")
	if not settings.enabled:
		frappe.throw(_("Zero Touch processing is not enabled"))

	mapping = frappe.get_doc("Document Field Mapping", document_profile)
	if not mapping.enabled:
		frappe.throw(_("This document type is disabled"))
	if mapping.company and mapping.company != company:
		frappe.throw(_("This document type is not available for the selected company"))

	safe_name = sanitize_filename(filename)
	check = check_upload(safe_name, content, _allowed_extensions(settings), int(settings.max_file_size_mb or DEFAULT_MAX_FILE_SIZE_MB) * MB)
	if not check.ok:
		write_event(
			"upload_rejected",
			message=f"{check.reason} sha256={check.sha256} file={safe_name} company={company}",
		)
		frappe.db.commit()
		frappe.throw(_(REJECTION_MESSAGES.get(check.reason, "The file could not be accepted.")))

	duplicate = frappe.db.get_value(
		"Document Intake",
		{
			"company": company,
			"file_sha256": check.sha256,
			"status": ["not in", [states.STATUS_CANCELLED, states.STATUS_REJECTED]],
		},
		"name",
	)

	intake = frappe.get_doc(
		{
			"doctype": "Document Intake",
			"company": company,
			"document_profile": mapping.name,
			"target_doctype": mapping.target_doctype,
			"original_filename": safe_name,
			"file_sha256": check.sha256,
			"file_size": check.size,
			"mime_type": MIME_BY_KIND.get(check.kind, "application/octet-stream"),
			"channel": channel,
			"submitted_by": frappe.session.user,
			"status": states.STATUS_RECEIVED,
		}
	)
	frappe.flags.zt_upload_in_progress = True
	try:
		intake.insert()
	finally:
		frappe.flags.zt_upload_in_progress = False

	if not duplicate:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": safe_name,
				"content": content,
				"is_private": 1,
				"attached_to_doctype": "Document Intake",
				"attached_to_name": intake.name,
				"attached_to_field": "original_file",
			}
		)
		file_doc.insert(ignore_permissions=True)
		frappe.db.set_value(
			"Document Intake", intake.name, "original_file", file_doc.file_url, update_modified=False
		)

	write_event("upload_accepted", intake=intake.name, to_status=states.STATUS_RECEIVED, message=safe_name)

	if duplicate:
		machine.transition(
			intake.name,
			states.STATUS_DUPLICATE,
			reason="Exact duplicate of an existing document in this company",
			expected_from=states.STATUS_RECEIVED,
			extra={"duplicate_of": duplicate},
		)
		write_event("duplicate_detected", intake=intake.name, message=f"duplicate of {duplicate}")
		visible = frappe.has_permission("Document Intake", "read", duplicate)
		return {
			"name": intake.name,
			"status": states.STATUS_DUPLICATE,
			"duplicate_of": duplicate if visible else None,
		}

	queue_intake(intake.name, reason="Accepted for processing", actor=frappe.session.user)
	return {"name": intake.name, "status": states.STATUS_QUEUED, "duplicate_of": None}
