frappe.provide("cgm_shipping.status_field");

const CGM_STATUS_CLASS_RE = /\bcgm-status-\S+/g;

const CGM_STATUS_TONE_STYLES = {
	muted: { background: "#f1f5f9", border: "#e2e8f0", color: "#475569" },
	info: { background: "#dbeafe", border: "#bfdbfe", color: "#1d4ed8" },
	primary: { background: "#ffe8ec", border: "#fecdd3", color: "#b8122c" },
	active: { background: "#fef3c7", border: "#fde68a", color: "#b45309" },
	warning: { background: "#ffedd5", border: "#fed7aa", color: "#c2410c" },
	success: { background: "#dcfce7", border: "#bbf7d0", color: "#15803d" },
	danger: { background: "#ffe8ec", border: "#fecaca", color: "#b91c1c" },
};

function cgm_escape_html(value) {
	return frappe.utils.escape_html(value || "");
}

function cgm_status_match(status, map, fallback = "muted") {
	if (!status) {
		return fallback;
	}
	if (map[status]) {
		return map[status];
	}
	const lower = String(status).toLowerCase();
	for (const [key, tone] of Object.entries(map)) {
		if (key.toLowerCase() === lower) {
			return tone;
		}
	}
	return fallback;
}

cgm_shipping.status_field = {
	tone_for_task(status) {
		return cgm_status_match(status, {
			Open: "warning",
			Working: "info",
			"Pending Review": "primary",
			Overdue: "danger",
			Completed: "success",
			Cancelled: "muted",
			Template: "muted",
		});
	},

	tone_for_shipment(status) {
		if (!status || status === "Draft") {
			return "muted";
		}
		if (status === "Completed") {
			return "success";
		}
		if (status === "Containers Returned") {
			return "primary";
		}
		if (["In Transit", "In Delivery", "Client Inspection"].includes(status)) {
			return "info";
		}
		if (
			[
				"Documents Received",
				"UCR Applied",
				"UCR Paid",
				"Pre-clearance",
				"Final Docs Received",
				"Manifest Requested",
				"Entry Lodged",
				"Post-clearance",
				"Field Clearance",
			].includes(status)
		) {
			return "primary";
		}
		if (["Line Paid & DO Lodged", "Entry Paid", "KPA Paid"].includes(status)) {
			return "warning";
		}
		return "active";
	},

	tone_for_inspection(status) {
		return cgm_status_match(status, {
			"Not Notified": "muted",
			Notified: "info",
			Confirmed: "success",
		});
	},

	tone_for_permit(status) {
		return cgm_status_match(status, {
			Applied: "muted",
			"Invoice Submitted": "info",
			"Invoice Verified": "warning",
			Paid: "primary",
			"Receipt Submitted": "info",
			"Receipt Verified": "success",
			Approved: "success",
			Released: "success",
			Rejected: "danger",
		});
	},

	tone_for_document(status) {
		return cgm_status_match(status, {
			Missing: "muted",
			Uploaded: "info",
			Verified: "success",
			Rejected: "danger",
		});
	},

	tone_for_project(status) {
		return cgm_status_match(status, {
			Open: "info",
			Completed: "success",
			Cancelled: "muted",
		});
	},

	badge_html(value, tone) {
		if (!value) {
			return "";
		}
		const palette = CGM_STATUS_TONE_STYLES[tone] || CGM_STATUS_TONE_STYLES.muted;
		const style = [
			"display:inline-flex",
			"align-items:center",
			"padding:1px 8px",
			"border-radius:999px",
			"font-size:11px",
			"font-weight:600",
			"line-height:1.35",
			"white-space:nowrap",
			`border:1px solid ${palette.border}`,
			`background:${palette.background}`,
			`color:${palette.color}`,
		].join(";");
		return `<span class="cgm-status-badge cgm-status-${tone}" style="${style}">${cgm_escape_html(
			value
		)}</span>`;
	},

	tone_fn_for_docfield(df, doc) {
		if (!df) {
			return null;
		}
		const sf = this;
		const doctype = df.parent || doc?.doctype;
		if (doctype === "Shipment Document" && df.fieldname === "status") {
			return (value) => sf.tone_for_document(value);
		}
		if (doctype === "Permit Register" && df.fieldname === "status") {
			return (value) => sf.tone_for_permit(value);
		}
		if (df.fieldname === "custom_shipment_status") {
			return (value) => sf.tone_for_shipment(value);
		}
		if (df.fieldname === "custom_inspection_notification_status") {
			return (value) => sf.tone_for_inspection(value);
		}
		if (df.fieldname === "status" && doctype === "Task") {
			return (value) => sf.tone_for_task(value);
		}
		if (df.fieldname === "status" && doctype === "Project") {
			return (value) => sf.tone_for_project(value);
		}
		return null;
	},

	make_formatter(tone_fn) {
		const sf = this;
		return function (value, df, doc) {
			if (!value) {
				return "";
			}
			return sf.badge_html(value, tone_fn(value, doc));
		};
	},

	register_meta_formatter(doctype, fieldname, tone_fn) {
		const df = frappe.meta.get_docfield(doctype, fieldname);
		if (!df) {
			return;
		}
		if (!frappe.meta.docfield_map[doctype]) {
			frappe.meta.docfield_map[doctype] = {};
		}
		frappe.meta.docfield_map[doctype][fieldname] = df;
		df.formatter = this.make_formatter(tone_fn);
	},

	attach_grid_formatters(grid, fieldname, tone_fn) {
		if (!grid) {
			return;
		}
		const formatter = this.make_formatter(tone_fn);
		for (const df of grid.docfields || []) {
			if (df.fieldname === fieldname) {
				df.formatter = formatter;
			}
		}
		for (const row of grid.grid_rows || []) {
			if (!row) {
				continue;
			}
			const df = row.docfields?.find((d) => d.fieldname === fieldname);
			if (df) {
				df.formatter = formatter;
			}
		}
	},

	reset_select($select) {
		if (!$select?.length) {
			return;
		}
		$select.removeClass((_, cls) => (cls.match(CGM_STATUS_CLASS_RE) || []).join(" "));
		$select.removeAttr("style");
	},

	clear_cell_background($col) {
		if (!$col?.length) {
			return;
		}
		$col.removeClass((_, cls) => (cls.match(CGM_STATUS_CLASS_RE) || []).join(" "));
		$col.addClass("cgm-status-col");
		$col.css({ backgroundColor: "", borderColor: "", color: "" });
	},

	apply_form_field(frm, fieldname, tone_fn) {
		const field = frm.fields_dict[fieldname];
		if (!field?.$wrapper) {
			return;
		}
		const value = frm.doc[fieldname];
		if (!value) {
			return;
		}
		const tone = tone_fn(value, frm.doc);
		if (field.$input?.is?.("select")) {
			this.reset_select(field.$input);
			return;
		}
		const $value = field.$wrapper.find(".control-value, .like-disabled-input").first();
		if ($value.length) {
			$value.html(this.badge_html(value, tone));
		}
	},

	apply_form_fields(frm, field_configs) {
		for (const { fieldname, tone_fn } of field_configs) {
			this.apply_form_field(frm, fieldname, tone_fn);
		}
	},

	is_status_cell_editing(grid_row, column) {
		return frappe.ui.form.editable_row === grid_row && column?.field_area?.is(":visible");
	},

	paint_status_column($col, value, tone) {
		if (!$col?.length || !value) {
			return;
		}
		this.clear_cell_background($col);
		this.reset_select($col.find("select"));
		const $static = $col.find(".static-area");
		if ($static.length) {
			$static.html(this.badge_html(value, tone));
		}
	},

	paint_grid_row(grid_row, fieldname, tone_fn) {
		if (!grid_row?.doc) {
			return;
		}

		const sf = this;
		const value = grid_row.doc[fieldname];
		const tone = tone_fn(value, grid_row.doc);
		const formatter = sf.make_formatter(tone_fn);
		const column = grid_row.columns?.[fieldname];

		for (const df of grid_row.docfields || []) {
			if (df.fieldname === fieldname) {
				df.formatter = formatter;
			}
		}

		if (column?.length) {
			if (sf.is_status_cell_editing(grid_row, column)) {
				sf.reset_select(column.find("select"));
				return;
			}
			sf.paint_status_column(column, value, tone);
			return;
		}

		const $col = grid_row.wrapper?.find(`.grid-static-col[data-fieldname="${fieldname}"]`).first();
		if ($col.length && !sf.is_status_cell_editing(grid_row, $col)) {
			sf.paint_status_column($col, value, tone);
		}
	},

	patch_grid_row_refresh_field(grid_row, fieldname, tone_fn) {
		const patch_key = `_cgm_status_refresh_${fieldname}`;
		if (!grid_row || grid_row[patch_key]) {
			return;
		}
		grid_row[patch_key] = true;

		const sf = this;
		const orig_refresh_field = grid_row.refresh_field.bind(grid_row);
		grid_row.refresh_field = function (fn, txt) {
			const df = grid_row.docfields?.find((d) => d.fieldname === fn);
			if (df && fn === fieldname) {
				df.formatter = sf.make_formatter(tone_fn);
			}
			orig_refresh_field(fn, txt);
			if (fn === fieldname) {
				sf.paint_grid_row(grid_row, fieldname, tone_fn);
			}
		};
	},

	paint_grid(grid, fieldname, tone_fn) {
		if (!grid) {
			return;
		}

		const sf = this;
		sf.attach_grid_formatters(grid, fieldname, tone_fn);

		for (const grid_row of grid.grid_rows || []) {
			if (!grid_row) {
				continue;
			}
			sf.patch_grid_row_refresh_field(grid_row, fieldname, tone_fn);
			sf.paint_grid_row(grid_row, fieldname, tone_fn);
		}

		grid.wrapper?.find(".grid-row[data-idx]").each(function () {
			const $row = $(this);
			const grid_row = $row.data("grid_row");
			const idx = cint($row.attr("data-idx"));
			const doc = grid_row?.doc || (grid.data || [])[idx - 1];
			if (!doc) {
				return;
			}
			if (grid_row) {
				sf.patch_grid_row_refresh_field(grid_row, fieldname, tone_fn);
				sf.paint_grid_row(grid_row, fieldname, tone_fn);
				return;
			}
			const value = doc[fieldname];
			if (!value) {
				return;
			}
			const $col = $row.find(`.grid-static-col[data-fieldname="${fieldname}"]`).first();
			sf.paint_status_column($col, value, tone_fn(value, doc));
		});

		if (grid.grid_form?.fields_dict?.[fieldname]?.$input) {
			sf.reset_select(grid.grid_form.fields_dict[fieldname].$input);
		}
	},

	_patch_grid_refresh(grid, fieldname, tone_fn) {
		if (!grid || grid._cgm_status_refresh_patched) {
			return;
		}
		grid._cgm_status_refresh_patched = true;
		const sf = this;
		const orig_refresh = grid.refresh.bind(grid);
		grid.refresh = function (...args) {
			const result = orig_refresh(...args);
			setTimeout(() => sf.paint_grid(grid, fieldname, tone_fn), 0);
			setTimeout(() => sf.paint_grid(grid, fieldname, tone_fn), 100);
			return result;
		};
	},

	configure_grid(grid, fieldname, tone_fn) {
		if (!grid) {
			return;
		}

		const sf = this;
		const doctype = grid.doctype;
		sf.register_meta_formatter(doctype, fieldname, (value, doc) => tone_fn(value, doc));
		sf._patch_grid_refresh(grid, fieldname, tone_fn);

		const paint_all = () => sf.paint_grid(grid, fieldname, tone_fn);
		const schedule_paint = () => {
			paint_all();
			setTimeout(paint_all, 0);
			setTimeout(paint_all, 120);
			setTimeout(paint_all, 400);
		};

		if (!grid._cgm_status_hooks) {
			grid._cgm_status_hooks = {};
		}

		if (!grid._cgm_status_hooks[fieldname]) {
			grid._cgm_status_hooks[fieldname] = true;
			const frm = grid.frm;
			const table_field = grid.df?.fieldname;
			const event_ns = `.cgm_status_${table_field || doctype}_${fieldname}`;
			const status_select = `.grid-static-col[data-fieldname="${fieldname}"] select`;

			if (frm?.wrapper) {
				$(frm.wrapper)
					.on(`grid-row-render${event_ns}`, (e, grid_row) => {
						if (grid_row?.grid !== grid) {
							return;
						}
						sf.patch_grid_row_refresh_field(grid_row, fieldname, tone_fn);
						sf.paint_grid_row(grid_row, fieldname, tone_fn);
					})
					.on(`click${event_ns}`, () => schedule_paint());
			}

			$(grid.wrapper)
				.on(`change${event_ns}`, status_select, schedule_paint)
				.on(`focusout${event_ns}`, status_select, schedule_paint);
		}

		schedule_paint();
	},

	repaint_parent_grid(frm, table_field, fieldname, tone_fn) {
		const grid = frm.fields_dict[table_field]?.grid;
		if (!grid) {
			return;
		}
		this.paint_grid(grid, fieldname, tone_fn);
	},
};

