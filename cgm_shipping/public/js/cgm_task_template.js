// CGM Task Template — Required Document Types as MultiSelect UX (stored as Data).
// Server-side MultiSelect is not in Frappe data_fieldtypes, so the DocField stays Data.
frappe.ui.form.on("CGM Task Template", {
	refresh(frm) {
		setup_required_document_types_multiselect(frm);
	},
	tasks_on_form_rendered(frm) {
		setup_required_document_types_multiselect(frm);
	},
});

function setup_required_document_types_multiselect(frm) {
	const grid = frm.fields_dict.tasks && frm.fields_dict.tasks.grid;
	if (!grid) {
		return;
	}
	// Client-only: render MultiSelect control while persisting as Data.
	grid.update_docfield_property("required_document_types", "fieldtype", "MultiSelect");
	grid.update_docfield_property("required_document_types", "ignore_validation", 1);
	frappe.db.get_list("Document Type", { fields: ["name"], limit: 500 }).then((rows) => {
		const names = (rows || []).map((r) => r.name).filter(Boolean);
		grid.update_docfield_property("required_document_types", "options", names.join("\n"));
		grid.update_docfield_property("required_document_types", "get_data", () => names);
	});
}
