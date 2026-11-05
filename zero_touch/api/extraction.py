"""Extraction read/save APIs for the Review Center. Every method checks permission on the intake."""

import json
import re

import frappe
from frappe import _
from frappe.utils import now_datetime

from zero_touch.audit.log import write_event
from zero_touch.extraction.items import amount_from
from zero_touch.extraction.links import resolve_links
from zero_touch.extraction.specs import has_item_rows, load_mapping
from zero_touch.extraction.parse import normalize_text, parse_date, parse_money
from zero_touch.pipeline import states

EDITABLE_STATUSES = (states.STATUS_PENDING_REVIEW, states.STATUS_READY)

def _current_extraction_name(intake_doc) -> str | None:
	if intake_doc.current_extraction:
		return intake_doc.current_extraction
	return frappe.db.get_value("Document Extraction", {"intake": intake_doc.name}, "name", order_by="attempt_no desc")


def _require_editable(intake_doc) -> None:
	if intake_doc.status not in EDITABLE_STATUSES:
		frappe.throw(
			_("This document is {0} and can no longer be edited").format(_(intake_doc.status)),
			frappe.ValidationError,
		)


def _effective(row) -> str | None:
	if row.reviewed_value is not None:
		return row.reviewed_value or None
	return row.value or None


def _normalize_submitted(row, raw: str | None) -> str:
	value = (raw or "").strip()
	if not value:
		return ""
	if row.value_type == "money":
		normalized = parse_money(value)
		if normalized is None:
			frappe.throw(_("{0} must be an amount, for example 1150.00").format(row.label or row.field_key))
		return normalized
	if row.value_type == "date":
		iso, _ambiguous = parse_date(value)
		if iso is None:
			frappe.throw(_("{0} must be a date, for example 28/10/2026").format(row.label or row.field_key))
		return iso
	return value


UNRESOLVED_LINK = ("not_found", "ambiguous", "error")


def _missing(rows) -> list[str]:
	missing = []
	for row in rows:
		value = row["effective_value"] if isinstance(row, dict) else _effective(row)
		link_status = row["link_status"] if isinstance(row, dict) else row.link_status
		required = row["required"] if isinstance(row, dict) else row.required
		key = row["field_key"] if isinstance(row, dict) else row.field_key
		if required and (not value or (link_status in UNRESOLVED_LINK)):
			missing.append(key)
	return missing


