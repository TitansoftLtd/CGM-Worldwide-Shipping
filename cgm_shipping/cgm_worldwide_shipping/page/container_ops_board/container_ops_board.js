frappe.pages["container-ops-board"].on_page_load = function (wrapper) {
	frappe.require("/assets/cgm_shipping/css/container_ops_board.css", () => {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Container Ops Board"),
			single_column: true,
		});

		page.hide_form();
		page.main.find(".page-form.row").remove();

		page.main.addClass("cgm-ops-board");
		page.main.append(`
			<div class="cgm-ops-hero">
				<h1>${__("Container Operations Board")}</h1>
				<p>${__("Live transport view — gate movements, warehouse, returns & demurrage")}</p>
			</div>
			<div class="cgm-ops-body">
				<div class="cgm-ops-filters"></div>
				<div class="cgm-ops-kpis"></div>
				<div class="cgm-ops-filter-hint" style="display:none"></div>
				<div class="cgm-ops-tabs">
					<button type="button" class="btn btn-sm btn-default active" data-tab="board">${__(
						"All Containers"
					)}</button>
					<button type="button" class="btn btn-sm btn-default" data-tab="returns">${__(
						"Empty Return Tracker"
					)}</button>
				</div>
				<div class="cgm-ops-table-wrap"><div class="cgm-ops-empty">${__("Loading…")}</div></div>
			</div>
		`);

		setup_cgm_ops_breadcrumbs();

		const filters = {};
		const filter_controls = {};
		let kpiFilter = null;
		let activeTab = "board";

		const KPI_META = {
			total_active: { label: __("Total Active"), icon: "📦", tone: "slate", alert: false },
			overdue_returns: { label: __("Overdue Returns"), icon: "🚨", tone: "red", alert: true },
			in_demurrage: { label: __("In Demurrage"), icon: "⏱", tone: "red", alert: true },
			free_days_expiring: {
				label: __("Free Days Expiring (2d)"),
				icon: "⚠️",
				tone: "amber",
				alert: true,
			},
			returned_this_month: {
				label: __("Returned This Month"),
				icon: "✅",
				tone: "green",
				alert: false,
			},
		};

		const filter_fields = [
			{
				fieldname: "customer",
				label: __("Customer"),
				fieldtype: "Link",
				options: "Customer",
			},
			{
				fieldname: "project",
				label: __("Project"),
				fieldtype: "Link",
				options: "Project",
			},
			{
				fieldname: "clearance_station",
				label: __("Clearance Station"),
				fieldtype: "Link",
				options: "Clearance Station",
			},
			{
				fieldname: "container_mode",
				label: __("Container Mode"),
				fieldtype: "Select",
				options:
					"\nMombasa Port\nICD Nairobi\nTransit Kenya→Border\nTransit Border→Kenya\nExport",
			},
			{
				fieldname: "status",
				label: __("Status"),
				fieldtype: "Select",
				options:
					"\nPending Arrival\nVessel Berthed\nDischarged / At Port\nReleased / In Transit\nAt Warehouse\nCargo Offloaded\nEmpty Returned\nReturn Overdue\nInterchange Received",
			},
		];

		const $filter_parent = page.main.find(".cgm-ops-filters");
		filter_fields.forEach((df) => {
			const control = frappe.ui.form.make_control({
				df: {
					...df,
					placeholder: df.label,
					input_class: "input-xs",
				},
				parent: $filter_parent[0],
				only_input: true,
			});
			control.refresh();
			if (control.$input) {
				control.$input.attr("placeholder", df.label);
				control.$input.on("change", () => {
					filters[df.fieldname] = control.get_value();
					refresh();
				});
			}
			$(control.wrapper).addClass("cgm-ops-filter-field");
			filter_controls[df.fieldname] = control;
		});

		function fmtDate(val) {
			return val ? frappe.datetime.str_to_user(val) : "—";
		}

		function statusPill(row) {
			const pill = row.status_pill || "muted";
			const label = row.status || "";
			return `<span class="cgm-ops-pill ${frappe.utils.escape_html(pill)}"><span class="dot"></span>${frappe.utils.escape_html(label)}</span>`;
		}

		function trackerLink(row) {
			return `<a href="/app/container-tracker/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
				row.container_number || ""
			)}</a>`;
		}

		function projectLine(row) {
			const parts = [row.project_ref, row.batch_no, row.bl_number].filter(Boolean);
			return frappe.utils.escape_html(parts.join(" · ") || row.project || "");
		}

		function updateFilterHint() {
			const $hint = page.main.find(".cgm-ops-filter-hint");
			if (!kpiFilter || !KPI_META[kpiFilter]) {
				$hint.hide();
				return;
			}
			$hint
				.show()
				.html(
					`<span class="badge">${frappe.utils.escape_html(KPI_META[kpiFilter].label)}</span>
					<span>${__("Filtered view")}</span>
					<span class="clear-filter">${__("Clear filter")}</span>`
				);
		}

		function refresh() {
			const method =
				activeTab === "returns"
					? "cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board.get_container_return_tracker"
					: "cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board.get_container_ops_board";

			const args = { ...filters };
			if (kpiFilter) {
				args.kpi_filter = kpiFilter;
			}

			frappe.call({
				method,
				args: { filters: args },
				freeze: true,
				callback(r) {
					if (r.exc) {
					 return;
					}
					updateFilterHint();
					if (activeTab === "returns") {
						renderReturns(r.message || {});
					} else {
						renderBoard(r.message || {});
					}
				},
			});
		}

		function renderKpis(kpis) {
			kpis = kpis || {};
			const cards = [
				"total_active",
				"overdue_returns",
				"in_demurrage",
				"free_days_expiring",
				"returned_this_month",
			];
			page.main.find(".cgm-ops-kpis").html(
				cards
					.map((key) => {
						const meta = KPI_META[key];
						const active = kpiFilter === key ? " is-active" : "";
						const alertCls = meta.alert ? " is-alert" : "";
						return `<button type="button" class="cgm-ops-kpi${alertCls}${active}" data-kpi="${key}">
						<span class="cgm-ops-kpi-icon ${meta.tone}">${meta.icon}</span>
						<div>
							<div class="value">${frappe.utils.escape_html(String(kpis[key] || 0))}</div>
							<div class="label">${meta.label}</div>
						</div>
					</button>`;
					})
					.join("")
			);
		}

		function transportTableHeaders() {
			return `
				<th class="cgm-ops-sticky-col">${__("Container")}</th>
				<th>${__("Batch / B/L")}</th>
				<th>${__("Gate In MBA")}</th>
				<th>${__("Gate Out MBA")}</th>
				<th>${__("Truck No")}</th>
				<th>${__("Contact")}</th>
				<th>${__("Gate In Warehouse")}</th>
				<th>${__("Offloaded")}</th>
				<th>${__("Status")}</th>
				<th>${__("Expected Return")}</th>
				<th>${__("Actual Return")}</th>
				<th>${__("Transporter")}</th>
				<th>${__("Dem.")}</th>
				<th>${__("Det.")}</th>
			`;
		}

		function transportTableRow(row, extraCol = "") {
			const ret = row.effective_return_date || row.actual_empty_return || row.interchange_date;
			const alert = row.alert_status
				? `<div class="cgm-ops-alert">${frappe.utils.escape_html(row.alert_status)}</div>`
				: "";
			return `<tr class="${frappe.utils.escape_html(row.traffic_css || "")}">
				<td class="cgm-ops-sticky-col">${trackerLink(row)}${alert}</td>
				<td>${projectLine(row)}</td>
				<td>${fmtDate(row.gate_in_port)}</td>
				<td>${fmtDate(row.gate_out_date_port)}</td>
				<td>${frappe.utils.escape_html(row.truck_number || "—")}</td>
				<td>${frappe.utils.escape_html(row.contact_display || "—")}</td>
				<td>${fmtDate(row.gate_in_date_warehouse)}<div class="text-muted small">${frappe.utils.escape_html(row.clearance_station || "")}</div></td>
				<td>${fmtDate(row.offloading_date)}</td>
				<td>${statusPill(row)}</td>
				<td>${fmtDate(row.expected_empty_return)}</td>
				<td>${fmtDate(ret)}</td>
				<td>${frappe.utils.escape_html(row.transporter_name || "—")}</td>
				<td>${row.demurrage_days || 0}</td>
				<td>${row.detention_days || 0}</td>
				${extraCol}
			</tr>`;
		}

		function renderBoard(data) {
			renderKpis(data.kpis);
			const rows = data.rows || [];
			if (!rows.length) {
				page.main.find(".cgm-ops-table-wrap").html(`
					<div class="cgm-ops-empty">
						<div class="cgm-ops-empty-icon">📭</div>
						${__("No containers match these filters.")}
					</div>`);
				return;
			}
			page.main.find(".cgm-ops-table-wrap").html(`
				<table class="cgm-ops-table">
					<thead><tr>${transportTableHeaders()}</tr></thead>
					<tbody>${rows.map((row) => transportTableRow(row)).join("")}</tbody>
				</table>`);
		}

		function renderReturns(data) {
			renderKpis(data.kpis);
			const rows = data.rows || [];
			if (!rows.length) {
				page.main.find(".cgm-ops-table-wrap").html(`
					<div class="cgm-ops-empty">
						<div class="cgm-ops-empty-icon">📦</div>
						${__("No containers in the return pipeline. Containers appear here after gate out from port.")}
					</div>`);
				return;
			}
			page.main.find(".cgm-ops-table-wrap").html(`
				<table class="cgm-ops-table">
					<thead><tr>
						${transportTableHeaders()}
						<th>${__("Days Out")}</th>
					</tr></thead>
					<tbody>${rows
						.map((row) => transportTableRow(row, `<td>${row.days_outstanding || 0}</td>`))
						.join("")}</tbody>
				</table>`);
		}

		page.main.find(".cgm-ops-kpis").on("click", ".cgm-ops-kpi", function () {
			const key = $(this).data("kpi");
			kpiFilter = kpiFilter === key ? null : key;
			refresh();
		});

		page.main.find(".cgm-ops-filter-hint").on("click", ".clear-filter", () => {
			kpiFilter = null;
			refresh();
		});

		page.main.find(".cgm-ops-tabs").on("click", "button", function () {
			activeTab = $(this).data("tab");
			page.main.find(".cgm-ops-tabs button").removeClass("active");
			$(this).addClass("active");
			refresh();
		});

		wrapper.on_page_show = function () {
			setup_cgm_ops_breadcrumbs();
			page.hide_form();
			page.main.find(".page-form.row").remove();
		};

		setTimeout(setup_cgm_ops_breadcrumbs, 0);
		refresh();
	});
};

function setup_cgm_ops_breadcrumbs() {
	frappe.breadcrumbs.clear();
	const workspace_label = frappe.app.sidebar?.sidebar_title || __("CGM Shipping");
	let workspace_route = "/desk/cgm-shipping";

	if (frappe.app.sidebar?.sidebar_title) {
		const icon = frappe.utils.get_desktop_icon_by_label(frappe.app.sidebar.sidebar_title);
		const url = frappe.utils.get_route_for_icon(icon);
		if (url) {
			workspace_route = url;
		}
	}

	frappe.breadcrumbs.append_breadcrumb_element(
		workspace_route,
		workspace_label,
		"worksapce-breadcrumb"
	);
	frappe.breadcrumbs.append_breadcrumb_element(
		"/desk/container-ops-board",
		__("Container Ops Board"),
		"title-text"
	);
	frappe.breadcrumbs.toggle(true);
}
