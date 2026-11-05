import frappe
from frappe import _
from frappe.model.document import Document

from zero_touch.intake.file_checks import SUPPORTED_EXTENSIONS


class ZeroTouchSettings(Document):
	def validate(self):
		self.validate_extensions()
		self.validate_limits()

	def validate_extensions(self):
		requested = [e.strip().lower() for e in (self.allowed_extensions or "").split(",") if e.strip()]
		if not requested:
			frappe.throw(_("At least one file extension must be allowed"))
		unsupported = sorted(set(requested) - SUPPORTED_EXTENSIONS)
		if unsupported:
			frappe.throw(_("Unsupported file extensions: {0}").format(", ".join(unsupported)))
		self.allowed_extensions = ",".join(dict.fromkeys(requested))

	def validate_limits(self):
		if (self.max_file_size_mb or 0) < 1:
			frappe.throw(_("Maximum file size must be at least 1 MB"))
		frappe_limit_mb = (frappe.conf.get("max_file_size") or 10485760) / (1024 * 1024)
		if self.max_file_size_mb > frappe_limit_mb:
			frappe.throw(
				_("Maximum file size cannot exceed the site limit of {0} MB (max_file_size)").format(
					round(frappe_limit_mb, 1)
				)
			)
		if not 1 <= (self.max_attempts or 0) <= 20:
			frappe.throw(_("Maximum automatic attempts must be between 1 and 20"))
		if (self.retry_base_seconds or 0) < 1 or (self.retry_max_seconds or 0) < (self.retry_base_seconds or 0):
			frappe.throw(_("Retry delays must be positive and the maximum must not be below the base"))