@frappe.whitelist()
def get_extraction(intake: str) -> dict:
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("read")

	name = _current_extraction_name(intake_doc)
	if not name:
		return {"available": False, "message": _("No extraction has been made for this document yet.")}

	extraction = frappe.get_doc("Document Extraction", name)
	if any(
		row.link_doctype
		and (row.reviewed_value or row.value)
		and row.link_status not in ("matched", "created")
		for row in extraction.fields
	):
		# The record may have been created in ERPNext after the document was read, so try
		# matching again. No records are created here: this can be a read-only visit.
		resolve_links(name, allow_create=False)
		extraction = frappe.get_doc("Document Extraction", name)
	pages = frappe.get_all(
		"Document Page",
		filters={"extraction": name},
		fields=["page_no", "preview_file", "width", "height"],
		order_by="page_no asc",
	)
	mapping = load_mapping(intake_doc.document_profile, intake_doc.company)
	searched = {}
	if mapping:
		for row in mapping.rows:
			if row.target_table:
				continue
			labels = [label for label in (row.pdf_label_en, row.pdf_label_ar) if label]
			if labels:
				searched[row.target_field] = labels
	fields = [
		{
			"field_key": row.field_key,
			"label": row.label,
			"value": row.value,
			"reviewed_value": row.reviewed_value,
			"effective_value": _effective(row),
			"value_type": row.value_type,
			"state": row.state,
			"confidence": row.confidence,
			"page_no": row.page_no,
			"source_text": row.source_text,
			"required": bool(row.required),
			"link_doctype": row.link_doctype,
			"link_create": bool(row.link_create),
			"link_status": row.link_status,
			"link_name": row.link_name,
			"searched_labels": searched.get(row.field_key, []),
		}
		for row in extraction.fields
	]
	required_keys = [f["field_key"] for f in fields if f["required"]]
	lines = [
		{
			"row_name": row.name,
			"line_no": row.line_no,
			"item_code": row.item_code,
			"item_name": row.item_name,
			"qty": row.qty,
			"rate": row.rate,
			"amount": row.amount,
			"page_no": row.page_no,
			"state": row.state,
		}
		for row in sorted(extraction.lines, key=lambda r: r.line_no or 0)
	]
	automatic = []
	if mapping:
		try:
			# What ERPNext will actually put in the draft for the rows that are not read from
			# the document (Item Code, Item Group, Default Unit of Measure, ...).
			from zero_touch.creation.sales_invoice import build_payload

			payload = build_payload(intake_doc, extraction, mapping).payload
		except Exception:
			payload = {}
		for row in mapping.rows:
			if row.target_table or row.source != "ERPNext fills automatically" or not row.target_field:
				continue
			value = payload.get(row.target_field)
			automatic.append(
				{
					"field_key": row.target_field,
					"label": row.target_label or row.target_field,
					"value": "" if value in (None, "") else value,
					"required": bool(row.required),
				}
			)
	return {
		"available": True,
		"extraction": extraction.name,
		"mapping": mapping.name if mapping else None,
		"target_doctype": intake_doc.target_doctype,
		"has_lines": bool(lines) or has_item_rows(mapping),
		"lines": lines,
		"status": extraction.status,
		"language": extraction.language,
		"page_count": extraction.page_count,
		"checks_totals": extraction.checks_totals,
		"required_keys": required_keys,
		"missing_required": _missing(fields),
		"automatic_fields": automatic,
		"review_saved": bool(intake_doc.review_saved),
		"reviewed_by": intake_doc.reviewed_by,
		"reviewed_at": intake_doc.reviewed_at,
		"pages": [
			{"page_no": p.page_no, "width": p.width, "height": p.height, "has_preview": bool(p.preview_file)}
			for p in pages
		],
		"fields": fields,
		"can_save": intake_doc.status in EDITABLE_STATUSES
		and frappe.has_permission("Document Intake", "write", intake_doc),
	}


@frappe.whitelist()
def get_page_preview(intake: str, page_no: int):
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("read")

	name = _current_extraction_name(intake_doc)
	preview_url = frappe.db.get_value(
		"Document Page",
		{"intake": intake, "extraction": name, "page_no": int(page_no)},
		"preview_file",
	)
	if not preview_url:
		frappe.throw(_("No preview is available for this page"), frappe.DoesNotExistError)

	file_name = frappe.db.get_value(
		"File",
		{"file_url": preview_url, "attached_to_doctype": "Document Page"},
		"name",
	)
	frappe.local.response.filename = f"page-{int(page_no)}.png"
	frappe.local.response.filecontent = frappe.get_doc("File", file_name).get_content()
	frappe.local.response.type = "download"


def _normalize_line_value(field: str, raw) -> str:
	value = str(raw or "").strip()
	if not value:
		return ""
	if field == "qty":
		try:
			return f"{float(value.replace(',', '')):g}"
		except ValueError:
			frappe.throw(_("Quantity must be a number"))
	if field in ("rate", "amount"):
		normalized = parse_money(value)
		if normalized is None:
			frappe.throw(_("{0} must be an amount, for example 230.00").format(field.title()))
		return normalized
	return value


