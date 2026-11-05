"""Phase 1 integration tests. Require a disposable test site with ERPNext and at least one Company.

Run on the test site only, for example:
  bench --site zt_test.local run-tests --app zero_touch
"""

import hashlib
import uuid
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from zero_touch.audit.redaction import redact
from zero_touch.pipeline import jobs, machine, states
from zero_touch.providers.base import ErrorCode, ExtractionResult, ProviderError
from zero_touch.security.access import intake_has_permission, intake_query_conditions
from zero_touch.security.policy import ROLE_UPLOADER

PDF_BYTES = b"%PDF-1.4\n% zero touch test\n%%EOF\n"


def _company() -> str:
	company = frappe.db.get_value("Company", {}, "name")
	if not company:
		raise frappe.ValidationError("The test site needs at least one Company")
	return company


def _enable_processing():
	settings = frappe.get_single("Zero Touch Settings")
	settings.enabled = 1
	settings.max_attempts = 3
	settings.save(ignore_permissions=True)


def _new_user(email: str, roles: list[str], companies: list[str]) -> str:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "ZT",
				"send_welcome_email": 0,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
	for company in companies:
		if not frappe.db.exists("User Permission", {"user": email, "allow": "Company", "for_value": company}):
			frappe.get_doc(
				{"doctype": "User Permission", "user": email, "allow": "Company", "for_value": company}
			).insert(ignore_permissions=True)
	return email


