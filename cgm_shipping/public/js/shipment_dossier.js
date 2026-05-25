// Shipment Dossier — workflow uses the `status` field (override_status=1).
// Frappe otherwise shows a red "Draft" badge for all unsubmitted docs; use status instead.

const WORKFLOW_COLOURS = {
	Success: "green",
	Warning: "orange",
	Danger: "red",
	Primary: "blue",
	Inverse: "black",
	Info: "light-blue",
};

function shipment_dossier_indicator(doc) {
	if (doc.__unsaved) {
		return [__("Not Saved"), "orange"];
	}
	const status = doc.status;
	if (!status) {
		return null;
	}
	let colour = frappe.utils.guess_colour(status);
	const wf_state = locals["Workflow State"] && locals["Workflow State"][status];
	if (wf_state && wf_state.style && WORKFLOW_COLOURS[wf_state.style]) {
		colour = WORKFLOW_COLOURS[wf_state.style];
	}
	return [__(status), colour, "status,=," + status];
}

frappe.listview_settings["Shipment Dossier"] = {
	has_indicator_for_draft: 1,
	get_indicator: shipment_dossier_indicator,
};

frappe.ui.form.on("Shipment Dossier", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.status) {
			return;
		}
		const indicator = shipment_dossier_indicator(frm.doc);
		if (indicator) {
			frm.page.set_indicator(indicator[0], indicator[1]);
		}
		if (frm.doc.status && frm.fields_dict.status) {
			frm.set_df_property("status", "read_only", 1);
		}
	},
});
