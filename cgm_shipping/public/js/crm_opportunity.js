frappe.ui.form.on("Opportunity", {
	onload(frm) {
		cgm_shipping.opportunity_shipment.init_intake_wizard(frm);
		run_opportunity_form_syncs(frm, { apply_pending_bl: true });
	},

	before_save(frm) {
		if (!frm.doc.opportunity_from) {
			frm.set_value("opportunity_from", "Customer");
		}
	},

	after_save(frm) {
		cgm_shipping.opportunity_shipment.on_after_save(frm);
	},

	before_workflow_action(frm) {
		// Workflow already saved on the server; skip read-only syncs on the next refresh.
		frm._cgm_skip_readonly_sync = true;
	},

	refresh(frm) {
		if (frm.doc.docstatus > 0) {
			// Submitted Opportunity — show fields only; never run BL sync / clear logic.
			sync_opportunity_transport_and_containers(frm);
			schedule_shipment_project_create_menu(frm);
			hide_procurement_create_buttons(frm);
			return;
		}

		const skip_readonly_sync = frm._cgm_skip_readonly_sync;

		if (skip_readonly_sync) {
			sync_opportunity_transport_and_containers(frm);
			setup_opportunity_bill_of_lading_create(frm);
		} else {
			run_opportunity_form_syncs(frm, {
				apply_pending_bl: !frm._cgm_skip_pending_bl_on_refresh,
			});
			frm._cgm_skip_pending_bl_on_refresh = false;
		}

		schedule_shipment_project_create_menu(frm);
		hide_procurement_create_buttons(frm);
	},

	after_workflow_action(frm) {
		frm._cgm_skip_readonly_sync = false;
		invalidate_opportunity_bl_sync(frm);
		restore_opportunity_clean_state(frm);
		// Re-render the Create menu immediately after the workflow state changes
		// (e.g. Opp Intake → Approved) so the Shipment Project button appears
		// without needing a manual page refresh.
		// We also schedule a late pass (900 ms) because the form refresh triggered
		// by the workflow action will re-run hide_procurement_create_buttons up to
		// 600 ms later, which can wipe the whole Create group.
		schedule_shipment_project_create_menu(frm);
		hide_procurement_create_buttons(frm);
		setTimeout(() => {
			schedule_shipment_project_create_menu(frm);
			hide_procurement_create_buttons(frm);
		}, 900);
	},

	workflow_state(frm) {
		schedule_shipment_project_create_menu(frm);
		hide_procurement_create_buttons(frm);
	},

	custom_shipment_type(frm) {
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},

	party_name(frm) {
		sync_opportunity_consignee_from_customer(frm, { force_show: true });
	},

	custom_bill_of_lading(frm) {
		sync_opportunity_transport_and_containers(frm);
		sync_bl_propagation_from_link(frm, { silent: true });
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},

	custom_air_waybill(frm) {
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},

	custom_booking_confirmation(frm) {
		cgm_shipping.opportunity_shipment.sync_from_linked_booking(frm);
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},
});

frappe.ui.form.on("Shipment Document", {
	custom_clients_documents_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "uploaded_by", frappe.session.user);
		frappe.model.set_value(cdt, cdn, "uploaded_on", frappe.datetime.now_datetime());
	},
});

function sync_opportunity_consignee_from_customer(frm, opts = {}) {
	if (!frm.fields_dict.custom_consignee) {
		return;
	}
	if (opts.force_show || frm.doc.party_name) {
		frm.set_df_property("custom_consignee", "hidden", 0);
		frm.toggle_display("custom_consignee", true);
	}
	if ((frm.doc.opportunity_from || "Customer") !== "Customer" || !frm.doc.party_name) {
		return;
	}
	frappe.db.get_value("Customer", frm.doc.party_name, "customer_name", (values) => {
		const label = values?.customer_name || frm.doc.party_name;
		if (frm.doc.custom_consignee !== label) {
			frm.set_value("custom_consignee", label);
		}
	});
}

