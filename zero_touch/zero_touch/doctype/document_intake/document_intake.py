import frappe
from frappe import _
from frappe.model.document import Document


class DocumentIntake(Document):
	def before_insert(self):
		if not frappe.flags.zt_upload_in_progress:
			frappe.throw(_("Documents are added by uploading a file, not by creating a record"))

	def validate(self):
		# Status is owned by the pipeline state machine. Forms and scripts cannot change it directly.
		if not self.is_new() and self.has_value_changed("status"):
			frappe.throw(_("Status is changed by the processing pipeline, not by editing the record"))
