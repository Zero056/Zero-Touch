"""Background stage jobs, retries, and recovery. Each job is idempotent for its checkpoint."""

import time
import traceback
import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

from zero_touch.audit.log import write_event
from zero_touch.audit.redaction import redact
from zero_touch.extraction.service import IMAGE_EXTENSIONS, image_to_pdf, run_pdf_extraction
from zero_touch.intake.file_checks import extension_of
from zero_touch.pipeline import machine, states
from zero_touch.pipeline.backoff import backoff_seconds
from zero_touch.providers.base import DocumentInput
from zero_touch.providers.registry import get_engine

QUEUE = "default"
JOB_TIMEOUT_SECONDS = 300
STAGE_LOCK_MINUTES = {"extract": 15}
MAINTENANCE_BATCH = 200


class TransientStageError(Exception):
	pass


def job_id_for(intake: str, stage: str, attempt: int) -> str:
	return f"zt:{intake}:{stage}:{attempt}"


def _settings():
	return frappe.get_single("Zero Touch Settings")


def queue_intake(intake: str, *, reason: str, extra: dict | None = None, actor: str | None = None) -> None:
	machine.transition(
		intake,
		states.STATUS_QUEUED,
		reason=reason,
		extra=extra,
		actor=actor,
	)
	attempts = (frappe.db.get_value("Document Intake", intake, "attempt_count") or 0) + 1
	frappe.db.set_value("Document Intake", intake, "attempt_count", attempts, update_modified=False)
	frappe.enqueue(
		"zero_touch.pipeline.jobs.run_stage",
		queue=QUEUE,
		timeout=JOB_TIMEOUT_SECONDS,
		job_id=job_id_for(intake, "extract", attempts),
		deduplicate=True,
		enqueue_after_commit=True,
		intake=intake,
		stage="extract",
		job_token=uuid.uuid4().hex,
	)


def run_stage(intake: str, stage: str, job_token: str) -> None:
	attempt = frappe.db.get_value("Document Intake", intake, "attempt_count") or 0
	job_id = job_id_for(intake, stage, attempt)
	started = time.monotonic()

	if not machine.acquire_lock(intake, job_token, STAGE_LOCK_MINUTES[stage], job_id=job_id):
		frappe.db.commit()
		return
	frappe.db.commit()

	write_event("stage_start", intake=intake, stage=stage, job_id=job_id)
	frappe.db.commit()
	try:
		_extract(intake, job_token, job_id)
		write_event(
			"stage_end",
			intake=intake,
			stage=stage,
			job_id=job_id,
			duration_ms=int((time.monotonic() - started) * 1000),
		)
		frappe.db.commit()
	except TransientStageError as exc:
		frappe.db.rollback()
		_fail_safely(intake, str(exc), job_token, job_id)
	except Exception:
		frappe.db.rollback()
		frappe.log_error(
			title="Zero Touch: stage failed",
			message=redact(traceback.format_exc(), max_length=4000),
		)
		_fail_safely(intake, "Unexpected processing error. See the error log.", job_token, job_id)


def _fail_safely(intake: str, reason: str, token: str, job_id: str) -> None:
	try:
		_mark_failed(intake, reason, token, job_id)
		frappe.db.commit()
	except machine.StaleTransition:
		frappe.db.rollback()


def _extract(intake: str, token: str, job_id: str) -> None:
	row = frappe.db.get_value(
		"Document Intake",
		intake,
		["original_file", "original_filename", "document_profile"],
		as_dict=True,
	)
	content = _read_original(intake, row.original_file)
	extension = extension_of(row.original_filename or "")
	if extension in IMAGE_EXTENSIONS:
		# A photo or a scanned image is wrapped in a one-page PDF so the OCR, table and
		# preview steps that already work for scanned PDFs apply to it unchanged.
		content = image_to_pdf(content)
		extension = "pdf"

	if extension == "pdf":
		outcome = run_pdf_extraction(intake, content, row.document_profile)
		if outcome.ok:
			return _hand_to_review(
				intake,
				token,
				job_id,
				f"Extracted {outcome.field_count} fields. Review and save.",
				extra={"stage": "extracted", "current_extraction": outcome.extraction},
			)
		if outcome.transient:
			raise TransientStageError(outcome.reason)
		if outcome.permanent:
			return _fail_permanent(intake, token, job_id, outcome.reason)
		return _hand_to_review(intake, token, job_id, outcome.reason)

	providers = frappe.get_all(
		"Extraction Provider",
		filters={"enabled": 1},
		fields=["provider_code", "engine"],
		order_by="priority asc, name asc",
	)
	if not providers:
		return _hand_to_review(
			intake, token, job_id, "No extraction provider is enabled for this file type. Manual entry is required."
		)

	document = DocumentInput(content=content, extension=extension)
	for provider in providers:
		result = get_engine(provider.engine, provider.provider_code).extract(document)
		if result.ok:
			return _hand_to_review(intake, token, job_id, "Extraction completed. Review is required.")

		error = result.errors[0] if result.errors else None
		write_event(
			"provider_skipped",
			intake=intake,
			stage="extract",
			provider_code=provider.provider_code,
			job_id=job_id,
			message=error.message if error else "no result",
		)
		if error and error.transient:
			raise TransientStageError(f"{provider.provider_code} unavailable: {error.code.value}")

	return _hand_to_review(
		intake, token, job_id, "No configured provider could extract this document. Manual entry is required."
	)