function cgm_register_global_status_formatters() {
	const sf = cgm_shipping.status_field;
	sf.register_meta_formatter("Permit Register", "status", (value) => sf.tone_for_permit(value));
	sf.register_meta_formatter("Shipment Document", "status", (value) => sf.tone_for_document(value));
}

function cgm_inject_status_styles() {
	if (document.getElementById("cgm-status-field-styles")) {
		return;
	}
	const style = document.createElement("style");
	style.id = "cgm-status-field-styles";
	style.textContent = `
		.form-grid .grid-static-col.cgm-status-col .static-area {
			display: inline-flex;
			align-items: center;
			padding: 0;
			overflow: visible;
		}
		.form-grid .grid-static-col.cgm-status-col select.input-sm {
			background: var(--control-bg, #fff) !important;
			color: var(--text-color, #333) !important;
			border: 1px solid var(--border-color, #d1d8dd) !important;
			border-radius: var(--border-radius-sm, 4px) !important;
			font-weight: normal;
		}
	`;
	document.head.appendChild(style);
}

function cgm_patch_frappe_format() {
	if (frappe._cgm_status_format_patched) {
		return;
	}
	frappe._cgm_status_format_patched = true;

	const sf = cgm_shipping.status_field;
	const orig_format = frappe.format;

	frappe.format = function (value, df, options, doc) {
		const tone_fn = sf.tone_fn_for_docfield(df, doc);
		if (tone_fn && value && df?.fieldname) {
			return sf.badge_html(value, tone_fn(value, doc));
		}
		return orig_format.apply(this, arguments);
	};
}

