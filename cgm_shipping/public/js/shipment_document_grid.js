function cgm_draft_document_field() {
	if (frappe.meta.get_docfield("Shipment Document", "draft_documents")) {
		return "draft_documents";
	}
	if (frappe.meta.get_docfield("Shipment Document", "initial_attachment")) {
		return "initial_attachment";
	}
	return null;
}

function cgm_has_shipment_document_versioning() {
	return Boolean(
		cgm_draft_document_field() || frappe.meta.get_docfield("Shipment Document", "final_attachment")
	);
}

function cgm_shipment_document_slot_fields() {
	const draft_field = cgm_draft_document_field();
	const fields = [];
	if (draft_field) {
		fields.push(draft_field);
	}
	if (frappe.meta.get_docfield("Shipment Document", "final_attachment")) {
		fields.push("final_attachment");
	}
	return fields;
}

function cgm_configure_shipment_document_grid(grid, { initial_read_only = false } = {}) {
	if (!grid) {
		return;
	}
	const hidden = ["attachment", "version_status"];
	const slot_fields = cgm_shipment_document_slot_fields();

	if (!cgm_has_shipment_document_versioning()) {
		grid.update_docfield_property("attachment", "hidden", 0);
		hidden.slice(1).forEach((fieldname) => grid.update_docfield_property(fieldname, "hidden", 1));
		slot_fields.forEach((fieldname) => {
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
	slot_fields.forEach((fieldname) => {
		if (frappe.meta.get_docfield("Shipment Document", fieldname)) {
			grid.update_docfield_property(fieldname, "hidden", 0);
			grid.update_docfield_property(fieldname, "in_list_view", 1);
		}
	});
	if (initial_read_only) {
		const draft_field = cgm_draft_document_field();
		if (draft_field) {
			grid.update_docfield_property(draft_field, "read_only", 1);
		}
		grid.update_docfield_property("final_attachment", "read_only", 0);
		grid.update_docfield_property("document_type", "read_only", 1);
	}
}

function cgm_on_shipment_document_slot_change(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	const draft_field = cgm_draft_document_field();
	const draft = draft_field ? row[draft_field] : null;
	const has_file = row.final_attachment || draft || row.attachment;
	if (has_file) {
		if (!row.status || row.status === "Missing") {
			frappe.model.set_value(cdt, cdn, "status", "Uploaded");
		}
		if (row.final_attachment) {
			frappe.model.set_value(cdt, cdn, "version_status", "Final Received");
			if (
				frappe.meta.get_docfield("Shipment Document", "final_document_status") &&
				!row.final_document_status
			) {
				frappe.model.set_value(cdt, cdn, "final_document_status", "Draft");
			}
		} else if (draft) {
			frappe.model.set_value(cdt, cdn, "version_status", "Awaiting Final");
		}
		frappe.model.set_value(cdt, cdn, "attachment", row.final_attachment || draft || row.attachment);
	} else if (!draft && !row.final_attachment && !row.attachment) {
		frappe.model.set_value(cdt, cdn, "status", "Missing");
		frappe.model.set_value(cdt, cdn, "verified_by", "");
		frappe.model.set_value(cdt, cdn, "verified_on", "");
		frappe.model.set_value(cdt, cdn, "version_status", "");
	}
}

function cgm_sync_shipment_document_rows_on_refresh(frm, table_field) {
	if (!table_field || !frm.doc[table_field]?.length) {
		return;
	}
	const cdt = frm.fields_dict[table_field]?.grid?.doctype;
	if (!cdt) {
		return;
	}
	for (const row of frm.doc[table_field]) {
		if (!row.name) {
			continue;
		}
		cgm_on_shipment_document_slot_change(frm, cdt, row.name);
	}
}

frappe.ui.form.on("Shipment Document", {
	draft_documents(frm, cdt, cdn) {
		cgm_on_shipment_document_slot_change(frm, cdt, cdn);
	},
	initial_attachment(frm, cdt, cdn) {
		cgm_on_shipment_document_slot_change(frm, cdt, cdn);
	},
	final_attachment(frm, cdt, cdn) {
		cgm_on_shipment_document_slot_change(frm, cdt, cdn);
	},
	attachment(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const draft_field = cgm_draft_document_field();
		const draft = draft_field ? row[draft_field] : null;
		if (
			frm.doctype === "Task" &&
			draft &&
			row.attachment &&
			row.attachment !== draft &&
			!row.final_attachment
		) {
			frappe.model.set_value(cdt, cdn, "final_attachment", row.attachment);
		}
		cgm_on_shipment_document_slot_change(frm, cdt, cdn);
	},
	status(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const draft_field = cgm_draft_document_field();
		const draft = draft_field ? row[draft_field] : null;
		const file = row.final_attachment || draft || row.attachment;
		if (["Verified", "Rejected"].includes(row.status)) {
			if (!file) {
				frappe.msgprint(__("Attach a file before verification."));
				frappe.model.set_value(cdt, cdn, "status", "Missing");
				return;
			}
			frappe.model.set_value(cdt, cdn, "verified_by", frappe.session.user);
			frappe.model.set_value(cdt, cdn, "verified_on", frappe.datetime.now_datetime());
		} else if (row.status === "Uploaded") {
			frappe.model.set_value(cdt, cdn, "verified_by", "");
			frappe.model.set_value(cdt, cdn, "verified_on", "");
		}
	},
});

function cgm_hydrate_legacy_document_rows(frm, table_field) {
	if (!cgm_has_shipment_document_versioning() || !frm.doc[table_field]) {
		return false;
	}
	const draft_field = cgm_draft_document_field();
	let changed = false;
	for (const row of frm.doc[table_field]) {
		const draft = draft_field ? row[draft_field] : null;
		if (draft_field && !draft && row.attachment) {
			row[draft_field] = row.attachment;
			changed = true;
		}
		if (draft || row.final_attachment) {
			row.attachment = row.final_attachment || draft || row.attachment;
		}
	}
	return changed;
}
