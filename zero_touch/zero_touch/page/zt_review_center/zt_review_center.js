frappe.pages["zt-review-center"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Review Center"),
		single_column: true,
	});
	const center = new ReviewCenter(page);
	$(wrapper).bind("show", () => center.load(zt_intake_from_route()));
};

const ZT_STYLE = `
<style>
.zt-review { font-size: 13px; color: #1f2937; }
.zt-card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; box-shadow: 0 1px 3px rgba(15,23,42,.06); padding: 16px 18px; margin-bottom: 16px; }
.zt-card h4 { margin: 0 0 10px 0; font-size: 15px; color: #0f172a; }
.zt-hero { background: linear-gradient(120deg, #eef2ff 0%, #f0fdfa 100%); border: 1px solid #c7d2fe; }
.zt-hero-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; }
.zt-hero-title { font-size: 18px; font-weight: 700; color: #1e1b4b; }
.zt-meta { color: #475569; font-size: 12px; margin-top: 4px; }
.zt-pill { display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 12px; font-weight: 600; color: #fff; }
.zt-pill-review { background: #d97706; }
.zt-pill-ready { background: #059669; }
.zt-pill-created { background: #4f46e5; }
.zt-pill-failed { background: #dc2626; }
.zt-pill-other { background: #64748b; }
.zt-badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }
.zt-badge-ok { background: #dcfce7; color: #166534; }
.zt-badge-warn { background: #ffedd5; color: #9a3412; }
.zt-badge-bad { background: #fee2e2; color: #991b1b; }
.zt-badge-muted { background: #f1f5f9; color: #475569; }
.zt-missing { background: #fff1f2; border: 1px solid #fecdd3; border-left: 5px solid #e11d48; }
.zt-missing li { margin-bottom: 6px; }
.zt-grid { display: grid; grid-template-columns: minmax(240px, 1fr) minmax(0, 2fr); gap: 16px; }
.zt-preview img { width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; margin-bottom: 10px; background: #f8fafc; }
.zt-table { width: 100%; border-collapse: separate; border-spacing: 0; }
.zt-table th { background: #f8fafc; color: #334155; font-weight: 600; padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: left; }
.zt-table td { padding: 8px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
.zt-row-missing td { background: #fff7ed; }
.zt-row-linked td { background: #f0fdf4; }
.zt-source { color: #64748b; font-size: 11px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.zt-section-note { color: #64748b; font-size: 12px; margin-bottom: 8px; }
.zt-blocker { color: #9f1239; }
.zt-ready { color: #166534; font-weight: 600; }
.zt-history li { margin-bottom: 6px; color: #334155; }
.zt-link { color: #4338ca; font-weight: 600; }
</style>`;

function zt_intake_from_route() {
	const fromUrl = frappe.utils.get_url_arg("intake");
	const fromRoute = frappe.route_options && frappe.route_options.intake;
	frappe.route_options = null;
	return fromUrl || fromRoute || null;
}

const ZT_STATUS_CLASS = {
	"Pending Review": "zt-pill-review",
	"Ready to Create": "zt-pill-ready",
	Created: "zt-pill-created",
	Failed: "zt-pill-failed",
	Rejected: "zt-pill-failed",
};

const ZT_STATE_BADGE = {
	extracted: ["zt-badge-ok", "Read"],
	uncertain: ["zt-badge-warn", "Check"],
	missing: ["zt-badge-bad", "Missing"],
	conflict: ["zt-badge-bad", "Conflict"],
};

function zt_esc(value) {
	return frappe.utils.escape_html(String(value === null || value === undefined ? "" : value));
}

