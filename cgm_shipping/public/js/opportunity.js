// Runs after crm_opportunity.js — late pass removes ERPNext procurement Create items.
frappe.provide("cgm_shipping.opportunity");

const CGM_OPPORTUNITY_MENU_LATE_DELAYS_MS = [400, 1200];

function cgm_late_paint_opportunity_create_menu(frm) {
	if (typeof cgm_shipping.opportunity_menu?.hide_procurement === "function") {
		cgm_shipping.opportunity_menu.hide_procurement(frm);
	}
	// Inner Actions menu is owned by crm_opportunity.js — one debounced rebuild only.
	if (typeof cgm_shipping.opportunity_menu?.paint === "function") {
		cgm_shipping.opportunity_menu.paint(frm);
	}
}

frappe.ui.form.on("Opportunity", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.opportunity_from !== "Customer") {
			return;
		}
		CGM_OPPORTUNITY_MENU_LATE_DELAYS_MS.forEach((delay) => {
			setTimeout(() => {
				if (cur_frm === frm) {
					cgm_late_paint_opportunity_create_menu(frm);
				}
			}, delay);
		});
	},

	after_workflow_action(frm) {
		setTimeout(() => {
			if (cur_frm === frm) {
				cgm_late_paint_opportunity_create_menu(frm);
			}
		}, 1200);
	},
});
