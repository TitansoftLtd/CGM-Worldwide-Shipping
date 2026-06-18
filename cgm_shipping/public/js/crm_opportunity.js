frappe.ui.form.on("Opportunity", {
	onload(frm) {
		run_opportunity_form_syncs(frm, { apply_pending_bl: true });
	},

	before_workflow_action(frm) {
		// Workflow already saved on the server; skip read-only syncs on the next refresh.
		frm._cgm_skip_readonly_sync = true;
	},

	refresh(frm) {
		if (frm.doc.docstatus > 0) {
			// Submitted Opportunity — show fields only; never run BL sync / clear logic.
			sync_opportunity_transport_and_containers(frm);
			setup_create_shipment_project_button(frm);
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

		setup_create_shipment_project_button(frm);
		hide_procurement_create_buttons(frm);
	},

	after_workflow_action(frm) {
		frm._cgm_skip_readonly_sync = false;
		invalidate_opportunity_bl_sync(frm);
		restore_opportunity_clean_state(frm);
	},

	custom_shipment_type(frm) {
		sync_opportunity_transport_and_containers(frm);
	},

	custom_bill_of_lading(frm) {
		sync_opportunity_transport_and_containers(frm);
	},
});

frappe.ui.form.on("Shipment Document", {
	custom_clients_documents_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "uploaded_by", frappe.session.user);
		frappe.model.set_value(cdt, cdn, "uploaded_on", frappe.datetime.now_datetime());
	},
});