class _Base(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.company = _company()
		_enable_processing()

	def _upload(self, content: bytes = PDF_BYTES, filename: str = "invoice.pdf") -> dict:
		from zero_touch.intake.service import create_intake_from_upload

		return create_intake_from_upload(self.company, "supplier_invoice", filename, content)

	def _status(self, name: str) -> str:
		return frappe.db.get_value("Document Intake", name, "status")


class TestUploadAndDuplicates(_Base):
	def test_settings_default_disabled(self):
		frappe.db.set_single_value("Zero Touch Settings", "enabled", 0)
		from zero_touch.intake.service import create_intake_from_upload

		with self.assertRaises(frappe.ValidationError):
			create_intake_from_upload(self.company, "supplier_invoice", "a.pdf", PDF_BYTES)
		_enable_processing()

	def test_valid_pdf_is_stored_privately_and_queued(self):
		with mock.patch("zero_touch.intake.service.queue_intake") as queue:
			result = self._upload()
		self.assertEqual(result["status"], states.STATUS_QUEUED)
		intake = frappe.get_doc("Document Intake", result["name"])
		self.assertEqual(intake.file_sha256, hashlib.sha256(PDF_BYTES).hexdigest())
		file_doc = frappe.get_doc("File", {"file_url": intake.original_file})
		self.assertEqual(file_doc.is_private, 1)
		self.assertEqual(file_doc.get_content(), PDF_BYTES)
		queue.assert_called_once()

	def test_exact_duplicate_in_same_company(self):
		with mock.patch("zero_touch.intake.service.queue_intake"):
			first = self._upload()
			second = self._upload()
		self.assertEqual(second["status"], states.STATUS_DUPLICATE)
		self.assertEqual(self._status(second["name"]), states.STATUS_DUPLICATE)
		self.assertEqual(frappe.db.get_value("Document Intake", second["name"], "duplicate_of"), first["name"])

	def test_rejected_upload_creates_no_intake_and_is_logged(self):
		before = frappe.db.count("Document Intake")
		with self.assertRaises(frappe.ValidationError):
			self._upload(content=b"<html>not a pdf</html>", filename="invoice.pdf")
		self.assertEqual(frappe.db.count("Document Intake"), before)
		self.assertTrue(
			frappe.db.exists("Document Processing Log", {"event_type": "upload_rejected"})
		)

	def test_disallowed_extension_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._upload(content=b"MZ....", filename="setup.exe")


class TestStateMachine(_Base):
	def test_invalid_transition_refused_and_logged(self):
		result = self._upload()
		name = result["name"]
		with self.assertRaises(states.InvalidTransition):
			machine.transition(name, states.STATUS_CREATED, reason="attempt")
		self.assertTrue(
			frappe.db.exists("Document Processing Log", {"intake": name, "event_type": "transition_refused"})
		)

	def test_status_cannot_be_edited_on_form(self):
		name = self._upload()["name"]
		doc = frappe.get_doc("Document Intake", name)
		doc.status = states.STATUS_CANCELLED
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_processing_log_is_immutable(self):
		name = self._upload()["name"]
		log_name = frappe.db.get_value("Document Processing Log", {"intake": name}, "name")
		log = frappe.get_doc("Document Processing Log", log_name)
		log.message = "changed"
		with self.assertRaises(frappe.ValidationError):
			log.save()
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Document Processing Log", log.name)

	def test_lock_is_exclusive(self):
		name = self._upload()["name"]
		self.assertTrue(machine.acquire_lock(name, "token-a", 5))
		self.assertFalse(machine.acquire_lock(name, "token-b", 5))
		with self.assertRaises(machine.StaleTransition):
			machine.transition(name, states.STATUS_PENDING_REVIEW, lock_token="token-b")


class TestProcessing(_Base):
	def test_no_provider_goes_to_manual_review(self):
		name = self._upload()["name"]
		frappe.db.set_value("Document Intake", name, "status", states.STATUS_QUEUED)
		jobs.run_stage(name, "extract", "token-1")
		self.assertEqual(self._status(name), states.STATUS_PENDING_REVIEW)
		self.assertTrue(
			frappe.db.exists("Document Processing Log", {"intake": name, "event_type": "manual_review_required"})
		)

	def test_transient_provider_error_schedules_retry(self):
		name = self._upload()["name"]
		frappe.db.set_value("Document Intake", name, "status", states.STATUS_QUEUED)
		frappe.db.set_value("Document Intake", name, "attempt_count", 1)
		provider = frappe.get_doc(
			{
				"doctype": "Extraction Provider",
				"provider_code": f"test_{uuid.uuid4().hex[:8]}",
				"provider_type": "text_layer",
				"engine": "text_layer_stub",
				"enabled": 1,
				"data_residency": "local",
			}
		).insert(ignore_permissions=True)
		transient = ExtractionResult(
			ok=False,
			provider_code=provider.provider_code,
			errors=(ProviderError(ErrorCode.UNAVAILABLE, "down"),),
		)
		fake_engine = mock.Mock()
		fake_engine.extract.return_value = transient
		with mock.patch("zero_touch.pipeline.jobs.get_engine", return_value=fake_engine):
			jobs.run_stage(name, "extract", "token-2")
		row = frappe.db.get_value(
			"Document Intake", name, ["status", "retry_count", "next_retry_at"], as_dict=True
		)
		self.assertEqual(row.status, states.STATUS_FAILED)
		self.assertEqual(row.retry_count, 1)
		self.assertIsNotNone(row.next_retry_at)

	def test_retries_exhausted_no_next_retry(self):
		name = self._upload()["name"]
		frappe.db.set_value("Document Intake", name, "status", states.STATUS_QUEUED)
		frappe.db.set_value("Document Intake", name, "attempt_count", 3)
		fake_engine = mock.Mock()
		fake_engine.extract.return_value = ExtractionResult(
			ok=False, provider_code="x", errors=(ProviderError(ErrorCode.TIMEOUT, "slow"),)
		)
		provider = frappe.get_doc(
			{
				"doctype": "Extraction Provider",
				"provider_code": f"test_{uuid.uuid4().hex[:8]}",
				"provider_type": "text_layer",
				"engine": "text_layer_stub",
				"enabled": 1,
				"data_residency": "local",
			}
		).insert(ignore_permissions=True)
		with mock.patch("zero_touch.pipeline.jobs.get_engine", return_value=fake_engine):
			jobs.run_stage(name, "extract", "token-3")
		row = frappe.db.get_value("Document Intake", name, ["status", "next_retry_at"], as_dict=True)
		self.assertEqual(row.status, states.STATUS_FAILED)
		self.assertIsNone(row.next_retry_at)
		frappe.delete_doc("Extraction Provider", provider.name, force=True)

	def test_stale_lock_recovered_to_failed_with_retry(self):
		name = self._upload()["name"]
		frappe.db.set_value(
			"Document Intake",
			name,
			{
				"status": states.STATUS_PROCESSING,
				"lock_token": "dead-worker",
				"lock_expires_at": add_to_date(now_datetime(), minutes=-30),
				"attempt_count": 1,
			},
		)
		self.assertGreaterEqual(jobs.recover_stale_locks(), 1)
		row = frappe.db.get_value("Document Intake", name, ["status", "lock_token", "next_retry_at"], as_dict=True)
		self.assertEqual(row.status, states.STATUS_FAILED)
		self.assertIsNone(row.lock_token)
		self.assertIsNotNone(row.next_retry_at)

	def test_due_retry_is_requeued_once(self):
		name = self._upload()["name"]
		frappe.db.set_value(
			"Document Intake",
			name,
			{
				"status": states.STATUS_FAILED,
				"next_retry_at": add_to_date(now_datetime(), minutes=-1),
				"attempt_count": 1,
			},
		)
		with mock.patch("zero_touch.pipeline.jobs.frappe.enqueue") as enqueue:
			self.assertEqual(jobs.enqueue_due_retries(), 1)
			self.assertEqual(jobs.enqueue_due_retries(), 0)
		enqueue.assert_called_once()
		self.assertEqual(self._status(name), states.STATUS_QUEUED)

	def test_manual_retry_requires_failed_status(self):
		name = self._upload()["name"]
		from zero_touch.api.intake import retry_intake

		with self.assertRaises(frappe.ValidationError):
			retry_intake(name)


class TestAccess(_Base):
	def setUp(self):
		super().setUp()
		self.owner = _new_user("zt-owner@example.com", [ROLE_UPLOADER], [self.company])
		self.other = _new_user("zt-other@example.com", [ROLE_UPLOADER], [self.company])
		self.stranger = _new_user("zt-stranger@example.com", [ROLE_UPLOADER], [])
		with mock.patch("zero_touch.intake.service.queue_intake"), _as(self.owner):
			self.intake = self._upload(filename=f"{uuid.uuid4().hex}.pdf")["name"]

	def test_owner_can_read_other_cannot(self):
		with _as(self.owner):
			self.assertTrue(frappe.get_doc("Document Intake", self.intake).has_permission("read"))
		with _as(self.other):
			self.assertFalse(intake_has_permission(frappe.get_doc("Document Intake", self.intake), "read", self.other))

	def test_user_without_company_scope_sees_nothing(self):
		with _as(self.stranger):
			self.assertEqual(intake_query_conditions(self.stranger), "1=0")

	def test_list_query_excludes_other_users_records(self):
		conditions = intake_query_conditions(self.other)
		visible = frappe.db.sql(
			f"select name from `tabDocument Intake` where name = %s and {conditions}",
			self.intake,
		)
		self.assertEqual(visible, ())

	def test_download_refused_for_other_user(self):
		from zero_touch.api.intake import download_original

		with _as(self.other):
			with self.assertRaises(frappe.PermissionError):
				download_original(self.intake)
		self.assertTrue(
			frappe.db.exists("Document Processing Log", {"intake": self.intake, "event_type": "access_denied"})
		)

	def test_cannot_upload_to_company_without_scope(self):
		with _as(self.stranger):
			from zero_touch.intake.service import create_intake_from_upload

			with self.assertRaises(frappe.PermissionError):
				create_intake_from_upload(self.company, "supplier_invoice", "x.pdf", PDF_BYTES + b"x")


class TestRedactionInLogs(_Base):
	def test_log_message_is_redacted(self):
		name = self._upload()["name"]
		from zero_touch.audit.log import write_event

		log = write_event("stage_fail", intake=name, message="contact ali@example.com key=sk-123")
		stored = frappe.db.get_value("Document Processing Log", log.name, "message")
		self.assertNotIn("ali@example.com", stored)
		self.assertEqual(stored, redact(stored))


class TestEndpointValidation(_Base):
	def test_external_http_provider_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Extraction Provider",
					"provider_code": f"bad_{uuid.uuid4().hex[:8]}",
					"provider_type": "llm",
					"engine": "null",
					"data_residency": "external",
					"base_url": "http://api.example.com",
				}
			).insert(ignore_permissions=True)


class _as:
	def __init__(self, user):
		self.user = user

	def __enter__(self):
		self.previous = frappe.session.user
		frappe.set_user(self.user)

	def __exit__(self, *exc):
		frappe.set_user(self.previous)