function run_opportunity_form_syncs(frm, opts = {}) {
	register_clients_documents_remove_handler(frm);
	configure_opportunity_clients_documents_grid(frm);
	setup_opportunity_bill_of_lading_create(frm);
	cgm_shipping.opportunity_shipment.init_intake_wizard(frm);
	sync_opportunity_consignee_from_customer(frm, { force_show: true });

	// Pending transport-doc redirects only apply to the saved Opportunity they came from.
	if (!frm.is_new()) {
		if (opts.apply_pending_bl) {
			apply_pending_bl_from_submit(frm);
		}
		cgm_shipping.opportunity_shipment.apply_pending_awb_from_submit(frm);
		cgm_shipping.opportunity_shipment.apply_pending_booking_from_submit(frm);
		cgm_shipping.opportunity_shipment.sync_from_linked_booking(frm);
		sync_bl_from_clients_documents(frm, { silent: true });
		const bl_link_field = get_opportunity_bl_link_field(frm);
		if (frm.doc[bl_link_field]) {
			sync_bl_propagation_from_link(frm, { silent: true });
			sync_opportunity_transport_and_containers(frm);
			if (cgm_shipping?.bl_containers?.schedule_sync) {
				cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
			}
		}
	}
}

function row_has_shipment_document_file(row) {
	if (!row) {
		return false;
	}
	return Boolean(row.final_attachment || row.initial_attachment || row.attachment);
}

function configure_opportunity_clients_documents_grid(frm) {
	const docs_field = get_clients_documents_field(frm);
	if (!docs_field || !frm.fields_dict[docs_field]?.grid) {
		return;
	}
	if (cgm_hydrate_legacy_document_rows(frm, docs_field)) {
		frm.refresh_field(docs_field);
	}
	cgm_configure_shipment_document_grid(frm.fields_dict[docs_field].grid);
}

function invalidate_opportunity_bl_sync(frm) {
	frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1;
}

function restore_opportunity_clean_state(frm) {
	cgm_shipping.bl_containers.restore_clean_form_state?.(frm);
}

function meta_has_field(doctype, fieldname) {
	const meta = doctype && frappe.get_meta(doctype);
	return Boolean(meta && (meta.fields || []).some((df) => df.fieldname === fieldname));
}

function get_clients_documents_field(frm) {
	if (frm.meta.has_field("custom_clients_documents")) {
		return "custom_clients_documents";
	}
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype === "Table" && df.options === "Shipment Document") {
			return df.fieldname;
		}
	}
	return null;
}

function is_bl_document_type(document_type) {
	if (!document_type) {
		return false;
	}
	const name = String(document_type).toLowerCase();
	return name === "bl" || name.includes("bill of lading");
}

function find_bl_clients_document_row(frm) {
	const docs_field = get_clients_documents_field(frm);
	if (!docs_field) {
		return null;
	}
	const rows = frm.doc[docs_field] || [];
	return (
		rows.find((row) => row_has_shipment_document_file(row) && is_bl_document_type(row.document_type)) ||
		rows.find((row) => row_has_shipment_document_file(row)) ||
		null
	);
}

function get_link_field_for_doctype(frm, linked_doctype) {
	if (!linked_doctype) {
		return null;
	}
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype === "Link" && df.options === linked_doctype) {
			return df.fieldname;
		}
	}
	return null;
}

function linked_doctype_has_container_table(doctype) {
	const meta = frappe.get_meta(doctype);
	if (!meta) {
		return false;
	}
	return meta.fields.some((df) => {
		if (df.fieldtype !== "Table") {
			return false;
		}
		return meta_has_field(df.options, "container_number");
	});
}

function get_opportunity_bl_link_field(frm) {
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype !== "Link" || !df.options) {
			continue;
		}
		if (linked_doctype_has_container_table(df.options)) {
			return df.fieldname;
		}
	}
	return null;
}

function get_container_table_field(frm) {
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype !== "Table") {
			continue;
		}
		if (meta_has_field(df.options, "container_number")) {
			return df.fieldname;
		}
	}
	return null;
}

function get_quantity_field(frm, bl_link_field) {
	if (!bl_link_field) {
		return null;
	}
	const fields = frappe.meta.get_docfields(frm.doctype, frm.doc.name);
	const start = fields.findIndex((df) => df.fieldname === bl_link_field);
	if (start < 0) {
		return null;
	}
	for (let i = start + 1; i < fields.length; i++) {
		const df = fields[i];
		if (df.fieldtype === "Section Break" || df.fieldtype === "Tab Break") {
			break;
		}
		if (df.fieldtype === "Table") {
			break;
		}
		if (["Data", "Float", "Int"].includes(df.fieldtype)) {
			return df.fieldname;
		}
	}
	return null;
}

