const VALUE_TYPES = {
	Date: "date", Datetime: "date", Currency: "money", Float: "money", Percent: "money", Int: "money",
	Link: "name", Data: "text", "Small Text": "text", Text: "text", "Long Text": "text", Select: "text",
};

function transform_for(fieldtype) {
	if (["Date", "Datetime"].includes(fieldtype)) {
		return "date_iso";
	}
	return ["Currency", "Float", "Percent", "Int"].includes(fieldtype) ? "money" : "none";
}

function fill_rows(frm, rows, silent) {
	try {
		// A new child grid can start with one blank row; it would block validation.
		frm.doc.rows = (frm.doc.rows || []).filter(
			(row) => row.target_field || row.pdf_label_en || row.pdf_label_ar
		);
		const mapped = frm.doc.rows.map((r) => r.target_field);
		const missing = (rows || []).filter((r) => !mapped.includes(r.target_field));
		if (!missing.length) {
			if (!silent) {
				frappe.show_alert({ message: __("All required fields are already listed."), indicator: "green" });
			}
			return;
		}
		missing.forEach((row) => frm.add_child("rows", row));
		frappe.show_alert({ message: __("{0} required field(s) added.", [missing.length]), indicator: "green" });
	} catch (error) {
		console.error("Zero Touch: could not add the required fields", error);
	} finally {
		frm.refresh_field("rows");
	}
}

frappe.ui.form.on("Document Field Mapping", {
	refresh(frm) {
		frm._zt_fill_added = false;
		frm.trigger("load_target_fields");
	},
	target_doctype(frm) {
		frm.trigger("load_target_fields");
	},
	load_target_fields(frm) {
		if (!frm.doc.target_doctype) {
			return;
		}
		frappe.call({
			method: "zero_touch.api.mapping.get_target_fields",
			args: { target_doctype: frm.doc.target_doctype },
			callback(r) {
				const info = r.message;
				frm._zt_fields = {};
				info.fields.forEach((f) => {
					frm._zt_fields[f.fieldname] = { ...f, table: null };
				});
				const options = [...info.fields.map((f) => f.fieldname)];
				Object.entries(info.tables).forEach(([table, data]) => {
					data.fields.forEach((f) => {
						const key = `${table}.${f.fieldname}`;
						frm._zt_fields[key] = { ...f, fieldname: key, table, label: `${f.label} (${data.label})` };
						options.push(key);
					});
				});
				frm.get_field("rows").grid.update_docfield_property("target_field", "options", options.join("\n"));
				frm.get_field("rows").grid.refresh();

				const lineTables = Object.entries(info.tables)
					.filter(([, data]) => data.line_item)
					.slice(0, 1);
				const required = [
					...info.mandatory,
					...lineTables.flatMap(([t, d]) => d.mandatory.map((f) => `${t}.${f}`)),
				];
				frm.set_intro(
					required.length
						? __("ERPNext requires: {0}", [required.join(", ")])
						: __("Choose the fields to fill from the document."),
					"blue"
				);
				if (!frm._zt_fill_added) {
					frm.add_custom_button(__("Fill Required Fields"), () =>
						fill_rows(frm, frm._zt_defaults, false)
					);
					frm._zt_fill_added = true;
				}
			},
		});
		frappe.call({
			method: "zero_touch.api.mapping.get_default_rows",
			args: { target_doctype: frm.doc.target_doctype },
			callback(r) {
				frm._zt_defaults = r.message || [];
				const has_data = (frm.doc.rows || []).some(
					(row) => row.target_field || row.pdf_label_en || row.pdf_label_ar
				);
				if (frm.is_new() && !has_data) {
					fill_rows(frm, frm._zt_defaults, true);
				}
			},
		});
	},
});

frappe.ui.form.on("Document Field Mapping Row", {
	target_field(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const field = (frm._zt_fields || {})[row.target_field];
		if (!field) {
			return;
		}
		frappe.model.set_value(cdt, cdn, {
			target_table: field.table || "",
			target_label: field.label,
			target_type: field.fieldtype,
			value_type: VALUE_TYPES[field.fieldtype] || "text",
			transform: transform_for(field.fieldtype),
		});
	},
});
