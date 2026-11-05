"""Intake status table from docs/architecture/03-state-machine.md. No Frappe imports."""

STATUS_RECEIVED = "Received"
STATUS_QUEUED = "Queued"
STATUS_PROCESSING = "Processing"
STATUS_PENDING_REVIEW = "Pending Review"
STATUS_PENDING_APPROVAL = "Pending Approval"
STATUS_READY = "Ready to Create"
STATUS_CREATING = "Creating"
STATUS_CREATED = "Created"
STATUS_FAILED = "Failed"
STATUS_REJECTED = "Rejected"
STATUS_DUPLICATE = "Duplicate"
STATUS_CANCELLED = "Cancelled"

STATUSES = (
	STATUS_RECEIVED,
	STATUS_QUEUED,
	STATUS_PROCESSING,
	STATUS_PENDING_REVIEW,
	STATUS_PENDING_APPROVAL,
	STATUS_READY,
	STATUS_CREATING,
	STATUS_CREATED,
	STATUS_FAILED,
	STATUS_REJECTED,
	STATUS_DUPLICATE,
	STATUS_CANCELLED,
)

TERMINAL_STATUSES = frozenset({STATUS_CREATED, STATUS_DUPLICATE, STATUS_CANCELLED})

TRANSITIONS: dict[str, frozenset[str]] = {
	STATUS_RECEIVED: frozenset({STATUS_QUEUED, STATUS_DUPLICATE, STATUS_REJECTED}),
	STATUS_QUEUED: frozenset({STATUS_PROCESSING, STATUS_CANCELLED}),
	STATUS_PROCESSING: frozenset(
		{
			STATUS_PROCESSING,
			STATUS_PENDING_REVIEW,
			STATUS_PENDING_APPROVAL,
			STATUS_READY,
			STATUS_FAILED,
		}
	),
	STATUS_PENDING_REVIEW: frozenset({STATUS_QUEUED, STATUS_READY, STATUS_REJECTED, STATUS_CANCELLED}),
	STATUS_PENDING_APPROVAL: frozenset({STATUS_READY, STATUS_PENDING_REVIEW, STATUS_REJECTED}),
	STATUS_READY: frozenset({STATUS_CREATING, STATUS_PENDING_REVIEW}),
	STATUS_CREATING: frozenset({STATUS_CREATED, STATUS_PENDING_REVIEW, STATUS_FAILED}),
	STATUS_FAILED: frozenset({STATUS_QUEUED, STATUS_CANCELLED}),
	STATUS_REJECTED: frozenset({STATUS_PENDING_REVIEW}),
	STATUS_CREATED: frozenset(),
	STATUS_DUPLICATE: frozenset(),
	STATUS_CANCELLED: frozenset(),
}

# Transitions that release the processing lock as part of the change.
LOCK_RELEASING = frozenset(
	{
		STATUS_PENDING_REVIEW,
		STATUS_PENDING_APPROVAL,
		STATUS_READY,
		STATUS_FAILED,
		STATUS_CREATED,
		STATUS_REJECTED,
		STATUS_DUPLICATE,
		STATUS_CANCELLED,
	}
)


class InvalidTransition(Exception):
	def __init__(self, from_status: str | None, to_status: str):
		self.from_status = from_status
		self.to_status = to_status
		super().__init__(f"Invalid transition: {from_status!r} -> {to_status!r}")


def is_allowed(from_status: str | None, to_status: str) -> bool:
	if from_status is None:
		return to_status in STATUSES
	return to_status in TRANSITIONS.get(from_status, frozenset())


def assert_allowed(from_status: str | None, to_status: str) -> None:
	if not is_allowed(from_status, to_status):
		raise InvalidTransition(from_status, to_status)