function find_populate_containers_row(frm) {
	return find_bl_clients_document_row(frm);
}

function get_opportunity_cargo_type_field(frm) {
	if (frm.fields_dict.custom_cargo_type) {
		return "custom_cargo_type";
	}
	if (frm.fields_dict.custom_cargo_type_) {
		return "custom_cargo_type_";
	}
	return null;
}

function set_opportunity_bl_field(frm, fieldname, value) {
	if (value == null || value === "") {
		return;
	}
	if (frm.fields_dict[fieldname]) {
		frm.set_value(fieldname, value);
		frm.refresh_field(fieldname);
		return;
	}
	frm.doc[fieldname] = value;
	if (frm.doc.name && !frm.is_new()) {
		frappe.model.set_value(frm.doctype, frm.doc.name, fieldname, value);
	}
}

function apply_bl_classification_fields(frm, data) {
	if (!data) {
		return;
	}
	if (data.shipment_type) {
		set_opportunity_bl_field(frm, "custom_shipment_type", data.shipment_type);
	}
	if (data.default_mode_of_transport) {
		set_opportunity_bl_field(frm, "custom_mode_of_transport", data.default_mode_of_transport);
	}
	const cargo_type_field = get_opportunity_cargo_type_field(frm);
	if (data.cargo_type && cargo_type_field) {
		set_opportunity_bl_field(frm, cargo_type_field, data.cargo_type);
	}

	const tracking_fields = [
		["client_refrence_no", "custom_client_refrence_no"],
		["batch_no", "custom_batch_no"],
	];
	for (const [src, dest] of tracking_fields) {
		if (data[src] != null && data[src] !== "") {
			set_opportunity_bl_field(frm, dest, data[src]);
		}
	}

	const detail_fields = [
		"custom_description_of_goods",
		"custom_draft_bl_number",
		"custom_number_of_packages",
		"custom_package_type",
		// Confirmed shipping / cargo — Opportunity stays the latest shipment record.
		"custom_shipping_line",
		"custom_vessel",
		"custom_etd",
		"custom_eta",
		"custom_port_of_loading",
		"custom_port_of_discharge",
		"custom_voyage_number",
		"custom_gross_weight",
		"custom_weight_nw",
		"custom_weight_uom_",
	];
	detail_fields.forEach((fieldname) => {
		if (data[fieldname] != null && data[fieldname] !== "") {
			set_opportunity_bl_field(frm, fieldname, data[fieldname]);
		}
	});
}

function apply_bl_propagation_data(frm, data) {
	if (!data) {
		return;
	}
	const bl_link_field = get_opportunity_bl_link_field(frm);
	const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;

	apply_bl_classification_fields(frm, data);
	if (
		quantity_field &&
		data.quantity != null &&
		String(frm.doc[quantity_field] ?? "") !== String(data.quantity ?? "")
	) {
		set_opportunity_bl_field(frm, quantity_field, data.quantity || "");
	}
}

function sync_bl_propagation_from_link(frm, opts = {}) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const bl_link_field = get_opportunity_bl_link_field(frm);
	const bl_name = bl_link_field && frm.doc[bl_link_field];
	if (!bl_name) {
		return;
	}

	const sync_id = (frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1);

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_containers_for_bl_attachment",
		args: { attachment: bl_name },
		callback(r) {
			if (sync_id !== frm._cgm_bl_sync_id || cur_frm !== frm) {
				return;
			}
			if (r.exc || !r.message) {
				return;
			}
			apply_bl_propagation_data(frm, r.message);
			if (opts.silent) {
				restore_opportunity_clean_state(frm);
			}
		},
	});
}


// ─── Clients Documents remove handler ─────────────────────────────────────────

function register_clients_documents_remove_handler(frm) {
	const docs_field = get_clients_documents_field(frm);
	if (!docs_field || frm.__cgm_docs_remove_registered) {
		return;
	}
	frm.__cgm_docs_remove_registered = true;

	frappe.ui.form.on("Opportunity", {
		[docs_field + "_remove"](frm) {
			on_clients_documents_removed(frm);
		},
	});
}

