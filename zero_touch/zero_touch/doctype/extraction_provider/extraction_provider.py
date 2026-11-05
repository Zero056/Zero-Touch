import frappe
from frappe import _
from frappe.model.document import Document

from zero_touch.providers.registry import engine_names
from zero_touch.security.endpoints import EndpointPolicyError, check_endpoint_url


class ExtractionProvider(Document):
	def validate(self):
		if self.engine not in engine_names():
			frappe.throw(_("Engine {0} is not registered").format(self.engine))
		try:
			check_endpoint_url(self.base_url or "", local_provider=self.data_residency == "local")
		except EndpointPolicyError as exc:
			frappe.throw(_("Invalid Base URL: {0}").format(str(exc)))
		if (self.timeout_seconds or 0) < 1 or (self.timeout_seconds or 0) > 300:
			frappe.throw(_("Timeout must be between 1 and 300 seconds"))
