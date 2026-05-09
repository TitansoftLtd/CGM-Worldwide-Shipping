frappe.ui.form.on("Task", {
	onload(frm) {
		frm.__loaded_status = frm.doc.status;
		frm.set_query("department", () => {
			return {
				filters: {
					parent_department: ["like", "Operations%"],
				},
			};
		});
	},

	refresh(frm) {
		frm.set_df_property("status", "read_only", 1);
		const show_completion_meta = frm.doc.status === "Completed";
		frm.set_df_property("completed_by", "read_only", 1);
		frm.set_df_property("completed_on", "read_only", 1);
		frm.set_df_property("completed_by", "hidden", show_completion_meta ? 0 : 1);
		frm.set_df_property("completed_on", "hidden", show_completion_meta ? 0 : 1);
		// Step 1: make completion easy from task form.
		if (
			frm.doc.docstatus === 0 &&
			frm.doc.status !== "Completed" &&
			frm.doc.status !== "Cancelled" &&
			!is_combined_ucr_idf_task(frm)
		) {
			frm.add_custom_button(__("Mark Completed"), async () => {
				// Step 2: stamp completion metadata from current user/time.
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			});
		}

		// Step 1b: UCR+IDF — Purchase Invoice → Payment Entry → task completed.
		if (
			is_combined_ucr_idf_task(frm) &&
			frm.doc.status !== "Completed" &&
			frm.doc.status !== "Cancelled" &&
			!frm.doc.custom_purchase_invoice &&
			user_can_record_purchase_invoice()
		) {
			frm.add_custom_button(__("Create Purchase Invoice"), () => {
				localStorage.setItem("cgm_return_task", frm.doc.name);
				localStorage.setItem("cgm_pi_for_task", "1");
				frappe.set_route("Form", "Purchase Invoice", "new-purchase-invoice-1");
			});
		}
		if (
			is_combined_ucr_idf_task(frm) &&
			frm.doc.status !== "Completed" &&
			frm.doc.status !== "Cancelled" &&
			frm.doc.custom_purchase_invoice &&
			!frm.doc.custom_payment_entry &&
			user_can_make_payment()
		) {
			frm.add_custom_button(__("Make Payment"), () => {
				localStorage.setItem("cgm_return_task", frm.doc.name);
				localStorage.setItem("cgm_pe_for_task", "1");
				frappe.set_route("Form", "Payment Entry", "new-payment-entry-1");
			});
		}
	},

	validate(frm) {
		// Step 3: ensure metadata exists whenever task is completed.
		if (frm.doc.status === "Completed") {
			if (!frm.doc.completed_by) {
				frm.set_value("completed_by", frappe.session.user);
			}
			if (!frm.doc.completed_on) {
				frm.set_value("completed_on", frappe.datetime.now_datetime());
			}
		}
	},

	after_save(frm) {
		// Step 4: when just completed, offer one-click navigation to next task.
		const just_completed = frm.doc.status === "Completed" && frm.__loaded_status !== "Completed";
		frm.__loaded_status = frm.doc.status;

		// Step 5: PI is on the task; notify finance when payment is still needed.
		if (
			is_combined_ucr_idf_task(frm) &&
			frm.doc.custom_purchase_invoice &&
			!frm.doc.custom_payment_entry &&
			frm.doc.status !== "Completed"
		) {
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.utils.notify_finance_for_task",
				args: { task_name: frm.doc.name },
			});
		}

		if (!just_completed) {
			return;
		}
		open_next_task_prompt(frm);
	},
});

function is_combined_ucr_idf_task(frm) {
	return (
		frm.doc.custom_task_flow_key === "SEA_IMPORT_E2E" &&
		Number(frm.doc.custom_sequence_no || 0) === 1
	);
}

function user_can_make_payment() {
	const roles = frappe.user_roles || [];
	return ["Finance Manager", "Accounts User", "Accounts Manager"].some((role) => roles.includes(role));
}

function user_can_record_purchase_invoice() {
	const roles = frappe.user_roles || [];
	return [
		"Finance Manager",
		"Accounts User",
		"Accounts Manager",
		"Purchase Manager",
		"Purchase User",
	].some((role) => roles.includes(role));
}

function open_next_task_prompt(frm) {
	if (!frm.doc.project || !frm.doc.custom_task_flow_key || !frm.doc.custom_sequence_no) {
		frappe.show_alert({
			message: __("Task marked Completed. Docstatus stays Draft by design for Task doctype."),
			indicator: "green",
		});
		return;
	}

	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Task",
			filters: {
				project: frm.doc.project,
				custom_task_flow_key: frm.doc.custom_task_flow_key,
			},
			fields: ["name", "subject", "custom_sequence_no", "status"],
			order_by: "custom_sequence_no asc",
			limit_page_length: 500,
		},
		callback(r) {
			const tasks = r.message || [];
			const current_seq = Number(frm.doc.custom_sequence_no || 0);
			const next = tasks.find(
				(t) =>
					Number(t.custom_sequence_no || 0) > current_seq &&
					t.status !== "Completed" &&
					t.status !== "Cancelled"
			);

			if (!next) {
				frappe.show_alert({
					message: __("Task completed. No next open task found in this sequence."),
					indicator: "green",
				});
				return;
			}

			frappe.confirm(
				__("Task completed. Open next task: <b>{0}</b>?", [next.subject || next.name]),
				() => frappe.set_route("Form", "Task", next.name)
			);
		},
	});
}