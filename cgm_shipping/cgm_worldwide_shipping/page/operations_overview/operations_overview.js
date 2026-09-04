frappe.pages["operations-overview"].on_page_load = function (wrapper) {
	frappe.require(["/assets/cgm_shipping/css/operations_overview.css"], () => {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Operations Overview"),
			single_column: true,
		});

		page.hide_form();
		page.main.find(".page-form.row").remove();
		page.main.addClass("cgm-mgmt");

		// This page head carries breadcrumbs, not a title: set_title writes
		// into a .title-text node the template does not have. Frappe adds the
		// breadcrumb while constructing the page, but this file runs inside an
		// async frappe.require callback, so make_app_page rebuilds the head
		// afterwards and the breadcrumb goes with it. Built the same way the
		// Container Ops Board builds its own, so the two pages sit at the same
		// level under the workspace instead of looking unrelated.
		function setup_breadcrumbs() {
			frappe.breadcrumbs.clear();
			const workspace_label =
				frappe.app.sidebar?.sidebar_title || __("CGM Shipping");
			let workspace_route = "/desk/cgm-shipping";
			if (frappe.app.sidebar?.sidebar_title) {
				const icon = frappe.utils.get_desktop_icon_by_label(
					frappe.app.sidebar.sidebar_title
				);
				const url = frappe.utils.get_route_for_icon(icon);
				if (url) workspace_route = url;
			}
			frappe.breadcrumbs.append_breadcrumb_element(
				workspace_route,
				workspace_label,
				"worksapce-breadcrumb"
			);
			frappe.breadcrumbs.append_breadcrumb_element(
				"/desk/operations-overview",
				__("Operations Overview"),
				"title-text"
			);
			frappe.breadcrumbs.toggle(true);
		}

		setup_breadcrumbs();
		// Re-applied on the next tick as well: anything that rebuilds the page
		// head after this callback would otherwise leave the head blank again,
		// which is exactly how the title went missing in the first place.
		setTimeout(setup_breadcrumbs, 0);
		page.wrapper.on("show", setup_breadcrumbs);

		const METHOD = "cgm_shipping.cgm_worldwide_shipping.page.operations_overview.operations_overview";
		const filters = {
			date_from: null,
			date_to: null,
			shipping_line: null,
			customer: null,
			project: null,
			status: null,
			cargo_size: null,
			currency: null,
		};
		const filter_controls = {};
		let data = null;
		let options = {};

		page.main.append(`
			<div class="cgm-mgmt-top">
				<div class="cgm-mgmt-subtitle">
					<span class="cgm-mgmt-status"></span>
					<span class="cgm-mgmt-stamp"></span>
				</div>
				<div class="cgm-mgmt-filters"></div>
			</div>
			<div class="cgm-mgmt-kpis"></div>
			<div class="cgm-mgmt-hidden-note" style="display:none"></div>
			<div class="cgm-mgmt-grid"></div>
		`);

		// add_action_icon rather than set_primary_action: this page has no
		// primary action to commit, refreshing is just a convenience, and a
		// filled button implied otherwise.
		page.add_action_icon("refresh", () => load(), "", __("Refresh"));
		page.add_menu_item(__("Open Container Ops Board"), () =>
			frappe.set_route("container-ops-board")
		);

		// ---------- helpers ----------

		const esc = (v) => frappe.utils.escape_html(String(v === null || v === undefined ? "" : v));

		function fmtNumber(v) {
			// Deliberately not frappe.format: its Int formatter returns
			// right-aligned markup, which put the integer cards out of step
			// with the currency ones sitting beside them in the same grid.
			const n = Number(v || 0);
			return esc(n.toLocaleString(frappe.boot.lang === "en" ? "en-US" : undefined));
		}

		function fmtMoney(v, currency) {
			// frappe.format is (value, df, options, doc) and resolves the
			// symbol from doc[df.options]. Passing {currency} third put it in
			// options, where it was ignored, so every amount fell back to the
			// site default and USD figures rendered with the shilling symbol.
			return frappe.format(
				v,
				{ fieldtype: "Currency", options: "currency" },
				null,
				{ currency: currency || (data && data.currency) }
			);
		}

		function containersLabel(n) {
			return n === 1 ? __("1 container") : __("{0} containers", [n]);
		}

		// A severity only ever comes from the server. The UI must not invent
		// one, otherwise two places would decide what "bad" means and they
		// would drift apart.
		const SEV_LABEL = {
			warn: __("Watch"),
			critical: __("Action"),
			nodata: __("No data"),
		};

		function renderFilters() {
			const $wrap = page.main.find(".cgm-mgmt-filters").empty();
			// Select options come from the data rather than a hardcoded list,
			// so a status or currency that is never used never appears.
			const asSelect = (values) => [""].concat(values || []);
			const fields = [
				{
					// "Arrival Between" did not say which date, nor that it
					// also moves the profit and loss window. Past tense reads
					// as a fact about the container rather than a schedule.
					fieldname: "date_range",
					label: __("Arrived Between"),
					fieldtype: "DateRange",
				},
				{
					fieldname: "customer",
					label: __("Client"),
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
					fieldname: "shipping_line",
					label: __("Shipping Line"),
					fieldtype: "Select",
					options: asSelect(options.shipping_lines),
				},
				{
					fieldname: "status",
					label: __("Status"),
					fieldtype: "Select",
					options: asSelect(options.statuses),
				},
				{
					fieldname: "cargo_size",
					label: __("Size"),
					fieldtype: "Select",
					options: asSelect(options.cargo_sizes),
				},
			];
			fields.forEach((df) => {
				const $f = $(`<div class="cgm-mgmt-filter-field cgm-mgmt-filter-${df.fieldname}"></div>`).appendTo($wrap);
				const control = frappe.ui.form.make_control({
					df: {
						...df,
						placeholder: df.label,
						onchange: () => onFilterChange(df.fieldname),
					},
					parent: $f,
					render_input: true,
				});
				control.refresh();
				// df.onchange alone is not enough: Select and Link controls
				// can set their value without firing it, which left the
				// filter looking applied while the numbers never moved. The
				// native events are listened to as well, and the reload is
				// debounced so the two paths cannot fire two requests.
				if (control.$input) {
					control.$input.on("change awesomplete-selectcomplete", () =>
						onFilterChange(df.fieldname)
					);
				}
				filter_controls[df.fieldname] = control;
			});
		}

		let filterTimer = null;
		function onFilterChange(fieldname) {
			applyFilterValue(fieldname);
			clearTimeout(filterTimer);
			filterTimer = setTimeout(load, 120);
		}

		function applyFilterValue(fieldname) {
			const control = filter_controls[fieldname];
			if (!control) return;
			const value = control.get_value();
			if (fieldname === "date_range") {
				const range = Array.isArray(value) ? value : null;
				filters.date_from = (range && range[0]) || null;
				filters.date_to = (range && range[1]) || null;
				return;
			}
			filters[fieldname] = value || null;
		}

		// ---------- headline ----------

		function renderKpis(cards) {
			// A card that ignores the active filter is removed rather than
			// left sitting beside filtered ones, where it would be read as an
			// answer to the filter.
			const html = (cards || [])
				.filter((c) => c.applies !== false)
				.map((c) => {
					const sev = c.severity || "ok";
					// Only critical pulses. If several states animated, the
					// page would shimmer and nothing would stand out.
					const pulse = sev === "critical" ? " is-pulsing" : "";
					// The flag sits on the same line as the value rather than
					// on a row of its own: it saves a line of card height and,
					// being in normal flow, it cannot overlap the number the
					// way an absolutely positioned badge did.
					const flag = SEV_LABEL[sev]
						? `<span class="flag">${esc(SEV_LABEL[sev])}</span>`
						: "";
					const value =
						c.format === "currency"
							? fmtMoney(c.value, data && data.currency)
							: fmtNumber(c.value);
					// The card is a real button when it can drill through, so
					// it is reachable by keyboard and announced as clickable.
					const clickable = c.route ? " is-clickable" : "";
					const tag = c.route ? "button" : "div";
					const attrs = c.route
						? ` type="button" data-kpi="${esc(c.key)}" title="${__("Open the records behind this number")}"`
						: "";
					return `<${tag} class="cgm-mgmt-kpi sev-${esc(sev)}${pulse}${clickable}"${attrs}>
						<div class="cgm-mgmt-kpi-head">
							<span class="value">${value}</span>
							${flag}
						</div>
						<div class="label">${esc(c.label)}</div>
						<div class="hint">${esc(c.hint)}</div>
					</${tag}>`;
				})
				.join("");
			page.main.find(".cgm-mgmt-kpis").html(html);
		}

		page.main.on("click", ".cgm-mgmt-chip", function () {
			const value = $(this).data("currency");
			filters.currency = value === "" ? null : value;
			load();
		});

		// Routes are built on the server next to the queries that produce the
		// numbers, so the list a click opens always matches what was counted.
		page.main.on("click", ".cgm-mgmt-kpi.is-clickable", function () {
			const key = $(this).data("kpi");
			const card = ((data && data.headline) || []).find((c) => c.key === key);
			if (!card || !card.route) return;
			showCardDialog(card);
		});

		// A dialog rather than a route change: the dashboard is a scanning
		// view, and navigating away to a list meant losing the filters, the
		// scroll position and the panel below that prompted the click. The
		// list view is still one button away for anyone who wants to work
		// through the records properly.
		function showCardDialog(card) {
			const d = new frappe.ui.Dialog({
				title: card.label,
				size: "extra-large",
				primary_action_label: __("Open full list"),
				primary_action: () => {
					d.hide();
					// Filters travel in route_options; set_route builds the
					// URL from its arguments only.
					frappe.route_options = card.route.filters || {};
					frappe.set_route("List", card.route.doctype);
				},
			});
			// Scoped class on the wrapper: the styling below is for this
			// dialog only, so it cannot leak into every other frappe dialog
			// on the site.
			d.$wrapper.addClass("cgm-mgmt-dialog");
			d.$body.html(`<div class="cgm-mgmt-dialog-loading">${__("Loading…")}</div>`);
			d.show();

			frappe.call({
				method: `${METHOD}.get_card_records`,
				args: { key: card.key, filters },
				callback: (r) => {
					const res = r.message;
					if (!res || !res.rows || !res.rows.length) {
						d.$body.html(
							`<div class="cgm-mgmt-dialog-empty">${__("No records behind this number")}</div>`
						);
						return;
					}
					renderCardBody(d, res);
				},
			});
		}

		// Cells are built once and kept with a lowercased haystack of their
		// own display text. Searching then matches what the reader can
		// actually see, including formatted dates, rather than the raw field
		// values underneath them.
		function buildCardRows(res) {
			return res.rows.map((row) => {
				const display = res.columns.map((col) => {
					const raw = row[col.field];
					if (raw === null || raw === undefined || raw === "") {
						return { html: `<span class="muted">—</span>`, text: "" };
					}
					if (col.type === "Date") {
						const t = frappe.datetime.str_to_user(raw);
						return { html: esc(t), text: String(t) };
					}
					if (col.type === "Int") {
						return { html: fmtNumber(raw), text: String(raw) };
					}
					if (col.type === "Link") {
						const slug = frappe.scrub(res.doctype).replace(/_/g, "-");
						return {
							html: `<a href="/app/${encodeURIComponent(slug)}/${encodeURIComponent(
								row.name
							)}">${esc(raw)}</a>`,
							text: String(raw),
						};
					}
					return { html: esc(raw), text: String(raw) };
				});
				return {
					cells: display.map((d2) => d2.html),
					haystack: display.map((d2) => d2.text).join(" ").toLowerCase(),
					// Raw values kept beside the formatted ones: totals are
					// summed from the numbers, never parsed back out of the
					// rendered text.
					values: res.columns.map((col) => row[col.field]),
				};
			});
		}

		function renderCardBody(d, res) {
			const built = buildCardRows(res);
			const head =
				`<th class="rownum">#</th>` +
				res.columns.map((col) => `<th>${esc(col.label)}</th>`).join("");

			// Only quantities are worth totalling. Summing a status or a
			// container number would be noise, and summing a date is
			// meaningless, so the footer is built solely from numeric columns
			// and is skipped entirely when there are none.
			const numericCols = res.columns
				.map((col, i) => ({ col, i }))
				.filter(({ col }) => col.type === "Int" || col.type === "Currency");

			d.$body.html(`
				<div class="cgm-mgmt-dialog-bar">
					<input type="text" class="form-control cgm-mgmt-dialog-search"
						placeholder="${__("Search these records…")}" autocomplete="off">
					<span class="cgm-mgmt-dialog-note"></span>
				</div>
				<div class="cgm-mgmt-dialog-scroll">
					<table class="cgm-mgmt-dialog-table">
						<thead><tr>${head}</tr></thead>
						<tbody></tbody>
						${numericCols.length ? "<tfoot></tfoot>" : ""}
					</table>
				</div>
			`);

			const $note = d.$body.find(".cgm-mgmt-dialog-note");
			const $tbody = d.$body.find("tbody");
			const $tfoot = d.$body.find("tfoot");
			const $search = d.$body.find(".cgm-mgmt-dialog-search");

			// Totals are recomputed against whatever is on screen, so a
			// search narrows the total with the rows. A footer left showing
			// the unfiltered sum beside filtered rows would be wrong.
			function renderTotals(matched) {
				if (!numericCols.length) return;
				const sums = {};
				numericCols.forEach(({ i }) => {
					sums[i] = matched.reduce(
						(acc, r) => acc + (Number(r.values[i]) || 0),
						0
					);
				});
				const label =
					matched.length === 1
						? __("Total of 1 row")
						: __("Total of {0} rows", [matched.length]);
				const cells = res.columns
					.map((col, i) => {
						if (!(i in sums)) return "<td></td>";
						const v =
							col.type === "Currency"
								? fmtMoney(sums[i], res.currency)
								: fmtNumber(sums[i]);
						return `<td class="total-value">${v}</td>`;
					})
					.join("");
				$tfoot.html(
					`<tr><td class="rownum total-label" colspan="1">&Sigma;</td>${cells}</tr>` +
						`<tr class="total-caption"><td colspan="${
							res.columns.length + 1
						}">${esc(label)}</td></tr>`
				);
			}

			function paint(term) {
				const q = (term || "").trim().toLowerCase();
				const matched = q ? built.filter((r) => r.haystack.includes(q)) : built;

				$tbody.html(
					matched.length
						? matched
								// Renumbered against the filtered set, so the
								// numbers stay contiguous instead of showing the
								// gaps of whatever was filtered out.
								.map(
									(r, i) =>
										`<tr><td class="rownum">${fmtNumber(i + 1)}</td>${r.cells
											.map((cell) => `<td>${cell}</td>`)
											.join("")}</tr>`
								)
								.join("")
						: `<tr><td colspan="${res.columns.length + 1}" class="cgm-mgmt-dialog-empty">${__(
								"Nothing matches that search"
						  )}</td></tr>`
				);

				renderTotals(matched);

				// The search only sees the rows that were loaded. When the set
				// was capped, that is said plainly rather than letting a search
				// over part of the data look like a search over all of it.
				const capped = res.total > res.shown;
				if (q) {
					$note.text(
						capped
							? __("{0} of the {1} loaded rows match. {2} records in total.", [
									matched.length,
									res.shown,
									res.total,
							  ])
							: __("{0} of {1} match", [matched.length, res.total])
					);
				} else {
					$note.text(
						capped
							? __("Showing the first {0} of {1}. Open the full list to see them all.", [
									res.shown,
									res.total,
							  ])
							: __("{0} records", [res.total])
					);
				}
			}

			let searchTimer = null;
			$search.on("input", function () {
				const value = this.value;
				clearTimeout(searchTimer);
				searchTimer = setTimeout(() => paint(value), 120);
			});

			paint("");
			// Focus the search so the dialog is usable from the keyboard the
			// moment it opens.
			setTimeout(() => $search.focus(), 60);
		}

		// The strapline that used to sit here said the same thing on every
		// visit. This says what is actually wrong today, counted from the same
		// severities the cards use, so the two can never disagree.
		function renderStatusLine() {
			const cards = (data && data.headline) || [];
			const critical = cards.filter((c) => c.severity === "critical");
			const warn = cards.filter((c) => c.severity === "warn");
			const blind = cards.filter((c) => c.severity === "nodata");

			const parts = [];
			if (critical.length) {
				parts.push(
					critical.length === 1
						? __("1 issue needs action")
						: __("{0} issues need action", [critical.length])
				);
			}
			if (warn.length) {
				parts.push(__("{0} to watch", [warn.length]));
			}
			if (blind.length) {
				parts.push(__("{0} not tracked", [blind.length]));
			}

			const tone = critical.length ? "critical" : warn.length ? "warn" : "ok";
			// Only critical and warn carry a name worth listing. When the only
			// finding is "not tracked" there is nothing to name, and the
			// summary must not end on a dangling colon.
			const named = critical.concat(warn).map((c) => c.label);
			let text;
			if (!parts.length) {
				text = __("Nothing needs action right now");
			} else if (named.length) {
				text = `${parts.join(", ")}: ${named.join(", ")}`;
			} else {
				text = parts.join(", ");
			}

			page.main
				.find(".cgm-mgmt-status")
				.html(`<span class="tag tone-${tone}">${esc(text)}</span>`);
		}

		const SECTION_LABELS = {
			compliance: __("Documentation and Compliance"),
			financials: __("Income, receivables and payables"),
			cycle: __("Container flow"),
			exposure: __("Cost exposure"),
			mix: __("Container status"),
			commercial: __("Top clients"),
		};

		// Panels disappearing with no explanation reads as a bug. This says
		// which ones went and why, so their absence is a statement rather
		// than a gap.
		function renderHiddenNote(hidden) {
			const $note = page.main.find(".cgm-mgmt-hidden-note");
			if (!hidden || !hidden.size) {
				$note.empty().hide();
				return;
			}
			const names = Array.from(hidden).map((s) => SECTION_LABELS[s] || s);
			$note
				.html(
					`<span class="tag">${esc(
						__("Hidden while filtered, because they do not respond to it: {0}", [
							names.join(", "),
						])
					)}</span>`
				)
				.show();
		}

		// ---------- panel building blocks ----------

		function panel(title, note, body, wide) {
			return `<div class="cgm-mgmt-panel${wide ? " is-wide" : ""}">
				<div class="cgm-mgmt-panel-head">
					<span class="cgm-mgmt-panel-title">${esc(title)}</span>
					<span class="cgm-mgmt-panel-note">${esc(note || "")}</span>
				</div>
				<div class="cgm-mgmt-panel-body">${body}</div>
			</div>`;
		}

		function row(name, num, sub, barPct, barTone) {
			// A 2% minimum keeps a small value visible, but applying it to
			// zero drew a stub bar for rows with nothing in them, so six
			// shipping lines on 0 days all looked like they had some.
			const width =
				barPct > 0 ? Math.max(2, Math.min(100, barPct)) : 0;
			const bar =
				barPct === null || barPct === undefined
					? ""
					: `<div class="cgm-mgmt-bar${barTone ? " is-" + barTone : ""}"><span style="width:${width}%"></span></div>`;
			return `<div class="cgm-mgmt-row">
				<span class="name">${esc(name)}</span>
				<span class="num">${num}${sub ? `<span class="sub">${esc(sub)}</span>` : ""}</span>
				${bar}
			</div>`;
		}

		function empty(msg) {
			return `<div class="cgm-mgmt-empty">${esc(msg)}</div>`;
		}

		function callout(tone, html) {
			return `<div class="cgm-mgmt-callout tone-${tone}">${html}</div>`;
		}

		// ---------- panels ----------

		function containerFlowPanel(cycle) {
			let body = "";
			if (cycle.bottleneck) {
				// Spelled out rather than "slowest leg": the stage is named by
				// both its endpoints, the average is labelled as days spent,
				// and the sample is described instead of shown as "n=".
				body += callout(
					"warn",
					__(
						"Containers spend longest at <strong>{0}</strong>: {1} days on average across {2} containers, with the slowest taking {3} days.",
						[
							esc(cycle.bottleneck.label),
							esc(cycle.bottleneck.avg_days),
							esc(cycle.bottleneck.sample),
							esc(cycle.bottleneck.max_days),
						]
					)
				);
			}
			// Schedule slip is reported on its own, because it is the shipping
			// line missing its ETA rather than time spent working the box.
			const sch = cycle.schedule || {};
			if (sch.sample) {
				const d = sch.avg_days;
				const text =
					d > 0
						? __(
								"Vessels arrived <strong>{0} days late</strong> against ETA on average. {1} of {2} arrived after their ETA.",
								[esc(d), esc(sch.late), esc(sch.sample)]
						  )
						: d < 0
						? __("Vessels arrived <strong>{0} days early</strong> against ETA on average.", [
								esc(Math.abs(d)),
						  ])
						: __("Vessels arrived on their ETA on average.");
				body += callout(d > 2 ? "warn" : "info", text);
			}
			if (cycle.avg_port_dwell !== null && cycle.avg_port_dwell !== undefined) {
				body += callout(
					cycle.dwell_severity === "critical" ? "critical" : "info",
					__("Containers still in port have been there <strong>{0} days</strong> on average.", [
						esc(cycle.avg_port_dwell),
					])
				);
			}
			const legs = cycle.legs || [];
			const worst = Math.max(1, ...legs.map((l) => l.avg_days || 0));
			body += legs
				.map((l) => {
					if (!l.sample) {
						return row(l.label, `<span class="cgm-mgmt-pill tone-muted">${__("no data")}</span>`, "", null);
					}
					const tone = l.avg_days >= 7 ? "critical" : l.avg_days >= 4 ? "warn" : null;
					// The sample size is shown next to every average. Without
					// it a 1-container average reads with the same authority
					// as a 20-container one.
					// The longest case is shown beside the average because at
					// these volumes one stuck container moves the mean a long
					// way: "4.6 days, longest 20" reads as one outlier, while
					// "4.6 days" alone reads as a slow stage.
					const count =
						containersLabel(l.sample);
					const sample =
						l.max_days > l.avg_days
							? __("{0} · longest {1}d", [count, l.max_days])
							: count;
					return row(
						l.label,
						// "1 days" otherwise, which is what an average landing
						// exactly on a whole number produces.
						l.avg_days === 1 ? __("1 day") : __("{0} days", [l.avg_days]),
						sample,
						(l.avg_days / worst) * 100,
						tone
					);
				})
				.join("");
			return panel(
				__("Container Flow"),
				__("average days spent at each stage"),
				body || empty(__("No journey dates recorded"))
			);
		}

		function ageingPanel(cycle) {
			const buckets = cycle.ageing || [];
			const total = buckets.reduce((s, b) => s + b.count, 0);
			let body = "";
			if (!total) {
				body = empty(__("Nothing sitting in port"));
			} else {
				body = buckets
					.map((b) =>
						row(
							b.label,
							fmtNumber(b.count),
							"",
							(b.count / total) * 100,
							b.critical && b.count ? "critical" : b.count ? "warn" : null
						)
					)
					.join("");
			}
			if (cycle.reversed_dates) {
				// Surfaced deliberately. Management should know when the
				// numbers above rest on records that contradict themselves.
				body += callout(
					"warn",
					__("<strong>{0}</strong> records have a milestone date earlier than the one before it. Those are excluded from the averages.", [
						esc(cycle.reversed_dates),
					])
				);
			}
			return panel(__("Time in Port"), __("since vessel arrival"), body);
		}

		function exposurePanel(exposure, currency) {
			// The currency choice sits in this panel rather than in the global
			// filter bar because it changes nothing else on the page. As a
			// global filter it looked like it applied to container counts and
			// open jobs too, which it never did.
			const available = options.currencies || [];
			let body = "";
			if (available.length > 1) {
				const active = exposure.currency_filter || "";
				body +=
					`<div class="cgm-mgmt-chips" role="group" aria-label="${__("Charge currency")}">` +
					[{ v: "", l: __("All currencies") }]
						.concat(available.map((x) => ({ v: x, l: x })))
						.map(
							(o) =>
								`<button type="button" class="cgm-mgmt-chip${
									o.v === active ? " is-active" : ""
								}" data-currency="${esc(o.v)}" aria-pressed="${o.v === active}">${esc(
									o.l
								)}</button>`
						)
						.join("") +
					"</div>";
			}
			const money = [];
			// "Demurrage · KES · 4 containers" read as three unrelated tags.
			// Spelled out instead: what the charge is, then how many
			// containers it is spread across, with the count pluralised.
			const across = (n) => __("across {0}", [containersLabel(n)]);
			const moneyTile = (label, d) =>
				`<div class="cgm-mgmt-money-item">
					<div class="amt">${fmtMoney(d.amount, d.currency)}</div>
					<div class="cur">${esc(label)} <span class="code">${esc(d.currency)}</span></div>
					<div class="sub">${esc(across(d.containers))}</div>
				</div>`;
			(exposure.demurrage || []).forEach((d) => money.push(moneyTile(__("Demurrage"), d)));
			(exposure.kpa || []).forEach((d) => money.push(moneyTile(__("KPA port charges"), d)));
			// Deliberately not summed into one figure: these are held in
			// different currencies, and adding them would invent a number.
			body += money.length
				? `<div class="cgm-mgmt-money">${money.join("")}</div>`
				: empty(__("No charges posted"));

			const lines = exposure.by_line || [];
			const worst = Math.max(1, ...lines.map((l) => l.demurrage_days || 0));
			body += lines.length
				? lines
						.map((l) =>
							row(
								l.line,
								__("{0}d", [l.demurrage_days || 0]),
								containersLabel(l.containers),
								((l.demurrage_days || 0) / worst) * 100,
								l.demurrage_days >= 20 ? "critical" : l.demurrage_days ? "warn" : null
							)
						)
						.join("")
				: "";
			// The amounts above respond to the currency chip; the day counts
			// below cannot, because a day is not denominated in anything. Said
			// plainly, otherwise the lower half looks like it ignored the chip.
			const note = exposure.currency_filter
				? __("amounts in {0} · days below are not currency specific", [
						exposure.currency_filter,
				  ])
				: __("demurrage days by shipping line");
			return panel(__("Cost Exposure"), note, body);
		}

		function clientPanel(exposure) {
			const rows = exposure.by_client || [];
			const worst = Math.max(1, ...rows.map((r) => r.containers || 0));
			const body = rows.length
				? rows
						.map((r) =>
							row(
								r.client,
								fmtNumber(r.containers),
								r.demurrage_days
									? __("{0}d demurrage, {1} in port", [r.demurrage_days, r.at_port])
									: __("{0} in port", [r.at_port]),
								((r.containers || 0) / worst) * 100,
								r.demurrage_days >= 20 ? "critical" : r.demurrage_days ? "warn" : null
							)
						)
						.join("")
				: empty(__("No containers in the selected period"));
			return panel(__("Client Exposure"), __("containers and demurrage"), body);
		}

		function mixPanel(mix) {
			const st = mix.status || [];
			const total = st.reduce((s, r) => s + r.count, 0);
			const body = st.length
				? st.map((r) => row(r.label, fmtNumber(r.count), "", (r.count / (total || 1)) * 100)).join("")
				: empty(__("No containers"));
			return panel(__("Container Status"), __("current mix"), body);
		}

		function locationPanel(mix) {
			const loc = mix.location || [];
			const total = loc.reduce((s, r) => s + r.count, 0);
			const body = loc.length
				? loc.map((r) => row(r.label, fmtNumber(r.count), "", (r.count / (total || 1)) * 100)).join("")
				: empty(__("No locations recorded"));
			return panel(__("Where Containers Are"), __("current location"), body);
		}

		function compliancePanel(c) {
			let body = "";
			body += row(__("Bills of Lading submitted"), fmtNumber(c.bol.submitted), "", null);
			body += row(
				__("Bills of Lading in draft"),
				c.bol.draft
					? `<span class="cgm-mgmt-pill tone-warn">${fmtNumber(c.bol.draft)}</span>`
					: fmtNumber(0),
				"",
				null
			);
			body += row(
				__("IDF / UCR not submitted"),
				c.idf.draft
					? `<span class="cgm-mgmt-pill tone-warn">${fmtNumber(c.idf.draft)}</span>`
					: fmtNumber(0),
				"",
				null
			);
			body += row(
				__("Permits not yet closed"),
				c.permits_open
					? `<span class="cgm-mgmt-pill tone-warn">${fmtNumber(c.permits_open)}</span>`
					: fmtNumber(0),
				"",
				null
			);
			if ((c.licences || []).length) {
				body += callout(
					"critical",
					__("<strong>{0}</strong> licences expired or expiring within 60 days.", [c.licences.length])
				);
				body += c.licences
					.map((l) =>
						row(
							l.license_type || l.name,
							// The second argument is a raw HTML slot, so it is
							// escaped here; the third is escaped inside row()
							// already and must be passed through untouched.
							l.days_to_expiry === null || l.days_to_expiry === undefined
								? esc(l.status)
								: __("{0}d", [l.days_to_expiry]),
							l.status,
							null
						)
					)
					.join("");
			}
			return panel(__("Documentation and Compliance"), __("clearance blockers"), body);
		}

		function permitPanel(c) {
			const rows = c.permits || [];
			const total = rows.reduce((s, r) => s + r.count, 0);
			const body = rows.length
				? rows.map((r) => row(r.label, fmtNumber(r.count), "", (r.count / (total || 1)) * 100)).join("")
				: empty(__("No permits registered"));
			return panel(__("Permits by Status"), __("{0} total", [total]), body);
		}

		function incomeExpensePanel(f) {
			const cur = f.currency;
			const scale = Math.max(1, f.income, f.expense);
			let body = `<div class="cgm-mgmt-money">
				<div class="cgm-mgmt-money-item"><div class="amt">${fmtMoney(f.income, cur)}</div>
					<div class="cur">${__("Income")}</div></div>
				<div class="cgm-mgmt-money-item"><div class="amt">${fmtMoney(f.expense, cur)}</div>
					<div class="cur">${__("Expense")}</div></div>
				<div class="cgm-mgmt-money-item"><div class="amt ${f.net < 0 ? "is-neg" : "is-pos"}">${fmtMoney(
				f.net,
				cur
			)}</div>
					<div class="cur">${__("Net")}${
			f.margin === null || f.margin === undefined ? "" : ` · ${f.margin}% ${__("margin")}`
		}</div></div>
			</div>`;

			body += row(__("Income"), fmtMoney(f.income, cur), "", (f.income / scale) * 100, "ok");
			body += row(__("Expense"), fmtMoney(f.expense, cur), "", (f.expense / scale) * 100, "warn");

			const trend = f.trend || [];
			// A healthy full-period margin can still hide months that lost
			// money, so the monthly split is shown rather than the total alone.
			const losing = trend.filter((t) => t.net < 0);
			if (losing.length) {
				body += callout(
					losing.length > trend.length / 2 ? "critical" : "warn",
					__("<strong>{0} of {1}</strong> months in this period ran at a loss.", [
						losing.length,
						trend.length,
					])
				);
			}
			if (trend.length) {
				const tScale = Math.max(1, ...trend.map((t) => Math.max(t.income, t.expense)));
				body += trend
					.map(
						(t) => `<div class="cgm-mgmt-row cgm-mgmt-trend">
							<span class="name">${esc(t.label)}</span>
							<span class="num ${t.net < 0 ? "is-neg" : "is-pos"}">${fmtMoney(t.net, cur)}</span>
							<div class="cgm-mgmt-dual">
								<div class="cgm-mgmt-bar is-ok"><span style="width:${(t.income / tScale) * 100}%"></span></div>
								<div class="cgm-mgmt-bar is-warn"><span style="width:${(t.expense / tScale) * 100}%"></span></div>
							</div>
						</div>`
					)
					.join("");
			}
			return panel(
				__("Income vs Expense"),
				`${f.period_label} · ${f.period_from} → ${f.period_to}`,
				body
			);
		}

		function arApPanel(f) {
			const cur = f.currency;
			const ar = f.receivable || {};
			const ap = f.payable || {};
			const scale = Math.max(1, ar.amount || 0, ap.amount || 0);
			let body = `<div class="cgm-mgmt-money">
				<div class="cgm-mgmt-money-item"><div class="amt">${fmtMoney(ar.amount || 0, cur)}</div>
					<div class="cur">${__("Receivables")} · ${esc(ar.count || 0)} ${__("invoices")}</div></div>
				<div class="cgm-mgmt-money-item"><div class="amt">${fmtMoney(ap.amount || 0, cur)}</div>
					<div class="cur">${__("Payables")} · ${esc(ap.count || 0)} ${__("bills")}</div></div>
				<div class="cgm-mgmt-money-item"><div class="amt ${
					f.working_position < 0 ? "is-neg" : "is-pos"
				}">${fmtMoney(f.working_position, cur)}</div>
					<div class="cur">${__("Net position")}</div></div>
			</div>`;

			body += row(__("Owed to us"), fmtMoney(ar.amount || 0, cur),
				ar.overdue_count ? __("{0} overdue", [ar.overdue_count]) : "",
				((ar.amount || 0) / scale) * 100, ar.overdue_amount ? "critical" : "ok");
			body += row(__("Owed by us"), fmtMoney(ap.amount || 0, cur),
				ap.overdue_count ? __("{0} overdue", [ap.overdue_count]) : "",
				((ap.amount || 0) / scale) * 100, ap.overdue_amount ? "critical" : null);

			[["receivable", __("Receivables ageing")], ["payable", __("Payables ageing")]].forEach(
				([key, heading]) => {
					const buckets = (f[key] || {}).ageing || [];
					if (!buckets.some((b) => b.amount)) return;
					const maxAmt = Math.max(1, ...buckets.map((b) => b.amount || 0));
					body += `<div class="cgm-mgmt-subhead">${esc(heading)}</div>`;
					body += buckets
						.map((b) =>
							row(b.label, fmtMoney(b.amount, cur),
								b.count ? __("{0} docs", [b.count]) : "",
								((b.amount || 0) / maxAmt) * 100,
								b.critical && b.amount ? "critical" : b.amount ? "warn" : null)
						)
						.join("");
				}
			);
			return panel(__("Receivables vs Payables"), __("outstanding both ways"), body);
		}

		function expenseBreakdownPanel(f) {
			const cur = f.currency;
			const rows = f.top_expenses || [];
			const worst = Math.max(1, ...rows.map((r) => r.amount || 0));
			const body = rows.length
				? rows
						.map((r) =>
							row(r.account, fmtMoney(r.amount, cur), "", ((r.amount || 0) / worst) * 100, "warn")
						)
						.join("")
				: empty(__("No expenses posted in this period"));
			return panel(__("Where the Money Goes"), __("largest expense accounts"), body);
		}

		function topClientPanel(cm) {
			const rows = cm.top_clients || [];
			const worst = Math.max(1, ...rows.map((r) => r.containers || 0));
			const body = rows.length
				? rows
						.map((r) =>
							row(
								r.client,
								fmtNumber(r.containers),
								__("{0} jobs", [r.jobs]),
								((r.containers || 0) / worst) * 100
							)
						)
						.join("")
				: empty(__("No client activity"));
			return panel(__("Top Clients by Volume"), __("containers handled"), body);
		}

		// Panels hold wildly different amounts of content: a four row status
		// mix next to a twelve row ledger. In a plain grid each row is as tall
		// as its tallest member, so a short panel beside a long one leaves a
		// block of dead space. Ordering the panels by their measured height
		// puts similarly sized panels next to each other, which makes every
		// row roughly uniform and removes most of that gap.
		//
		// Height is measured rather than assumed because it depends on the
		// data and on the column width, both of which change.
		let arrangeFrame = null;
		let pendingScroll = null;
		let pendingFocus = null;

		function restoreAfterRender() {
			// Runs once the panels have been reordered, which is the last
			// thing that can change the page height.
			if (pendingScroll !== null) {
				window.scrollTo(0, pendingScroll);
				pendingScroll = null;
			}
			if (pendingFocus !== null) {
				const sel = `.cgm-mgmt-chip[data-currency="${pendingFocus}"]`;
				const el = page.main.find(sel).get(0);
				if (el) el.focus({ preventScroll: true });
				pendingFocus = null;
			}
		}

		function arrangePanelsByHeight() {
			const $grid = page.main.find(".cgm-mgmt-grid");
			const panels = $grid.children(".cgm-mgmt-panel").toArray();
			if (panels.length < 2) return;

			const measured = panels.map((el, i) => ({
				el,
				// Ties keep their original order, so the arrangement is
				// deterministic and panels do not shuffle between refreshes
				// when their content has not changed.
				index: i,
				height: el.getBoundingClientRect().height,
				wide: el.classList.contains("is-wide"),
			}));
			measured.sort((a, b) => {
				if (a.wide !== b.wide) return a.wide ? -1 : 1;
				if (b.height !== a.height) return b.height - a.height;
				return a.index - b.index;
			});
			const frag = document.createDocumentFragment();
			measured.forEach((m) => frag.appendChild(m.el));
			$grid.get(0).appendChild(frag);
		}

		function arrangeAndRestore() {
			arrangePanelsByHeight();
			restoreAfterRender();
		}

		function scheduleArrange() {
			// Measure after the browser has laid the panels out, otherwise
			// every height reads as zero.
			if (arrangeFrame) cancelAnimationFrame(arrangeFrame);
			arrangeFrame = requestAnimationFrame(() => {
				arrangeFrame = null;
				arrangeAndRestore();
			});
		}

		let resizeTimer = null;
		$(window).on("resize.cgmMgmt", () => {
			// Column count and therefore panel height change with the
			// viewport, so the order is recomputed after resizing settles.
			clearTimeout(resizeTimer);
			resizeTimer = setTimeout(() => {
				const el = page.main && page.main.get(0);
				if (el && !el.isConnected) {
					$(window).off("resize.cgmMgmt");
					return;
				}
				if (boardIsLive()) scheduleArrange();
			}, 180);
		});

		// jQuery does not fire a "remove" event, so the previous cleanup here
		// never ran and the handler kept firing for a page that was no longer
		// on screen. Frappe keeps page wrappers in the DOM and hides them, so
		// the handler checks visibility and unbinds itself once the page is
		// genuinely gone.
		function boardIsLive() {
			const el = page.main && page.main.get(0);
			return !!(el && el.isConnected && el.offsetParent !== null);
		}

		function render() {
			if (!data) return;
			renderStatusLine();
			page.main.find(".cgm-mgmt-stamp").text(__("Updated {0}", [data.generated_on]));
			renderKpis(data.headline);

			// Each panel is tagged with the section it reads from, so a
			// section the filter does not reach takes its panels with it
			// instead of showing unfiltered numbers among filtered ones.
			const applies = data.applies || {};
			const panels = [
				["cycle", () => containerFlowPanel(data.cycle)],
				["cycle", () => ageingPanel(data.cycle)],
				["exposure", () => exposurePanel(data.exposure, data.currency)],
				["exposure", () => clientPanel(data.exposure)],
				["mix", () => mixPanel(data.mix)],
				["mix", () => locationPanel(data.mix)],
				["compliance", () => compliancePanel(data.compliance)],
				["compliance", () => permitPanel(data.compliance)],
				["financials", () => incomeExpensePanel(data.financials)],
				["financials", () => arApPanel(data.financials)],
				["financials", () => expenseBreakdownPanel(data.financials)],
				["commercial", () => topClientPanel(data.commercial)],
			];
			const hidden = new Set(
				panels.filter(([s]) => applies[s] === false).map(([s]) => s)
			);
			page.main.find(".cgm-mgmt-grid").html(
				panels
					.filter(([section]) => applies[section] !== false)
					.map(([, build]) => build())
					.join("")
			);
			renderHiddenNote(hidden);
			scheduleArrange();
		}

		function load() {
			const $grid = page.main.find(".cgm-mgmt-grid");
			const firstLoad = !$grid.children(".cgm-mgmt-panel").length;

			// Only the very first load empties the grid. Doing it on every
			// filter change collapsed the page to the height of a one-line
			// placeholder, and the browser, with nothing left to scroll,
			// snapped back to the top. The panels now stay in place and are
			// only dimmed while the new numbers are on their way.
			if (firstLoad) {
				$grid.html(`<div class="cgm-mgmt-loading">${__("Loading…")}</div>`);
			} else {
				$grid.addClass("is-busy").attr("aria-busy", "true");
			}

			// Even with the height held, re-rendering can shift things by a
			// few pixels, so the scroll position is captured and restored
			// after the panels have been laid out again.
			pendingScroll = firstLoad ? null : window.scrollY;

			// A chip or control that was focused is replaced by the re-render,
			// which would drop keyboard focus back to the document body.
			const active = document.activeElement;
			pendingFocus =
				active && active.classList && active.classList.contains("cgm-mgmt-chip")
					? active.getAttribute("data-currency")
					: null;

			frappe.call({
				method: `${METHOD}.get_overview`,
				args: { filters },
				callback: (r) => {
					data = r.message || null;
					// render() bails out when there is no data, so the arrange
					// pass never runs and never clears these. Left set, they
					// would fire on some later refresh and scroll the page
					// somewhere the user did not ask to be.
					if (!data) {
						pendingScroll = null;
						pendingFocus = null;
					}
					render();
					$grid.removeClass("is-busy").removeAttr("aria-busy");
				},
			});
		}

		frappe.call({
			method: `${METHOD}.get_filter_options`,
			callback: (r) => {
				options = r.message || {};
				renderFilters();
				load();
			},
		});
	});
};
