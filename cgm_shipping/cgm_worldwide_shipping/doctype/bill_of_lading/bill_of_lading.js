// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

/**
 * FCL → container table + derived quantity / batch
 * LCL → packages only (no derived quantity)
 */
function bl_cargo_type_code(frm) {
	return (frm.doc.cargo_type || "").trim().toUpperCase();
}

function bl_is_lcl_cargo(frm) {
	const cargo = bl_cargo_type_code(frm);
	if (cargo === "LCL") {
		return true;
	}
	if (cargo === "FCL") {
		return false;
	}
	// Cargo type missing on older/submitted docs — infer from filled rows.
	if ((frm.doc.number_of_packages || "").trim() || frm.doc.package_type) {
		return true;
	}
	return false;
}

function toggle_cargo_fields(frm) {
	const is_lcl = bl_is_lcl_cargo(frm);
	const show_fcl = !is_lcl;

	[
		["section_fcl", show_fcl],
		["container_information", show_fcl],
		["section_lcl", is_lcl],
		["number_of_packages", is_lcl],
		["package_type", is_lcl],
		["quantity", !is_lcl],
		["batch_no", !is_lcl],
	].forEach(([fieldname, show]) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		frm.set_df_property(fieldname, "hidden", show ? 0 : 1);
	});

	if (frm.fields_dict.cargo_type) {
		frm.set_df_property("cargo_type", "hidden", 0);
	}

	if (show_fcl) {
		frm.refresh_field("container_information");
	}
	if (is_lcl) {
		frm.refresh_field("number_of_packages");
		frm.refresh_field("package_type");
	}
}