function zt_route(doctype, name) {
	return `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
}

function open_upload(center) {
	const dialog = new frappe.ui.Dialog({
		title: __("Upload Document"),
		fields: [
			{ fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1 },
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
					'<label class="control-label">' + __("File") + '</label><input type="file" class="zt-upload-file form-control" accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.csv,.xlsx,.docx">',
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
						throw new Error(messages.length ? JSON.parse(messages[0]).message : __("Upload failed"));
					}
					return payload.message;
				})
				.then((result) => {
					dialog.hide();
					frappe.show_alert({
						message: result.status === "Duplicate" ? __("This document was already uploaded.") : __("Uploaded. Reading the document now."),
						indicator: result.status === "Duplicate" ? "orange" : "green",
					});
					frappe.set_route("zt-review-center", { intake: result.name });
				})
				.catch((error) => {
					dialog.enable_primary_action();
					frappe.msgprint({ title: __("Upload failed"), message: error.message, indicator: "red" });
				});
		},
	});
	dialog.show();
}

class ReviewCenter {
	constructor(page) {
		this.page = page;
		this.body = $('<div class="zt-review"></div>').appendTo(this.page.main);
		this.intake = null;
		this.body.on("click", ".zt-remove-line", (event) => $(event.currentTarget).closest("tr").remove());
		this.body.on("click", ".zt-add-line", () => this.add_item_row());
		this.body.on("input change", ".zt-line", (event) => {
			const field = $(event.currentTarget).data("field");
			if (field === "qty" || field === "rate") {
				this.fill_row_amount($(event.currentTarget).closest("tr"));
			}
		});
		this.body.on("click", ".zt-open", (event) => {
			event.preventDefault();
			this.load($(event.currentTarget).data("intake"));
		});
	}

	fill_row_amount(row) {
		const read = (field) => {
			const raw = String(row.find(`.zt-line[data-field="${field}"]`).val() || "").replace(/,/g, "").trim();
			const value = Number.parseFloat(raw);
			return Number.isFinite(value) ? value : null;
		};
		const qty = read("qty");
		const rate = read("rate");
		const amount = row.find('.zt-line[data-field="amount"]');
		// Only fill a missing amount. An amount read from the document may already include
		// a discount or a rounding, and must never be replaced by qty × rate.
		if (qty === null || rate === null || String(amount.val() || "").trim()) {
			return;
		}
		amount.val((Math.round(qty * rate * 100) / 100).toFixed(2));
	}

	fill_missing_amounts() {
		this.body.find(".zt-lines tbody tr").each((_, tr) => this.fill_row_amount($(tr)));
	}

	add_item_row() {
		const cells = ["item_name", "qty", "rate", "amount"]
			.map((f) => `<td><input class="form-control input-sm zt-line" data-field="${f}" value=""></td>`)
			.join("");
		const table = this.body.find(".zt-lines tbody");
		table.append(
			`<tr data-row="" class="zt-row-missing"><td>${__("new")}</td>${cells}<td><div class="zt-item-control" data-item=""></div></td><td></td><td><button class="btn btn-default btn-xs zt-remove-line">${__("Remove")}</button></td></tr>`
		);
		const last = table.find("tr").last().find(".zt-item-control");
		const control = frappe.ui.form.make_control({
			parent: last,
			df: { fieldtype: "Link", options: "Item", label: __("Item"), fieldname: "item_code" },
			render_input: true,
		});
		last.data("control", control);
	}

	load(intake) {
		this.intake = intake;
		this.body.empty();
		if (!intake) {
			this.show_picker();
			return;
		}
		const show_error = (error) => {
			const message = (error && error.message) || String(error || "");
			this.body.html(
				`${ZT_STYLE}<div class="zt-card zt-missing"><h4>${__("This page could not be shown.")}</h4><pre class="small">${zt_esc(String(message).slice(0, 800))}</pre></div>`
			);
		};
		frappe.call({
			method: "zero_touch.api.monitor.get_intake_detail",
			args: { intake },
			callback: (detail) => {
				frappe.call({
					method: "zero_touch.api.extraction.get_extraction",
					args: { intake },
					callback: (extraction) => {
						frappe.call({
							method: "zero_touch.api.creation.preview_draft",
							args: { intake },
							callback: (preview) => {
								try {
									this.render(detail.message, extraction.message, preview.message);
								} catch (error) {
									show_error(error);
								}
							},
							error: show_error,
						});
					},
					error: show_error,
				});
			},
			error: show_error,
		});
	}

	show_picker() {
		this.page.clear_actions();
		this.page.clear_custom_actions();
		this.page.add_button(__("Upload Document"), () => open_upload(this));
		this.body.html(
			`${ZT_STYLE}<div class="zt-card zt-hero"><h4>${__("Choose a document")}</h4>
			<p class="zt-section-note">${__("Pick a document below, or type its number, for example DI-2026-00007.")}</p>
			<div class="zt-picker-box"></div></div>
			<div class="zt-card"><div class="zt-recent"><p class="zt-section-note">${__("Loading...")}</p></div></div>`
		);
		const field = frappe.ui.form.make_control({
			parent: this.body.find(".zt-picker-box"),
			df: { fieldtype: "Link", options: "Document Intake", label: __("Document"), fieldname: "intake" },
			render_input: true,
		});
		field.$input.on("change", () => {
			const value = field.get_value();
			if (value) {
				frappe.set_route("zt-review-center", { intake: value });
			}
		});
		frappe.call({
			method: "zero_touch.api.monitor.get_intakes",
			args: { page_length: 20 },
			callback: (r) => {
				const rows = (r.message || []).map(
					(row) => `<tr>
						<td><a class="zt-link zt-open" href="#" data-intake="${zt_esc(row.name)}">${zt_esc(row.name)}</a></td>
						<td>${zt_esc(row.original_filename || "")}</td>
						<td>${zt_esc(row.company || "")}</td>
						<td><span class="zt-pill ${ZT_STATUS_CLASS[row.status] || "zt-pill-other"}">${zt_esc(__(row.status))}</span></td>
						<td>${zt_esc(frappe.datetime.str_to_user(row.modified))}</td></tr>`
				);
				this.body.find(".zt-recent").html(
					rows.length
						? `<table class="zt-table"><thead><tr><th>${__("Document")}</th><th>${__("File")}</th><th>${__("Company")}</th><th>${__("Status")}</th><th>${__("Updated")}</th></tr></thead><tbody>${rows.join("")}</tbody></table>`
						: `<p class="zt-section-note">${__("No documents yet. Upload one with Upload Document.")}</p>`
				);
			},
		});
	}

	render(d, e, preview) {
		this.page.set_title(d.original_filename || d.name);
		this.page.clear_actions();
		this.page.clear_custom_actions();
		this.page.add_button(__("Upload Document"), () => open_upload(this));
		if (d.has_original) {
			this.page.add_button(__("Download Original"), () => {
				window.open(`/api/method/zero_touch.api.intake.download_original?intake=${encodeURIComponent(d.name)}`);
			});
		}
		if (e && e.available && e.can_save) {
			this.page.add_button(__("Save Review"), () => this.save_review(), { icon: "save" });
		}
		if (["Pending Review", "Ready to Create"].includes(d.status) && d.has_original) {
			this.page.add_button(__("Re-run Extraction"), () =>
				frappe.call({
					method: "zero_touch.api.intake.reprocess_intake",
					args: { intake: d.name },
					freeze: true,
					freeze_message: __("Reading the document again..."),
					callback: () => this.load(d.name),
				})
			);
		}
		if (d.can_retry) {
			this.page.add_button(__("Retry"), () =>
				frappe.call({ method: "zero_touch.api.intake.retry_intake", args: { intake: d.name }, callback: () => this.load(d.name) })
			);
		}
		if (d.can_cancel) {
			this.page.add_button(__("Cancel Document"), () =>
				frappe.prompt(
					{ fieldname: "reason", fieldtype: "Small Text", label: __("Reason"), reqd: 1 },
					(values) =>
						frappe.call({
							method: "zero_touch.api.intake.cancel_intake",
							args: { intake: d.name, reason: values.reason },
							callback: () => this.load(d.name),
						}),
					__("Cancel Document")
				)
			);
		}
		if (d.created) {
			this.page.add_button(__("Open {0}", [d.created.doctype]), () => frappe.set_route("Form", d.created.doctype, d.created.name));
		}

		const pill = `<span class="zt-pill ${ZT_STATUS_CLASS[d.status] || "zt-pill-other"}">${zt_esc(__(d.status))}</span>`;
		const duplicate = d.duplicate_of ? ` · ${__("Duplicate of")} <a class="zt-link zt-open" href="#" data-intake="${zt_esc(d.duplicate_of)}">${zt_esc(d.duplicate_of)}</a>` : "";
		const hero = `<div class="zt-card zt-hero"><div class="zt-hero-row">
			<div><div class="zt-hero-title">${zt_esc(d.original_filename || d.name)}</div>
			<div class="zt-meta">${zt_esc(d.name)} · ${zt_esc(d.company)} · ${zt_esc(d.document_type || d.document_profile)} → ${zt_esc(d.target_doctype)} · ${zt_esc(d.channel)} · ${zt_esc(frappe.datetime.str_to_user(d.creation))}${duplicate}</div>
			${d.status_reason ? `<div class="zt-meta">${zt_esc(d.status_reason)}</div>` : ""}</div>
			<div>${pill}</div></div></div>`;

		if (!e || !e.available) {
			this.body.html(`${ZT_STYLE}${hero}<div class="zt-card"><p class="zt-section-note">${zt_esc(e ? e.message : "")}</p></div>${this.history_html(d)}`);
			return;
		}

		this.extraction = e;
		this.preview = preview || {};
		// Every label below follows the profile's target doctype: Customer, Supplier,
		// Sales Invoice, ... — never a hard-coded Sales Invoice.
		this.target_doctype = d.target_doctype || "Sales Invoice";
		this.is_invoice = ["Sales Invoice", "Purchase Invoice"].includes(this.target_doctype);
		// A Quotation, Sales Order, ... has a line-item table too; show it whenever the
		// mapping reads one, not only for invoices.
		this.show_lines = this.is_invoice || !!e.has_lines || !!(e.lines && e.lines.length);
		// Only these two statuses can still be edited. Everything after them (Created,
		// Cancelled, Failed, ...) is a read-only record of what was extracted.
		this.editable = ["Pending Review", "Ready to Create"].includes(d.status);
		this.body.html(`${ZT_STYLE}${hero}
			<div id="zt-missing"></div>
			<div class="zt-grid">
				<div class="zt-card zt-preview"><h4>${__("Document")}</h4>${this.previews_html(e)}</div>
				<div class="zt-card"><h4>${__("Fields")}</h4>${
					e.mapping
						? ""
						: `<p class="zt-section-note">${__("This document type has no field mapping rows. Using the standard fields of {0}. Add rows to control the labels.", [this.target_doctype])}</p>`
				}${this.fields_html(e)}</div>
			</div>
			${this.show_lines ? `<div class="zt-card"><h4>${__("Items")}</h4>${this.items_html(e)}</div>` : ""}
			<div id="zt-create"></div>
			<div id="zt-linked"></div>
			${this.history_html(d)}`);

		if (this.editable) {
			this.mount_controls(e);
			this.fill_missing_amounts();
			this.render_missing(e);
		} else {
			this.body.find("#zt-missing").empty();
		}
		this.render_create(this.preview);
		this.render_linked(e, this.preview);
	}

	previews_html(e) {
		const pages = e.pages.filter((p) => p.has_preview);
		if (!pages.length) {
			return `<p class="zt-section-note">${__("No page preview. Scanned pages show a preview after the document is read.")}</p>`;
		}
		return pages
			.map(
				(p) => `<figure><img src="/api/method/zero_touch.api.extraction.get_page_preview?intake=${encodeURIComponent(this.intake)}&page_no=${p.page_no}" alt="${__("Page")} ${p.page_no}">
				<figcaption class="zt-section-note">${__("Page")} ${p.page_no}</figcaption></figure>`
			)
			.join("");
	}

	fields_html(e) {
		const editable = this.editable;
		const rows = e.fields
			.map((f) => {
				const missing = editable && f.required && !f.effective_value;
				const badge = ZT_STATE_BADGE[f.state] || ["zt-badge-muted", f.state || ""];
				let linked;
				if (f.link_doctype && editable) {
					linked = `<div class="zt-link-control" data-key="${zt_esc(f.field_key)}" data-doctype="${zt_esc(f.link_doctype)}" data-value="${zt_esc(f.link_name || "")}"></div>${
						!f.link_name && f.effective_value
							? `<div class="zt-section-note">${__("Read from the document")}: <strong>${zt_esc(f.effective_value)}</strong> — ${__("pick the matching {0} above", [f.link_doctype])}</div>`
							: ""
					}`;
				} else if (f.link_doctype) {
					linked = f.link_name
						? `<a class="zt-link" href="${zt_route(f.link_doctype, f.link_name)}">${zt_esc(f.link_name)}</a>`
						: `<span>${zt_esc(f.effective_value || "")}</span>`;
				} else if (editable) {
					linked = `<input class="form-control input-sm zt-field" data-key="${zt_esc(f.field_key)}" value="${zt_esc(f.reviewed_value ?? f.value ?? "")}">`;
				} else {
					linked = `<span>${zt_esc(f.reviewed_value ?? f.value ?? "")}</span>`;
				}
				const linkBadge = f.link_doctype
					? `<span class="zt-badge ${f.link_status === "matched" || f.link_status === "created" ? "zt-badge-ok" : "zt-badge-warn"}">${zt_esc(f.link_status ? __(f.link_status) : __("not linked"))}</span>`
					: "";
				const searched = missing && f.searched_labels && f.searched_labels.length
					? `<div class="zt-section-note">${__("Searched for: {0}", [f.searched_labels.join(" / ")])}</div>`
					: "";
				return `<tr class="${missing ? "zt-row-missing" : f.link_name ? "zt-row-linked" : ""}" data-field="${zt_esc(f.field_key)}">
					<td><strong>${zt_esc(f.label || f.field_key)}</strong>${missing ? ` <span class="zt-badge zt-badge-bad">${__("Required")}</span>` : ""}${searched}</td>
					<td style="min-width:220px">${linked}</td>
					<td><span class="zt-badge ${badge[0]}">${zt_esc(__(badge[1]))}</span> ${linkBadge}</td>
					<td>${f.confidence !== null && f.confidence !== undefined ? zt_esc(f.confidence) + "%" : ""}</td>
					<td>${f.page_no || ""}</td>
					<td class="zt-source" title="${zt_esc(f.source_text || "")}">${zt_esc(f.source_text || "")}</td>
				</tr>`;
			})
			.join("");
		const hasPostingDate = e.fields.some((f) => f.field_key === "posting_date");
		const postingRow = !editable || !this.is_invoice || hasPostingDate
			? ""
			: `<tr class="zt-row-missing" data-field="posting_date"><td><strong>${__("Posting Date")}</strong> <span class="zt-badge zt-badge-bad">${__("Add")}</span></td>
				<td><input type="date" class="form-control input-sm zt-field" data-key="posting_date" value=""></td>
				<td colspan="4" class="zt-source">${__("The mapping does not provide a posting date. Enter it here.")}</td></tr>`;
		const automaticRows = (e.automatic_fields || [])
			.map((f) => `<tr class="zt-row-auto" data-field="${zt_esc(f.field_key)}">
				<td><strong>${zt_esc(f.label || f.field_key)}</strong></td>
				<td>${f.value !== "" && f.value !== null && f.value !== undefined ? zt_esc(f.value) : `<span class="zt-section-note">${__("Set by ERPNext")}</span>`}</td>
				<td><span class="zt-badge zt-badge-muted">${__("ERPNext fills")}</span></td>
				<td></td>
				<td></td>
				<td class="zt-source">${__("Filled by ERPNext on creation. To read it from the document, change its Source in the mapping.")}</td>
			</tr>`)
			.join("");
		return `<table class="zt-table"><thead><tr><th>${__("Field")}</th><th>${__("Value")}</th><th>${__("State")}</th><th>${__("Confidence")}</th><th>${__("Page")}</th><th>${__("Source text")}</th></tr></thead>
			<tbody>${rows}${automaticRows}${postingRow}</tbody></table>`;
	}

	items_html(e) {
		const editable = this.editable;
		if (!editable) {
			const rows = (e.lines || [])
				.map(
					(l) => `<tr class="${l.item_code ? "zt-row-linked" : ""}">
						<td>${zt_esc(l.line_no)}</td>
						<td>${zt_esc(l.item_name || "")}</td>
						<td>${zt_esc(l.qty || "")}</td>
						<td>${zt_esc(l.rate || "")}</td>
						<td>${zt_esc(l.amount || "")}</td>
						<td>${l.item_code ? `<a class="zt-link" href="${zt_route("Item", l.item_code)}">${zt_esc(l.item_code)}</a>` : ""}</td>
						<td>${l.page_no || ""}</td>
					</tr>`
				)
				.join("");
			return `<table class="zt-table zt-lines"><thead><tr><th>#</th><th>${__("Item")}</th><th>${__("Quantity")}</th><th>${__("Rate")}</th><th>${__("Amount")}</th><th>${__("ERPNext Item")}</th><th>${__("Page")}</th></tr></thead>
				<tbody>${rows}</tbody></table>`;
		}
		const rows = (e.lines || [])
			.map(
				(l) => `<tr data-row="${zt_esc(l.row_name)}" class="${l.item_code ? "zt-row-linked" : "zt-row-missing"}">
					<td>${zt_esc(l.line_no)}</td>
					<td><input class="form-control input-sm zt-line" data-field="item_name" value="${zt_esc(l.item_name || "")}"></td>
					<td><input class="form-control input-sm zt-line" data-field="qty" value="${zt_esc(l.qty || "")}"></td>
					<td><input class="form-control input-sm zt-line" data-field="rate" value="${zt_esc(l.rate || "")}"></td>
					<td><input class="form-control input-sm zt-line" data-field="amount" value="${zt_esc(l.amount || "")}"></td>
					<td><div class="zt-item-control" data-item="${zt_esc(l.item_code || "")}"></div></td>
					<td>${l.page_no || ""}</td>
					<td><button class="btn btn-default btn-xs zt-remove-line">${__("Remove")}</button></td>
				</tr>`
			)
			.join("");
		const note = e.lines && e.lines.length ? "" : `<p class="zt-section-note">${__("No item rows yet. Add them with Add Item.")}</p>`;
		return `${note}<table class="zt-table zt-lines"><thead><tr><th>#</th><th>${__("Item (as read)")}</th><th>${__("Quantity")}</th><th>${__("Rate")}</th><th>${__("Amount")}</th><th>${__("ERPNext Item")}</th><th>${__("Page")}</th><th></th></tr></thead>
			<tbody>${rows}</tbody></table>
			<p><button class="btn btn-default btn-sm zt-add-line">${__("Add Item")}</button></p>`;
	}

	mount_controls(e) {
		if (!this.editable) {
			return;
		}
		const body = this.body;
		body.find(".zt-link-control").each((_, el) => {
			const box = $(el);
			const doctype = box.data("doctype");
			const key = box.data("key");
			const control = frappe.ui.form.make_control({
				parent: box,
				df: { fieldtype: "Link", options: doctype, label: doctype, fieldname: `link_${key}` },
				render_input: true,
			});
			control.set_value(box.data("value") || "");
			box.data("control", control);
			control.$input.on("change", () => {
				const record = control.get_value();
				if (record) {
					frappe.call({
						method: "zero_touch.api.extraction.set_link",
						args: { intake: this.intake, field_key: key, record },
						callback: () => this.load(this.intake),
					});
				}
			});
		});
		body.find(".zt-item-control").each((_, el) => {
			const box = $(el);
			const control = frappe.ui.form.make_control({
				parent: box,
				df: { fieldtype: "Link", options: "Item", label: __("Item"), fieldname: "item_code" },
				render_input: true,
			});
			control.set_value(box.data("item") || "");
			box.data("control", control);
		});
	}

	render_missing(e) {
		const missing = [];
		e.fields.forEach((f) => {
			if (f.required && !f.effective_value) {
				missing.push(`${f.label || f.field_key}: ${__("missing")}`);
			}
			if (f.link_doctype && f.effective_value && !["matched", "created"].includes(f.link_status)) {
				missing.push(`${f.label || f.field_key}: ${__("no {0} matches \"{1}\" yet — pick one in the field", [f.link_doctype, f.effective_value])}`);
			}
		});
		if (this.is_invoice && !e.fields.some((f) => f.field_key === "posting_date")) {
			missing.push(`${__("Posting Date")}: ${__("enter the date below")}`);
		}
		if (this.show_lines && (!e.lines || !e.lines.length)) {
			missing.push(__("Items: add at least one item row"));
		}
		// A not-linked field already has its own line above; do not repeat the same
		// message from the create preview.
		const linkedLabels = e.fields
			.filter((f) => f.link_doctype && f.effective_value && !["matched", "created"].includes(f.link_status))
			.map((f) => `${f.label || f.field_key}:`);
		(this.preview.blockers || [])
			.filter((b) => !b.startsWith("Posting date") && !linkedLabels.some((label) => b.startsWith(label)))
			.forEach((b) => missing.push(b));
		const unique = [...new Set(missing)];
		if (!unique.length) {
			this.body.find("#zt-missing").html(
				`<div class="zt-card" style="background:#f0fdf4;border-color:#bbf7d0"><span class="zt-ready">${__("Everything needed is filled in.")}</span></div>`
			);
			return;
		}
		this.body.find("#zt-missing").html(
			`<div class="zt-card zt-missing"><h4>${__("Still missing")}</h4><ul>${unique.map((m) => `<li>${zt_esc(m)}</li>`).join("")}</ul>
			<p class="zt-section-note">${__("Fill these in, click Save Review, then Create {0}.", [this.target_doctype])}</p></div>`
		);
	}

	render_create(preview) {
		const box = this.body.find("#zt-create");
		const doctype = this.target_doctype || __("Sales Invoice");
		if (preview && preview.created) {
			const done = this.is_invoice ? __("Draft created") : __("{0} created", [doctype]);
			box.html(`<div class="zt-card" style="background:#eef2ff;border-color:#c7d2fe"><h4>${zt_esc(doctype)}</h4>
				<p>${zt_esc(done)}: <a class="zt-link" href="${zt_route(preview.created.doctype, preview.created.name)}">${zt_esc(preview.created.name)}</a></p></div>`);
			return;
		}
		if (!this.editable) {
			box.empty();
			return;
		}
		const needsItems =
			this.is_invoice &&
			(preview && preview.blockers ? preview.blockers : []).some((b) =>
				String(b).includes("does not exist in ERPNext")
			);
		const note = this.is_invoice
			? __("A draft is created in ERPNext. It is never submitted.")
			: __("A new {0} is created in ERPNext.", [doctype]);
		box.html(`<div class="zt-card"><h4>${__("Create {0}", [doctype])}</h4>
			<p class="zt-section-note">${zt_esc(note)}</p>
			<button class="btn btn-primary btn-sm zt-create-invoice">${__("Create {0}", [doctype])}</button>
			${
				needsItems
					? `<button class="btn btn-default btn-sm zt-create-items" style="margin-left:8px">${__("Create missing items")}</button>
						<p class="zt-section-note" style="margin-top:8px">${__("Creates a service item for each line whose name is not in ERPNext yet.")}</p>`
					: ""
			}
			</div>`);
		box.find(".zt-create-invoice").on("click", () =>
			frappe.confirm(
				this.is_invoice
					? __("Save the review and create a draft Sales Invoice?")
					: __("Create a {0} from the reviewed values?", [doctype]),
				() => this.save_review(true)
			)
		);
		box.find(".zt-create-items").on("click", () =>
			frappe.confirm(__("Create the missing items in ERPNext as service items?"), () => this.create_missing_items())
		);
	}

	create_missing_items() {
		frappe.call({
			method: "zero_touch.api.creation.create_missing_items",
			args: { intake: this.intake },
			freeze: true,
			callback: (r) => {
				const result = r.message || {};
				frappe.show_alert({
					message: result.created && result.created.length
						? __("Items created: {0}", [result.created.join(", ")])
						: __("Items linked to existing records: {0}", [(result.matched || []).join(", ") || "-"]),
					indicator: "green",
				});
				this.load(this.intake);
			},
		});
	}

	render_linked(e, preview) {
		const rows = [];
		e.fields.forEach((f) => {
			if (f.link_doctype && f.link_name) {
				rows.push(`<tr class="zt-row-linked"><td>${zt_esc(f.label || f.field_key)}</td><td>${zt_esc(f.link_doctype)}</td>
					<td>${zt_esc(f.link_name)}</td><td><a class="zt-link" href="${zt_route(f.link_doctype, f.link_name)}">${__("Open")}</a></td></tr>`);
			}
		});
		(e.lines || []).forEach((l) => {
			if (l.item_code) {
				rows.push(`<tr class="zt-row-linked"><td>${__("Item row")} ${zt_esc(l.line_no)}</td><td>Item</td>
					<td>${zt_esc(l.item_code)}</td><td><a class="zt-link" href="${zt_route("Item", l.item_code)}">${__("Open")}</a></td></tr>`);
			}
		});
		if (preview && preview.created) {
			rows.push(`<tr class="zt-row-linked"><td>${__("Draft invoice")}</td><td>${zt_esc(preview.created.doctype)}</td>
				<td>${zt_esc(preview.created.name)}</td><td><a class="zt-link" href="${zt_route(preview.created.doctype, preview.created.name)}">${__("Open")}</a></td></tr>`);
		}
		this.body.find("#zt-linked").html(
			rows.length
				? `<div class="zt-card"><h4>${__("Linked records")}</h4><table class="zt-table"><thead><tr><th>${__("Field")}</th><th>${__("DocType")}</th><th>${__("Record")}</th><th></th></tr></thead><tbody>${rows.join("")}</tbody></table></div>`
				: ""
		);
	}

	history_html(d) {
		const logs = (d.logs || [])
			.map((l) => `<li><span class="zt-section-note">${zt_esc(frappe.datetime.str_to_user(l.creation))}</span> <strong>${zt_esc(l.event_type)}</strong>
				${l.from_status || l.to_status ? ` ${zt_esc(l.from_status || "")} → ${zt_esc(l.to_status || "")}` : ""}
				${l.message ? `<div class="zt-section-note">${zt_esc(l.message)}</div>` : ""}</li>`)
			.join("");
		return `<div class="zt-card"><h4>${__("History")}</h4><ol class="zt-history">${logs || `<li class="zt-section-note">${__("No history yet.")}</li>`}</ol></div>`;
	}

	collect() {
		const values = {};
		this.body.find(".zt-field").each((_, el) => {
			values[$(el).data("key")] = $(el).val();
		});
		this.body.find(".zt-link-control").each((_, el) => {
			const control = $(el).data("control");
			const chosen = control ? control.get_value() || "" : "";
			if (chosen) {
				values[$(el).data("key")] = chosen;
			}
		});
		const lines = [];
		this.body.find(".zt-lines tbody tr").each((_, tr) => {
			const row = { row_name: $(tr).data("row") || null };
			$(tr).find(".zt-line").each((_i, el) => {
				row[$(el).data("field")] = $(el).val();
			});
			const itemBox = $(tr).find(".zt-item-control");
			row.item_code = itemBox.data("control") ? itemBox.data("control").get_value() || "" : "";
			lines.push(row);
		});
		return { values, lines };
	}

	save_review(thenCreate) {
		const { values, lines } = this.collect();
		frappe.call({
			method: "zero_touch.api.extraction.save_review",
			args: { intake: this.intake, values: JSON.stringify(values), lines: JSON.stringify(lines) },
			freeze: true,
			callback: (r) => {
				const result = r.message || {};
				frappe.show_alert({
					message: result.changes ? __("Review saved. {0} change(s).", [result.changes]) : __("Review saved."),
					indicator: "green",
				});
				if (thenCreate) {
					this.create_invoice();
				} else {
					this.load(this.intake);
				}
			},
		});
	}

	create_invoice() {
		frappe.call({
			method: "zero_touch.api.creation.create_draft",
			args: { intake: this.intake },
			freeze: true,
			callback: (r) => {
				const result = r.message || {};
				if (result.status === "Created") {
					frappe.show_alert({
						message: this.is_invoice
							? __("Draft created: {0}", [result.name])
							: __("{0} created: {1}", [this.target_doctype, result.name]),
						indicator: "green",
					});
				} else {
					frappe.msgprint({
						title: __("Not created yet"),
						message: (result.blockers || []).map((b) => zt_esc(b)).join("<br>") || __("See the status reason."),
						indicator: "orange",
					});
				}
				this.load(this.intake);
			},
		});
	}
}
