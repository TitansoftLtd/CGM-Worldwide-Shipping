# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

const REQUESTED_CONTAINERS_FIELD = "requested_cargo_quantity";

function cargo_type_code(frm) {
	return (frm.doc.requested_cargo_type || "").trim().toUpperCase();
}

/**
 * LCL → packages only.
 * Otherwise show the requested-containers table (FCL, empty, or size-like
 * Cargo Type values). Hiding only when cargo === LCL avoids mid-edit
 * disappear when Cargo Type is not exactly "FCL".
 */
function toggle_cargo_fields(frm) {
	const is_lcl = cargo_type_code(frm) === "LCL";
	const show_table = !is_lcl;
	const show_packages = is_lcl;

	frm.set_df_property(REQUESTED_CONTAINERS_FIELD, "hidden", show_table ? 0 : 1);
	frm.set_df_property("number_of_packages", "hidden", show_packages ? 0 : 1);
	frm.set_df_property("package_type", "hidden", show_packages ? 0 : 1);

	if (show_table) {
		frm.refresh_field(REQUESTED_CONTAINERS_FIELD);
	}
	if (show_packages) {
		frm.refresh_field("number_of_packages");
		frm.refresh_field("package_type");
	}
}

frappe.ui.form.on("Booking Confirmation", {
	onload(frm) {
		toggle_cargo_fields(frm);

		if (frm.is_new()) {
			if (frappe.route_options?.linked_opportunity) {
				remember_return_opportunity(frm, frappe.route_options.linked_opportunity);
			}
			if (frappe.route_options?.customer && !frm.doc.customer) {
				frm.set_value("customer", frappe.route_options.customer);
			}
			if (frappe.route_options?.shipment_type && !frm.doc.shipment_type) {
				frm.set_value("shipment_type", frappe.route_options.shipment_type);
			}
		}
	},

	refresh(frm) {
		toggle_cargo_fields(frm);

		if (frm.doc.docstatus === 1) {
			add_create_opportunity_button(frm);
		}
		add_back_to_opportunity_button(frm);
	},

	on_submit(frm) {
		return_to_opportunity_after_submit(frm);
	},

	requested_cargo_type(frm) {
		toggle_cargo_fields(frm);
	},
});

const CGM_RETURN_OPPORTUNITY_KEY = "cgm_return_opportunity";
const CGM_PENDING_BOOKING_LINK_KEY = "cgm_pending_booking_link";

function is_saved_opportunity_name(name) {
	return Boolean(name && !String(name).startsWith("new-"));
}

function remember_return_opportunity(frm, opportunity) {
	if (!opportunity) {
		return;
	}
	localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, opportunity);
	if (is_saved_opportunity_name(opportunity)) {
		frm.doc.linked_opportunity = opportunity;
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
				method:
					"cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation.booking_confirmation.create_opportunity_from_booking_confirmation",
				args: { booking_confirmation: frm.doc.name },
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
			message: __("Booking Confirmation submitted — returning to Opportunity to continue."),
			indicator: "green",
		});
		frappe.set_route("Form", "Opportunity", target_opportunity);
	};

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation.booking_confirmation.get_booking_submit_payload",
		args: {
			booking_name: frm.doc.name,
			opportunity,
		},
		callback(r) {
			const target = (!r.exc && r.message && r.message.opportunity) || opportunity;
			if (!r.exc && r.message) {
				localStorage.setItem(
					CGM_PENDING_BOOKING_LINK_KEY,
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
