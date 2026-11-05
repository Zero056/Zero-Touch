import frappe

ROLES = (
	"Zero Touch Uploader",
	"Zero Touch Reviewer",
	"Zero Touch Creator",
	"Zero Touch Approver",
	"Zero Touch Manager",
	"Zero Touch Admin",
)

SETTINGS_DEFAULTS = {
	"privacy_mode": "local_only",
	"ai_enabled": 0,
	"max_file_size_mb": 20,
	"max_pages": 50,
	"allowed_extensions": "pdf,jpg,jpeg,png,tif,tiff,csv,xlsx,docx",
	"max_attempts": 5,
	"retry_base_seconds": 60,
	"retry_max_seconds": 3600,
	"retention_days_originals": 0,
}


def before_install():
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)


def ensure_settings_defaults():
	settings = frappe.get_single("Zero Touch Settings")
	for field, value in SETTINGS_DEFAULTS.items():
		if settings.get(field) in (None, ""):
			frappe.db.set_single_value("Zero Touch Settings", field, value)


DEFAULT_DOCUMENT_TYPES = (
	{"label": "Supplier Invoice", "target_doctype": "Purchase Invoice"},
	{"label": "Sales Invoice", "target_doctype": "Sales Invoice"},
	{"label": "Customer", "target_doctype": "Customer"},
)


def ensure_default_document_types():
	for document_type in DEFAULT_DOCUMENT_TYPES:
		if not frappe.db.exists("Document Field Mapping", {"label": document_type["label"]}):
			frappe.get_doc(
				{"doctype": "Document Field Mapping", "enabled": 1, **document_type}
			).insert(ignore_permissions=True)


def after_install():
	ensure_settings_defaults()
	ensure_default_document_types()
	ensure_custom_fields()


CUSTOM_FIELD_DOCTYPES = ("Sales Invoice", "Purchase Invoice")


def ensure_custom_fields():
	for doctype in CUSTOM_FIELD_DOCTYPES:
		if frappe.db.exists("Custom Field", {"dt": doctype, "fieldname": "zero_touch_intake"}):
			continue
		frappe.get_doc(
			{
				"doctype": "Custom Field",
				"dt": doctype,
				"fieldname": "zero_touch_intake",
				"label": "Zero Touch Intake",
				"fieldtype": "Link",
				"options": "Document Intake",
				"read_only": 1,
				"search_index": 1,
			}
		).insert(ignore_permissions=True)
