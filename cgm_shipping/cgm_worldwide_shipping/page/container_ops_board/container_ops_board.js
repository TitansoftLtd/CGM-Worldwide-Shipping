frappe.pages["container-ops-board"].on_page_load = function (wrapper) {
	frappe.require(
		[
			"/assets/cgm_shipping/css/container_ops_board.css",
			"/assets/cgm_shipping/css/operational_updates.css",
			"/assets/cgm_shipping/js/operational_updates_ui.js",
		],
		() => {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Shipment Tracker"),
			single_column: true,
		});

		page.hide_form();
		page.main.find(".page-form.row").remove();

		page.main.addClass("cgm-ops-board");
		page.main.append(`
			<div class="cgm-ops-sticky-top">
				<div class="cgm-ops-hero">
					<h1>${__("Shipment Tracker")}</h1>
					<p>${__("Shipment-level tracking with drill-down to container status and the existing container operations board")}</p>
				</div>
				<div class="cgm-ops-sticky-chrome">
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
						<button type="button" class="btn btn-sm btn-default" data-tab="updates">
							<span class="cgm-ops-updates-tab-label">${__("Updates")}</span>
							<span class="cgm-ops-updates-badge" style="display:none"></span>
						</button>
					</div>
				</div>
			</div>
			<div class="cgm-ops-body">
				<div class="cgm-ops-shipment-detail"></div>
				<div class="cgm-ops-list-panel">
					<div class="cgm-ops-list-header"></div>
					<div class="cgm-ops-table-wrap"><div class="cgm-ops-empty">${__("Loading…")}</div></div>
					<div class="cgm-ops-list-paging"></div>
				</div>
			</div>
		`);

		setup_cgm_ops_breadcrumbs();

		const filters = {};
		const filter_controls = {};
		let kpiFilter = null;
		let activeTab = "shipments";
		let shipmentRows = [];
		let selectedProject = null;
		let containerRowsCache = [];
		const updateRowByKey = {};
		const selectedKeys = new Set();
		const PAGE_LENGTH_OPTIONS = [20, 50, 100, 500];
		let pageLength = frappe.is_large_screen && frappe.is_large_screen() ? 50 : 20;
		let listStart = 0;
		let totalCount = 0;
		let unreadUpdateCount = 0;
		let updatesRows = [];

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
			deposit_unpaid: {
				label: __("Deposit Unpaid"),
				icon: "💳",
				tone: "amber",
				alert: true,
			},
			deposit_paid: {
				label: __("Deposit Paid"),
				icon: "💰",
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
			"deposit_unpaid",
			"deposit_paid",
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

		const BOARD_FILTER_FIELDS = [
			"customer",
			"shipping_line",
			"bill_of_lading",
			"clearance_station",
			"date_field",
			"date_from",
			"date_to",
			"status",
		];
		const UPDATE_FILTER_FIELDS = [
			"project",
			"container_tracker",
			"status",
			"subject",
			"date_from",
			"date_to",
			"customer",
			"transporter",
		];

		const filter_fields = [
			{
				fieldname: "customer",
				label: __("Customer"),
				fieldtype: "Link",
				options: "Customer",
			},
			{
				fieldname: "project",
				label: __("Shipment"),
				fieldtype: "Link",
				options: "Project",
			},
			{
				fieldname: "container_tracker",
				label: __("Container"),
				fieldtype: "Link",
				options: "Container Tracker",
			},
			{
				fieldname: "subject",
				label: __("Update Type"),
				fieldtype: "Data",
			},
			{
				fieldname: "transporter",
				label: __("Transporter"),
				fieldtype: "Link",
				options: "Supplier",
			},
			{
				fieldname: "shipping_line",
				label: __("Shipping Line"),
				fieldtype: "Link",
				options: "Supplier",
			},
			{
				fieldname: "bill_of_lading",
				label: __("B/L"),
				fieldtype: "Link",
				options: "Bill of Lading",
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
				activeTab === "updates"
					? "\nUnread\nRead"
					: activeTab === "shipments"
						? shipmentStatusOptions()
						: CONTAINER_STATUS_OPTIONS;
			control.df.options = options;
			control.refresh();
			if (control.$input) {
				control.$input.attr("placeholder", __("Status"));
			}
		}

		function syncFiltersForTab() {
			const isUpdates = activeTab === "updates";
			const visible = new Set(isUpdates ? UPDATE_FILTER_FIELDS : BOARD_FILTER_FIELDS);

			Object.keys(filter_controls).forEach((fieldname) => {
				const control = filter_controls[fieldname];
				const show = visible.has(fieldname);
				$(control.wrapper).toggle(show);
			});

			const $from = filter_controls.date_from;
			const $to = filter_controls.date_to;
			if ($from && $from.$input) {
				$from.$input.attr(
					"placeholder",
					isUpdates ? __("Posted From") : __("Date From")
				);
			}
			if ($to && $to.$input) {
				$to.$input.attr("placeholder", isUpdates ? __("Posted To") : __("Date To"));
			}

			syncStatusFilterForTab();
		}

		const $filter_parent = page.main.find(".cgm-ops-filters");
		filter_fields.forEach((df) => {
			const control = frappe.ui.form.make_control({
				df: {
					...df,
					placeholder: df.label,
					input_class: "input-xs",
					onchange() {
						filters[df.fieldname] = control.get_value() || null;
						listStart = 0;
						selectedKeys.clear();
						refresh();
					},
				},
				parent: $filter_parent[0],
				only_input: true,
			});
			control.refresh();
			if (control.$input) {
				control.$input.attr("placeholder", df.label);
				// Link / Date controls sometimes set value without firing df.onchange.
				control.$input.on("change awesomplete-selectcomplete", () => {
					filters[df.fieldname] = control.get_value() || null;
					listStart = 0;
					selectedKeys.clear();
					refresh();
				});
			}
			$(control.wrapper).addClass("cgm-ops-filter-field");
			filter_controls[df.fieldname] = control;
		});

		// Shipping Line = carriers only; Transporter = haulage suppliers only.
		if (filter_controls.shipping_line) {
			filter_controls.shipping_line.get_query =
				cgm_shipping.supplier_filters?.shipping_line_query ||
				(() => ({ filters: { disabled: 0, custom_is_shipping_line: 1 } }));
		}
		if (filter_controls.transporter) {
			filter_controls.transporter.get_query =
				cgm_shipping.supplier_filters?.transporter_query ||
				(() => ({ filters: { disabled: 0, is_transporter: 1 } }));
		}

		syncFiltersForTab();

		function syncFilterValues() {
			Object.keys(filter_controls).forEach((fieldname) => {
				filters[fieldname] = filter_controls[fieldname].get_value() || null;
			});
		}

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

		function updateUpdatesTabBadge(count) {
			unreadUpdateCount = cint(count || 0);
			const $btn = page.main.find('.cgm-ops-tabs button[data-tab="updates"]');
			const $badge = $btn.find(".cgm-ops-updates-badge");
			const $label = $btn.find(".cgm-ops-updates-tab-label");
			if (unreadUpdateCount > 0) {
				$label.text(__("Updates ({0})", [unreadUpdateCount]));
				$badge.text(unreadUpdateCount).show();
			} else {
				$label.text(__("Updates"));
				$badge.hide();
			}
		}

		function refreshUnreadBadge() {
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_unread_update_count",
				callback(r) {
					if (!r.exc) {
						updateUpdatesTabBadge(r.message || 0);
					}
				},
			});
		}

		function trackerLink(row) {
			return `<a href="/app/container-tracker/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(
				row.container_number || ""
			)}</a>`;
		}

		function shipmentCell(row) {
			const ref = row.project_ref || row.project || "—";
			if (!row.project) {
				return frappe.utils.escape_html(ref);
			}
			return `<a href="/app/project/${encodeURIComponent(row.project)}">${frappe.utils.escape_html(ref)}</a>`;
		}

		function clientCell(row) {
			return frappe.utils.escape_html(row.customer || "—");
		}

		function batchCell(row) {
			return frappe.utils.escape_html(row.batch_no || "—");
		}

		function cgmReferenceCell(row) {
			return frappe.utils.escape_html(row.cgm_ref_no || "—");
		}

		function clientReferenceCell(row) {
			return frappe.utils.escape_html(row.client_reference_no || "—");
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
			syncFilterValues();
			refreshUnreadBadge();

			if (activeTab === "updates") {
				exitShipmentDetailMode();
				page.main.find(".cgm-ops-kpis").empty();
				page.main.find(".cgm-ops-filter-hint").hide();
				frappe.call({
					method:
						"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_ops_updates",
					args: {
						filters: {
							customer: filters.customer || null,
							project: filters.project || null,
							container_tracker: filters.container_tracker || null,
							transporter: filters.transporter || null,
							subject: filters.subject || null,
							status: filters.status || null,
							date_from: filters.date_from || null,
							date_to: filters.date_to || null,
							start: listStart,
							page_length: pageLength,
						},
					},
					freeze: true,
					callback(r) {
						if (r.exc) {
							return;
						}
						renderUpdates(r.message || {});
					},
				});
				return;
			}

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
			args.start = listStart;
			args.page_length = pageLength;

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

		function recordNoun(count) {
			if (activeTab === "updates") {
				return count === 1 ? __("Update") : __("Updates");
			}
			if (activeTab === "shipments") {
				return count === 1 ? __("Shipment") : __("Shipments");
			}
			return count === 1 ? __("Container") : __("Containers");
		}

		function listCountLabel() {
			if (!totalCount) {
				return __("No {0}", [recordNoun(0).toLowerCase()]);
			}
			const from = listStart + 1;
			const to = Math.min(listStart + pageLength, totalCount);
			return __("Showing {0}–{1} of {2} {3}", [from, to, totalCount, recordNoun(totalCount)]);
		}

		function renderListChrome(rows) {
			const $header = page.main.find(".cgm-ops-list-header");
			const $paging = page.main.find(".cgm-ops-list-paging");
			const pageKeys = (rows || []).map((row) => row.name).filter(Boolean);
			const allSelected = pageKeys.length && pageKeys.every((key) => selectedKeys.has(key));
			const someSelected = pageKeys.some((key) => selectedKeys.has(key));

			$header.html(`
				<div class="cgm-ops-list-header-left">
					<span class="cgm-ops-list-count">${frappe.utils.escape_html(listCountLabel())}</span>
					${
						selectedKeys.size
							? `<span class="cgm-ops-list-selected">${__("{0} selected", [selectedKeys.size])}</span>`
							: ""
					}
				</div>
			`);

			const canPrev = listStart > 0;
			const canNext = listStart + pageLength < totalCount;
			$paging.html(`
				<div class="list-paging-area level cgm-ops-paging-area">
					<div class="level-left">
						<div class="btn-group">
							${PAGE_LENGTH_OPTIONS.map(
								(value) => `
								<button type="button" class="btn btn-default btn-sm btn-paging${
									value === pageLength ? " btn-info" : ""
								}" data-value="${value}" ${value === pageLength ? "disabled" : ""}>
									${value}
								</button>`
							).join("")}
						</div>
					</div>
					<div class="level-right cgm-ops-paging-nav">
						<button type="button" class="btn btn-default btn-sm cgm-ops-page-prev" ${canPrev ? "" : "disabled"}>
							${__("Previous")}
						</button>
						<button type="button" class="btn btn-default btn-sm cgm-ops-page-next" ${canNext ? "" : "disabled"}>
							${__("Next")}
						</button>
					</div>
				</div>
			`);

			// Keep select-all checkbox state in sync after re-render.
			const $selectAll = page.main.find(".cgm-ops-select-all");
			if ($selectAll.length) {
				$selectAll.prop("checked", allSelected);
				$selectAll.prop("indeterminate", !allSelected && someSelected);
			}
		}

		function checkboxCell(row) {
			const key = row.name || "";
			const checked = selectedKeys.has(key) ? "checked" : "";
			return `<td class="cgm-ops-check-col">
				<input type="checkbox" class="cgm-ops-row-check" data-name="${frappe.utils.escape_html(key)}" ${checked}>
			</td>`;
		}

		function selectAllHeader() {
			return `<th class="cgm-ops-check-col">
				<input type="checkbox" class="cgm-ops-select-all" title="${__("Select all")}">
			</th>`;
		}

		function renderEmptyState(message, icon) {
			page.main.find(".cgm-ops-list-header").empty();
			page.main.find(".cgm-ops-list-paging").empty();
			$tableWrap.html(`
				<div class="cgm-ops-empty">
					<div class="cgm-ops-empty-icon">${icon}</div>
					${message}
				</div>`);
		}

		function renderListTable(headersHtml, bodyHtml) {
			$tableWrap.html(`
				<div class="cgm-ops-table-scroll">
					<table class="cgm-ops-table">
						<thead><tr>${headersHtml}</tr></thead>
						<tbody>${bodyHtml}</tbody>
					</table>
				</div>`);
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

		function cacheUpdateRows(rows, scope) {
			(rows || []).forEach((row) => {
				const key = scope === "shipment" ? row.name : row.name;
				if (!key) {
					return;
				}
				updateRowByKey[`${scope}:${key}`] = row;
			});
		}

		function transporterUpdateBadge(row, scope) {
			const type = row.last_transporter_update_type || "";
			if (!type) {
				return `<span class="cgm-ops-update is-empty">—</span>`;
			}
			const key = row.name || "";
			const count = row.transporter_update_count || 0;
			const countLabel =
				scope === "shipment" && count > 1
					? `<span class="cgm-ops-update-count">${count}</span>`
					: "";
			return `<button type="button"
				class="cgm-ops-update-badge"
				data-update-scope="${frappe.utils.escape_html(scope)}"
				data-update-key="${frappe.utils.escape_html(key)}"
				title="${frappe.utils.escape_html(__("View updates"))}">
				<span class="cgm-ops-update-type">${frappe.utils.escape_html(type)}</span>
				${countLabel}
			</button>`;
		}

		function transportTableHeaders() {
			return `
				${selectAllHeader()}
				<th class="cgm-ops-sticky-col">${__("Client Name")}</th>
				<th>${__("B/L Number")}</th>
				<th>${__("CGM Ref No")}</th>
				<th>${__("CGM Batch No")}</th>
				<th>${__("Client Reference No")}</th>
				<th>${__("Shipment")}</th>
				<th>${__("Shipping Line")}</th>
				<th>${__("Country of Origin")}</th>
				<th>${__("ETA")}</th>
				<th>${__("Clearing Station")}</th>
				<th>${__("Remarks")}</th>
				<th>${__("Container")}</th>
				<th>${__("ATA")}</th>
				<th>${__("Operational Status")}</th>
				<th>${__("Container Status")}</th>
				<th>${__("Container Deposit")}</th>
				<th>${__("Deposit Payment Status")}</th>
				<th>${__("Vessel")}</th>
				<th>${__("Gate In Mombasa")}</th>
				<th>${__("Gate Out Mombasa")}</th>
				<th>${__("Gate In ICD")}</th>
				<th>${__("Gate Out ICD")}</th>
				<th>${__("Truck No")}</th>
				<th>${__("Update")}</th>
				<th>${__("Contact")}</th>
				<th>${__("Gate In Warehouse")}</th>
				<th>${__("Offloaded")}</th>
				<th>${__("Expected Return")}</th>
				<th>${__("Actual Return")}</th>
				<th>${__("Transporter")}</th>
				<th>${__("Dem./Det.")}</th>
			`;
		}

		function depositPaymentStatusCell(row) {
			const status = row.deposit_payment_status || "";
			const hasDeposit = cint(row.has_deposit) || flt(row.deposit_amount) > 0;
			if (!hasDeposit || !status || status === "Not Applicable") {
				return `<span class="indicator-pill gray ellipsis">${__("No Deposit")}</span>`;
			}
			const tone = status === "Paid" ? "success" : status === "Unpaid" ? "warning" : "muted";
			return `<span class="indicator-pill ${tone} ellipsis">${frappe.utils.escape_html(status)}</span>`;
		}

		function transportTableRow(row, extraCol = "") {
			const ret = row.effective_return_date || row.actual_empty_return || row.interchange_date;
			const alert = row.alert_status
				? `<div class="cgm-ops-alert">${frappe.utils.escape_html(row.alert_status)}</div>`
				: "";
			const remarks = row.remarks || row.alert_status || "";
			const selectedCls = selectedKeys.has(row.name) ? " is-selected" : "";
			return `<tr class="${frappe.utils.escape_html(row.traffic_css || "")}${selectedCls}" data-name="${frappe.utils.escape_html(row.name || "")}">
				${checkboxCell(row)}
				<td class="cgm-ops-sticky-col">${clientCell(row)}</td>
				<td>${blCell(row)}</td>
				<td>${cgmReferenceCell(row)}</td>
				<td>${batchCell(row)}</td>
				<td>${clientReferenceCell(row)}</td>
				<td>${shipmentCell(row)}</td>
				<td>${frappe.utils.escape_html(row.shipping_line || "—")}</td>
				<td>${frappe.utils.escape_html(row.country_of_origin || "—")}</td>
				<td>${fmtDate(row.eta)}</td>
				<td>${frappe.utils.escape_html(row.clearance_station || "—")}</td>
				<td>${frappe.utils.escape_html(remarks || "—")}</td>
				<td>${trackerLink(row)}${alert}</td>
				<td>${fmtDate(row.ata)}</td>
				<td>${statusPill(row)}</td>
				<td>${containerStatusCell(row.container_status)}</td>
				<td>${frappe.utils.escape_html(row.deposit_amount || 0)}</td>
				<td>${depositPaymentStatusCell(row)}</td>
				<td>${frappe.utils.escape_html(row.vessel_name || "—")}</td>
				<td>${fmtDate(row.gate_in_port)}</td>
				<td>${fmtDate(row.gate_out_date_port)}</td>
				<td>${fmtDate(row.icd_gate_in_date)}</td>
				<td>${fmtDate(row.icd_gate_out_date)}</td>
				<td>${frappe.utils.escape_html(row.truck_number || "—")}</td>
				<td>${transporterUpdateBadge(row, "tracker")}</td>
				<td>${frappe.utils.escape_html(row.contact_display || "—")}</td>
				<td>${fmtDate(row.gate_in_date_warehouse)}</td>
				<td>${fmtDate(row.offloading_date)}</td>
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
		const $listChrome = page.main.find(".cgm-ops-sticky-top");
		const $listPanel = page.main.find(".cgm-ops-list-panel");

		function enterShipmentDetailMode() {
			$opsBody.addClass("is-detail-view");
			$listChrome.hide();
			$listPanel.find(".cgm-ops-list-header, .cgm-ops-list-paging").hide();
		}

		function exitShipmentDetailMode() {
			$opsBody.removeClass("is-detail-view");
			$listChrome.show();
			$listPanel.find(".cgm-ops-list-header, .cgm-ops-list-paging").show();
			selectedProject = null;
			$shipmentDetail.empty();
			setup_cgm_ops_breadcrumbs();
		}

		function renderShipmentListTable() {
			renderListTable(
				shipmentTableHeaders(),
				shipmentRows.map((row) => shipmentTableRow(row)).join("")
			);
			renderListChrome(shipmentRows);
		}

		function shipmentTableHeaders() {
			return `
				${selectAllHeader()}
				<th class="cgm-ops-sticky-col">${__("Client Name")}</th>
				<th>${__("B/L Number")}</th>
				<th>${__("CGM Ref No")}</th>
				<th>${__("CGM Batch No")}</th>
				<th>${__("Client Reference No")}</th>
				<th>${__("Shipment")}</th>
				<th>${__("Shipping Line")}</th>
				<th>${__("Country of Origin")}</th>
				<th>${__("ETA")}</th>
				<th>${__("Clearing Station")}</th>
				<th>${__("Remarks")}</th>
				<th>${__("Containers")}</th>
				<th>${__("ATA")}</th>
				<th>${__("Operational Status")}</th>
				<th>${__("Container Status")}</th>
				<th>${__("Container Deposit")}</th>
				<th>${__("Vessel")}</th>
			`;
		}

		function projectLink(row) {
			const ref = row.project_ref || row.name || "—";
			if (!row.name) {
				return frappe.utils.escape_html(ref);
			}
			return `<a href="/app/project/${encodeURIComponent(row.name)}">${frappe.utils.escape_html(ref)}</a>`;
		}

		function shipmentTableRow(row) {
			const selectedCls = selectedKeys.has(row.name) ? " is-selected" : "";
			return `<tr class="cgm-ops-clickable${selectedCls}" data-project="${frappe.utils.escape_html(row.name)}" data-name="${frappe.utils.escape_html(row.name || "")}">
				${checkboxCell(row)}
				<td class="cgm-ops-sticky-col">${frappe.utils.escape_html(row.customer || "—")}</td>
				<td>${frappe.utils.escape_html(row.bl_number || "—")}</td>
				<td>${cgmReferenceCell(row)}</td>
				<td>${frappe.utils.escape_html(row.batch_no || "—")}</td>
				<td>${frappe.utils.escape_html(row.client_reference_no || "—")}</td>
				<td>${projectLink(row)}</td>
				<td>${frappe.utils.escape_html(row.shipping_line || "—")}</td>
				<td>${frappe.utils.escape_html(row.country_of_origin || "—")}</td>
				<td>${fmtDate(row.eta)}</td>
				<td>${frappe.utils.escape_html(row.clearance_station || "—")}</td>
				<td>${frappe.utils.escape_html(row.remarks || "—")}</td>
				<td>${frappe.utils.escape_html(row.quantity || "—")}</td>
				<td>${fmtDate(row.ata)}</td>
				<td>${shipmentOperationalStatusCell(row)}</td>
				<td>${containerStatusCell(row.container_status_summary)}</td>
				<td>${frappe.utils.escape_html(row.deposit_amount || 0)}</td>
				<td>${frappe.utils.escape_html(row.vessel_name || "—")}</td>
			</tr>`;
		}

		function applyPageMeta(data) {
			totalCount = cint(data.total_count || data.count || 0);
			listStart = cint(data.start != null ? data.start : listStart);
			if (data.page_length) {
				pageLength = cint(data.page_length);
			}
		}

		function renderShipments(data) {
			renderKpis(data.kpis);
			applyPageMeta(data);
			const rows = data.rows || [];
			shipmentRows = rows;
			cacheUpdateRows(rows, "shipment");
			if (!totalCount) {
				exitShipmentDetailMode();
				renderEmptyState(__("No shipments match these filters."), "📭");
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
						${shipmentDetailField(__("Client Reference No"), project.client_reference_no)}
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
					containerRowsCache = containerRows;
					cacheUpdateRows(containerRows, "tracker");
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
			applyPageMeta(data);
			const rows = data.rows || [];
			containerRowsCache = rows;
			cacheUpdateRows(rows, "tracker");
			if (!totalCount) {
				renderEmptyState(__("No containers match these filters."), "📭");
				return;
			}
			renderListTable(
				transportTableHeaders(),
				rows.map((row) => transportTableRow(row)).join("")
			);
			renderListChrome(rows);
		}

		function renderReturns(data) {
			renderKpis(data.kpis);
			applyPageMeta(data);
			const rows = data.rows || [];
			containerRowsCache = rows;
			cacheUpdateRows(rows, "tracker");
			if (!totalCount) {
				renderEmptyState(
					__("No containers in the return pipeline. Containers appear here after gate out from port."),
					"📦"
				);
				return;
			}
			renderListTable(
				`${transportTableHeaders()}<th>${__("Days Out")}</th>`,
				rows.map((row) => transportTableRow(row, `<td>${row.days_outstanding || 0}</td>`)).join("")
			);
			renderListChrome(rows);
		}

		function renderUpdates(data) {
			applyPageMeta(data);
			updateUpdatesTabBadge(data.unread_count);
			updatesRows = data.rows || [];
			if (!totalCount) {
				renderEmptyState(__("No updates yet. Transporter and customer posts appear here."), "💬");
				return;
			}
			page.main.find(".cgm-ops-list-header").empty();
			$tableWrap.html(cgm.updates.renderList(updatesRows));
			cgm.updates.bindListClicks($tableWrap, {
				onOpened() {
					refreshUnreadBadge();
				},
			});
			renderListChrome(updatesRows);
		}

		page.main.find(".cgm-ops-kpis").on("click", ".cgm-ops-kpi", function () {
			const key = $(this).data("kpi");
			kpiFilter = kpiFilter === key ? null : key;
			listStart = 0;
			selectedKeys.clear();
			refresh();
		});

		page.main.find(".cgm-ops-filter-hint").on("click", ".clear-filter", () => {
			kpiFilter = null;
			listStart = 0;
			selectedKeys.clear();
			refresh();
		});

		page.main.find(".cgm-ops-tabs").on("click", "button", function () {
			activeTab = $(this).data("tab");
			page.main.find(".cgm-ops-tabs button").removeClass("active");
			$(this).addClass("active");
			kpiFilter = null;
			listStart = 0;
			selectedKeys.clear();
			// Status options differ by tab — clear so a shipment status is not
			// applied against container statuses (and vice versa).
			if (filter_controls.status) {
				filter_controls.status.set_value("");
				filters.status = null;
			}
			exitShipmentDetailMode();
			syncFiltersForTab();
			refresh();
		});

		page.main.on("click", ".cgm-ops-back", () => {
			exitShipmentDetailMode();
			if (activeTab === "shipments" && shipmentRows.length) {
				renderShipmentListTable();
			} else {
				refresh();
			}
		});

		function openUpdatesTabForRow(scope, key) {
			const row = updateRowByKey[`${scope}:${key}`];
			if (!row) {
				return;
			}

			const setFilter = (fieldname, value) => {
				if (!filter_controls[fieldname]) {
					return;
				}
				filter_controls[fieldname].set_value(value || "");
				filters[fieldname] = value || null;
			};

			// Clear update-tab filters first so leftover values do not stick.
			["project", "container_tracker", "subject", "transporter", "customer", "status"].forEach(
				(fieldname) => setFilter(fieldname, "")
			);

			if (row.project) {
				setFilter("project", row.project);
			}
			if (scope === "tracker" && row.name) {
				setFilter("container_tracker", row.name);
			}

			activeTab = "updates";
			page.main.find(".cgm-ops-tabs button").removeClass("active");
			page.main.find('.cgm-ops-tabs button[data-tab="updates"]').addClass("active");
			kpiFilter = null;
			listStart = 0;
			selectedKeys.clear();
			exitShipmentDetailMode();
			syncFiltersForTab();
			refresh();
		}

		page.main.on("click", ".cgm-ops-update-badge", function (e) {
			e.preventDefault();
			e.stopPropagation();
			const scope = $(this).data("update-scope");
			const key = $(this).data("update-key");
			openUpdatesTabForRow(scope, key);
		});

		page.main.on("click", ".cgm-ops-table a", (e) => {
			e.stopPropagation();
		});

		page.main.on("click", ".cgm-ops-row-check, .cgm-ops-select-all", (e) => {
			e.stopPropagation();
		});

		page.main.on("change", ".cgm-ops-row-check", function () {
			const name = $(this).data("name");
			if (!name) {
				return;
			}
			if (this.checked) {
				selectedKeys.add(name);
			} else {
				selectedKeys.delete(name);
			}
			const $row = $(this).closest("tr");
			$row.toggleClass("is-selected", this.checked);
			renderListChrome(
				activeTab === "shipments"
					? shipmentRows
					: activeTab === "updates"
						? updatesRows
						: containerRowsCache
			);
		});

		page.main.on("change", ".cgm-ops-select-all", function () {
			const checked = this.checked;
			page.main.find(".cgm-ops-row-check").each(function () {
				const name = $(this).data("name");
				$(this).prop("checked", checked);
				$(this).closest("tr").toggleClass("is-selected", checked);
				if (!name) {
					return;
				}
				if (checked) {
					selectedKeys.add(name);
				} else {
					selectedKeys.delete(name);
				}
			});
			renderListChrome(
				activeTab === "shipments"
					? shipmentRows
					: activeTab === "updates"
						? updatesRows
						: containerRowsCache
			);
		});

		page.main.on("click", ".btn-paging", function () {
			const value = cint($(this).data("value"));
			if (!value || value === pageLength) {
				return;
			}
			pageLength = value;
			listStart = 0;
			selectedKeys.clear();
			refresh();
		});

		page.main.on("click", ".cgm-ops-page-prev", function () {
			if ($(this).prop("disabled")) {
				return;
			}
			listStart = Math.max(0, listStart - pageLength);
			refresh();
		});

		page.main.on("click", ".cgm-ops-page-next", function () {
			if ($(this).prop("disabled")) {
				return;
			}
			listStart = listStart + pageLength;
			refresh();
		});

		page.main.on("click", ".cgm-ops-clickable", function (e) {
			if ($(e.target).closest(".cgm-ops-row-check, .cgm-ops-update-badge, a").length) {
				return;
			}
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
		syncFiltersForTab();
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