def _read_original(intake: str, file_url: str) -> bytes:
	file_name = frappe.db.get_value(
		"File",
		{"file_url": file_url, "attached_to_doctype": "Document Intake", "attached_to_name": intake},
		"name",
	)
	if not file_name:
		raise frappe.DoesNotExistError("Original file is missing")
	return frappe.get_doc("File", file_name).get_content()


def _hand_to_review(intake: str, token: str, job_id: str, reason: str, extra: dict | None = None) -> None:
	machine.transition(
		intake,
		states.STATUS_PENDING_REVIEW,
		reason=reason,
		expected_from=states.STATUS_PROCESSING,
		lock_token=token,
		extra=extra,
		actor="System",
		job_id=job_id,
	)
	if not extra:
		write_event("manual_review_required", intake=intake, stage="extract", job_id=job_id, message=reason)


def _retry_fields(intake: str) -> dict:
	settings = _settings()
	row = frappe.db.get_value("Document Intake", intake, ["attempt_count", "retry_count"], as_dict=True)
	attempts = row.attempt_count or 0
	if attempts >= (settings.max_attempts or 1):
		return {"retry_count": row.retry_count or 0, "next_retry_at": None}
	delay = backoff_seconds(
		max(attempts, 1),
		base=settings.retry_base_seconds or 60,
		cap=settings.retry_max_seconds or 3600,
	)
	return {
		"retry_count": (row.retry_count or 0) + 1,
		"next_retry_at": add_to_date(now_datetime(), seconds=delay),
	}


def _fail_permanent(intake: str, token: str, job_id: str, reason: str) -> None:
	machine.transition(
		intake,
		states.STATUS_FAILED,
		reason=redact(reason) + ". Automatic retries do not apply",
		expected_from=states.STATUS_PROCESSING,
		lock_token=token,
		extra={"next_retry_at": None},
		actor="System",
		job_id=job_id,
	)


def _mark_failed(intake: str, reason: str, token: str | None, job_id: str | None) -> None:
	extra = _retry_fields(intake)
	scheduled = extra["next_retry_at"] is not None
	machine.transition(
		intake,
		states.STATUS_FAILED,
		reason=redact(reason) + (". Retry scheduled" if scheduled else ". Automatic retries exhausted"),
		expected_from=states.STATUS_PROCESSING,
		lock_token=token,
		extra=extra,
		actor="System",
		job_id=job_id,
	)
	if scheduled:
		write_event(
			"retry_scheduled",
			intake=intake,
			job_id=job_id,
			message=f"Next attempt at {extra['next_retry_at']}",
		)


def recover_stale_locks(limit: int = MAINTENANCE_BATCH) -> int:
	recovered = 0
	stale = frappe.get_all(
		"Document Intake",
		filters={"status": states.STATUS_PROCESSING, "lock_expires_at": ["<", now_datetime()]},
		pluck="name",
		limit=limit,
	)
	for intake in stale:
		try:
			_mark_failed(intake, "Worker interrupted before completion", None, None)
			write_event(
				"lock_recovered",
				intake=intake,
				from_status=states.STATUS_PROCESSING,
				to_status=states.STATUS_FAILED,
				actor="System",
			)
			frappe.db.commit()
			recovered += 1
		except (machine.StaleTransition, states.InvalidTransition):
			frappe.db.rollback()
	return recovered


def enqueue_due_retries(limit: int = MAINTENANCE_BATCH) -> int:
	queued = 0
	due = frappe.get_all(
		"Document Intake",
		filters={"status": states.STATUS_FAILED, "next_retry_at": ["<=", now_datetime()]},
		pluck="name",
		limit=limit,
	)
	for intake in due:
		try:
			queue_intake(intake, reason="Scheduled retry", extra={"next_retry_at": None}, actor="System")
			frappe.db.commit()
			queued += 1
		except (machine.StaleTransition, states.InvalidTransition):
			frappe.db.rollback()
	return queued


def scheduled_maintenance() -> None:
	recover_stale_locks()
	enqueue_due_retries()