function cgm_schedule_status_field_setup(frm) {
	if (!frm) {
		return;
	}
	const run = () => {
		cgm_register_global_status_formatters();
		cgm_configure_document_status_grids(frm);
		cgm_configure_permit_status_grids(frm);
		if (frm.doctype === "Project") {
			cgm_configure_project_status_fields(frm);
		}
		if (frm.doctype === "Task") {
			cgm_configure_task_status_fields(frm);
		}
	};
	run();
	[50, 200, 500, 1000].forEach((ms) => setTimeout(run, ms));
}

function cgm_init_status_field() {
	cgm_inject_status_styles();
	cgm_patch_frappe_format();
	cgm_register_global_status_formatters();
	if (cur_frm && ["Project", "Task"].includes(cur_frm.doctype)) {
		cgm_schedule_status_field_setup(cur_frm);
	}
}

if (frappe?.format) {
	cgm_init_status_field();
} else {
	$(document).on("app_ready", cgm_init_status_field);
	frappe.after_ajax(cgm_init_status_field);
}

frappe.after_ajax(cgm_register_global_status_formatters);

frappe.ui.form.on("Project", {
	refresh(frm) {
		cgm_schedule_status_field_setup(frm);
	},
});

frappe.ui.form.on("Task", {
	refresh(frm) {
		cgm_schedule_status_field_setup(frm);
	},
});