function on_clients_documents_removed(frm) {
	const bl_row = find_populate_containers_row(frm);
	if (bl_row) {
		fetch_and_apply_bl_data(frm, bl_row);
		return;
	}
	clear_bl_derived_opportunity_fields(frm);
}


// ─── Transport & container sync ───────────────────────────────────────────────

function sync_opportunity_transport_and_containers(frm) {
	const bl_link_field = get_opportunity_bl_link_field(frm);
	cgm_shipping.transport_reference.toggle_cargo_type(frm, {
		bill_of_lading: bl_link_field || "custom_bill_of_lading",
	});
}


// ─── Bill of Lading create route ──────────────────────────────────────────────

function is_saved_opportunity_name(name) {
	return Boolean(name && !String(name).startsWith("new-"));
}

function setup_opportunity_bill_of_lading_create(frm) {
	const bl_link_field = get_opportunity_bl_link_field(frm);
	const df = bl_link_field && frm.get_docfield(bl_link_field);
	if (!df || frm._cgm_bl_create_route_setup) {
		return;
	}

	frm._cgm_bl_create_route_setup = true;
	df.get_route_options_for_new_doc = () => {
		const opts = {};
		if (frm.doc.name) {
			localStorage.setItem("cgm_return_opportunity", frm.doc.name);
			localStorage.setItem("cgm_bl_seed_opportunity", frm.doc.name);
		}
		if (is_saved_opportunity_name(frm.doc.name)) {
			const linked_doctype = df.options;
			if (linked_doctype) {
				const linked_meta = frappe.get_meta(linked_doctype);
				const opp_link_field = linked_meta?.fields?.find(
					(field) =>
						field.fieldtype === "Link" &&
						field.options === frm.doctype
				);
				if (opp_link_field) {
					opts[opp_link_field.fieldname] = frm.doc.name;
				}
			}
			opts.linked_opportunity = frm.doc.name;
			if (frm.doc.custom_draft_bl_number) {
				opts.bl_number = frm.doc.custom_draft_bl_number;
			}
			// FCL batch is allocated on Booking/BL save — not from Opportunity.
			if (frm.doc.party_name) {
				opts.customer = frm.doc.party_name;
			}
			if (frm.doc.custom_shipment_type) {
				opts.shipment_type = frm.doc.custom_shipment_type;
			}
			const cargo_field = get_opportunity_cargo_type_field(frm);
			if (cargo_field && frm.doc[cargo_field]) {
				opts.cargo_type = frm.doc[cargo_field];
			}
			// Prefill planned → confirmed path when Booking already exists.
			if (frm.doc.custom_booking_confirmation) {
				opts.booking_confirmation = frm.doc.custom_booking_confirmation;
			}
		}
		return opts;
	};
}


// ─── Pending BL from submit ───────────────────────────────────────────────────

function apply_pending_bl_from_submit(frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}

	let pending;
	try {
		pending = JSON.parse(localStorage.getItem("cgm_pending_bl_link") || "null");
	} catch {
		return;
	}

	if (!pending || pending.opportunity !== frm.doc.name) {
		return;
	}

	const bl_link_field =
		get_link_field_for_doctype(frm, pending.linked_doctype) ||
		get_opportunity_bl_link_field(frm);
	const docs_field = get_clients_documents_field(frm);

	if (pending.bl_name && bl_link_field && frm.doc[bl_link_field] !== pending.bl_name) {
		frm.set_value(bl_link_field, pending.bl_name);
	}
	apply_bl_propagation_data(frm, pending);
	if (pending.attachment && docs_field && pending.document_type) {
		prepend_opportunity_bl_client_document(frm, pending, docs_field);
	}
	if (cgm_shipping?.bl_containers?.schedule_sync) {
		cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
	}

	localStorage.removeItem("cgm_pending_bl_link");
	frappe.show_alert({
		message: __("Bill of Lading {0} linked - continue completing this Opportunity.", [
			pending.bl_name,
		]),
		indicator: "green",
	});
}

