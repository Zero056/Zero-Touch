import frappe
from frappe import _
from frappe.model.document import Document

from zero_touch.mapping.compat import (
	allowed_transforms,
	allowed_value_types,
	default_transform,
	default_value_type,
)
from zero_touch.mapping.transforms import TRANSFORM_NAMES
from zero_touch.targets import validate_target_doctype

CREATABLE_LINKS = ("Customer", "Supplier")
FILLED_BY_SYSTEM = frozenset({"company", "naming_series"})
MIN_LABEL_LENGTH = 2


class DocumentFieldMapping(Document):
	def validate(self):
		self.validate_target()
		self.validate_unique_scope()
		self.validate_rows()
		self.warn_missing_mandatory()

	def validate_target(self):
		validate_target_doctype(self.target_doctype)

	def validate_unique_scope(self):
		if not self.enabled:
			return
		filters = {"label": self.label, "enabled": 1, "name": ["!=", self.name or ""]}
		filters["company"] = self.company or ["is", "not set"]
		clash = frappe.db.get_value("Document Field Mapping", filters, "name")
		if clash:
			scope = self.company or _("all companies")
			frappe.throw(
				_("Another enabled mapping for {0} already covers {1}: {2}").format(
					self.label, scope, clash
				)
			)

	def validate_rows(self):
		if not self.rows:
			# An empty mapping is valid: the target doctype's generic fields are used until
			# the user creates rows. This is how the Customer document type starts.
			return

		from zero_touch.api.mapping import child_tables_for

		main_meta = frappe.get_meta(self.target_doctype)
		allowed_tables = child_tables_for(self.target_doctype)
		seen_fields = set()
		seen_labels = {}
		for row in self.rows:
			where = _("Row {0}").format(row.idx)
			table, fieldname = self._split_target(row.target_field)
			if table and table not in allowed_tables:
				frappe.throw(_("{0}: {1} is not a line-item table for {2}").format(where, table, self.target_doctype))
			meta = frappe.get_meta(main_meta.get_field(table).options) if table else main_meta
			df = meta.get_field(fieldname) if fieldname else None
			if not df or not allowed_value_types(df.fieldtype):
				frappe.throw(_("{0}: choose a field from the list").format(where))
			key = f"{table}.{fieldname}" if table else fieldname
			if key in seen_fields:
				frappe.throw(_("{0}: {1} is listed more than once").format(where, key))
			seen_fields.add(key)

			row.target_field = key
			row.target_table = table or None
			row.target_label = df.label or df.fieldname
			row.target_type = df.fieldtype

			if row.source == "ERPNext fills automatically":
				row.value_type = default_value_type(df.fieldtype)
				row.transform = default_transform(df.fieldtype)
			if not row.value_type:
				row.value_type = default_value_type(df.fieldtype)
			if row.value_type not in allowed_value_types(df.fieldtype):
				frappe.throw(
					_("{0}: value type {1} cannot fill {2} ({3}). Choose one of: {4}").format(
						where,
						row.value_type,
						df.label,
						df.fieldtype,
						", ".join(allowed_value_types(df.fieldtype)),
					)
				)
			if not row.transform:
				row.transform = default_transform(df.fieldtype)
			if row.transform not in TRANSFORM_NAMES or row.transform not in allowed_transforms(df.fieldtype):
				frappe.throw(
					_("{0}: transform {1} does not fit {2} ({3}). Choose one of: {4}").format(
						where,
						row.transform,
						df.label,
						df.fieldtype,
						", ".join(allowed_transforms(df.fieldtype)),
					)
				)

			if row.source == "ERPNext fills automatically":
				row.pdf_label_en = (row.pdf_label_en or "").strip() or None
				row.pdf_label_ar = (row.pdf_label_ar or "").strip() or None
			else:
				self._check_labels(where, row, seen_labels)

			if row.create_if_missing:
				linked = None
				if df.fieldtype == "Link":
					linked = df.options
				elif df.fieldtype == "Dynamic Link" and df.options:
					link_field = meta.get_field(df.options)
					linked = (link_field.default if link_field else None) or None
				if table or linked not in CREATABLE_LINKS:
					frappe.throw(
						_("{0}: Create If Missing works only for header links to {1}").format(
							where, " or ".join(CREATABLE_LINKS)
						)
					)

	@staticmethod
	def _split_target(target_field: str):
		if not target_field:
			return None, None
		if "." in target_field:
			table, _, fieldname = target_field.partition(".")
			return table, fieldname
		return None, target_field

	def _check_labels(self, where, row, seen_labels):
		english = (row.pdf_label_en or "").strip()
		arabic = (row.pdf_label_ar or "").strip()
		if not (english or arabic):
			frappe.throw(_("{0}: enter the label as it appears on the document, in English or Arabic").format(where))
		row.pdf_label_en = english or None
		row.pdf_label_ar = arabic or None
		for text in (english, arabic):
			if not text:
				continue
			if len(text) < MIN_LABEL_LENGTH:
				frappe.throw(_("{0}: the label {1} is too short").format(where, text))
			key = text.casefold()
			if key in seen_labels and seen_labels[key] != row.target_field:
				frappe.throw(
					_("{0}: the label {1} is already used for {2}. Each label must point to one field").format(
						where, text, seen_labels[key]
					)
				)
			seen_labels[key] = row.target_field

	def warn_missing_mandatory(self):
		if not self.rows:
			return
		from zero_touch.api.mapping import child_tables_for, get_target_fields

		info = get_target_fields(self.target_doctype) if frappe.has_permission("Document Field Mapping", "write") else None
		if not info:
			return
		mapped = {row.target_field for row in self.rows}
		missing = [f for f in info["mandatory"] if f not in mapped]
		for table, data in info["tables"].items():
			if any(r.target_field and r.target_field.startswith(table + ".") for r in self.rows):
				missing += [f"{table}.{f}" for f in data["mandatory"] if f"{table}.{f}" not in mapped]
		if missing:
			frappe.msgprint(
				_("ERPNext requires these fields for {0}, and they are not mapped: {1}. Map them, or fill them in before creating the document.").format(
					self.target_doctype, ", ".join(missing)
				),
				indicator="orange",
				alert=True,
			)