def _save_lines(extraction, submitted_lines) -> int:
	"""The submitted list is the full list of item rows. Rows missing from it are removed; rows without a name are added."""
	existing = {row.name: row for row in extraction.lines}
	submitted_names = set()
	changed = 0
	added = []
	for submitted in submitted_lines or []:
		values = {}
		for field in ("item_name", "qty", "rate", "amount"):
			if field in submitted:
				values[field] = _normalize_line_value(field, submitted.get(field))
		if not values.get("amount") and values.get("qty") and values.get("rate"):
			values["amount"] = amount_from(values["qty"], values["rate"]) or ""
		if "item_code" in submitted:
			code = (submitted.get("item_code") or "").strip() or None
			if code and not frappe.db.exists("Item", code):
				frappe.throw(_("Item {0} does not exist").format(code))
			values["item_code"] = code
		row_name = submitted.get("row_name")
		if row_name in existing:
			submitted_names.add(row_name)
			row = existing[row_name]
			updates = {k: v for k, v in values.items() if v != (getattr(row, k) or None)}
			if updates:
				frappe.db.set_value("Extracted Line Item", row.name, updates, update_modified=False)
				changed += len(updates)
				write_event(
					"correction",
					intake=extraction.intake,
					stage="review",
					message=f"line {row.line_no}: " + ", ".join(f"{k}={v or '-'}" for k, v in updates.items()),
				)
		elif any(values.values()):
			added.append(values)

	removed = [row for name, row in existing.items() if name not in submitted_names]
	if not added and not removed:
		return changed

	fresh = frappe.get_doc("Document Extraction", extraction.name)
	for row in list(fresh.lines):
		if row.name not in submitted_names and row.name in existing:
			fresh.remove(row)
			changed += 1
			write_event("correction", intake=extraction.intake, stage="review", message=f"item row {row.line_no} removed")
	for values in added:
		fresh.append("lines", {**values, "state": "entered"})
		changed += 1
		write_event(
			"correction",
			intake=extraction.intake,
			stage="review",
			message="item row added: " + ", ".join(f"{k}={v or '-'}" for k, v in values.items()),
		)
	for number, row in enumerate(fresh.lines, start=1):
		row.line_no = number
	fresh.save(ignore_permissions=True)
	return changed


@frappe.whitelist(methods=["POST"])
def save_review(intake: str, values: str | dict, lines: str | list | None = None):
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("write")
	_require_editable(intake_doc)

	name = _current_extraction_name(intake_doc)
	if not name:
		frappe.throw(_("There is nothing to review for this document"))

	submitted = json.loads(values) if isinstance(values, str) else (values or {})
	extraction = frappe.get_doc("Document Extraction", name)

	changes = []
	for row in extraction.fields:
		if row.field_key not in submitted:
			continue
		if row.link_doctype and not str(submitted.get(row.field_key) or "").strip():
			# The page shows an empty picker when the value read from the document has no
			# matching ERPNext record yet. Saving other edits must not erase that value.
			continue
		new_value = _normalize_submitted(row, submitted.get(row.field_key))
		old_value = _effective(row)
		if (new_value or None) == old_value:
			continue
		frappe.db.set_value("Extracted Field", row.name, "reviewed_value", new_value, update_modified=False)
		row.reviewed_value = new_value
		changes.append((row.field_key, old_value, new_value))

	if "posting_date" in submitted and not any(row.field_key == "posting_date" for row in extraction.fields):
		entered = (submitted.get("posting_date") or "").strip()
		iso = parse_date(entered)[0] if entered else None
		if entered and not iso:
			frappe.throw(_("Posting Date must be a date, for example 28/10/2026"))
		fresh = frappe.get_doc("Document Extraction", name)
		fresh.append(
			"fields",
			{
				"field_key": "posting_date",
				"label": "Posting Date",
				"value_type": "date",
				"reviewed_value": iso or "",
				"state": "extracted" if iso else "missing",
				"required": 0,
			},
		)
		fresh.save(ignore_permissions=True)
		extraction = frappe.get_doc("Document Extraction", name)
		changes.append(("posting_date", None, iso))

	for field_key, old_value, new_value in changes:
		write_event(
			"correction",
			intake=intake,
			stage="review",
			message=f"{field_key}: {old_value or '-'} -> {new_value or '-'}",
		)

	frappe.db.set_value(
		"Document Intake",
		intake,
		{"review_saved": 1, "reviewed_by": frappe.session.user, "reviewed_at": now_datetime()},
		update_modified=False,
	)
	submitted_lines = json.loads(lines) if isinstance(lines, str) else (lines or [])
	line_changes = _save_lines(extraction, submitted_lines)
	links = resolve_links(name) if any(row.link_doctype for row in extraction.fields) else []
	extraction = frappe.get_doc("Document Extraction", name)
	missing = _missing(extraction.fields)
	status = frappe.db.get_value("Document Intake", intake, "status")
	ready = not missing and not any(link["status"] in UNRESOLVED_LINK for link in links)
	target = "Ready to Create" if ready else "Pending Review"
	if status in ("Pending Review", "Ready to Create") and status != target:
		from zero_touch.pipeline import machine

		machine.transition(
			intake,
			target,
			reason="Review saved and complete" if ready else "Review saved. Required values are still missing",
			expected_from=status,
			actor=frappe.session.user,
		)
	return {
		"saved": True,
		"changes": len(changes) + line_changes,
		"links": links,
		"missing_required": missing,
		"status": target if status in ("Pending Review", "Ready to Create") else status,
	}