function prepend_opportunity_bl_client_document(frm, pending, docs_field) {
	const rows = frm.doc[docs_field] || [];

	const already_exists = rows.some(
		(row) =>
			row.document_type === pending.document_type ||
			row.initial_attachment === pending.attachment ||
			row.attachment === pending.attachment
	);
	if (already_exists) {
		return;
	}

	const bl_row = {
		document_type: pending.document_type,
		status: "Uploaded",
	};
	if (cgm_has_shipment_document_versioning()) {
		bl_row.initial_attachment = pending.attachment;
		bl_row.attachment = pending.attachment;
		bl_row.version_status = "Awaiting Final";
	} else {
		bl_row.attachment = pending.attachment;
	}

	frm.clear_table(docs_field);
	frm.add_child(docs_field, bl_row);
	rows.forEach((row) => {
		frm.add_child(docs_field, {
			document_type: row.document_type,
			attachment: row.attachment,
			initial_attachment: row.initial_attachment,
			final_attachment: row.final_attachment,
			version_status: row.version_status,
			status: row.status,
			uploaded_by: row.uploaded_by,
			uploaded_on: row.uploaded_on,
			verified_by: row.verified_by,
			verified_on: row.verified_on,
			remarks: row.remarks,
		});
	});
	frm.refresh_field(docs_field);
}


// ─── BL data sync (single API call) ───────────────────────────────────────────

function sync_bl_from_clients_documents(frm, opts = {}) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const bl_link_field = get_opportunity_bl_link_field(frm);
	const bl_row = find_bl_clients_document_row(frm);

	if (!bl_row) {
		if (!bl_link_field || !frm.doc[bl_link_field]) {
			clear_bl_derived_opportunity_fields(frm);
		}
		return;
	}

	if (bl_link_field && frm.doc[bl_link_field]) {
		sync_bl_propagation_from_link(frm, opts);
		if (cgm_shipping?.bl_containers?.schedule_sync) {
			cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
		}
		return;
	}

	fetch_and_apply_bl_data(frm, bl_row, null, null, opts);
}

function fetch_and_apply_bl_data(frm, row, cdt, cdn, opts = {}) {
	const file_ref = row.final_attachment || row.initial_attachment || row.attachment;
	if (!file_ref) {
		return;
	}

	const sync_id = (frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1);

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_containers_for_bl_attachment",
		args: { attachment: file_ref },
		callback(r) {
			if (sync_id !== frm._cgm_bl_sync_id || cur_frm !== frm) {
				return;
			}
			if (r.exc || !r.message) {
				return;
			}
			apply_bl_data_from_response(frm, row, cdt, cdn, r.message, opts);
		},
	});
}

const BL_CONTAINER_COMPARE_FIELDS = [
	"container_number",
	"cargo_size",
	"no_container",
	"seal_no",
];

function opportunity_container_rows_match(existing, incoming) {
	existing = existing || [];
	incoming = incoming || [];
	if (existing.length !== incoming.length) {
		return false;
	}
	return incoming.every((row, i) =>
		BL_CONTAINER_COMPARE_FIELDS.every(
			(field) => String(existing[i]?.[field] ?? "") === String(row[field] ?? "")
		)
	);
}

function apply_bl_data_from_response(frm, row, cdt, cdn, data, opts = {}) {
	const silent = Boolean(opts.silent);
	const bl_link_field = get_link_field_for_doctype(frm, row.linked_doctype);
	const container_field = get_container_table_field(frm);
	const bl_name = data.bl_name || "";
	const attachment = data.attachment || "";

	if (cdt && cdn) {
		const child = locals[cdt]?.[cdn];
		if (child && child.attachment !== attachment) {
			if (cgm_has_shipment_document_versioning()) {
				frappe.model.set_value(cdt, cdn, "initial_attachment", attachment);
			}
			frappe.model.set_value(cdt, cdn, "attachment", attachment);
		}
	} else if (row.name) {
		const child = locals[row.doctype]?.[row.name];
		if (child && child.attachment !== attachment) {
			if (cgm_has_shipment_document_versioning()) {
				frappe.model.set_value(row.doctype, row.name, "initial_attachment", attachment);
			}
			frappe.model.set_value(row.doctype, row.name, "attachment", attachment);
		}
	}

	if (bl_link_field && bl_name && frm.doc[bl_link_field] !== bl_name) {
		frm.set_value(bl_link_field, bl_name);
	}
	apply_bl_propagation_data(frm, data);

	if (
		container_field &&
		!opportunity_container_rows_match(frm.doc[container_field], data.containers)
	) {
		frm.clear_table(container_field);
		(data.containers || []).forEach((container) => {
			Object.assign(frm.add_child(container_field), container);
		});
		frm.refresh_field(container_field);
	}

	if (silent) {
		restore_opportunity_clean_state(frm);
	}
}

