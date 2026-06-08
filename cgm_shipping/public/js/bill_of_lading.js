frappe.ui.form.on("Bill of Lading", {
	onload(frm) {
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
		clear_draft_linked_opportunity_link(frm);
		hide_linked_opportunity_field(frm);
		add_back_to_opportunity_button(frm);
		if (frm.doc.docstatus === 1) {
			return_to_opportunity_after_submit(frm);
		}
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
				"Bill of Lading submitted — returning to Opportunity to continue."
			),
			indicator: "green",
		});
		frappe.set_route("Form", "Opportunity", target_opportunity);
	};

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers.get_bl_submit_payload",
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
