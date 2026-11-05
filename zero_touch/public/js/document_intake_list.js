frappe.listview_settings["Document Intake"] = {
	add_fields: ["status", "stage", "original_filename"],
	hide_name_column: false,

	get_indicator(doc) {
		const colors = {
			Received: "blue",
			Queued: "blue",
			Processing: "blue",
			"Pending Review": "orange",
			"Pending Approval": "orange",
			"Ready to Create": "green",
			Creating: "blue",
			Created: "green",
			Failed: "red",
			Rejected: "red",
			Duplicate: "gray",
			Cancelled: "gray",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},

	onload(listview) {
		listview.page.add_inner_button(__("Upload Document"), () => open_upload_dialog(listview));
	},
};

function open_upload_dialog(listview) {
	const dialog = new frappe.ui.Dialog({
		title: __("Upload Document"),
		fields: [
			{
				fieldname: "company",
				fieldtype: "Link",
				options: "Company",
				label: __("Company"),
				reqd: 1,
			},
			{
				fieldname: "document_profile",
				fieldtype: "Link",
				options: "Document Field Mapping",
				label: __("Document Type"),
				reqd: 1,
				get_query: () => ({ filters: { enabled: 1 } }),
			},
			{
				fieldname: "file_html",
				fieldtype: "HTML",
				options:
					'<label class="control-label">' +
					__("File") +
					'</label><input type="file" class="zt-upload-file form-control" accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.csv,.xlsx,.docx">' +
					'<p class="text-muted small">' +
					__("Accepted: PDF, JPG, PNG, TIFF, CSV, XLSX, DOCX. The file is checked before it is stored.") +
					"</p>",
			},
		],
		primary_action_label: __("Upload"),
		primary_action(values) {
			const input = dialog.$wrapper.find(".zt-upload-file")[0];
			if (!input || !input.files.length) {
				frappe.msgprint(__("Choose a file to upload."));
				return;
			}
			const body = new FormData();
			body.append("file", input.files[0]);
			body.append("company", values.company);
			body.append("document_profile", values.document_profile);

			dialog.disable_primary_action();
			fetch("/api/method/zero_touch.api.intake.upload_document", {
				method: "POST",
				headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
				body,
			})
				.then(async (response) => {
					const payload = await response.json();
					if (!response.ok) {
						const messages = payload._server_messages ? JSON.parse(payload._server_messages) : [];
						const text = messages.length ? JSON.parse(messages[0]).message : __("Upload failed");
						throw new Error(text);
					}
					return payload.message;
				})
				.then((result) => {
					dialog.hide();
					if (result.status === "Duplicate") {
						frappe.show_alert({ message: __("This document was already uploaded."), indicator: "orange" });
					} else {
						frappe.show_alert({ message: __("Document queued for processing."), indicator: "green" });
					}
					frappe.set_route("Form", "Document Intake", result.name);
				})
				.catch((error) => {
					dialog.enable_primary_action();
					frappe.msgprint({ title: __("Upload failed"), message: error.message, indicator: "red" });
				});
		},
	});
	dialog.show();
}