function run_opportunity_form_syncs(frm, opts = {}) {
	register_clients_documents_remove_handler(frm);
	sync_opportunity_transport_and_containers(frm);
	setup_opportunity_bill_of_lading_create(frm);
	if (opts.apply_pending_bl) {
		apply_pending_bl_from_submit(frm);
	}
	sync_bl_from_clients_documents(frm, { silent: true });
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
		rows.find((row) => row.attachment && is_bl_document_type(row.document_type)) ||
		rows.find((row) => row.attachment) ||
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

function get_opportunity_container_type_field(frm) {
	if (frm.fields_dict.custom_container_type) {
		return "custom_container_type";
	}
	if (frm.fields_dict.custom_container_type_) {
		return "custom_container_type_";
	}
	return null;
}

function apply_bl_classification_fields(frm, data) {
	if (!data) {
		return;
	}
	if (data.shipment_type && frm.fields_dict.custom_shipment_type) {
		frm.set_value("custom_shipment_type", data.shipment_type);
	}
	if (data.default_mode_of_transport && frm.fields_dict.custom_mode_of_transport) {
		frm.set_value("custom_mode_of_transport", data.default_mode_of_transport);
	}
	const container_type_field = get_opportunity_container_type_field(frm);
	if (data.container_type && container_type_field) {
		frm.set_value(container_type_field, data.container_type);
	}

	const tracking_fields = [
		["client_refrence_no", "custom_client_refrence_no"],
		["batch_no", "custom_batch_no"],
	];
	for (const [src, dest] of tracking_fields) {
		if (data[src] != null && data[src] !== "" && frm.fields_dict[dest]) {
			frm.set_value(dest, data[src]);
		}
	}
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
	cgm_shipping.transport_reference.toggle(frm, {
		air_waybill: "custom_air_waybill",
		bill_of_lading: bl_link_field || undefined,
		section: "custom_section_break_idqn5",
	});
	cgm_shipping.transport_reference.toggle_container_type(frm, {
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
		}
		return opts;
	};
}


// ─── Pending BL from submit ───────────────────────────────────────────────────

function apply_pending_bl_from_submit(frm) {
	if (!frm.doc.name) {
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
	const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;
	const docs_field = get_clients_documents_field(frm);

	if (pending.bl_name && bl_link_field && frm.doc[bl_link_field] !== pending.bl_name) {
		frm.set_value(bl_link_field, pending.bl_name);
	}
	apply_bl_classification_fields(frm, pending);
	if (pending.quantity && quantity_field && frm.doc[quantity_field] !== pending.quantity) {
		frm.set_value(quantity_field, pending.quantity);
	}
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
			row.attachment === pending.attachment
	);
	if (already_exists) {
		return;
	}

	frm.clear_table(docs_field);
	frm.add_child(docs_field, {
		document_type: pending.document_type,
		attachment: pending.attachment,
		status: "Uploaded",
	});
	rows.forEach((row) => {
		frm.add_child(docs_field, {
			document_type: row.document_type,
			attachment: row.attachment,
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
		if (cgm_shipping?.bl_containers?.schedule_sync) {
			cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
		}
		return;
	}

	fetch_and_apply_bl_data(frm, bl_row, null, null, opts);
}

function fetch_and_apply_bl_data(frm, row, cdt, cdn, opts = {}) {
	if (!row.attachment) {
		return;
	}

	const sync_id = (frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1);

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_containers_for_bl_attachment",
		args: { attachment: row.attachment },
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
	"type_of_container",
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
	const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;
	const bl_name = data.bl_name || "";
	const attachment = data.attachment || "";

	if (cdt && cdn) {
		const child = locals[cdt]?.[cdn];
		if (child && child.attachment !== attachment) {
			frappe.model.set_value(cdt, cdn, "attachment", attachment);
		}
	} else if (row.name) {
		const child = locals[row.doctype]?.[row.name];
		if (child && child.attachment !== attachment) {
			frappe.model.set_value(row.doctype, row.name, "attachment", attachment);
		}
	}

	if (bl_link_field && bl_name && frm.doc[bl_link_field] !== bl_name) {
		frm.set_value(bl_link_field, bl_name);
	}
	apply_bl_classification_fields(frm, data);
	if (quantity_field && String(frm.doc[quantity_field] ?? "") !== String(data.quantity ?? "")) {
		frm.set_value(quantity_field, data.quantity || "");
	}

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

function setup_create_shipment_project_button(frm) {
	if (frm.is_new() || !frm.doc.name || frm.doc.opportunity_from !== "Customer") {
		return;
	}

	clearTimeout(frm._cgm_project_btn_timer);
	frm._cgm_project_btn_timer = setTimeout(() => {
		render_shipment_project_buttons(frm);
	}, 450);
}

function render_shipment_project_buttons(frm) {
	if (cur_frm !== frm || frm.is_new() || frm.doc.opportunity_from !== "Customer") {
		return;
	}

	const is_approved = frm.doc.workflow_state === "Approved";

	frappe.db
		.get_value("Project", { custom_source_opportunity: frm.doc.name }, "name")
		.then((r) => {
			if (cur_frm !== frm) {
				return;
			}

			const existing = r?.message?.name;
			if (existing) {
				const open_project = () => frappe.set_route("Form", "Project", existing);
				frm.add_custom_button(__("View Project"), open_project, __("Create"));
				frm.page.set_inner_btn_group_as_primary(__("Create"));
				return;
			}

			if (is_approved) {
				const create_fn = () => create_shipment_project_from_opportunity(frm);
				frm.add_custom_button(__("Create Shipment Project"), create_fn, __("Create"));
				frm.page.set_inner_btn_group_as_primary(__("Create"));
				return;
			}

			const explain = () => {
				frappe.msgprint({
					title: __("Approval required"),
					message: __(
						"This Opportunity must be <b>Approved</b> before creating a Shipment Project. Current status: <b>{0}</b>.",
						[frm.doc.workflow_state || __("Not set")]
					),
					indicator: "orange",
				});
			};
			frm.add_custom_button(__("Create Shipment Project"), explain, __("Create"));
			frm.page.set_inner_btn_group_as_primary(__("Create"));
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
	};
	remove();
	[50, 200, 600].forEach((delay) => setTimeout(remove, delay));
}
