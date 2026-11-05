"""Creates the draft Sales Invoice for an intake that is Ready to Create. Runs as the user who clicked."""

import hashlib
from decimal import Decimal

import frappe
from frappe import _
from frappe.utils import now_datetime

from zero_touch.audit.log import write_event
from zero_touch.creation.sales_invoice import build_payload, extracted_grand_total
from zero_touch.extraction.links import resolve_links
from zero_touch.extraction.specs import load_mapping
from zero_touch.pipeline import machine, states

TOTAL_TOLERANCE = Decimal("0.01")


def _relink(extraction, *, allow_create: bool):
	"""Matches extracted customer/supplier values against ERPNext again, in case the record
	was created after the document was read."""
	if not any(
		row.link_doctype
		and (row.reviewed_value or row.value)
		and row.link_status not in ("matched", "created")
		for row in extraction.fields
	):
		return extraction
	resolve_links(extraction.name, allow_create=allow_create)
	return frappe.get_doc("Document Extraction", extraction.name)


def creation_key(intake: str, extraction: str, doctype: str, mapping_version: str) -> str:
	return hashlib.sha256(f"{intake}|{extraction}|{doctype}|{mapping_version}".encode()).hexdigest()


def preview_draft(intake_name: str) -> dict:
	intake = frappe.get_doc("Document Intake", intake_name)
	intake.check_permission("read")
	if not intake.current_extraction:
		return {"ready": False, "blockers": [_("Document has not been read yet")], "created": None}
	created = frappe.db.get_value("Document Transaction Link", {"intake": intake_name}, ["target_doctype", "target_name"], as_dict=True)
	if created:
		return {"ready": False, "blockers": [], "created": {"doctype": created.target_doctype, "name": created.target_name}}
	extraction = frappe.get_doc("Document Extraction", intake.current_extraction)
	extraction = _relink(extraction, allow_create=False)
	mapping = load_mapping(intake.document_profile, intake.company)
	built = build_payload(intake, extraction, mapping)
	return {"ready": not built.blockers, "blockers": built.blockers, "created": None}


def create_draft(intake_name: str) -> dict:
	intake = frappe.get_doc("Document Intake", intake_name)
	intake.check_permission("write")
	if intake.status not in (states.STATUS_READY, states.STATUS_PENDING_REVIEW):
		frappe.throw(_("This document cannot be turned into a record in its current state"))
	mapping = load_mapping(intake.document_profile, intake.company)
	target_doctype = mapping.target_doctype if mapping else intake.target_doctype
	if not frappe.has_permission(target_doctype, "create"):
		frappe.throw(_("You do not have permission to create a {0}").format(target_doctype), frappe.PermissionError)

	extraction_name = intake.current_extraction
	extraction = frappe.get_doc("Document Extraction", extraction_name)
	extraction = _relink(extraction, allow_create=True)

	built = build_payload(intake, extraction, mapping)
	if built.blockers:
		if intake.status == states.STATUS_READY:
			machine.transition(
				intake_name,
				states.STATUS_PENDING_REVIEW,
				reason="; ".join(built.blockers),
				expected_from=states.STATUS_READY,
				actor=frappe.session.user,
			)
			frappe.db.commit()
		return {"status": states.STATUS_PENDING_REVIEW, "blockers": built.blockers}

	if intake.status == states.STATUS_PENDING_REVIEW:
		machine.transition(
			intake_name,
			states.STATUS_READY,
			reason="Review complete. Creating the draft invoice",
			expected_from=states.STATUS_PENDING_REVIEW,
			actor=frappe.session.user,
		)

	mapping_version = str(mapping.modified) if mapping else "default"
	key = creation_key(intake_name, extraction_name, target_doctype, mapping_version)
	existing = frappe.db.get_value("Document Transaction Link", {"creation_key": key}, "target_name")
	if existing:
		return {"status": states.STATUS_CREATED, "name": existing, "doctype": target_doctype}

	machine.transition(
		intake_name,
		states.STATUS_CREATING,
		reason="Creating the draft invoice",
		expected_from=states.STATUS_READY,
		actor=frappe.session.user,
	)
	frappe.db.commit()

	try:
		doc = frappe.get_doc(built.payload)
		doc.zero_touch_intake = intake_name
		doc.insert()

		expected = extracted_grand_total(extraction)
		if expected and frappe.get_meta(target_doctype).has_field("grand_total"):
			difference = abs(Decimal(str(doc.grand_total)) - Decimal(expected))
			if difference > TOTAL_TOLERANCE:
				frappe.throw(
					_("The total in ERPNext is {0}, but the document total is {1}. Check the tax and item amounts").format(
						doc.grand_total, expected
					)
				)

		frappe.get_doc(
			{
				"doctype": "Document Transaction Link",
				"intake": intake_name,
				"extraction": extraction_name,
				"target_doctype": doc.doctype,
				"target_name": doc.name,
				"creation_key": key,
				"created_by": frappe.session.user,
				"created_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
		machine.transition(
			intake_name,
			states.STATUS_CREATED,
			reason=f"{doc.doctype} {doc.name} created"
			if doc.doctype not in ("Sales Invoice", "Purchase Invoice")
			else f"Draft {doc.doctype} {doc.name} created",
			expected_from=states.STATUS_CREATING,
			actor=frappe.session.user,
		)
		write_event("transition", intake=intake_name, message=f"created {doc.doctype} {doc.name}")
		frappe.db.commit()
		return {"status": states.STATUS_CREATED, "name": doc.name, "doctype": doc.doctype}
	except (frappe.ValidationError, frappe.PermissionError) as exc:
		frappe.db.rollback()
		reason = frappe.utils.strip_html(str(exc))[:400] or _("ERPNext did not accept the invoice")
		machine.transition(
			intake_name,
			states.STATUS_PENDING_REVIEW,
			reason=reason,
			expected_from=states.STATUS_CREATING,
			actor=frappe.session.user,
		)
		write_event("stage_fail", intake=intake_name, message=reason)
		frappe.db.commit()
		return {"status": states.STATUS_PENDING_REVIEW, "blockers": [reason]}
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Zero Touch: draft creation failed")
		machine.transition(
			intake_name,
			states.STATUS_FAILED,
			reason="Creation failed unexpectedly. See the error log.",
			expected_from=states.STATUS_CREATING,
			extra={"next_retry_at": None},
			actor=frappe.session.user,
		)
		frappe.db.commit()
		return {"status": states.STATUS_FAILED, "blockers": []}
