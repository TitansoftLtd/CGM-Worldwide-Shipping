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
			title: __("Container Ops Board"),
			single_column: true,
		});

		page.hide_form();
		page.main.find(".page-form.row").remove();

		page.main.addClass("cgm-ops-board");
		page.main.append(`
			<div class="cgm-ops-sticky-top">
				<div class="cgm-ops-subtitle"><span>${__(
					"Shipment-level tracking with drill-down to container status and the existing container operations board"
				)}</span></div>
				<div class="cgm-ops-sticky-chrome">
					<div class="cgm-ops-filters"></div>
					<div class="cgm-ops-kpis-section is-collapsed">
						<button type="button" class="cgm-ops-kpis-toggle" aria-expanded="false">
							<span class="cgm-ops-kpis-toggle-label">${__("Summary")}</span>
							<span class="cgm-ops-kpis-toggle-hint">${__("Show or hide KPI cards")}</span>
							<span class="cgm-ops-kpis-toggle-icon" aria-hidden="true">▾</span>
						</button>
						<div class="cgm-ops-kpis-collapse">
							<div class="cgm-ops-kpis"></div>
						</div>
					</div>
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
						<span class="cgm-ops-list-count cgm-ops-tabs-count" style="display:none"></span>
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

		/* Versioned key.
		 *
		 * The previous code called set_kpis_collapsed() on load, and that
		 * function writes to localStorage. So it stamped "0" for every user on
		 * their first visit, and there is no way to tell "chose expanded" from
		 * "the old code wrote it". Reusing the key would mean the collapsed
		 * default never reaches anyone who has opened the page before.
		 */
		/* Fit the board to whatever height is actually left.
		 *
		 * The CSS falls back to calc(100dvh - 7rem), but 7rem is only a guess
		 * at frappe's navbar, page head and breadcrumbs. Whenever the real
		 * chrome is taller the board overruns the viewport and the whole PAGE
		 * scrolls, which defeats the point: the table has its own scroller and
		 * the filters, tabs and paging are meant to stay put.
		 */
		function fit_board_height() {
			const el = page.main.get(0);
			if (!el) return;
			const top = el.getBoundingClientRect().top + window.scrollY;
			el.style.setProperty("--cgm-ops-board-offset", `${Math.max(0, Math.round(top))}px`);
		}

		function watch_board_height() {
			fit_board_height();
			// Two frames in: fonts and sticky chrome settle after first paint.
			requestAnimationFrame(() => requestAnimationFrame(fit_board_height));

			let pending = null;
			const remeasure = () => {
				if (pending) cancelAnimationFrame(pending);
				pending = requestAnimationFrame(fit_board_height);
			};
			window.addEventListener("resize", remeasure);
			window.addEventListener("orientationchange", remeasure);

			// The chrome above can change height on its own, for instance when
			// breadcrumbs wrap, so watch it rather than only window events.
			if (window.ResizeObserver) {
				const chrome = document.querySelector(".navbar, .page-head");
				if (chrome) new ResizeObserver(remeasure).observe(chrome);
			}
		}

		const KPI_COLLAPSE_STORAGE_KEY = "cgm_ops_board_kpis_collapsed_v2";

		// `persist` is false when only applying the default on load. Writing
		// then is what turned a default into a preference nobody expressed.
		function set_kpis_collapsed(collapsed, persist = true) {
			const $section = page.main.find(".cgm-ops-kpis-section");
			const $toggle = $section.find(".cgm-ops-kpis-toggle");
			$section.toggleClass("is-collapsed", collapsed);
			$toggle.attr("aria-expanded", collapsed ? "false" : "true");
			if (persist) {
				try {
					localStorage.setItem(KPI_COLLAPSE_STORAGE_KEY, collapsed ? "1" : "0");
				} catch (e) {
					// Private browsing and blocked site data both throw here.
				}
			}
		}

		function init_kpis_collapse() {
			const $section = page.main.find(".cgm-ops-kpis-section");
			const $toggle = $section.find(".cgm-ops-kpis-toggle");
			let stored = null;
			try {
				stored = localStorage.getItem(KPI_COLLAPSE_STORAGE_KEY);
			} catch (e) {
				// Storage unavailable: fall through to the collapsed default.
			}

			// Collapsed unless this user has explicitly chosen otherwise: the
			// cards push the tabs and the table below the fold.
			const collapsed = stored === null ? true : stored === "1";
			set_kpis_collapsed(collapsed, false);

			$toggle.on("click", () => {
				set_kpis_collapsed(!$section.hasClass("is-collapsed"));
				// Collapsing frees vertical space; re-fit so the table takes it.
				requestAnimationFrame(fit_board_height);
			});

			watch_board_height();
		}

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
		// The first option in PAGE_LENGTH_OPTIONS, so the default always
		// matches the leftmost button rather than being a separate constant
		// that can drift away from it.
		let pageLength = PAGE_LENGTH_OPTIONS[0];
		let listStart = 0;
		// Empty sortBy means the server's default order: traffic-light rank
		// then ETA, which is the operationally useful default.
		let sortBy = "";
		let sortDir = "asc";
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
			deposit_refund_pending: {
				label: __("Deposit Refund Pending"),
				icon: "↩️",
				tone: "amber",
				alert: true,
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
			"deposit_refund_pending",
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
			"batch_no",
			"clearance_station",
			"date_field",
			"date_range",
			"status",
		];
		const UPDATE_FILTER_FIELDS = [
			"project",
			"container_tracker",
			"status",
			"subject",
			"date_range",
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
				fieldname: "batch_no",
				label: __("Client Batch No"),
				fieldtype: "Data",
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
				// One control, two server-side params. get_value() returns
				// [from, to], which applyFilterValue splits back into
				// filters.date_from / filters.date_to so the API is unchanged.
				fieldname: "date_range",
				label: __("Date"),
				fieldtype: "DateRange",
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

			const $range = filter_controls.date_range;
			if ($range && $range.$input) {
				$range.$input.attr("placeholder", isUpdates ? __("Posted Date") : __("Date"));
			}

			syncStatusFilterForTab();
		}

		// A control's value does not always map to a single filter. The date
		// range is one widget feeding two server-side params, so every read
		// goes through here rather than assuming filters[fieldname] = value.
		function applyFilterValue(fieldname) {
			const control = filter_controls[fieldname];
			if (!control) {
				return;
			}

			const value = control.get_value();

			if (fieldname === "date_range") {
				const range = Array.isArray(value) ? value : null;
				filters.date_from = (range && range[0]) || null;
				filters.date_to = (range && range[1]) || null;
				return;
			}

			filters[fieldname] = value || null;
		}

		const $filter_parent = page.main.find(".cgm-ops-filters");
		filter_fields.forEach((df) => {
			const control = frappe.ui.form.make_control({
				df: {
					...df,
					placeholder: df.label,
					input_class: "input-xs",
					onchange() {
						applyFilterValue(df.fieldname);
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
					applyFilterValue(df.fieldname);
					listStart = 0;
					selectedKeys.clear();
					refresh();
				});
			}
			$(control.wrapper).addClass(`cgm-ops-filter-field cgm-ops-filter-${df.fieldname}`);
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
			Object.keys(filter_controls).forEach(applyFilterValue);
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
							sort_by: sortBy || null,
							sort_dir: sortDir,
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
			args.sort_by = sortBy || null;
			args.sort_dir = sortDir;

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
			// How many rows are on screen, out of the total. The exact position
			// in the set ("51-100 of 412") now lives beside the paging arrows,
			// so repeating the range here was saying the same thing twice.
			const to = Math.min(listStart + pageLength, totalCount);
			const shown = to - listStart;
			return __("Showing {0} of {1}", [shown, totalCount]);
		}

		// The count sits at the right end of the tabs row rather than in a strip
		// of its own: it is one short line of metadata, and a dedicated bar for
		// it cost ~22px of table height on every screen.
		function setTabsCount(text) {
			const $count = page.main.find(".cgm-ops-tabs-count");
			if (!$count.length) return;
			if (!text) {
				$count.text("").hide();
				return;
			}
			$count.text(text).show();
		}

		function renderListChrome(rows) {
			const $header = page.main.find(".cgm-ops-list-header");
			const $paging = page.main.find(".cgm-ops-list-paging");
			const pageKeys = (rows || []).map((row) => row.name).filter(Boolean);
			const allSelected = pageKeys.length && pageKeys.every((key) => selectedKeys.has(key));
			const someSelected = pageKeys.some((key) => selectedKeys.has(key));

			setTabsCount(listCountLabel());

			// Selection is an action state, so it stays on the left where the
			// checkboxes are. With the count moved up to the tabs, this row has
			// nothing to say until something is selected, so it collapses.
			$header.html(
				selectedKeys.size
					? `<div class="cgm-ops-list-header-left">
					<span class="cgm-ops-list-selected">${__("{0} selected", [selectedKeys.size])}</span>
				</div>`
					: ""
			);
			$header.css("display", selectedKeys.size ? "" : "none");

			// A compact "51-100 of 412" beside the arrows, so the buttons say
			// where you are as well as what they do.
			function pagingRangeLabel() {
				if (!totalCount) {
					return "";
				}
				const from = listStart + 1;
				const to = Math.min(listStart + pageLength, totalCount);
				return `${from}\u2013${to} ${__("of")} ${totalCount}`;
			}

			const canPrev = listStart > 0;
			const canNext = listStart + pageLength < totalCount;
			$paging.html(`
				<div class="list-paging-area level cgm-ops-paging-area">
					<div class="level-left cgm-ops-paging-size">
						<span class="cgm-ops-paging-label">${__("Rows")}</span>
						<div class="btn-group cgm-ops-paging-group">
							${PAGE_LENGTH_OPTIONS.map(
								(value) => `
								<button type="button" class="btn btn-default btn-sm btn-paging${
									value === pageLength ? " is-current" : ""
								}" data-value="${value}" ${value === pageLength ? "disabled" : ""}>
									${value}
								</button>`
							).join("")}
						</div>
					</div>
					<div class="level-right cgm-ops-paging-nav">
						<span class="cgm-ops-paging-range">${frappe.utils.escape_html(
							pagingRangeLabel()
						)}</span>
						<button type="button" class="btn btn-default btn-sm cgm-ops-page-prev" ${
							canPrev ? "" : "disabled"
						} aria-label="${__("Previous page")}">
							<span aria-hidden="true">&lsaquo;</span> ${__("Prev")}
						</button>
						<button type="button" class="btn btn-default btn-sm cgm-ops-page-next" ${
							canNext ? "" : "disabled"
						} aria-label="${__("Next page")}">
							${__("Next")} <span aria-hidden="true">&rsaquo;</span>
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
			setTabsCount(listCountLabel());
			page.main.find(".cgm-ops-list-header").empty().css("display", "none");
			page.main.find(".cgm-ops-list-paging").empty();
			$tableWrap.html(`
				<div class="cgm-ops-empty">
					<div class="cgm-ops-empty-icon">${icon}</div>
					${message}
				</div>`);
		}

		function renderListTable(headersHtml, bodyHtml, extraHeaderRow = "") {
			$tableWrap.html(`
				<div class="cgm-ops-table-scroll">
					<table class="cgm-ops-table">
						<thead><tr>${headersHtml}</tr>${extraHeaderRow}</thead>
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
				<th class="cgm-ops-sticky-col">${__("Client")}</th>
				<th>${__("Client Reference No")}</th>
				<th>${__("CGM Ref No")}</th>
				<th>${__("B/L Number")}</th>
				<th>${__("Shipment")}</th>
				<th>${__("ETA")}</th>
				<th>${__("Operational Status")}</th>
				<th>${__("CGM Batch No")}</th>
				<th>${__("Shipping Line")}</th>
				<th>${__("Country of Origin")}</th>
				<th>${__("Clearance Station")}</th>
				<th>${__("Remarks")}</th>
				<th>${__("Container")}</th>
				<th>${__("ATA")}</th>
				<th>${__("Container Status")}</th>
				<th>${__("Container Deposit")}</th>
				<th>${__("Deposit Payment")}</th>
				<th>${__("Deposit Refund Status")}</th>
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
			const hasDeposit =
				flt(row.deposit_amount) > 0 || cint(row.has_deposit);
			if (!hasDeposit || !status || status === "Not Applicable") {
				return `<span class="cgm-ops-pill muted"><span class="dot"></span>${__("No Deposit")}</span>`;
			}
			const tone = status === "Paid" ? "success" : status === "Unpaid" ? "warning" : "muted";
			return `<span class="cgm-ops-pill ${tone}"><span class="dot"></span>${frappe.utils.escape_html(
				status
			)}</span>`;
		}

		function depositRefundStatusCell(row) {
			const label = (row.deposit_refund_display || "").trim();
			if (!label) {
				return `<span class="cgm-ops-muted">—</span>`;
			}
			// Mapped onto the board's own tones. "blue" and "gray" were
			// frappe indicator names with no equivalent in cgm-ops-pill, so
			// they became info and muted rather than silently rendering
			// unstyled.
			const toneMap = {
				success: "success",
				warning: "warning",
				blue: "info",
				muted: "muted",
			};
			const tone = toneMap[row.deposit_refund_display_tone] || "muted";
			return `<span class="cgm-ops-pill ${tone}"><span class="dot"></span>${frappe.utils.escape_html(
				label
			)}</span>`;
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
				<td>${clientReferenceCell(row)}</td>
				<td>${cgmReferenceCell(row)}</td>
				<td>${blCell(row)}</td>
				<td>${shipmentCell(row)}</td>
				<td>${fmtDate(row.eta)}</td>
				<td>${statusPill(row)}</td>
				<td>${batchCell(row)}</td>
				<td>${frappe.utils.escape_html(row.shipping_line || "—")}</td>
				<td>${frappe.utils.escape_html(row.country_of_origin || "—")}</td>
				<td>${frappe.utils.escape_html(row.clearance_station || "—")}</td>
				<td>${frappe.utils.escape_html(remarks || "—")}</td>
				<td>${trackerLink(row)}${alert}</td>
				<td>${fmtDate(row.ata)}</td>
				<td>${containerStatusCell(row.container_status)}</td>
				<td>${frappe.utils.escape_html(row.deposit_amount || 0)}</td>
				<td>${depositPaymentStatusCell(row)}</td>
				<td>${depositRefundStatusCell(row)}</td>
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

		// Only columns the server whitelists in _SHIPMENT_SORT_FIELDS are
		// sortable. The rest render as plain headers rather than offering a
		// control that would silently do nothing.
		function sortableHeader(label, field, extraClass = "") {
			const isActive = sortBy === field;
			const dir = isActive ? sortDir : "";
			return `<th class="cgm-ops-sortable${extraClass ? " " + extraClass : ""}${
				isActive ? " is-sorted" : ""
			}" data-sort="${field}" role="button" tabindex="0"
				aria-sort="${isActive ? (dir === "asc" ? "ascending" : "descending") : "none"}"
				title="${__("Sort by {0}", [label])}">
				<span class="cgm-ops-th-label">${label}</span>
				<span class="cgm-ops-sort-caret" aria-hidden="true">${
					isActive ? (dir === "asc" ? "\u25B4" : "\u25BE") : "\u21C5"
				}</span>
			</th>`;
		}

		// Delegated, because the header row is re-rendered on every refresh.
		// Row keys the server sorts on, mirrored here so a sort can be done
		// locally when the whole result set is already on screen. Kept in step
		// with _SHIPMENT_SORT_FIELDS in container_ops_board.py.
		const SORT_ROW_KEYS = {
			client_name: "customer",
			client_reference_no: "client_reference_no",
			cgm_ref_no: "cgm_ref_no",
			bill_of_lading: "bl_number",
			project_ref: "project_ref",
			eta: "eta",
			ata: "ata",
			operational_status: "operational_status",
			batch_no: "batch_no",
			shipping_line: "shipping_line",
			country_of_origin: "country_of_origin",
			clearance_station: "clearance_station",
			container_count: "quantity",
			vessel: "vessel_name",
		};

		function sortRowsLocally(rows) {
			if (!sortBy) return rows;
			const key = SORT_ROW_KEYS[sortBy];
			if (!key) return rows;

			const desc = sortDir === "desc";
			return rows.slice().sort((a, b) => {
				const av = a[key];
				const bv = b[key];
				// Blanks last in both directions: a missing B/L is absent
				// information, not the smallest value. Matches the server.
				const ab = av === null || av === undefined || av === "";
				const bb = bv === null || bv === undefined || bv === "";
				if (ab && bb) return 0;
				if (ab) return 1;
				if (bb) return -1;

				let cmp;
				if (typeof av === "number" && typeof bv === "number") {
					cmp = av - bv;
				} else {
					cmp = String(av).localeCompare(String(bv), undefined, {
						numeric: true,
						sensitivity: "base",
					});
				}
				return desc ? -cmp : cmp;
			});
		}

		function applySort(field) {
			if (!field) return;

			if (sortBy === field) {
				// Third click clears back to the server default rather than
				// trapping the user in asc/desc with no way out.
				if (sortDir === "asc") {
					sortDir = "desc";
				} else {
					sortBy = "";
					sortDir = "asc";
				}
			} else {
				sortBy = field;
				sortDir = "asc";
			}

			selectedKeys.clear();

			// If every matching row is already loaded, sorting is a local
			// operation and there is nothing to fetch. Going to the server
			// here would be a round trip to reorder data the browser already
			// holds.
			//
			// When the set IS paginated we must fetch, because sorting only
			// the rows on screen would order 20 of 41 and present it as the
			// sorted list, which is wrong rather than merely slower.
			const haveEverything =
				activeTab === "shipments" && shipmentRows.length >= totalCount && totalCount > 0;

			if (haveEverything) {
				listStart = 0;
				shipmentRows = sortRowsLocally(shipmentRows);
				renderShipmentListTable();
				return;
			}

			listStart = 0;
			refresh();
		}

		page.main.on("click", ".cgm-ops-sortable", function () {
			applySort($(this).data("sort"));
		});

		page.main.on("keydown", ".cgm-ops-sortable", function (e) {
			if (e.key === "Enter" || e.key === " ") {
				e.preventDefault();
				applySort($(this).data("sort"));
			}
		});

		function shipmentTableHeaders() {
			return `
				${selectAllHeader()}
				${sortableHeader(__("Client"), "client_name", "cgm-ops-sticky-col")}
				${sortableHeader(__("Client Reference No"), "client_reference_no")}
				${sortableHeader(__("CGM Ref No"), "cgm_ref_no")}
				${sortableHeader(__("B/L Number"), "bill_of_lading")}
				${sortableHeader(__("Shipment"), "project_ref")}
				${sortableHeader(__("ETA"), "eta")}
				${sortableHeader(__("Operational Status"), "operational_status")}
				${sortableHeader(__("CGM Batch No"), "batch_no")}
				${sortableHeader(__("Shipping Line"), "shipping_line")}
				${sortableHeader(__("Country of Origin"), "country_of_origin")}
				${sortableHeader(__("Clearance Station"), "clearance_station")}
				<th>${__("Remarks")}</th>
				${sortableHeader(__("Containers"), "container_count")}
				${sortableHeader(__("ATA"), "ata")}
				<th>${__("Container Status")}</th>
				<th>${__("Container Deposit")}</th>
				<th>${__("Deposit Payment")}</th>
				<th>${__("Deposit Refund Status")}</th>
				${sortableHeader(__("Vessel"), "vessel")}
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
				<td>${frappe.utils.escape_html(row.client_reference_no || "—")}</td>
				<td>${cgmReferenceCell(row)}</td>
				<td>${frappe.utils.escape_html(row.bl_number || "—")}</td>
				<td>${projectLink(row)}</td>
				<td>${fmtDate(row.eta)}</td>
				<td>${shipmentOperationalStatusCell(row)}</td>
				<td>${frappe.utils.escape_html(row.batch_no || "—")}</td>
				<td>${frappe.utils.escape_html(row.shipping_line || "—")}</td>
				<td>${frappe.utils.escape_html(row.country_of_origin || "—")}</td>
				<td>${frappe.utils.escape_html(row.clearance_station || "—")}</td>
				<td>${frappe.utils.escape_html(row.remarks || "—")}</td>
				<td>${frappe.utils.escape_html(row.quantity || "—")}</td>
				<td>${fmtDate(row.ata)}</td>
				<td>${containerStatusCell(row.container_status_summary)}</td>
				<td>${frappe.utils.escape_html(row.deposit_amount || 0)}</td>
				<td>${depositPaymentStatusCell(row)}</td>
				<td>${depositRefundStatusCell(row)}</td>
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
						${shipmentDetailField(__("Deposit Payment"), project.deposit_payment_status || "—", { pill: true })}
						${shipmentDetailField(__("Deposit Refund Status"), project.deposit_refund_display || "—", { pill: true })}
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
						<div class="cgm-ops-table-scroll">
							<table class="cgm-ops-table">
								<thead><tr>${transportTableHeaders()}</tr></thead>
								<tbody>${containerRows.map((row) => transportTableRow(row)).join("")}</tbody>
							</table>
						</div>`);
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
		init_kpis_collapse();
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
		__("Container Ops Board"),
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