@frappe.whitelist(methods=["POST"])
def set_link(intake: str, field_key: str, record: str):
	"""Links an extracted customer or supplier value to an existing ERPNext record chosen on the page."""
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("write")
	_require_editable(intake_doc)
	name = _current_extraction_name(intake_doc)
	row = frappe.db.get_value(
		"Extracted Field",
		{"parent": name, "field_key": field_key},
		["name", "link_doctype"],
		as_dict=True,
	)
	if not row or not row.link_doctype:
		frappe.throw(_("{0} is not a linked field").format(field_key))
	if not frappe.has_permission(row.link_doctype, "read", record):
		frappe.throw(_("You cannot use that {0}").format(row.link_doctype), frappe.PermissionError)
	frappe.db.set_value(
		"Extracted Field",
		row.name,
		{"link_status": "matched", "link_name": record, "reviewed_value": record},
		update_modified=False,
	)
	write_event("correction", intake=intake, stage="review", message=f"{field_key} linked to {record}")
	return {"linked": record}


CANDIDATE_RE = re.compile(r"^\s*([^:|]{2,40}?)\s*[:：]\s*(.{1,160}?)\s*$")


@frappe.whitelist()
def get_candidates(intake: str) -> list[dict]:
	"""Label and value pairs found on the pages (for example 'Date: 28-Jan-2026'), for the user to assign."""
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("read")
	name = _current_extraction_name(intake_doc)
	if not name:
		return []
	pages = frappe.get_all(
		"Document Page",
		filters={"extraction": name},
		fields=["page_no", "text_layer"],
		order_by="page_no asc",
	)
	found, seen = [], set()
	for page in pages:
		for raw in normalize_text(page.text_layer).splitlines():
			match = CANDIDATE_RE.match(raw)
			if not match:
				continue
			label, value = match.group(1).strip(), match.group(2).strip()
			if not re.search(r"[^\W\d_]", label) or not value:
				continue
			key = (label.casefold(), value)
			if key in seen:
				continue
			seen.add(key)
			found.append({"label": label, "value": value, "page_no": page.page_no})
	return found[:200]


@frappe.whitelist(methods=["POST"])
def use_candidate(intake: str, field_key: str, value: str, label: str | None = None):
	"""Puts a value found on the document into a field. Creates the field on the review if it is not there yet."""
	intake_doc = frappe.get_doc("Document Intake", intake)
	intake_doc.check_permission("write")
	name = _current_extraction_name(intake_doc)
	if not name:
		frappe.throw(_("There is nothing to review for this document"))
	value = (value or "").strip()
	if not value:
		frappe.throw(_("The value is empty"))
	extraction = frappe.get_doc("Document Extraction", name)
	existing = next((row for row in extraction.fields if row.field_key == field_key), None)
	if existing is None:
		extraction.append(
			"fields",
			{
				"field_key": field_key,
				"label": (label or field_key).strip()[:140],
				"value_type": "text",
				"reviewed_value": value,
				"state": "extracted",
				"required": 0,
			},
		)
		extraction.save(ignore_permissions=True)
	else:
		frappe.db.set_value("Extracted Field", existing.name, "reviewed_value", value, update_modified=False)
	write_event("correction", intake=intake, stage="review", message=f"{field_key} set to {value}")
	return {"field_key": field_key, "value": value}
