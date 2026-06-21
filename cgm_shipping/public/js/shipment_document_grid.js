function cgm_has_shipment_document_versioning() {
	return Boolean(frappe.meta.get_docfield("Shipment Document", "initial_attachment"));
}

function cgm_configure_shipment_document_grid(grid, { initial_read_only = false } = {}) {
	if (!grid) {
		return;
	}
	const hidden = ["attachment", "version_status"];

	if (!cgm_has_shipment_document_versioning()) {
		grid.update_docfield_property("attachment", "hidden", 0);
		hidden.slice(1).forEach((fieldname) => grid.update_docfield_property(fieldname, "hidden", 1));
		["initial_attachment", "final_attachment"].forEach((fieldname) => {
			grid.update_docfield_property(fieldname, "hidden", 1);
		});
		return;
	}

	hidden.forEach((fieldname) => {
		if (frappe.meta.get_docfield("Shipment Document", fieldname)) {
			grid.update_docfield_property(fieldname, "hidden", 1);
			grid.update_docfield_property(fieldname, "in_list_view", 0);
		}
	});
	["initial_attachment", "final_attachment"].forEach((fieldname) => {
		if (frappe.meta.get_docfield("Shipment Document", fieldname)) {
			grid.update_docfield_property(fieldname, "hidden", 0);
			grid.update_docfield_property(fieldname, "in_list_view", 1);
		}
	});
	if (initial_read_only) {
		grid.update_docfield_property("initial_attachment", "read_only", 1);
		grid.update_docfield_property("final_attachment", "read_only", 0);
		grid.update_docfield_property("document_type", "read_only", 1);
	}
}

function cgm_hydrate_legacy_document_rows(frm, table_field) {
	if (!cgm_has_shipment_document_versioning() || !frm.doc[table_field]) {
		return false;
	}
	let changed = false;
	for (const row of frm.doc[table_field]) {
		if (!row.initial_attachment && row.attachment) {
			row.initial_attachment = row.attachment;
			changed = true;
		}
		if (row.initial_attachment || row.final_attachment) {
			row.attachment = row.final_attachment || row.initial_attachment || row.attachment;
		}
	}
	return changed;
}