function clear_bl_derived_opportunity_fields(frm) {
	const bl_link_field = get_opportunity_bl_link_field(frm);
	const container_field = get_container_table_field(frm);
	const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;
	const tracking_fields = [
		"custom_client_refrence_no",
		"custom_batch_no",
	];

	if (container_field && (frm.doc[container_field] || []).length) {
		frm.clear_table(container_field);
		frm.refresh_field(container_field);
	}
	if (quantity_field && frm.doc[quantity_field]) {
		frm.set_value(quantity_field, "");
	}
	for (const fieldname of tracking_fields) {
		if (frm.fields_dict[fieldname] && frm.doc[fieldname]) {
			frm.set_value(fieldname, "");
		}
	}
	if (bl_link_field && frm.doc[bl_link_field]) {
		frm.set_value(bl_link_field, "");
	}
}

const CGM_OPPORTUNITY_CREATE_GROUP = __("Create");

// ─── Shipment Project create menu ─────────────────────────────────────────────
// Opportunity is NOT a submittable document, so docstatus always stays 0.
// Gate creation on workflow_state === "Approved" at click time (not docstatus).

function shipment_project_cache_key(opp_name) {
	return `cgm_shipment_project:${opp_name}`;
}

function cache_shipment_project_for_opportunity(frm, project_name) {
	if (!frm?.doc?.name || !project_name) {
		return;
	}
	frm._cgm_shipment_project_name = project_name;
	try {
		localStorage.setItem(shipment_project_cache_key(frm.doc.name), project_name);
	} catch {
		// ignore quota / private mode
	}
}

function read_cached_shipment_project_for_opportunity(opp_name) {
	if (!opp_name) {
		return null;
	}
	try {
		return localStorage.getItem(shipment_project_cache_key(opp_name)) || null;
	} catch {
		return null;
	}
}

function project_name_from_get_value(message) {
	if (!message) {
		return null;
	}
	if (typeof message === "string") {
		return message;
	}
	return message.name || null;
}

function finalize_opportunity_create_menu(frm) {
	frm.page.set_inner_btn_group_as_primary(CGM_OPPORTUNITY_CREATE_GROUP);
	hide_procurement_create_buttons(frm);
}

function force_remove_opportunity_create_menu_item(frm, label) {
	const translated = __(label);
	frm.remove_custom_button(translated, CGM_OPPORTUNITY_CREATE_GROUP);
	const $group = frm.page.get_inner_group_button?.(CGM_OPPORTUNITY_CREATE_GROUP);
	if ($group?.length) {
		$group
			.find(`.dropdown-item[data-label="${encodeURIComponent(translated)}"]`)
			.remove();
	}
	delete frm.custom_buttons?.[translated];
}

function force_add_opportunity_create_menu_item(frm, label, fn) {
	const translated = __(label);
	force_remove_opportunity_create_menu_item(frm, label);
	frm.add_custom_button(translated, fn, CGM_OPPORTUNITY_CREATE_GROUP);
}

function schedule_shipment_project_create_menu(frm) {
	if (frm.is_new() || !frm.doc.name || frm.doc.opportunity_from !== "Customer") {
		return;
	}

	clearTimeout(frm._cgm_project_btn_timer);
	clearTimeout(frm._cgm_project_btn_timer_late);
	clearTimeout(frm._cgm_project_btn_timer_latest);
	clearTimeout(frm._cgm_project_btn_timer_final);

	// First pass: before ERPNext adds its standard Create items.
	frm._cgm_project_btn_timer = setTimeout(() => {
		add_shipment_project_create_menu_item(frm);
	}, 0);

	// Second pass: after ERPNext's standard items land (~300 ms).
	frm._cgm_project_btn_timer_late = setTimeout(() => {
		add_shipment_project_create_menu_item(frm);
	}, 500);

	// Third pass: after hide_procurement_create_buttons' last interval (600 ms)
	// to ensure our button survives any group cleanup Frappe does.
	frm._cgm_project_btn_timer_latest = setTimeout(() => {
		add_shipment_project_create_menu_item(frm);
	}, 800);

	// Fourth pass: after workflow-action form reload (~900 ms).
	frm._cgm_project_btn_timer_final = setTimeout(() => {
		add_shipment_project_create_menu_item(frm);
	}, 1200);
}

