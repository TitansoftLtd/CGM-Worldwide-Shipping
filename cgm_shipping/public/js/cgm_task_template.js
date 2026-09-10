// CGM Task Template — Required Document Types picker.
//
// The field is stored as a comma-separated Data field. It cannot be a Table
// MultiSelect: CGM Task Template Item is itself a child table and Frappe does
// not support a table inside a table (see fix_cgm_task_template_item_nested_table).
// MultiSelectList is a client-only control, so it is applied here at runtime.
//
// This uses grid.update_docfield_property rather than layout.replace_field: it
// writes the property onto every row's docfield and the grid's own before any
// row form is built, so there is no control to swap after render and no retry
// timers. The previous approach replaced the control post-render and passed no
// `render` flag, so replace_field built the control without its input and the
// row kept showing a plain text box with no Document Type list.

let _document_type_names_promise = null;

function load_document_type_names() {
	if (!_document_type_names_promise) {
		_document_type_names_promise = frappe.db
			.get_list("Document Type", {
				fields: ["name"],
				limit: 500,
				order_by: "name asc",
			})
			.then((rows) => {
				const names = (rows || []).map((r) => r.name).filter(Boolean);
				// Never cache an empty result: one transient failure would otherwise
				// leave the picker empty for the rest of the desk session.
				if (!names.length) {
					_document_type_names_promise = null;
				}
				return names;
			})
			.catch((err) => {
				_document_type_names_promise = null;
				// eslint-disable-next-line no-console
				console.error("CGM: could not load the Document Type list", err);
				return [];
			});
	}
	return _document_type_names_promise;
}

function document_type_options(txt) {
	return load_document_type_names().then((names) => {
		const query = (txt || "").trim().toLowerCase();
		return names
			.filter((name) => !query || name.toLowerCase().includes(query))
			.map((name) => ({
				value: name,
				label: name,
				description: __("Document Type"),
			}));
	});
}

function apply_document_type_picker(frm) {
	const grid = frm.fields_dict.tasks?.grid;
	if (!grid || grid._cgm_document_type_picker) {
		return;
	}
	try {
		grid.update_docfield_property("required_document_types", "fieldtype", "MultiSelectList");
		grid.update_docfield_property("required_document_types", "get_data", document_type_options);
		// Values are validated server-side in CGMTaskTemplate.validate.
		grid.update_docfield_property("required_document_types", "ignore_validation", 1);
		grid._cgm_document_type_picker = true;
	} catch (err) {
		// update_docfield_property throws if the field is missing (e.g. an older
		// site before migrate). Leave the plain Data control rather than break the form.
		// eslint-disable-next-line no-console
		console.error("CGM: could not apply the Document Type picker", err);
	}
}

frappe.ui.form.on("CGM Task Template", {
	refresh(frm) {
		apply_document_type_picker(frm);
	},
});
