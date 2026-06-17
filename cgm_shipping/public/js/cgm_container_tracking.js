frappe.provide("cgm_shipping.container_tracking");

const CGM_CONTAINER_TRACKING_TASK_KEY = "cgm_container_tracking_task";
const CGM_CONTAINER_TRACKING_PROJECT_KEY = "cgm_container_tracking_project";

cgm_shipping.container_tracking.open_from_task = function (frm) {
	if (!frm.doc.project) {
		frappe.msgprint(__("Link this task to a Project before starting container tracking."));
		return;
	}

	frappe.db.get_value(
		"Project",
		frm.doc.project,
		["custom_bill_of_lading", "custom_eta", "custom_batch_no"],
		(values) => {
			if (!values) {
				frappe.msgprint(__("Could not load Project details."));
				return;
			}

			const project = frm.doc.project;
			localStorage.setItem(CGM_CONTAINER_TRACKING_TASK_KEY, frm.doc.name);
			localStorage.setItem(CGM_CONTAINER_TRACKING_PROJECT_KEY, project);

			frappe.model.with_doctype("Container Tracker", () => {
				const doc = frappe.model.get_new_doc("Container Tracker");
				doc.project = project;
				if (values.custom_bill_of_lading) {
					doc.custom_bill_of_lading = values.custom_bill_of_lading;
					doc.bl_number = values.custom_bill_of_lading;
				}
				if (values.custom_eta) {
					doc.eta = values.custom_eta;
				}
				if (values.custom_batch_no) {
					doc.batch_bl_no = values.custom_batch_no;
				}

				frappe.show_alert({
					message: __("Select the Bill of Lading and container to track"),
					indicator: "blue",
				});
				frappe.set_route("Form", "Container Tracker", doc.name);
			});
		}
	);
};
