frappe.provide("cgm_shipping.bl_containers");

function bl_container_rows(rows) {
	return (rows || []).map((row) => ({
		container_number: row.container_number || "",
		type_of_container: row.type_of_container || "",
	}));
}

function container_rows_match(existing, from_bl) {
	const current = bl_container_rows(existing);
	const next = bl_container_rows(from_bl);
	if (current.length !== next.length) {
		return false;
	}
	return current.every(
		(row, i) =>
			row.container_number === next[i].container_number &&
			row.type_of_container === next[i].type_of_container
	);
}

function apply_bl_containers(frm, bl_rows) {
	frm.clear_table("custom_container_information");
	(bl_rows || []).forEach((row) => {
		const child = frm.add_child("custom_container_information");
		child.container_number = row.container_number;
		child.type_of_container = row.type_of_container;
	});
	frm.refresh_field("custom_container_information");
}

function restore_clean_form_state(frm) {
	frm.dirty(false);
	frm.toolbar?.set_indicator?.();
	frm.states?.refresh?.();
}

/**
 * Copy container rows from linked Bill of Lading into custom_container_information.
 * @param {object} frm - Frappe form
 * @param {{ silent?: boolean }} opts - silent: refresh-only sync; do not show "Not Saved"
 */
cgm_shipping.bl_containers.sync_from_bl = function (frm, opts = {}) {
	const silent = Boolean(opts.silent);

	if (!frm.fields_dict.custom_container_information) {
		return Promise.resolve();
	}

	const existing = frm.doc.custom_container_information || [];

	if (!frm.doc.custom_bill_of_lading) {
		if (!existing.length) {
			return Promise.resolve();
		}
		apply_bl_containers(frm, []);
		if (silent) {
			restore_clean_form_state(frm);
		}
		return Promise.resolve();
	}

	return frappe.db.get_doc("Bill of Lading", frm.doc.custom_bill_of_lading).then((bl) => {
		const bl_rows = bl.container_information || [];
		if (container_rows_match(existing, bl_rows)) {
			return;
		}
		apply_bl_containers(frm, bl_rows);
		if (silent) {
			restore_clean_form_state(frm);
		}
	});
};
