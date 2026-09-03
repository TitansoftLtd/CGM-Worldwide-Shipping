// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("Air Waybill", {
	onload(frm) {
		if (frm.is_new() && frappe.route_options?.linked_opportunity) {
			remember_return_opportunity(frm, frappe.route_options.linked_opportunity);
		}
		apply_awb_route_defaults(frm);
		apply_awb_seed_from_opportunity(frm);
	},

	refresh(frm) {
		apply_awb_route_defaults(frm);
		if (frm.doc.docstatus === 1) {
			add_create_opportunity_button(frm);
		}
		add_back_to_opportunity_button(frm);
	},

	on_submit(frm) {
		return_to_opportunity_after_submit(frm);
	},
});

const CGM_RETURN_OPPORTUNITY_KEY = "cgm_return_opportunity";
const CGM_PENDING_AWB_LINK_KEY = "cgm_pending_awb_link";
const CGM_AWB_SEED_OPPORTUNITY_KEY = "cgm_awb_seed_opportunity";

const AWB_SEED_SCALAR_FIELDS = [
	"customer",
	"shipment_type",
	"client_reference_no",
	"airline",
	"eta",
	"etd",
	"weight_uom",
	"net_weight",
	"gross_weight",
	"port_of_loading",
	"port_of_discharge",
	"description",
	"number_of_packages",
	"package_type",
	"linked_opportunity",
];

function is_saved_opportunity_name(name) {
	return Boolean(name && !String(name).startsWith("new-"));
}

function apply_awb_route_defaults(frm) {
	if (!frm.is_new()) {
		return;
	}

	const opts = frappe.route_options || {};
	if (opts.linked_opportunity) {
		remember_return_opportunity(frm, opts.linked_opportunity);
	}

	AWB_SEED_SCALAR_FIELDS.forEach((fieldname) => {
		const value = opts[fieldname];
		if (value == null || value === "" || !frm.fields_dict[fieldname]) {
			return;
		}
		if (frm.doc[fieldname]) {
			return;
		}
		frm.set_value(fieldname, value);
	});

	// Legacy route_options aliases from older Opportunity seeds.
	if (opts.client_ref && !frm.doc.client_reference_no) {
		frm.set_value("client_reference_no", opts.client_ref);
	}
	if (opts.client_refrence_no && !frm.doc.client_reference_no) {
		frm.set_value("client_reference_no", opts.client_refrence_no);
	}

	set_default_air_shipment_type(frm);
}

function apply_awb_seed_from_opportunity(frm) {
	if (!frm.is_new() || frm._cgm_awb_seed_applied) {
		return;
	}

	const opportunity =
		frm.doc.linked_opportunity ||
		localStorage.getItem(CGM_AWB_SEED_OPPORTUNITY_KEY) ||
		localStorage.getItem(CGM_RETURN_OPPORTUNITY_KEY);

	if (!is_saved_opportunity_name(opportunity)) {
		return;
	}

	remember_return_opportunity(frm, opportunity);
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill.get_awb_seed_for_opportunity",
		args: { opportunity },
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			apply_awb_seed_payload(frm, r.message);
			frm._cgm_awb_seed_applied = true;
			localStorage.removeItem(CGM_AWB_SEED_OPPORTUNITY_KEY);
		},
	});
}

function apply_awb_seed_payload(frm, seed) {
	if (!seed || typeof seed !== "object") {
		return;
	}

	AWB_SEED_SCALAR_FIELDS.forEach((fieldname) => {
		const value = seed[fieldname];
		if (value == null || value === "" || !frm.fields_dict[fieldname]) {
			return;
		}
		const current = frm.doc[fieldname];
		if (current != null && current !== "") {
			return;
		}
		frm.set_value(fieldname, value);
	});

	if (seed.linked_opportunity) {
		remember_return_opportunity(frm, seed.linked_opportunity);
	}
}

function remember_return_opportunity(frm, opportunity) {
	if (!opportunity) {
		return;
	}
	localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, opportunity);
	if (is_saved_opportunity_name(opportunity)) {
		frm.set_value("linked_opportunity", opportunity);
	}
}

function get_cgm_return_opportunity(frm) {
	const from_storage = localStorage.getItem(CGM_RETURN_OPPORTUNITY_KEY);
	if (is_saved_opportunity_name(from_storage)) {
		return from_storage;
	}
	if (is_saved_opportunity_name(frm.doc.linked_opportunity)) {
		return frm.doc.linked_opportunity;
	}
	return null;
}

function add_back_to_opportunity_button(frm) {
	const opportunity = get_cgm_return_opportunity(frm);
	if (!opportunity) {
		return;
	}
	frm.add_custom_button(__("Back to Opportunity"), () => {
		frappe.set_route("Form", "Opportunity", opportunity);
	});
}

function set_default_air_shipment_type(frm) {
	if (!frm.is_new() || frm.doc.shipment_type) {
		return;
	}
	frappe.db.get_value(
		"Shipment Type",
		{ default_mode_of_transport: "Air", is_active: 1 },
		"name",
		(r) => {
			if (r && r.name && frm.is_new() && !frm.doc.shipment_type) {
				frm.set_value("shipment_type", r.name);
			}
		}
	);
}

function add_create_opportunity_button(frm) {
	if (frm.doc.linked_opportunity) {
		frm.add_custom_button(
			__("Opportunity"),
			() => frappe.set_route("Form", "Opportunity", frm.doc.linked_opportunity),
			__("View")
		);
		frm.page.set_inner_btn_group_as_primary(__("View"));
		return;
	}

	frm.add_custom_button(
		__("Opportunity"),
		() => {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill.create_opportunity_from_air_waybill",
				args: { air_waybill: frm.doc.name },
				freeze: true,
				callback(r) {
					if (!r.exc && r.message) {
						frappe.show_alert({
							message: __("Opportunity {0} created", [r.message]),
							indicator: "green",
						});
						frappe.set_route("Form", "Opportunity", r.message);
					}
				},
			});
		},
		__("Create")
	);
	frm.page.set_inner_btn_group_as_primary(__("Create"));
}

function return_to_opportunity_after_submit(frm) {
	if (frm.doc.docstatus !== 1) {
		return;
	}
	const opportunity = get_cgm_return_opportunity(frm);
	if (!opportunity || frm.__cgm_returned_to_opportunity) {
		return;
	}
	frm.__cgm_returned_to_opportunity = true;

	const redirect = (target_opportunity) => {
		if (!target_opportunity) {
			frm.__cgm_returned_to_opportunity = false;
			return;
		}
		localStorage.removeItem(CGM_RETURN_OPPORTUNITY_KEY);
		frappe.show_alert({
			message: __("Air Waybill submitted — returning to Opportunity to continue."),
			indicator: "green",
		});
		frappe.set_route("Form", "Opportunity", target_opportunity);
	};

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill.get_awb_submit_payload",
		args: {
			awb_name: frm.doc.name,
			opportunity,
		},
		callback(r) {
			const target = (!r.exc && r.message && r.message.opportunity) || opportunity;
			if (!r.exc && r.message) {
				localStorage.setItem(
					CGM_PENDING_AWB_LINK_KEY,
					JSON.stringify({
						opportunity: target,
						...r.message,
					})
				);
			}
			redirect(target);
		},
		error() {
			redirect(opportunity);
		},
	});
}
