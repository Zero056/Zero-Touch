"""Unit tests for pure Phase 1 modules. These do not need a Frappe site or database."""

import io
import unittest
import zipfile

from zero_touch.audit.redaction import redact
from zero_touch.intake.file_checks import check_upload, sanitize_filename
from zero_touch.pipeline import states
from zero_touch.pipeline.backoff import backoff_seconds
from zero_touch.providers.base import DocumentInput, ErrorCode
from zero_touch.providers.registry import UnknownEngine, engine_names, get_engine
from zero_touch.security.endpoints import EndpointPolicyError, check_endpoint_url
from zero_touch.security.policy import (
	ROLE_ADMIN,
	ROLE_MANAGER,
	ROLE_REVIEWER,
	ROLE_UPLOADER,
	can_see_intake,
	intake_scope,
)

EXTS = ["pdf", "jpg", "jpeg", "png", "tif", "tiff", "csv", "xlsx", "docx"]
MAX = 1024 * 1024


def make_zip(members: dict[str, bytes]) -> bytes:
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		for name, data in members.items():
			zf.writestr(name, data)
	return buf.getvalue()


DOCX_MEMBERS = {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<w/>"}
XLSX_MEMBERS = {"[Content_Types].xml": b"<x/>", "xl/workbook.xml": b"<w/>"}


class FileChecksTest(unittest.TestCase):
	def test_valid_pdf(self):
		result = check_upload("inv.pdf", b"%PDF-1.7\n...", EXTS, MAX)
		self.assertTrue(result.ok)
		self.assertEqual(result.kind, "pdf")
		self.assertEqual(len(result.sha256), 64)

	def test_extension_not_allowed(self):
		self.assertEqual(check_upload("evil.exe", b"MZ..", EXTS, MAX).reason, "EXTENSION_NOT_ALLOWED")

	def test_xlsm_not_allowed(self):
		self.assertEqual(check_upload("book.xlsm", b"PK\x03\x04", EXTS, MAX).reason, "EXTENSION_NOT_ALLOWED")

	def test_signature_mismatch_pdf_disguised(self):
		self.assertEqual(check_upload("inv.pdf", b"<html>not pdf</html>", EXTS, MAX).reason, "SIGNATURE_MISMATCH")

	def test_png_and_jpeg_signatures(self):
		self.assertTrue(check_upload("a.png", b"\x89PNG\r\n\x1a\n...", EXTS, MAX).ok)
		self.assertTrue(check_upload("a.jpg", b"\xff\xd8\xff\xe0...", EXTS, MAX).ok)
		self.assertEqual(check_upload("a.jpg", b"\x89PNG\r\n\x1a\n", EXTS, MAX).reason, "SIGNATURE_MISMATCH")

	def test_tiff_both_byte_orders(self):
		self.assertTrue(check_upload("a.tif", b"II*\x00....", EXTS, MAX).ok)
		self.assertTrue(check_upload("a.tiff", b"MM\x00*....", EXTS, MAX).ok)

	def test_empty_file(self):
		self.assertEqual(check_upload("a.pdf", b"", EXTS, MAX).reason, "EMPTY_FILE")

	def test_too_large(self):
		self.assertEqual(check_upload("a.pdf", b"%PDF-" + b"x" * 100, EXTS, 50).reason, "FILE_TOO_LARGE")

	def test_csv_rejects_binary(self):
		self.assertTrue(check_upload("a.csv", "name,amount\nمورد,10\n".encode("utf-8"), EXTS, MAX).ok)
		self.assertEqual(check_upload("a.csv", b"a,b\x00\x01", EXTS, MAX).reason, "SIGNATURE_MISMATCH")

	def test_valid_docx(self):
		content = make_zip(DOCX_MEMBERS)
		self.assertTrue(check_upload("a.docx", content, EXTS, MAX).ok)

	def test_xlsx_missing_required_member(self):
		content = make_zip(DOCX_MEMBERS)
		self.assertEqual(check_upload("a.xlsx", content, EXTS, MAX).reason, "SIGNATURE_MISMATCH")

	def test_corrupt_zip(self):
		self.assertEqual(check_upload("a.docx", b"PK\x03\x04garbage", EXTS, MAX).reason, "ARCHIVE_INVALID")

	def test_macro_in_ooxml_rejected(self):
		content = make_zip({**DOCX_MEMBERS, "word/vbaProject.bin": b"\x00"})
		self.assertEqual(check_upload("a.docx", content, EXTS, MAX).reason, "ARCHIVE_MACRO")

	def test_nested_archive_rejected(self):
		content = make_zip({**DOCX_MEMBERS, "word/embedded.zip": b"PK"})
		self.assertEqual(check_upload("a.docx", content, EXTS, MAX).reason, "ARCHIVE_NESTED")

	def test_path_traversal_member_rejected(self):
		content = make_zip({**DOCX_MEMBERS, "../../evil.xml": b"x"})
		self.assertEqual(check_upload("a.docx", content, EXTS, MAX).reason, "ARCHIVE_INVALID")

	def test_zip_bomb_ratio_rejected(self):
		bomb = make_zip({**DOCX_MEMBERS, "word/big.xml": b"0" * (20 * 1024 * 1024)})
		self.assertEqual(check_upload("a.docx", bomb, EXTS, 10 * MAX).reason, "ARCHIVE_TOO_LARGE")

	def test_too_many_members(self):
		members = {**DOCX_MEMBERS}
		members.update({f"m/{i}.xml": b"x" for i in range(1001)})
		self.assertEqual(check_upload("a.docx", make_zip(members), EXTS, 10 * MAX).reason, "ARCHIVE_TOO_MANY_MEMBERS")

	def test_sanitize_filename(self):
		self.assertEqual(sanitize_filename("../../etc/passwd.pdf"), "passwd.pdf")
		self.assertEqual(sanitize_filename("C:\\docs\\inv 1.pdf"), "inv 1.pdf")
		self.assertEqual(sanitize_filename("..."), "...")
		self.assertEqual(sanitize_filename(""), "document")
		self.assertTrue(len(sanitize_filename("a" * 300 + ".pdf")) <= 140)
		self.assertTrue(sanitize_filename("a" * 300 + ".pdf").endswith(".pdf"))


class StateTableTest(unittest.TestCase):
	def test_happy_path_allowed(self):
		for frm, to in [
			("Received", "Queued"),
			("Queued", "Processing"),
			("Processing", "Pending Review"),
			("Pending Review", "Queued"),
			("Processing", "Ready to Create"),
			("Ready to Create", "Creating"),
			("Creating", "Created"),
			("Failed", "Queued"),
			("Rejected", "Pending Review"),
		]:
			self.assertTrue(states.is_allowed(frm, to), f"{frm} -> {to}")

	def test_invalid_transitions_refused(self):
		for frm, to in [
			("Created", "Creating"),
			("Created", "Queued"),
			("Duplicate", "Queued"),
			("Cancelled", "Queued"),
			("Received", "Created"),
			("Queued", "Created"),
			("Ready to Create", "Created"),
			("Pending Review", "Created"),
		]:
			self.assertFalse(states.is_allowed(frm, to), f"{frm} -> {to}")
			with self.assertRaises(states.InvalidTransition):
				states.assert_allowed(frm, to)

	def test_terminal_states_have_no_exits(self):
		for status in states.TERMINAL_STATUSES:
			self.assertEqual(states.TRANSITIONS[status], frozenset(), status)

	def test_every_status_is_in_table(self):
		self.assertEqual(set(states.TRANSITIONS), set(states.STATUSES))
		for targets in states.TRANSITIONS.values():
			self.assertTrue(targets <= set(states.STATUSES))

	def test_unknown_source_status_refused(self):
		self.assertFalse(states.is_allowed("Nonsense", "Queued"))


class BackoffTest(unittest.TestCase):
	def test_exponential_ceiling(self):
		self.assertEqual([backoff_seconds(a, 60, 10**6, lambda: 1.0) for a in (1, 2, 3, 4)], [60, 120, 240, 480])

	def test_cap(self):
		self.assertEqual(backoff_seconds(20, 60, 3600, lambda: 1.0), 3600)

	def test_jitter_bounds(self):
		self.assertEqual(backoff_seconds(3, 60, 3600, lambda: 0.0), 0)
		self.assertLessEqual(backoff_seconds(3, 60, 3600, lambda: 0.5), 120)
		self.assertEqual(backoff_seconds(1, 60, 3600, lambda: 5.0), 60)

	def test_invalid_inputs(self):
		with self.assertRaises(ValueError):
			backoff_seconds(0)


class RedactionTest(unittest.TestCase):
	def test_email_masked(self):
		self.assertNotIn("ali@example.com", redact("contact ali@example.com now"))

	def test_iban_masked(self):
		self.assertIn("[IBAN]", redact("IBAN SA0380000000608010167519 paid"))

	def test_secret_masked(self):
		out = redact("api_key=sk-live-123456 failed")
		self.assertNotIn("sk-live-123456", out)

	def test_card_and_phone_masked(self):
		self.assertIn("[CARD]", redact("card 4111 1111 1111 1111"))
		self.assertIn("[PHONE]", redact("call +966 50 123 4567"))

	def test_plain_text_kept(self):
		self.assertEqual(redact("Invoice total mismatch"), "Invoice total mismatch")

	def test_truncation(self):
		self.assertEqual(len(redact("x" * 1000)), 500)

	def test_empty(self):
		self.assertEqual(redact(None), "")


class AccessPolicyTest(unittest.TestCase):
	def test_no_company_scope_fails_closed(self):
		scope = intake_scope({ROLE_MANAGER}, [])
		self.assertFalse(can_see_intake(scope, "a@x", "ACME", "a@x"))

	def test_uploader_sees_only_own_in_company(self):
		scope = intake_scope({ROLE_UPLOADER}, ["ACME"])
		self.assertTrue(can_see_intake(scope, "u@x", "ACME", "u@x"))
		self.assertFalse(can_see_intake(scope, "u@x", "ACME", "other@x"))
		self.assertFalse(can_see_intake(scope, "u@x", "BETA", "u@x"))

	def test_reviewer_sees_company_not_others(self):
		scope = intake_scope({ROLE_REVIEWER}, ["ACME"])
		self.assertTrue(can_see_intake(scope, "r@x", "ACME", "other@x"))
		self.assertFalse(can_see_intake(scope, "r@x", "BETA", "other@x"))

	def test_admin_alone_denied(self):
		scope = intake_scope({ROLE_ADMIN}, ["ACME"])
		self.assertFalse(can_see_intake(scope, "admin@x", "ACME", "u@x"))

	def test_no_role_denied(self):
		scope = intake_scope(set(), ["ACME"])
		self.assertTrue(scope.deny_all)


class EndpointPolicyTest(unittest.TestCase):
	def test_external_https_hostname_allowed(self):
		check_endpoint_url("https://api.example.com/v1", local_provider=False)

	def test_external_http_refused(self):
		with self.assertRaises(EndpointPolicyError):
			check_endpoint_url("http://api.example.com", local_provider=False)

	def test_metadata_address_refused(self):
		with self.assertRaises(EndpointPolicyError):
			check_endpoint_url("https://169.254.169.254/latest", local_provider=False)

	def test_private_literal_refused_for_external(self):
		with self.assertRaises(EndpointPolicyError):
			check_endpoint_url("https://10.0.0.5/api", local_provider=False)

	def test_loopback_allowed_only_for_local_provider(self):
		check_endpoint_url("http://127.0.0.1:11434", local_provider=True)
		with self.assertRaises(EndpointPolicyError):
			check_endpoint_url("http://127.0.0.1:11434", local_provider=False)

	def test_credentials_in_url_refused(self):
		with self.assertRaises(EndpointPolicyError):
			check_endpoint_url("https://user:pw@api.example.com", local_provider=False)

	def test_empty_url_is_ok(self):
		check_endpoint_url("", local_provider=False)


class ProviderRegistryTest(unittest.TestCase):
	def test_registered_engines(self):
		self.assertEqual(engine_names(), ["null", "text_layer_stub"])

	def test_unknown_engine_refused(self):
		with self.assertRaises(UnknownEngine):
			get_engine("os.system")

	def test_placeholder_engines_return_unsupported(self):
		doc = DocumentInput(content=b"%PDF-", extension="pdf")
		for name in engine_names():
			result = get_engine(name, "p1").extract(doc)
			self.assertFalse(result.ok)
			self.assertEqual(result.errors[0].code, ErrorCode.UNSUPPORTED)
			self.assertFalse(result.errors[0].transient)

	def test_transient_codes(self):
		from zero_touch.providers.base import ProviderError

		self.assertTrue(ProviderError(ErrorCode.TIMEOUT, "t").transient)
		self.assertFalse(ProviderError(ErrorCode.AUTH, "t").transient)


if __name__ == "__main__":
	unittest.main()
