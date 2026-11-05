frappe.ui.form.on("Document Intake", {
	refresh(frm) {
		if (!frm.is_new() && frm.doc.original_file) {
			frm.add_custom_button(__("Download Original"), () => {
				window.open(
					"/api/method/zero_touch.api.intake.download_original?intake=" +
						encodeURIComponent(frm.doc.name)
				);
			});
		}

		if (frm.is_new()) {
			return;
		}

		frm.disable_save();
		frm.set_intro(
			`${__("Review the values, then create the Sales Invoice.")} <a href="#" class="zt-intro-review"><strong>${__("Open Review")}</strong></a>`,
			"blue"
		);
		frm.$wrapper.off("click.zt").on("click.zt", ".zt-intro-review", (event) => {
			event.preventDefault();
			frappe.set_route("zt-review-center", { intake: frm.doc.name });
		});

		if (frm.doc.status === "Ready to Create") {
			frm.add_custom_button(__("Create Draft Sales Invoice"), () => {
				frappe.confirm(__("Create a draft Sales Invoice from this document? It will not be submitted."), () => {
					frappe.call({
						method: "zero_touch.api.creation.create_draft",
						args: { intake: frm.doc.name },
						freeze: true,
						callback: () => frm.reload_doc(),
					});
				});
			});
		}

		if (frm.doc.status === "Pending Review" && frm.doc.original_file) {
			frm.add_custom_button(__("Re-run Extraction"), () => {
				frappe.call({
					method: "zero_touch.api.intake.reprocess_intake",
					args: { intake: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			});
		}

		if (frm.doc.status === "Failed") {
			frm.add_custom_button(__("Retry"), () => {
				frappe.call({
					method: "zero_touch.api.intake.retry_intake",
					args: { intake: frm.doc.name },
					callback: () => frm.reload_doc(),
				});
			});
		}

		if (["Queued", "Pending Review", "Failed", "Pending Approval"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Cancel Document"), () => {
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
					(values) => {
						frappe.call({
							method: "zero_touch.api.intake.cancel_intake",
							args: { intake: frm.doc.name, reason: values.reason },
							callback: () => frm.reload_doc(),
						});
					},
					__("Cancel Document")
				);
			});
		}
	},
});
