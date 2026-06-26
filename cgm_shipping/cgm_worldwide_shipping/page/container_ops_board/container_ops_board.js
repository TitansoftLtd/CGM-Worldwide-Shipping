frappe.pages["container-ops-board"].on_page_load = function (wrapper) {
	frappe.require("/assets/cgm_shipping/css/container_ops_board.css", () => {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Shipment Tracker"),
			single_column: true,
		});

		page.hide_form();
		page.main.find(".page-form.row").remove();

		page.main.addClass("cgm-ops-board");
		page.main.append(`
			<div class="cgm-ops-hero">
				<h1>${__("Shipment Tracker")}</h1>
				<p>${__("Shipment-level tracking with drill-down to container status and the existing container operations board")}</p>
			</div>
			<div class="cgm-ops-body">
				<div class="cgm-ops-filters"></div>
				<div class="cgm-ops-kpis"></div>
				<div class="cgm-ops-filter-hint" style="display:none"></div>
				<div class="cgm-ops-tabs">
					<button type="button" class="btn btn-sm btn-default active" data-tab="shipments">${__(
						"Shipments"
					)}</button>
					<button type="button" class="btn btn-sm btn-default" data-tab="board">${__(
						"All Containers"
					)}</button>
					<button type="button" class="btn btn-sm btn-default" data-tab="returns">${__(
						"Empty Return Tracker"
					)}</button>
				</div>
				<div class="cgm-ops-shipment-detail"></div>
				<div class="cgm-ops-table-wrap"><div class="cgm-ops-empty">${__("Loading…")}</div></div>
			</div>
		`);

		setup_cgm_ops_breadcrumbs();

		const filters = {};
		const filter_controls = {};
		let kpiFilter = null;
		let activeTab = "shipments";
		let shipmentRows = [];
		let selectedProject = null;

		const CONTAINER_KPI_META = {
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

		const SHIPMENT_KPI_META = {
			active_shipments: { label: __("Active Shipments"), icon: "📦", tone: "slate", alert: false },
			completed_shipments: {
				label: __("Completed Shipments"),
				icon: "✅",
				tone: "green",
				alert: false,
			},
			total_shipments: { label: __("All Shipments"), icon: "📋", tone: "slate", alert: false },
			overdue_returns: { label: __("Overdue Returns"), icon: "🚨", tone: "red", alert: true },
			in_demurrage: { label: __("In Demurrage"), icon: "⏱", tone: "red", alert: true },
		};

		const CONTAINER_KPI_CARDS = [
			"total_active",
			"overdue_returns",
			"in_demurrage",
			"free_days_expiring",
			"returned_this_month",
		];
		const SHIPMENT_KPI_CARDS = [
			"active_shipments",
			"completed_shipments",
			"total_shipments",
			"overdue_returns",
			"in_demurrage",
		];

		const CONTAINER_STATUS_OPTIONS =
			"\nPending Arrival\nVessel Berthed\nDischarged / At Port\nReleased / In Transit\nAt Warehouse\nCargo Offloaded\nEmpty Returned\nReturn Overdue\nInterchange Received";

		function shipmentStatusOptions() {
			const df = frappe.meta.get_docfield("Project", "custom_shipment_status");
			return df && df.options ? `\n${df.options}` : "\nCompleted\nDraft";
		}

		const filter_fields = [
			{
				fieldname: "customer",
				label: __("Customer"),
				fieldtype: "Link",
				options: "Customer",
			},
			{
				fieldname: "shipping_line",
				label: __("Shipping Line"),
				fieldtype: "Link",
				options: "Supplier",
			},
			{
				fieldname: "clearance_station",
				label: __("Clearance Station"),
				fieldtype: "Link",
				options: "Clearance Station",
			},
			{
				fieldname: "date_field",
				label: __("Date Field"),
				fieldtype: "Select",
				options: "\nETA\nATA",
			},
			{
				fieldname: "date_from",
				label: __("Date From"),
				fieldtype: "Date",
			},
			{
				fieldname: "date_to",
				label: __("Date To"),
				fieldtype: "Date",
			},
			{
				fieldname: "status",
				label: __("Status"),
				fieldtype: "Select",
				options: shipmentStatusOptions(),
			},
		];

		function syncStatusFilterForTab() {
			const control = filter_controls.status;
			if (!control) {
				return;
			}
			const options =
				activeTab === "shipments" ? shipmentStatusOptions() : CONTAINER_STATUS_OPTIONS;
			control.df.options = options;
			control.refresh();
			if (control.$input) {
				control.$input.attr("placeholder", __("Status"));
			}
		}

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
			const label = row.operational_status || row.status || "";
			return `<span class="cgm-ops-pill ${frappe.utils.escape_html(pill)}"><span class="dot"></span>${frappe.utils.escape_html(label)}</span>`;
		}

		function containerStatusCell(value) {
			return frappe.utils.escape_html(value || "—");
		}

		function shipmentOperationalStatusCell(row) {
			const label = row.operational_status || row.shipment_status || "";
			if (!label) {
				return "—";
			}
			return `<span class="cgm-ops-pill muted"><span class="dot"></span>${frappe.utils.escape_html(label)}</span>`;
		}

		function currentKpiMeta() {
			return activeTab === "shipments" ? SHIPMENT_KPI_META : CONTAINER_KPI_META;
		}

		function trackerLink(row) {
			return `<a href="/app/container-tracker/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
				row.container_number || ""
			)}</a>`;
		}

		function projectLink(row) {
			const docname = row.project || row.name;
			const label = row.project_ref || row.project || row.name || "";
			if (!docname) {
				return frappe.utils.escape_html(label || "—");
			}
			return `<a href="/app/project/${encodeURIComponent(docname)}">${frappe.utils.escape_html(
				label || docname
			)}</a>`;
		}

		function projectCell(row) {
			return projectLink(row);
		}

		function batchCell(row) {
			return frappe.utils.escape_html(row.batch_no || "—");
		}

		function blCell(row) {
			return frappe.utils.escape_html(row.bl_number || "—");
		}

		function updateFilterHint() {
			const $hint = page.main.find(".cgm-ops-filter-hint");
			const meta = currentKpiMeta()[kpiFilter];
			if (!kpiFilter || !meta) {
				$hint.hide();
				return;
			}
			$hint
				.show()
				.html(
					`<span class="badge">${frappe.utils.escape_html(meta.label)}</span>
					<span>${__("Filtered view")}</span>
					<span class="clear-filter">${__("Clear filter")}</span>`
				);
		}

		function refresh() {
			let method = "cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board.get_container_ops_board";
			if (activeTab === "returns") {
				method = "cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board.get_container_return_tracker";
			} else if (activeTab === "shipments") {
				method = "cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board.get_shipment_tracker";
			}

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
					if (activeTab !== "shipments") {
						exitShipmentDetailMode();
					}
					if (activeTab === "returns") {
						renderReturns(r.message || {});
					} else if (activeTab === "shipments") {
						renderShipments(r.message || {});
					} else {
						renderBoard(r.message || {});
					}
				},
			});
		}

		function renderKpis(kpis) {
			kpis = kpis || {};
			const cards = activeTab === "shipments" ? SHIPMENT_KPI_CARDS : CONTAINER_KPI_CARDS;
			const metaSource = currentKpiMeta();
			page.main.find(".cgm-ops-kpis").html(
				cards
					.map((key) => {
						const meta = metaSource[key];
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
				<th>${__("Project")}</th>
				<th>${__("Batch")}</th>
				<th>${__("B/L")}</th>
				<th>${__("Gate In MBA")}</th>
				<th>${__("Gate Out MBA")}</th>
				<th>${__("Truck No")}</th>
				<th>${__("Contact")}</th>
				<th>${__("Gate In Warehouse")}</th>
				<th>${__("Offloaded")}</th>
				<th>${__("Operational Status")}</th>
				<th>${__("Container Status")}</th>
				<th>${__("Expected Return")}</th>
				<th>${__("Actual Return")}</th>
				<th>${__("Transporter")}</th>
				<th>${__("Dem./Det.")}</th>
			`;
		}

		function transportTableRow(row, extraCol = "") {
			const ret = row.effective_return_date || row.actual_empty_return || row.interchange_date;
			const alert = row.alert_status
				? `<div class="cgm-ops-alert">${frappe.utils.escape_html(row.alert_status)}</div>`
				: "";
			return `<tr class="${frappe.utils.escape_html(row.traffic_css || "")}">
				<td class="cgm-ops-sticky-col">${trackerLink(row)}${alert}</td>
				<td>${projectCell(row)}</td>
				<td>${batchCell(row)}</td>
				<td>${blCell(row)}</td>
				<td>${fmtDate(row.gate_in_port)}</td>
				<td>${fmtDate(row.gate_out_date_port)}</td>
				<td>${frappe.utils.escape_html(row.truck_number || "—")}</td>
				<td>${frappe.utils.escape_html(row.contact_display || "—")}</td>
				<td>${fmtDate(row.gate_in_date_warehouse)}<div class="text-muted small">${frappe.utils.escape_html(row.clearance_station || "")}</div></td>
				<td>${fmtDate(row.offloading_date)}</td>
				<td>${statusPill(row)}</td>
				<td>${containerStatusCell(row.container_status)}</td>
				<td>${fmtDate(row.expected_empty_return)}</td>
				<td>${fmtDate(ret)}</td>
				<td>${frappe.utils.escape_html(row.transporter_name || "—")}</td>
				<td>${row.demurrage_days || 0}</td>
				${extraCol}
			</tr>`;
		}

		const $opsBody = page.main.find(".cgm-ops-body");
		const $tableWrap = page.main.find(".cgm-ops-table-wrap");
		const $shipmentDetail = page.main.find(".cgm-ops-shipment-detail");
		const $listChrome = $opsBody.find(
			".cgm-ops-filters, .cgm-ops-kpis, .cgm-ops-filter-hint, .cgm-ops-tabs"
		);

		function enterShipmentDetailMode() {
			$opsBody.addClass("is-detail-view");
			$listChrome.hide();
		}

		function exitShipmentDetailMode() {
			$opsBody.removeClass("is-detail-view");
			$listChrome.show();
			selectedProject = null;
			$shipmentDetail.empty();
			setup_cgm_ops_breadcrumbs();
		}

		function renderShipmentListTable() {
			$tableWrap.html(`
				<table class="cgm-ops-table">
					<thead><tr>${shipmentTableHeaders()}</tr></thead>
					<tbody>${shipmentRows.map((row) => shipmentTableRow(row)).join("")}</tbody>
				</table>`);
		}

		function shipmentTableHeaders() {
			return `
				<th>${__("Shipment")}</th>
				<th>${__("Client")}</th>
				<th>${__("B/L")}</th>
				<th>${__("Batch")}</th>
				<th>${__("Containers")}</th>
				<th>${__("Shipping Line")}</th>
				<th>${__("Country of Origin")}</th>
				<th>${__("ETA")}</th>
				<th>${__("ATA")}</th>
				<th>${__("Clearing Station")}</th>
				<th>${__("Operational Status")}</th>
				<th>${__("Container Status")}</th>
				<th>${__("Remarks")}</th>
				<th>${__("Container Deposit")}</th>
				<th>${__("Vessel")}</th>
			`;
		}

		function shipmentTableRow(row) {
			return `<tr class="cgm-ops-clickable" data-project="${frappe.utils.escape_html(row.name)}">
				<td>${projectLink(row)}</td>
				<td>${frappe.utils.escape_html(row.customer || "—")}</td>
				<td>${frappe.utils.escape_html(row.bl_number || "—")}</td>
				<td>${frappe.utils.escape_html(row.batch_no || "—")}</td>
				<td>${frappe.utils.escape_html(row.quantity || "—")}</td>
				<td>${frappe.utils.escape_html(row.shipping_line || "—")}</td>
				<td>${frappe.utils.escape_html(row.country_of_origin || "—")}</td>
				<td>${fmtDate(row.eta)}</td>
				<td>${fmtDate(row.ata)}</td>
				<td>${frappe.utils.escape_html(row.clearance_station || "—")}</td>
				<td>${shipmentOperationalStatusCell(row)}</td>
				<td>${containerStatusCell(row.container_status_summary)}</td>
				<td>${frappe.utils.escape_html(row.remarks || "—")}</td>
				<td>${frappe.utils.escape_html(row.deposit_amount || 0)}</td>
				<td>${frappe.utils.escape_html(row.vessel_name || "—")}</td>
			</tr>`;
		}

		function renderShipments(data) {
			renderKpis(data.kpis);
			const rows = data.rows || [];
			shipmentRows = rows;
			if (!rows.length) {
				exitShipmentDetailMode();
				$tableWrap.html(`
					<div class="cgm-ops-empty">
						<div class="cgm-ops-empty-icon">📭</div>
						${__("No shipments match these filters.")}
					</div>`);
				return;
			}
			if (selectedProject) {
				const project = rows.find((row) => row.name === selectedProject);
				if (project) {
					renderShipmentDetail(project);
					return;
				}
				exitShipmentDetailMode();
			}
			renderShipmentListTable();
		}

		function shipmentDetailField(label, value, options = {}) {
			const display =
				value === null || value === undefined || value === "" ? "—" : String(value);
			const valueHtml = options.pill
				? `<span class="cgm-ops-pill muted"><span class="dot"></span>${frappe.utils.escape_html(display)}</span>`
				: frappe.utils.escape_html(display);
			return `<div class="cgm-ops-detail-field${options.wide ? " is-wide" : ""}">
				<div class="cgm-ops-detail-label">${frappe.utils.escape_html(label)}</div>
				<div class="cgm-ops-detail-value">${valueHtml}</div>
			</div>`;
		}

		function renderShipmentDetail(project) {
			selectedProject = project.name;
			enterShipmentDetailMode();
			const shipmentLabel = project.project_ref || project.name;
			setup_cgm_ops_breadcrumbs(shipmentLabel);
			const summary = `
				<div class="cgm-ops-shipment-detail-card">
					<div class="cgm-ops-shipment-detail-toolbar">
						<button type="button" class="btn btn-sm btn-default cgm-ops-back">
							&larr; ${__("Back to Shipments")}
						</button>
					</div>
					<h2 class="cgm-ops-shipment-detail-heading">${__("Shipment")}: ${frappe.utils.escape_html(shipmentLabel)}</h2>
					<div class="cgm-ops-shipment-detail-grid">
						${shipmentDetailField(__("Client"), project.customer)}
						${shipmentDetailField(__("B/L"), project.bl_number)}
						${shipmentDetailField(__("Batch"), project.batch_no)}
						${shipmentDetailField(__("Containers"), project.quantity)}
						${shipmentDetailField(__("Operational Status"), project.operational_status, { pill: true })}
						${shipmentDetailField(__("Country of Origin"), project.country_of_origin)}
						${shipmentDetailField(__("ETA"), project.eta ? fmtDate(project.eta) : "")}
						${shipmentDetailField(__("ATA"), project.ata ? fmtDate(project.ata) : "")}
						${shipmentDetailField(__("Shipping Line"), project.shipping_line)}
						${shipmentDetailField(__("Clearance Station"), project.clearance_station)}
						${shipmentDetailField(__("Container Deposit"), project.deposit_amount)}
						${shipmentDetailField(__("Vessel"), project.vessel_name)}
					</div>
				</div>`;
			$shipmentDetail.html(summary);
			$tableWrap.html(`
				<div class="cgm-ops-containers-panel">
					<h3 class="cgm-ops-containers-heading">${__("Containers on this shipment")}</h3>
					<div class="cgm-ops-containers-body"><div class="cgm-ops-empty">${__("Loading containers…")}</div></div>
				</div>`);
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.container_ops_board.get_project_containers_for_board",
				args: { project: project.name },
				freeze: true,
				callback(r) {
					const $body = $tableWrap.find(".cgm-ops-containers-body");
					if (r.exc) {
						$body.html(`<div class="cgm-ops-empty">${__("Could not load containers.")}</div>`);
						return;
					}
					const containerRows = r.message || [];
					if (!containerRows.length) {
						$body.html(`<div class="cgm-ops-empty">${__("No containers linked to this shipment.")}</div>`);
						return;
					}
					$body.html(`
						<table class="cgm-ops-table">
							<thead><tr>${transportTableHeaders()}</tr></thead>
							<tbody>${containerRows.map((row) => transportTableRow(row)).join("")}</tbody>
						</table>`);
				},
			});
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
			kpiFilter = null;
			exitShipmentDetailMode();
			syncStatusFilterForTab();
			refresh();
		});

		page.main.on("click", ".cgm-ops-back", () => {
			exitShipmentDetailMode();
			if (activeTab === "shipments" && shipmentRows.length) {
				renderShipmentListTable();
			}
		});

		page.main.on("click", ".cgm-ops-table a", (e) => {
			e.stopPropagation();
		});

		page.main.on("click", ".cgm-ops-clickable", function () {
			if (activeTab !== "shipments" || selectedProject) {
				return;
			}
			const project = $(this).data("project");
			const rows = shipmentRows.filter((r) => r.name === project);
			if (rows.length) {
				renderShipmentDetail(rows[0]);
			}
		});

		wrapper.on_page_show = function () {
			setup_cgm_ops_breadcrumbs();
			page.hide_form();
			page.main.find(".page-form.row").remove();
		};

		setTimeout(setup_cgm_ops_breadcrumbs, 0);
		syncStatusFilterForTab();
		refresh();
	});
};

function setup_cgm_ops_breadcrumbs(shipmentLabel) {
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
		__("Shipment Tracker"),
		shipmentLabel ? "shipment-list-breadcrumb" : "title-text"
	);
	if (shipmentLabel) {
		frappe.breadcrumbs.append_breadcrumb_element(
			"#",
			shipmentLabel,
			"title-text"
		);
	}
	frappe.breadcrumbs.toggle(true);
}