$(document).on("form-load", function (e, frm) {
	if (!frm || !["Project", "Task"].includes(frm.doctype)) {
		return;
	}
	cgm_schedule_status_field_setup(frm);
});

function cgm_configure_document_status_grids(frm) {
	const sf = cgm_shipping.status_field;
	const tone = (value, doc) => sf.tone_for_document(value, doc);

	for (const fieldname of ["custom_shipment_documents", "custom_task_documents"]) {
		sf.configure_grid(frm.fields_dict[fieldname]?.grid, "status", tone);
	}
}

function cgm_configure_permit_status_grids(frm) {
	cgm_register_global_status_formatters();
	const sf = cgm_shipping.status_field;
	const tone = (value, doc) => sf.tone_for_permit(value, doc);

	for (const fieldname of ["custom_permit_register", "custom_task_permits"]) {
		const grid = frm.fields_dict[fieldname]?.grid;
		if (grid) {
			grid.update_docfield_property("status", "in_list_view", 1);
		}
		sf.configure_grid(grid, "status", tone);
	}
}

function cgm_configure_project_status_fields(frm) {
	cgm_shipping.status_field.apply_form_fields(frm, [
		{ fieldname: "custom_shipment_status", tone_fn: (value) => cgm_shipping.status_field.tone_for_shipment(value) },
		{
			fieldname: "custom_inspection_notification_status",
			tone_fn: (value) => cgm_shipping.status_field.tone_for_inspection(value),
		},
		{ fieldname: "status", tone_fn: (value) => cgm_shipping.status_field.tone_for_project(value) },
	]);
}

