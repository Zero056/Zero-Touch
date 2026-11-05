import frappe

from zero_touch.audit.redaction import redact

EVENT_TYPES = frozenset(
	{
		"transition",
		"transition_refused",
		"upload_accepted",
		"upload_rejected",
		"duplicate_detected",
		"original_downloaded",
		"access_denied",
		"stage_start",
		"stage_end",
		"stage_fail",
		"retry_scheduled",
		"lock_recovered",
		"lock_skipped",
		"provider_skipped",
		"manual_review_required",
		"correction",
		"master_created",
	}
)


def write_event(
	event_type: str,
	*,
	intake: str | None = None,
	stage: str | None = None,
	from_status: str | None = None,
	to_status: str | None = None,
	actor: str | None = None,
	job_id: str | None = None,
	provider_code: str | None = None,
	duration_ms: int | None = None,
	message: str | None = None,
):
	if event_type not in EVENT_TYPES:
		raise ValueError(f"Unknown processing event: {event_type}")
	return frappe.get_doc(
		{
			"doctype": "Document Processing Log",
			"intake": intake,
			"event_type": event_type,
			"stage": stage,
			"from_status": from_status,
			"to_status": to_status,
			"actor": actor or frappe.session.user,
			"job_id": job_id,
			"provider_code": provider_code,
			"duration_ms": duration_ms,
			"message": redact(message),
		}
	).insert(ignore_permissions=True)
