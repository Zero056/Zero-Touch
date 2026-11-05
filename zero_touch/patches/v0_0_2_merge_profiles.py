"""Merge Document Profile into Document Field Mapping.

The mapping is now the document type. This patch keeps existing uploads and intakes working:
it gives every mapping the profile's label/target, creates a mapping for document types that
had no rows yet, and points the intakes at the mapping names.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Document Profile"):
		return
	if not frappe.db.has_column("Document Field Mapping", "profile"):
		return

	profiles = frappe.get_all(
		"Document Profile",
		fields=["name", "label", "target_doctype", "company", "enabled"],
	)
	for profile in profiles:
		mappings = frappe.db.sql(
			"""select name, company, enabled from `tabDocument Field Mapping` where profile=%s""",
			(profile.name,),
			as_dict=True,
		)
		mapping = next(
			(row for row in mappings if (row.company or None) == (profile.company or None)),
			mappings[0] if mappings else None,
		)
		if mapping:
			doc = frappe.get_doc("Document Field Mapping", mapping.name)
			doc.label = profile.label or profile.name
			doc.target_doctype = profile.target_doctype
			doc.company = doc.company or profile.company
			doc.enabled = 1 if profile.enabled and doc.enabled else 0
			doc.profile = profile.name
			doc.flags.ignore_validate = True
			doc.save(ignore_permissions=True)
		else:
			doc = frappe.get_doc(
				{
					"doctype": "Document Field Mapping",
					"label": profile.label or profile.name,
					"target_doctype": profile.target_doctype,
					"company": profile.company,
					"enabled": 1 if profile.enabled else 0,
					"profile": profile.name,
				}
			)
			doc.flags.ignore_validate = True
			doc.flags.ignore_mandatory = True
			doc.insert(ignore_permissions=True)

		mapping_name = doc.name
		if doc.name != profile.name and not frappe.db.exists("Document Field Mapping", profile.name):
			frappe.rename_doc("Document Field Mapping", doc.name, profile.name, force=True)
			mapping_name = profile.name

		frappe.db.sql(
			"update `tabDocument Intake` set document_profile=%s where document_profile=%s",
			(mapping_name, profile.name),
		)
		frappe.db.sql(
			"update `tabDocument Extraction` set document_profile=%s where document_profile=%s",
			(mapping_name, profile.name),
		)

	for profile in profiles:
		# The controller folder is already gone in this version; delete the rows directly.
		frappe.db.sql("delete from `tabDocument Profile` where name=%s", (profile.name,))

	frappe.db.sql("update `tabDocument Field Mapping` set profile=NULL")
	if frappe.db.exists("DocType", "Document Profile"):
		frappe.delete_doc("DocType", "Document Profile", force=True, ignore_permissions=True)
	if frappe.db.table_exists("Document Profile"):
		frappe.db.sql("DROP TABLE IF EXISTS `tabDocument Profile`")
	frappe.db.commit()
