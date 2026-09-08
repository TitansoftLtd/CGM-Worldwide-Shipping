// CGM Task Template — Required Document Types picker (stored as comma-separated Data).
// DocField stays Data server-side; Desk replaces the control with MultiSelectList
// fed from the Document Type master when a task row form opens.

let _document_type_names_promise = null;

function load_document_type_names() {
	if (!_document_type_names_promise) {
		_document_type_names_promise = frappe.db
			.get_list("Document Type", {
				fields: ["name"],
				limit: 500,
				order_by: "name asc",
			})
			.then((rows) => (rows || []).map((r) => r.name).filter(Boolean));
	}
	return _document_type_names_promise;
}

function required_document_types_visible(doc) {
	if (!doc) {
		return false;
	}
	const role = (doc.task_role || "").trim();
	return (
		["Document", "Document Checkpoint", "Application"].includes(role) ||
		cint(doc.requires_document_upload)
	);
}

function get_tasks_grid_row(frm, cdn) {
	const grid = frm.fields_dict.tasks?.grid;
	if (!grid || !cdn) {
		return null;
	}
	return grid.get_grid_row(cdn);
}

function document_type_picker_df(base_df) {
	const df = frappe.utils.deep_clone(base_df);
	df.fieldtype = "MultiSelectList";
	df.options = [];
	df.get_data = (txt) =>
		load_document_type_names().then((names) => {
			const q = (txt || "").trim().toLowerCase();
			return names
				.filter((name) => !q || name.toLowerCase().includes(q))
				.map((name) => ({
					value: name,
					label: name,
					description: __("Document Type"),
				}));
		});
	df.ignore_validation = 1;
	return df;
}

function enhance_required_document_types_field(row_obj, saved_value) {
	const layout = row_obj?.grid_form?.layout;
	if (!layout) {
		return false;
	}
	const current = layout.fields_dict?.required_document_types;
	if (!current || current.df?.hidden) {
		return false;
	}
	if (current._cgm_document_type_picker) {
		return true;
	}

	const value = saved_value || current.get_value?.() || "";
	layout.replace_field("required_document_types", document_type_picker_df(current.df));
	const field = layout.fields_dict.required_document_types;
	if (!field) {
		return false;
	}
	field._cgm_document_type_picker = true;
	if (value) {
		field.set_value(value);
	}
	return true;
}

function setup_required_document_types_picker(frm, cdt, cdn) {
	const doc = locals[cdt]?.[cdn];
	if (!doc || !required_document_types_visible(doc)) {
		return;
	}

	const apply = () => {
		const row_obj = get_tasks_grid_row(frm, cdn);
		if (!row_obj?.grid_form) {
			return;
		}
		enhance_required_document_types_field(row_obj, doc.required_document_types);
	};

	// Depends-on sections can render after form_render; retry until control is replaced.
	[0, 50, 150, 350, 700].forEach((ms) => setTimeout(apply, ms));
}

function open_tasks_grid_row(frm) {
	return frappe.ui.form.get_open_grid_form();
}

frappe.ui.form.on("CGM Task Template", {
	tasks_on_form_rendered(frm) {
		const row_obj = open_tasks_grid_row(frm);
		if (!row_obj?.doc?.name) {
			return;
		}
		setup_required_document_types_picker(frm, row_obj.doc.doctype, row_obj.doc.name);
	},
});

frappe.ui.form.on("CGM Task Template Item", {
	form_render(frm, cdt, cdn) {
		setup_required_document_types_picker(frm, cdt, cdn);
	},
	requires_document_upload(frm, cdt, cdn) {
		setup_required_document_types_picker(frm, cdt, cdn);
	},
	task_role(frm, cdt, cdn) {
		setup_required_document_types_picker(frm, cdt, cdn);
	},
});
