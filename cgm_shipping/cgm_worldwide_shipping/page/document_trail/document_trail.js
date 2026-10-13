frappe.pages["document-trail"].on_page_load = function (wrapper) {
	frappe.require(["/assets/cgm_shipping/css/document_trail.css"], () => {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Document Trail"),
			single_column: true,
		});
		page.main.addClass("cgm-trail");

		// Same breadcrumb handling as Operations Overview: this runs inside an
		// async frappe.require callback, so the page head is rebuilt after it.
		function setup_breadcrumbs() {
			frappe.breadcrumbs.clear();
			const workspace_label = frappe.app.sidebar?.sidebar_title || __("CGM Shipping");
			let workspace_route = "/desk/cgm-shipping";
			if (frappe.app.sidebar?.sidebar_title) {
				const icon = frappe.utils.get_desktop_icon_by_label(frappe.app.sidebar.sidebar_title);
				const url = frappe.utils.get_route_for_icon(icon);
				if (url) workspace_route = url;
			}
			frappe.breadcrumbs.append_breadcrumb_element(
				workspace_route,
				workspace_label,
				"worksapce-breadcrumb"
			);
			frappe.breadcrumbs.append_breadcrumb_element(
				"/desk/document-trail",
				__("Document Trail"),
				"title-text"
			);
			frappe.breadcrumbs.toggle(true);
		}
		setup_breadcrumbs();
		setTimeout(setup_breadcrumbs, 0);

		const METHOD = "cgm_shipping.cgm_worldwide_shipping.customizations.document_trail";
		const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));
		const body = $('<div class="cgm-trail-body"></div>').appendTo(page.main);
		let request = 0;

		const doctype_field = page.add_field({
			fieldname: "doctype",
			label: __("Document Type"),
			fieldtype: "Select",
			options: [],
			change() {
				const doctype = doctype_field.get_value();
				if (name_field.df.options !== doctype) {
					name_field.df.options = doctype;
					name_field.refresh();
					name_field.set_value("");
					show_hint();
				}
			},
		});
		const name_field = page.add_field({
			fieldname: "name",
			label: __("Document"),
			fieldtype: "Link",
			options: "Project",
			change() {
				load();
			},
		});

		function show_hint(message) {
			body.html(
				`<div class="cgm-trail-empty">${esc(
					message || __("Choose a document type and a document to see what happened to it.")
				)}</div>`
			);
		}

		function when(value) {
			return value ? frappe.datetime.str_to_user(value) : "";
		}

		function render_facts(data) {
			const facts = (data.facts || [])
				.map(
					(f) =>
						`<div class="cgm-trail-fact"><span>${esc(f.label)}</span><b>${esc(f.value)}</b></div>`
				)
				.join("");
			return `
				<div class="cgm-trail-card">
					<div class="cgm-trail-head">
						<div>
							<div class="cgm-trail-doctype">${esc(__(data.doctype))}</div>
							<a class="cgm-trail-title" href="${esc(
								frappe.utils.get_form_link(data.doctype, data.name)
							)}">${esc(data.title)}</a>
							${data.title !== data.name ? `<div class="cgm-trail-name">${esc(data.name)}</div>` : ""}
						</div>
						<div class="cgm-trail-stamps">
							<div><span>${__("Created")}</span> ${esc(when(data.created.time))} · ${esc(
								data.created.user_name
							)}</div>
							<div><span>${__("Last changed")}</span> ${esc(when(data.modified.time))} · ${esc(
								data.modified.user_name
							)}</div>
						</div>
					</div>
					${facts ? `<div class="cgm-trail-facts">${facts}</div>` : ""}
				</div>`;
		}

		function render_warnings(data) {
			const warnings = data.warnings || [];
			if (!warnings.length) {
				return `<div class="cgm-trail-card cgm-trail-clear">${__(
					"No warnings. None of the checks found anything unusual about this document."
				)}</div>`;
			}
			const items = warnings
				.map(
					(w) =>
						`<li class="cgm-trail-${w.level === "note" ? "note" : "warn"}">
							<span class="cgm-trail-tag">${w.level === "note" ? __("Note") : __("Warning")}</span>
							${esc(w.text)}
						</li>`
				)
				.join("");
			return `<div class="cgm-trail-card"><h4>${__("What stands out")}</h4><ul class="cgm-trail-warnings">${items}</ul></div>`;
		}

		function render_related(data) {
			return (data.related || [])
				.map((section) => {
					const head = section.columns.map((c) => `<th>${esc(c)}</th>`).join("");
					const rows = section.rows
						.map((row) => {
							const cells = row.cells
								.map((cell, i) => {
									let text = cell;
									if (section.datetime_columns.includes(i)) text = when(cell);
									else if (section.date_columns.includes(i))
										text = cell ? frappe.datetime.str_to_user(cell) : "";
									else if (section.user_columns.includes(i))
										text = (data.user_names || {})[cell] || cell;
									if (i === 0) {
										return `<td><a href="${esc(
											frappe.utils.get_form_link(section.doctype, row.name)
										)}">${esc(text)}</a></td>`;
									}
									return `<td>${esc(text) || '<span class="cgm-trail-blank">-</span>'}</td>`;
								})
								.join("");
							return `<tr class="${row.flag ? "cgm-trail-flag" : ""}">${cells}</tr>`;
						})
						.join("");
					return `
						<div class="cgm-trail-card">
							<h4>${esc(section.title)}</h4>
							<div class="cgm-trail-table-wrap">
								<table class="cgm-trail-table"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table>
							</div>
						</div>`;
				})
				.join("");
		}

		function render_event(e) {
			const changes = (e.changes || [])
				.map((c) => {
					const values =
						c.old || c.new
							? `: <span class="cgm-trail-old">${esc(c.old) || "-"}</span> → <span class="cgm-trail-new">${
									esc(c.new) || "-"
							  }</span>`
							: "";
					return `<li><b>${esc(c.label)}</b>${values}</li>`;
				})
				.join("");
			const more = e.more_changes
				? `<li class="cgm-trail-more">${__("and {0} more", [e.more_changes])}</li>`
				: "";
			const details = (e.details || []).map((d) => `<div class="cgm-trail-detail">${esc(d)}</div>`).join("");
			return `
				<li class="cgm-trail-event cgm-trail-kind-${esc(e.kind)}">
					<div class="cgm-trail-time">${esc(when(e.time))}</div>
					<div class="cgm-trail-what">
						<div><b>${esc(e.title)}</b>${e.user_name ? ` · ${esc(e.user_name)}` : ""}</div>
						${details}
						${changes || more ? `<ul class="cgm-trail-changes">${changes}${more}</ul>` : ""}
					</div>
				</li>`;
		}

		function render(data) {
			const events = (data.events || []).map(render_event).join("");
			body.html(`
				${render_facts(data)}
				${render_warnings(data)}
				${render_related(data)}
				<div class="cgm-trail-card">
					<h4>${__("Timeline")} <span class="cgm-trail-count">${(data.events || []).length}</span></h4>
					<ul class="cgm-trail-timeline">${events}</ul>
				</div>
			`);
		}

		function load() {
			const doctype = doctype_field.get_value();
			const name = name_field.get_value();
			if (!doctype || !name) {
				show_hint();
				return;
			}
			const this_request = ++request;
			body.html(`<div class="cgm-trail-empty">${__("Loading...")}</div>`);
			frappe.call({
				method: `${METHOD}.get_document_trail`,
				args: { doctype, name },
				callback(r) {
					if (this_request !== request) return;
					if (r.exc || !r.message) {
						show_hint(__("Could not load this document."));
						return;
					}
					render(r.message);
				},
				error() {
					if (this_request === request) show_hint(__("Could not load this document."));
				},
			});
		}

		// /desk/document-trail?doctype=Project&name=PROJ-0037, or route_options from a form.
		function apply_route() {
			const opts = frappe.route_options || {};
			const params = new URLSearchParams(window.location.search);
			const doctype = opts.doctype || params.get("doctype");
			const name = opts.name || params.get("name");
			frappe.route_options = null;
			if (!doctype || !name) return;
			doctype_field.set_value(doctype).then(() => {
				name_field.df.options = doctype;
				name_field.refresh();
				name_field.set_value(name);
			});
		}

		show_hint();
		frappe.call({
			method: `${METHOD}.get_trail_doctypes`,
			callback(r) {
				const doctypes = r.message || [];
				doctype_field.df.options = doctypes;
				doctype_field.refresh();
				if (doctypes.length) {
					doctype_field.set_value(doctypes[0]);
					name_field.df.options = doctypes[0];
					name_field.refresh();
				}
				apply_route();
			},
		});
		page.wrapper.on("show", () => {
			setup_breadcrumbs();
			if (frappe.route_options) apply_route();
		});
	});
};
