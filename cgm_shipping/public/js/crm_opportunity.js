const CGM_PENDING_BL_LINK_KEY = "cgm_pending_bl_link";
const CGM_RETURN_OPPORTUNITY_KEY = "cgm_return_opportunity";

frappe.ui.form.on("Opportunity", {
	onload(frm) {
		sync_opportunity_transport_and_containers(frm);
		setup_opportunity_bill_of_lading_create(frm);
		apply_pending_bl_from_submit(frm);
	},

	refresh(frm) {
		sync_opportunity_transport_and_containers(frm);
		setup_opportunity_bill_of_lading_create(frm);
		apply_pending_bl_from_submit(frm);

		if (
			frm.doc.custom_cgm_preshipment_status !== "Opp Ready for Project" ||
			frm.doc.opportunity_from !== "Customer"
		) {
			return;
		}
		frm.add_custom_button(
			__("Create Shipment Project"),
			() => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.create_project_from_opportunity",
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
			},
			__("Create")
		);
	},

	custom_shipment_type(frm) {
		sync_opportunity_transport_and_containers(frm);
	},
});

function sync_opportunity_transport_and_containers(frm) {
	cgm_shipping.transport_reference.toggle(frm, {
		air_waybill: "custom_airway_bill",
		section: "custom_section_break_idqn5",
	});
}

function is_saved_opportunity_name(name) {
	return Boolean(name && !String(name).startsWith("new-"));
}

function setup_opportunity_bill_of_lading_create(frm) {
	const df = frm.get_docfield("custom_bill_of_lading");
	if (!df || frm._cgm_bl_create_route_setup) {
		return;
	}
	frm._cgm_bl_create_route_setup = true;
	df.get_route_options_for_new_doc = () => {
		const opts = {};
		// Remember return route for BL (saved or draft Opportunity).
		if (frm.doc.name) {
			localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, frm.doc.name);
		}
		if (is_saved_opportunity_name(frm.doc.name)) {
			opts.custom_linked_opportunity = frm.doc.name;
		}
		return opts;
	};
}

function apply_pending_bl_from_submit(frm) {
	if (!frm.doc.name) {
		return;
	}

	let pending;
	try {
		pending = JSON.parse(localStorage.getItem(CGM_PENDING_BL_LINK_KEY) || "null");
	} catch {
		return;
	}
	if (!pending || pending.opportunity !== frm.doc.name) {
		return;
	}

	if (pending.bl_name && frm.doc.custom_bill_of_lading !== pending.bl_name) {
		frm.set_value("custom_bill_of_lading", pending.bl_name);
	}
	if (pending.quantity && frm.fields_dict.custom_quantity) {
		frm.set_value("custom_quantity", pending.quantity);
	}
	if (
		pending.attachment &&
		frm.fields_dict.custom_clients_documents &&
		pending.document_type
	) {
		prepend_opportunity_bl_client_document(frm, pending);
	}
	if (cgm_shipping?.bl_containers?.schedule_sync) {
		cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
	}
	localStorage.removeItem(CGM_PENDING_BL_LINK_KEY);
	frappe.show_alert({
		message: __("Bill of Lading {0} linked — continue completing this Opportunity.", [
			pending.bl_name,
		]),
		indicator: "green",
	});
}

function prepend_opportunity_bl_client_document(frm, pending) {
	const field = "custom_clients_documents";
	const rows = frm.doc[field] || [];
	const has_bl = rows.some(
		(row) =>
			row.document_type === pending.document_type ||
			row.attachment === pending.attachment
	);
	if (has_bl) {
		return;
	}

	frm.clear_table(field);
	frm.add_child(field, {
		document_type: pending.document_type,
		attachment: pending.attachment,
		status: "Uploaded",
	});
	(rows || []).forEach((row) => {
		frm.add_child(field, {
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
	frm.refresh_field(field);
}
