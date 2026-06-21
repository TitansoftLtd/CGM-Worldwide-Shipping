frappe.provide("cgm_shipping.container_tracking");
frappe.provide("cgm_shipping.grid_attach");

// ---------------------------------------------------------------------------
// Child-table Attach fields: render controls on idle rows.
// Frappe's grid_row.js only idle-renders Button fields via
// should_show_button_in_idle_grid_cell(). GridRow is an ES module and is NOT
// on frappe.ui.form — patch the live prototype from grid instances instead.
// ---------------------------------------------------------------------------

cgm_shipping.grid_attach.should_show_attach_in_idle_cell = function (row, column) {
	const df = column.df || {};
	return (
		["Attach", "Attach Image"].includes(df.fieldtype) &&
		row.grid?.allow_on_grid_editing?.() &&
		row.grid?.is_editable?.() &&
		row.doc &&
		!df.hidden &&
		!df.read_only
	);
};

cgm_shipping.grid_attach.show_idle_attach_controls = function (row) {
	if (!row?.columns_list?.length) {
		return;
	}
	const rowProto = row.constructor.prototype;
	const shouldShow = rowProto.should_show_button_in_idle_grid_cell;
	row.columns_list.forEach((column) => {
		const show =
			shouldShow.call(row, column) ||
			cgm_shipping.grid_attach.should_show_attach_in_idle_cell(row, column);
		if (!show) {
			return;
		}
		row.make_control(column);
		column.static_area?.toggle(false);
		column.field_area?.toggle(true);
	});
};

cgm_shipping.grid_attach.patch_row_prototype = function (rowProto) {
	if (!rowProto || rowProto._cgm_attach_idle_patch) {
		return;
	}
	const originalShouldShow = rowProto.should_show_button_in_idle_grid_cell;
	rowProto.should_show_button_in_idle_grid_cell = function (column) {
		if (originalShouldShow.call(this, column)) {
			return true;
		}
		return cgm_shipping.grid_attach.should_show_attach_in_idle_cell(this, column);
	};

	const originalSetupColumns = rowProto.setup_columns;
	if (typeof originalSetupColumns === "function") {
		rowProto.setup_columns = function (...args) {
			originalSetupColumns.apply(this, args);
			if (this.doc && !this.row?.hasClass("editable-row")) {
				cgm_shipping.grid_attach.show_idle_attach_controls(this);
			}
		};
	}

	rowProto._cgm_attach_idle_patch = true;
};

cgm_shipping.grid_attach.patch_grid = function (grid) {
	if (!grid?.grid_rows?.length) {
		return;
	}
	const rowProto = grid.grid_rows[0].constructor.prototype;
	cgm_shipping.grid_attach.patch_row_prototype(rowProto);
	grid.grid_rows.forEach((row) => {
		if (row.doc) {
			cgm_shipping.grid_attach.show_idle_attach_controls(row);
		}
	});
};

cgm_shipping.grid_attach.patch_form = function (frm) {
	if (!frm?.fields_dict) {
		return;
	}
	Object.values(frm.fields_dict).forEach((field) => {
		if (field?.grid) {
			cgm_shipping.grid_attach.patch_grid(field.grid);
		}
	});
};

frappe.ui.form.on("*", {
	refresh(frm) {
		cgm_shipping.grid_attach.patch_form(frm);
	},
});

const CGM_CONTAINER_TRACKING_TASK_KEY = "cgm_container_tracking_task";
const CGM_CONTAINER_TRACKING_PROJECT_KEY = "cgm_container_tracking_project";

cgm_shipping.container_tracking.open_from_task = function (frm) {
	if (!frm.doc.project) {
		frappe.msgprint(__("Link this task to a Project before starting container tracking."));
		return;
	}

	frappe.db.get_value(
		"Project",
		frm.doc.project,
		["custom_bill_of_lading", "custom_eta", "custom_batch_no"],
		(values) => {
			if (!values) {
				frappe.msgprint(__("Could not load Project details."));
				return;
			}

			const project = frm.doc.project;
			localStorage.setItem(CGM_CONTAINER_TRACKING_TASK_KEY, frm.doc.name);
			localStorage.setItem(CGM_CONTAINER_TRACKING_PROJECT_KEY, project);

			frappe.model.with_doctype("Container Tracker", () => {
				const doc = frappe.model.get_new_doc("Container Tracker");
				doc.project = project;
				if (values.custom_bill_of_lading) {
					doc.custom_bill_of_lading = values.custom_bill_of_lading;
					doc.bl_number = values.custom_bill_of_lading;
				}
				if (values.custom_eta) {
					doc.eta = values.custom_eta;
				}
				if (values.custom_batch_no) {
					doc.batch_bl_no = values.custom_batch_no;
				}

				frappe.show_alert({
					message: __("Select the Bill of Lading and container to track"),
					indicator: "blue",
				});
				frappe.set_route("Form", "Container Tracker", doc.name);
			});
		}
	);
};
