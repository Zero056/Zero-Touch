"""Single writer for Document Intake status and processing locks.

Every change runs in the caller's transaction: a row lock (SELECT ... FOR UPDATE) guards the
status, the change is checked against the state table, and the log entry is written with it.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from zero_touch.audit.log import write_event
from zero_touch.pipeline import states


class StaleTransition(Exception):
	pass


def _current(intake: str):
	row = frappe.db.get_value(
		"Document Intake",
		intake,
		["status", "lock_token"],
		as_dict=True,
		for_update=True,
	)
	if not row:
		raise frappe.DoesNotExistError(f"Document Intake {intake} does not exist")
	return row


def transition(
	intake: str,
	to_status: str,
	*,
	reason: str | None = None,
	expected_from: str | None = None,
	lock_token: str | None = None,
	extra: dict | None = None,
	actor: str | None = None,
	job_id: str | None = None,
) -> str:
	row = _current(intake)
	current = row.status

	if expected_from is not None and current != expected_from:
		write_event(
			"transition_refused",
			intake=intake,
			from_status=current,
			to_status=to_status,
			actor=actor,
			job_id=job_id,
			message=f"expected {expected_from}",
		)
		raise StaleTransition(f"{intake} is {current}, expected {expected_from}")

	if lock_token is not None and row.lock_token != lock_token:
		raise StaleTransition(f"{intake} lock is held by another job")

	try:
		states.assert_allowed(current, to_status)
	except states.InvalidTransition:
		write_event(
			"transition_refused",
			intake=intake,
			from_status=current,
			to_status=to_status,
			actor=actor,
			job_id=job_id,
			message=reason,
		)
		raise

	values = {"status": to_status, "status_reason": reason, "modified": now_datetime(), "modified_by": frappe.session.user}
	if to_status in states.LOCK_RELEASING:
		values["lock_token"] = None
		values["lock_expires_at"] = None
	values.update(extra or {})

	frappe.db.set_value("Document Intake", intake, values, update_modified=False)
	write_event(
		"transition",
		intake=intake,
		from_status=current,
		to_status=to_status,
		actor=actor,
		job_id=job_id,
		message=reason,
	)
	return to_status


def acquire_lock(intake: str, token: str, lock_minutes: int, job_id: str | None = None) -> bool:
	row = _current(intake)
	lock_is_free = not row.lock_token
	if row.status != states.STATUS_QUEUED or not lock_is_free:
		write_event("lock_skipped", intake=intake, from_status=row.status, job_id=job_id)
		return False
	transition(
		intake,
		states.STATUS_PROCESSING,
		reason="Processing started",
		expected_from=states.STATUS_QUEUED,
		extra={
			"lock_token": token,
			"lock_expires_at": add_to_date(now_datetime(), minutes=lock_minutes),
		},
		actor="System",
		job_id=job_id,
	)
	return True


def extend_lock(intake: str, token: str, lock_minutes: int) -> None:
	row = _current(intake)
	if row.lock_token != token:
		raise StaleTransition(f"{intake} lock is held by another job")
	frappe.db.set_value(
		"Document Intake",
		intake,
		{"lock_expires_at": add_to_date(now_datetime(), minutes=lock_minutes)},
		update_modified=False,
	)
