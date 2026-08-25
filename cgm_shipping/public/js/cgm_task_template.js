// CGM Task Template — Required Document Types as MultiSelect UX (stored as Data).
// Server-side MultiSelect is not in Frappe data_fieldtypes, so the DocField stays Data.
//
// Only enhance the control when the row form is open AND the field is visible.
// Do NOT mutate grid docfield fieldtype globally — hidden MultiSelect controls on
// Standard rows break the pencil (full row) editor.

let _document_type_names_promise = null;

function load_document_type_names() {
	if (!_document_type_names_promise) {
		_document_type_names_promise = frappe.db
			.get_list("Document Type", { fields: ["name"], limit: 500 })
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

function enhance_required_document_types_field(field, names) {
	if (!field) {
		return;
	}
	field.df.fieldtype = "MultiSelect";
	field.df.options = names.join("\n");
	field.df.get_data = () => names;
	field.df.ignore_validation = 1;
	field.refresh();
}

frappe.ui.form.on("CGM Task Template Item", {
	form_render(frm, cdt, cdn) {
		const doc = locals[cdt]?.[cdn];
		if (!required_document_types_visible(doc)) {
			return;
		}
		const open_form = frappe.ui.form.get_open_grid_form();
		const field = open_form?.fields_dict?.required_document_types;
		if (!field) {
			return;
		}
		load_document_type_names().then((names) => {
			const active_field = frappe.ui.form.get_open_grid_form()?.fields_dict
				?.required_document_types;
			if (!active_field) {
				return;
			}
			enhance_required_document_types_field(active_field, names);
		});
	},
});
