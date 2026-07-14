// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

/**
 * FCL → container table
 * LCL → number of packages / package type
 */
function toggle_cargo_fields(frm) {
	const cargo = (frm.doc.cargo_type || "").trim().toUpperCase();
	const is_fcl = cargo === "FCL";
	const is_lcl = cargo === "LCL";

	[
		["section_fcl", is_fcl],
		["container_information", is_fcl],
		["section_lcl", is_lcl],
		["number_of_packages", is_lcl],
		["package_type", is_lcl],
	].forEach(([fieldname, show]) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		frm.set_df_property(fieldname, "hidden", show ? 0 : 1);
	});

	if (is_fcl) {
		frm.refresh_field("container_information");
	}
	if (is_lcl) {
		frm.refresh_field("number_of_packages");
		frm.refresh_field("package_type");
	}
}


frappe.ui.form.on("Bill of Lading", {
	onload(frm) {
		toggle_cargo_fields(frm);
		defer_opportunity_link_on_create(frm);
		if (frm.is_new()) {
			if (frappe.route_options?.custom_linked_opportunity) {
				remember_return_opportunity(frm, frappe.route_options.custom_linked_opportunity);
			} else if (frm.doc.custom_linked_opportunity) {
				remember_return_opportunity(frm, frm.doc.custom_linked_opportunity);
			}
		} else if (frm.doc.custom_linked_opportunity) {
			remember_return_opportunity(frm, frm.doc.custom_linked_opportunity);
		}
		clear_draft_linked_opportunity_link(frm);
		hide_linked_opportunity_field(frm);
	},

	refresh(frm) {
		toggle_cargo_fields(frm);
		clear_draft_linked_opportunity_link(frm);
		hide_linked_opportunity_field(frm);
		add_back_to_opportunity_button(frm);
		if (!frm.is_new()) {
			add_create_opportunity_button(frm);
		}
		setup_bill_of_lading_shipment_type_query(frm);
	},

	cargo_type(frm) {
		toggle_cargo_fields(frm);
	},

	before_save(frm) {
		sync_linked_opportunity_on_bl(frm);
	},

	before_submit(frm) {
		sync_linked_opportunity_on_bl(frm);
	},

	on_submit(frm) {
		return_to_opportunity_after_submit(frm);
	},
});

const CGM_RETURN_OPPORTUNITY_KEY = "cgm_return_opportunity";
const CGM_PENDING_BL_LINK_KEY = "cgm_pending_bl_link";

function is_saved_opportunity_name(name) {
	return Boolean(name && !String(name).startsWith("new-"));
}

function is_opportunity_route_name(name) {
	return Boolean(name && String(name).trim());
}

function hide_linked_opportunity_field(frm) {
	if (frm.fields_dict.custom_linked_opportunity) {
		frm.set_df_property("custom_linked_opportunity", "hidden", 1);
	}
}

function remember_return_opportunity(frm, opportunity) {
	if (!is_opportunity_route_name(opportunity)) {
		return;
	}
	localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, opportunity);
	if (
		frm.fields_dict.custom_linked_opportunity &&
		is_saved_opportunity_name(opportunity)
	) {
		frm.doc.custom_linked_opportunity = opportunity;
	}
}

function defer_opportunity_link_on_create(frm) {
	const from_link = frappe._from_link;
	if (!from_link?.field_obj?.frm || from_link.field_obj.frm.doctype !== "Opportunity") {
		return;
	}
	if (from_link.field_obj.df?.fieldname !== "custom_bill_of_lading") {
		return;
	}

	const opportunity =
		from_link.set_route_args?.[2] || from_link.field_obj.frm.docname;
	remember_return_opportunity(frm, opportunity);
	delete frappe._from_link;
}

function clear_draft_linked_opportunity_link(frm) {
	if (
		frm.fields_dict.custom_linked_opportunity &&
		frm.doc.custom_linked_opportunity &&
		!is_saved_opportunity_name(frm.doc.custom_linked_opportunity)
	) {
		frm.doc.custom_linked_opportunity = null;
	}
}

function sync_linked_opportunity_on_bl(frm) {
	const opportunity = get_cgm_return_opportunity(frm);
	if (
		!opportunity ||
		!is_saved_opportunity_name(opportunity) ||
		!frm.fields_dict.custom_linked_opportunity
	) {
		return;
	}
	frm.doc.custom_linked_opportunity = opportunity;
}

function get_cgm_return_opportunity(frm) {
	const from_storage = localStorage.getItem(CGM_RETURN_OPPORTUNITY_KEY);
	if (is_saved_opportunity_name(from_storage)) {
		return from_storage;
	}
	if (is_saved_opportunity_name(frm.doc.custom_linked_opportunity)) {
		return frm.doc.custom_linked_opportunity;
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
	}, __("CGM"));
	frm.page.set_inner_btn_group_as_primary(__("CGM"));
}