function clear_shipment_project_create_menu_items(frm) {
	force_remove_opportunity_create_menu_item(frm, "Create Shipment Project");
	force_remove_opportunity_create_menu_item(frm, "Start Shipment");
	force_remove_opportunity_create_menu_item(frm, "View Project");
}

function prompt_shipment_project_approval_required(frm) {
	frappe.msgprint({
		title: __("Approval required"),
		message: __(
			"This Opportunity must be <b>Approved</b> before creating a Shipment Project. Current status: <b>{0}</b>.",
			[frm.doc.workflow_state || __("Not set")]
		),
		indicator: "orange",
	});
}

function on_create_shipment_project_click(frm) {
	// Unified Start Shipment path: document gates + Approved + Project create.
	cgm_shipping.opportunity_shipment.start_shipment(frm);
}

function add_shipment_project_create_menu_item(frm) {
	if (frm.is_new() || !frm.doc.name || frm.doc.opportunity_from !== "Customer") {
		return;
	}

	const opp_name = frm.doc.name;

	const add_create_item = () => {
		if (frm.doc.name !== opp_name) {
			return;
		}
		force_remove_opportunity_create_menu_item(frm, "View Project");
		force_add_opportunity_create_menu_item(
			frm,
			"Start Shipment",
			() => on_create_shipment_project_click(frm)
		);
		finalize_opportunity_create_menu(frm);
	};

	const add_view_item = (project_name) => {
		if (frm.doc.name !== opp_name || !project_name) {
			return;
		}
		cache_shipment_project_for_opportunity(frm, project_name);
		force_remove_opportunity_create_menu_item(frm, "Create Shipment Project");
		force_add_opportunity_create_menu_item(frm, "View Project", () =>
			frappe.set_route("Form", "Project", project_name)
		);
		finalize_opportunity_create_menu(frm);
	};

	const project_meta = frappe.get_meta("Project");
	const has_source_link = Boolean(
		project_meta &&
			(project_meta.fields || []).some((df) => df.fieldname === "custom_source_opportunity")
	);

	const cached =
		frm._cgm_shipment_project_name || read_cached_shipment_project_for_opportunity(opp_name);

	if (!has_source_link) {
		add_create_item();
		return;
	}

	if (cached) {
		add_view_item(cached);
		return;
	}

	// Paint immediately for Approved opps — do not wait on the DB lookup.
	if (frm.doc.workflow_state === "Approved") {
		add_create_item();
	}

	frappe.db
		.get_value("Project", { custom_source_opportunity: opp_name }, "name")
		.then((r) => {
			if (cur_frm !== frm || frm.doc.name !== opp_name) {
				return;
			}
			const existing = project_name_from_get_value(r?.message);
			if (existing) {
				add_view_item(existing);
				return;
			}
			if (frm.doc.workflow_state === "Approved") {
				add_create_item();
			}
		})
		.catch(() => {
			if (frm.doc.workflow_state === "Approved") {
				add_create_item();
			}
		});
}

function create_shipment_project_from_opportunity(frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.project.create_project_from_opportunity",
		args: { opportunity: frm.doc.name },
		freeze: true,
		callback(r) {
			if (!r.exc && r.message) {
				cache_shipment_project_for_opportunity(frm, r.message);
				frappe.show_alert({
					message: __("Shipment Project created"),
					indicator: "green",
				});
				frappe.set_route("Form", "Project", r.message);
			}
		},
	});
}

function hide_procurement_create_buttons(frm) {
	const remove = () => {
		frm.remove_custom_button(__("Supplier Quotation"), __("Create"));
		frm.remove_custom_button(__("Request For Quotation"), __("Create"));
		// NOTE: Do NOT remove "Create Shipment Project" or "View Project" here.
	};
	remove();
	[50, 200, 600, 1000, 1500].forEach((delay) => setTimeout(remove, delay));
}

frappe.provide("cgm_shipping.opportunity_menu");

cgm_shipping.opportunity_menu = {
	paint: add_shipment_project_create_menu_item,
	schedule: schedule_shipment_project_create_menu,
	hide_procurement: hide_procurement_create_buttons,
};
