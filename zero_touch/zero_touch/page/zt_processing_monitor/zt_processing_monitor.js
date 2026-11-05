frappe.pages["zt-processing-monitor"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Processing Monitor"),
		single_column: true,
	});
	const monitor = new ProcessingMonitor(page);
	$(wrapper).bind("show", () => monitor.refresh());
};

class ProcessingMonitor {
	constructor(page) {
		this.page = page;
		this.status_filter = null;
		this.company_filter = null;

		this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");
		this.company_field = this.page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			change: () => {
				this.company_filter = this.company_field.get_value() || null;
				this.refresh();
			},
		});
		this.status_field = this.page.add_field({
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Received", "Queued", "Processing", "Pending Review", "Ready to Create", "Created", "Failed", "Rejected", "Duplicate", "Cancelled"].join("\n"),
			change: () => {
				this.status_filter = this.status_field.get_value() || null;
				this.refresh();
			},
		});

		this.summary = $('<div class="zt-summary"></div>').appendTo(this.page.main);
		this.table = $('<div class="zt-table"></div>').appendTo(this.page.main);
		this.table.on("click", ".zt-open", (event) => {
			event.preventDefault();
			frappe.set_route("zt-review-center", { intake: $(event.currentTarget).data("intake") });
		});
	}

	refresh() {
		frappe.call({
			method: "zero_touch.api.monitor.get_status_counts",
			args: { company: this.company_filter },
			callback: (r) => this.render_summary(r.message),
		});
		frappe.call({
			method: "zero_touch.api.monitor.get_intakes",
			args: { status: this.status_filter, company: this.company_filter, page_length: 100 },
			callback: (r) => this.render_table(r.message || []),
		});
	}

	render_summary(data) {
		const cards = Object.entries(data.counts)
			.filter(([, count]) => count > 0)
			.map(
				([status, count]) =>
					`<div class="zt-card" data-status="${frappe.utils.escape_html(status)}">
						<div class="zt-card-count">${count}</div>
						<div class="zt-card-label">${frappe.utils.escape_html(__(status))}</div>
					</div>`
			)
			.join("");
		this.summary.html(`<div class="zt-cards">${cards}</div>`);
		this.summary.find(".zt-card").on("click", (e) => {
			const status = $(e.currentTarget).data("status");
			this.status_field.set_value(status);
			this.status_filter = status;
			this.refresh();
		});
	}

	render_table(rows) {
		if (!rows.length) {
			this.table.html(`<p class="text-muted">${__("No documents match these filters.")}</p>`);
			return;
		}
		const esc = frappe.utils.escape_html;
		const body = rows
			.map((row) => {
				const retry = row.next_retry_at
					? `${esc(frappe.datetime.str_to_user(row.next_retry_at))}`
					: "";
				return `<tr>
					<td><a href="#" class="zt-open" data-intake="${esc(row.name)}">${esc(row.name)}</a></td>
					<td>${esc(row.original_filename || "")}</td>
					<td>${esc(row.company || "")}</td>
					<td>${esc(__(row.status))}</td>
					<td>${esc(row.stage || "")}</td>
					<td>${esc(row.status_reason || "")}</td>
					<td>${row.attempt_count || 0}</td>
					<td>${retry}</td>
					<td>${esc(frappe.datetime.str_to_user(row.modified))}</td>
				</tr>`;
			})
			.join("");
		this.table.html(`
			<table class="table table-bordered zt-monitor-table">
				<thead><tr>
					<th>${__("Document")}</th><th>${__("File")}</th><th>${__("Company")}</th>
					<th>${__("Status")}</th><th>${__("Stage")}</th><th>${__("Reason")}</th>
					<th>${__("Attempts")}</th><th>${__("Next Retry")}</th><th>${__("Updated")}</th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table>`);
	}
}
