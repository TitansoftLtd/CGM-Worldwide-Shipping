frappe.ui.form.on("Payment Entry", {
	onload(frm) {
		persist_cgm_source_task_on_pe(frm);
	},

	refresh(frm) {
		add_back_to_cgm_task_button_pe(frm);
	},

	on_submit(frm) {
		return_to_cgm_task_from_pe(frm);
	},
});

function get_cgm_source_task_pe(frm) {
	return (
		localStorage.getItem("cgm_return_task") ||
		frm.doc.custom_cgm_source_task ||
		null
	);
}

function persist_cgm_source_task_on_pe(frm) {
	if (!frm.is_new()) {
		return;
	}
	const task_name = localStorage.getItem("cgm_return_task");
	if (task_name && frm.fields_dict.custom_cgm_source_task && !frm.doc.custom_cgm_source_task) {
		frm.set_value("custom_cgm_source_task", task_name);
	}
	if (localStorage.getItem("cgm_pe_for_task") === "1") {
		return;
	}
	if (frm.doc.custom_cgm_source_task) {
		localStorage.setItem("cgm_return_task", frm.doc.custom_cgm_source_task);
		localStorage.setItem("cgm_pe_for_task", "1");
	}
}

function add_back_to_cgm_task_button_pe(frm) {
	const task_name = get_cgm_source_task_pe(frm);
	if (!task_name) {
		return;
	}
	frm.add_custom_button(__("Back to Task"), () => {
		frappe.set_route("Form", "Task", task_name);
	}, __("CGM"));
	frm.page.set_inner_btn_group_as_primary(__("CGM"));
}

function return_to_cgm_task_from_pe(frm) {
	const task_name = get_cgm_source_task_pe(frm);
	if (!task_name || frm.__cgm_returned_to_task) {
		return;
	}
	frm.__cgm_returned_to_task = true;
	localStorage.removeItem("cgm_return_task");
	localStorage.removeItem("cgm_pe_for_task");

	// Server links PE → task on after_commit; redirect once submit finishes.
	frappe.after_ajax(() => {
		frappe.show_alert({
			message: __(
				"Payment submitted - returning to task {0}. Upload and verify receipts there if required.",
				[task_name]
			),
			indicator: "green",
		});
		frappe.set_route("Form", "Task", task_name);
	});
}