frappe.ui.form.on("Bill of Lading", {
	onload(frm) {
		setup_bill_of_lading_cargo_type_query(frm);
		toggle_cargo_fields(frm);
		defer_opportunity_link_on_create(frm);
		if (frm.is_new()) {
			if (frappe.route_options?.custom_linked_opportunity) {
				remember_return_opportunity(frm, frappe.route_options.custom_linked_opportunity);
			} else if (frappe.route_options?.linked_opportunity) {
				remember_return_opportunity(frm, frappe.route_options.linked_opportunity);
			} else if (frm.doc.custom_linked_opportunity) {
				remember_return_opportunity(frm, frm.doc.custom_linked_opportunity);
			} else if (frm.doc.linked_opportunity) {
				remember_return_opportunity(frm, frm.doc.linked_opportunity);
			}
			apply_bl_seed_from_opportunity_or_booking(frm);
		} else if (frm.doc.custom_linked_opportunity || frm.doc.linked_opportunity) {
			remember_return_opportunity(
				frm,
				frm.doc.linked_opportunity || frm.doc.custom_linked_opportunity
			);
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

	booking_confirmation(frm) {
		if (!frm.is_new() || frm._cgm_bl_seed_applied) {
			return;
		}
		apply_bl_seed_from_opportunity_or_booking(frm);
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
const CGM_BL_SEED_OPPORTUNITY_KEY = "cgm_bl_seed_opportunity";

const BL_SEED_SCALAR_FIELDS = [
	"customer",
	"client_refrence_no",
	"shipment_type",
	"cargo_type",
	"shipping_line",
	"vessel",
	"voyage_number",
	"port_of_loading",
	"port_of_discharge",
	"etd",
	"eta",
	"commodity",
	"gross_weight",
	"net_weight",
	"weight_uom",
	"number_of_packages",
	"package_type",
	"batch_no",
	"quantity",
	"booking_confirmation",
	"linked_opportunity",
	"bl_number",
];

function apply_bl_seed_from_opportunity_or_booking(frm) {
	if (!frm.is_new() || frm._cgm_bl_seed_applied) {
		return;
	}

	const opportunity =
		frm.doc.linked_opportunity ||
		frm.doc.custom_linked_opportunity ||
		localStorage.getItem(CGM_BL_SEED_OPPORTUNITY_KEY) ||
		localStorage.getItem(CGM_RETURN_OPPORTUNITY_KEY);
	const booking = frm.doc.booking_confirmation;

	const finish = (seed) => {
		if (!seed || typeof seed !== "object") {
			return;
		}
		apply_bl_seed_payload(frm, seed);
		frm._cgm_bl_seed_applied = true;
		localStorage.removeItem(CGM_BL_SEED_OPPORTUNITY_KEY);
	};

	if (is_saved_opportunity_name(opportunity)) {
		remember_return_opportunity(frm, opportunity);
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.get_bl_seed_for_opportunity",
			args: { opportunity },
			callback(r) {
				if (!r.exc && r.message) {
					finish(r.message);
				}
			},
		});
		return;
	}

	if (booking) {
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.get_bl_seed_from_booking",
			args: { booking_confirmation: booking },
			callback(r) {
				if (!r.exc && r.message) {
					finish(r.message);
				}
			},
		});
	}
}

function apply_bl_seed_payload(frm, seed) {
	BL_SEED_SCALAR_FIELDS.forEach((fieldname) => {
		const value = seed[fieldname];
		if (value == null || value === "") {
			return;
		}
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		// Never overwrite a value the user (or route_options) already set,
		// except empty container-driven quantity / batch from booking.
		const current = frm.doc[fieldname];
		if (current != null && current !== "" && !["quantity", "batch_no"].includes(fieldname)) {
			return;
		}
		frm.set_value(fieldname, value);
	});

	if (seed.linked_opportunity) {
		remember_return_opportunity(frm, seed.linked_opportunity);
	}

	const stubs = seed.container_stubs || [];
	const cargo = String(seed.cargo_type || frm.doc.cargo_type || "")
		.trim()
		.toUpperCase();

	if (cargo === "FCL" && stubs.length) {
		const existing = frm.doc.container_information || [];
		const has_real_rows = existing.some(
			(row) =>
				(row.container_number || "").trim() ||
				(row.seal_no || "").trim() ||
				(row.cargo_size || "").trim()
		);
		if (!has_real_rows) {
			frm.clear_table("container_information");
			stubs.forEach((stub) => {
				const row = frm.add_child("container_information");
				row.cargo_size = stub.cargo_size || "";
				row.container_number = stub.container_number || "";
				row.seal_no = stub.seal_no || "";
			});
			frm.refresh_field("container_information");
		}
	}

	toggle_cargo_fields(frm);
	frappe.show_alert({
		message: __(
			"Bill of Lading prefilled from {0}. Enter BL Number, container/seal numbers, and upload the BL.",
			[seed.booking_confirmation ? __("Booking Confirmation") : __("Opportunity")]
		),
		indicator: "blue",
	});
}

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
	if (frm.fields_dict.linked_opportunity) {
		frm.set_df_property("linked_opportunity", "hidden", 1);
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
	if (frm.fields_dict.linked_opportunity && is_saved_opportunity_name(opportunity)) {
		frm.doc.linked_opportunity = opportunity;
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
	if (
		frm.fields_dict.linked_opportunity &&
		frm.doc.linked_opportunity &&
		!is_saved_opportunity_name(frm.doc.linked_opportunity)
	) {
		frm.doc.linked_opportunity = null;
	}
}

function sync_linked_opportunity_on_bl(frm) {
	const opportunity = get_cgm_return_opportunity(frm);
	if (!opportunity || !is_saved_opportunity_name(opportunity)) {
		return;
	}
	if (frm.fields_dict.custom_linked_opportunity) {
		frm.doc.custom_linked_opportunity = opportunity;
	}
	if (frm.fields_dict.linked_opportunity) {
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

function setup_bill_of_lading_cargo_type_query(frm) {
	if (!frm.fields_dict.cargo_type || frm._cgm_bl_cargo_type_query_setup) {
		return;
	}
	frm._cgm_bl_cargo_type_query_setup = true;
	frm.set_query("cargo_type", () => ({
		filters: { cargo_type: ["in", ["FCL", "LCL"]] },
	}));
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