function get_bl_linked_opportunity_name(frm) {
	if (is_saved_opportunity_name(frm.doc.linked_opportunity)) {
		return frm.doc.linked_opportunity;
	}
	if (is_saved_opportunity_name(frm.doc.custom_linked_opportunity)) {
		return frm.doc.custom_linked_opportunity;
	}
	const from_return = get_cgm_return_opportunity(frm);
	if (is_saved_opportunity_name(from_return)) {
		return from_return;
	}
	return null;
}

function clear_bl_opportunity_menu_buttons(frm) {
	frm.remove_custom_button(__("Opportunity"), __("Create"));
	frm.remove_custom_button(__("Opportunity"), __("View"));
}

function add_create_opportunity_button(frm) {
	if (frm.is_new()) {
		return;
	}

	clearTimeout(frm._cgm_bl_opp_btn_timer);
	// ERPNext form refresh can run after client scripts; defer like crm_lead.js.
	frm._cgm_bl_opp_btn_timer = setTimeout(() => {
		render_bl_opportunity_button(frm);
	}, 0);
}

function render_bl_opportunity_button(frm) {
	if (cur_frm !== frm || frm.is_new()) {
		return;
	}

	clear_bl_opportunity_menu_buttons(frm);

	const show_view = (opportunity) => {
		clear_bl_opportunity_menu_buttons(frm);
		frm.add_custom_button(
			__("Opportunity"),
			() => frappe.set_route("Form", "Opportunity", opportunity),
			__("View")
		);
		frm.page.set_inner_btn_group_as_primary(__("View"));
	};

	const show_create = () => {
		clear_bl_opportunity_menu_buttons(frm);

		const create_opportunity = () => {
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.create_opportunity_from_bill_of_lading",
				args: { bill_of_lading: frm.doc.name },
				freeze: true,
				callback(r) {
					if (!r.exc && r.message) {
						frm.doc.linked_opportunity = r.message;
						frappe.show_alert({
							message: __("Opportunity {0} created", [r.message]),
							indicator: "green",
						});
						frappe.set_route("Form", "Opportunity", r.message);
					}
				},
			});
		};

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("Opportunity"),
				() => {
					frappe.confirm(
						__(
							"Submit this Bill of Lading first, then create the linked Opportunity?"
						),
						() => {
							frm.save("Submit").then(() => create_opportunity());
						}
					);
				},
				__("Create")
			);
		} else if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Opportunity"), create_opportunity, __("Create"));
		}

		frm.page.set_inner_btn_group_as_primary(__("Create"));
	};

	const linked = get_bl_linked_opportunity_name(frm);
	if (linked) {
		show_view(linked);
		return;
	}

	// Back-link may exist in DB but not be on the loaded form doc yet.
	frappe.db
		.get_value("Opportunity", { custom_bill_of_lading: frm.doc.name }, "name")
		.then((r) => {
			if (cur_frm !== frm) {
				return;
			}
			const opportunity = r?.message?.name;
			if (opportunity) {
				if (frm.fields_dict.linked_opportunity) {
					frm.doc.linked_opportunity = opportunity;
				}
				show_view(opportunity);
				return;
			}
			show_create();
		})
		.catch(() => show_create());
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
			message: __(
				"Bill of Lading submitted - returning to Opportunity to continue."
			),
			indicator: "green",
		});
		frappe.set_route("Form", "Opportunity", target_opportunity);
	};

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.get_bl_submit_payload",
		args: {
			bl_name: frm.doc.name,
			opportunity,
		},
		callback(r) {
			const target =
				(!r.exc && r.message && r.message.opportunity) || opportunity;
			if (!r.exc && r.message) {
				localStorage.setItem(
					CGM_PENDING_BL_LINK_KEY,
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

function setup_bill_of_lading_shipment_type_query(frm) {
	if (!frm.fields_dict.shipment_type || frm._cgm_bl_shipment_type_query_setup) {
		return;
	}
	frm._cgm_bl_shipment_type_query_setup = true;

	const apply_query = (profiles) => {
		const sea_types = cgm_shipping.transport_reference.shipment_type_names_for_category(
			profiles,
			"sea"
		);
		frm.set_query("shipment_type", () => {
			if (!sea_types.length) {
				return { filters: { is_active: 1 } };
			}
			return { filters: { name: ["in", sea_types] } };
		});
	};

	if (cgm_shipping.transport_reference._profiles) {
		apply_query(cgm_shipping.transport_reference._profiles);
		return;
	}

	cgm_shipping.transport_reference.ensure_profiles().then(apply_query);
}