function cgm_configure_task_status_fields(frm) {
	cgm_shipping.status_field.apply_form_field(frm, "status", (value) =>
		cgm_shipping.status_field.tone_for_task(value)
	);
}

frappe.ui.form.on("Permit Register", {
	status(frm) {
		setTimeout(() => {
			cgm_shipping.status_field.repaint_parent_grid(
				frm,
				"custom_task_permits",
				"status",
				(v, d) => cgm_shipping.status_field.tone_for_permit(v, d)
			);
			cgm_shipping.status_field.repaint_parent_grid(
				frm,
				"custom_permit_register",
				"status",
				(v, d) => cgm_shipping.status_field.tone_for_permit(v, d)
			);
		}, 60);
	},
	form_render(frm) {
		const grid = cur_frm?.cur_grid;
		if (grid?.doctype === "Permit Register") {
			cgm_shipping.status_field.paint_grid(grid, "status", (v, d) =>
				cgm_shipping.status_field.tone_for_permit(v, d)
			);
			return;
		}
		cgm_configure_permit_status_grids(frm);
	},
});

frappe.ui.form.on("Shipment Document", {
	status(frm) {
		setTimeout(() => {
			cgm_shipping.status_field.repaint_parent_grid(
				frm,
				"custom_shipment_documents",
				"status",
				(v, d) => cgm_shipping.status_field.tone_for_document(v, d)
			);
			cgm_shipping.status_field.repaint_parent_grid(
				frm,
				"custom_task_documents",
				"status",
				(v, d) => cgm_shipping.status_field.tone_for_document(v, d)
			);
		}, 60);
	},
	form_render(frm) {
		const grid = cur_frm?.cur_grid;
		if (grid?.doctype === "Shipment Document") {
			cgm_shipping.status_field.paint_grid(grid, "status", (v, d) =>
				cgm_shipping.status_field.tone_for_document(v, d)
			);
			return;
		}
		cgm_configure_document_status_grids(frm);
	},
});
