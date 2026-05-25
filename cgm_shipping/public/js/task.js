frappe.ui.form.on("Task", {
	onload(frm) {
		frm.__loaded_status = frm.doc.status;
		frm.set_query("department", () => ({
			filters: { parent_department: ["like", "Operations%"] },
		}));
	},

	refresh(frm) {
		apply_sea_task_form_layout(frm);

		frm.set_df_property("status", "read_only", 1);
		const show_completion_meta = frm.doc.status === "Completed";
		frm.set_df_property("completed_by", "read_only", 1);
		frm.set_df_property("completed_on", "read_only", 1);
		frm.set_df_property("completed_by", "hidden", show_completion_meta ? 0 : 1);
		frm.set_df_property("completed_on", "hidden", show_completion_meta ? 0 : 1);

		const ui = get_sea_task_ui(frm);
		if (ui.auto_intake_intro) {
			frm.set_intro(
				__(
					"Completed automatically at Project creation. Documents were copied from the Project file (approved on Lead/Opportunity)."
				),
				"blue"
			);
		} else if (ui.is_sea_task && frm.doc.project) {
			let intro = __(
				"Shipment master data lives on the linked <b>Project</b>. Use Task Documents for step-specific proofs only."
			);
			if (ui.show_permits) {
				const seq = sea_task_sequence(frm);
				if (seq === 6) {
					intro = __(
						"<b>1 Finance:</b> Create PI & <b>Make Payment</b> · " +
							"<b>2 Operations:</b> Upload <b>Payment Receipt</b> per permit · " +
							"<b>3 Finance:</b> Tick <b>Receipt Verified</b> · " +
							"<b>4</b> Then <b>Complete Permit Payment Task</b>."
					);
				} else {
					intro = __(
						"<b>Declaration:</b> Attach <b>Permit Invoice (for Finance)</b> on each row, then click " +
							"<b>Notify Finance — invoices ready</b>. This task stays open until payment and receipts are done on the finance task."
					);
				}
			} else if (ui.show_payments) {
				intro = __(
					"Attach the <b>Supplier Invoice</b> on Task Documents for Accounts, then <b>Create Purchase Invoice</b> and <b>Make Payment</b>."
				);
			}
			frm.set_intro(intro, "blue");
		}

		if (
			ui.show_permits &&
			sea_task_sequence(frm) === 5 &&
			frm.doc.status !== "Completed" &&
			!frm.doc.custom_permit_invoices_submitted
		) {
			frm.add_custom_button(__("Notify Finance — invoices ready"), () => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow.submit_permit_invoices_to_finance",
					args: { task_name: frm.doc.name },
					freeze: true,
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: r.message.message || __("Finance notified"),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
				});
			});
		}

		if (
			frm.doc.docstatus === 0 &&
			frm.doc.status !== "Completed" &&
			frm.doc.status !== "Cancelled" &&
			!ui.hide_mark_complete &&
			!ui.show_payments &&
			!ui.show_permits
		) {
			frm.add_custom_button(__("Mark Completed"), async () => {
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			});
		}

		if (
			sea_task_sequence(frm) === 6 &&
			frm.doc.status !== "Completed" &&
			frm.doc.custom_payment_entry &&
			user_can_make_payment()
		) {
			frm.add_custom_button(__("Complete Permit Payment Task"), async () => {
				await frm.set_value("completed_by", frappe.session.user);
				await frm.set_value("completed_on", frappe.datetime.now_datetime());
				await frm.set_value("status", "Completed");
				await frm.save();
			});
		}

		if (ui.show_permits && frm.doc.status === "Completed" && !permit_rows_have_invoices(frm)) {
			frm.add_custom_button(__("Re-open to attach invoices"), () => {
				frappe.call({
					method: "cgm_shipping.cgm_worldwide_shipping.customizations.task_completion_rules.reopen_task_for_permit_attachments",
					args: { task_name: frm.doc.name },
					callback(r) {
						if (!r.exc) {
							frappe.show_alert({
								message: __("Task re-opened — attach Permit Invoice on each row, then save."),
								indicator: "orange",
							});
							frm.reload_doc();
						}
					},
				});
			});
		}

		if (ui.show_payments && sea_task_sequence(frm) === 6 && frm.doc.project) {
			frm.add_custom_button(__("View Permit Invoices on Project"), () => {
				frappe.set_route("Form", "Project", frm.doc.project);
			}, __("Finance"));
		}

		if (ui.show_payments && frm.doc.status !== "Completed" && frm.doc.status !== "Cancelled") {
			if (!frm.doc.custom_purchase_invoice && user_can_record_purchase_invoice()) {
				frm.add_custom_button(__("Create Purchase Invoice"), () => {
					open_purchase_invoice_from_task(frm);
				});
			}
			if (frm.doc.custom_purchase_invoice) {
				if (!frm.doc.custom_payment_entry && user_can_make_payment()) {
					frm.add_custom_button(__("Make Payment"), () => {
						open_payment_entry_from_task(frm);
					});
				}
				if (frm.doc.project && user_can_record_purchase_invoice()) {
					frm.add_custom_button(
						__("Sync PI Project"),
						() => sync_pi_project_from_task(frm),
						__("Finance")
					);
				}
			}
		}

		if (ui.is_sea_task && frm.doc.project) {
			frm.add_custom_button(__("Open Shipment Project"), () => {
				frappe.set_route("Form", "Project", frm.doc.project);
			});
		}
	},

	validate(frm) {
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
		const just_completed = frm.doc.status === "Completed" && frm.__loaded_status !== "Completed";
		frm.__loaded_status = frm.doc.status;
		const ui = get_sea_task_ui(frm);

		if (
			ui.show_payments &&
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

const SEA_FLOW_KEY = "SEA_IMPORT_E2E";
const SEA_PAYMENT_TASK_SEQS = [4, 6, 12, 14, 18];
const SEA_PERMIT_APPLICATION_TASK_SEQS = [5, 15];
const SEA_AUTO_COMPLETE_TASK_SEQS = [1, 2];
const SEA_LIGHT_TASK_SEQS = [8, 19, 20, 21, 22, 23, 24];
const SEA_NO_DOCUMENT_TASK_SEQS = [1, 2];

const SEA_TASK_HIDDEN_FIELDS = [
	"is_template",
	"issue",
	"type",
	"color",
	"is_milestone",
	"task_weight",
	"exp_start_date",
	"exp_end_date",
	"expected_time",
	"duration",
	"progress",
	"total_costing_amount",
	"total_billing_amount",
	"total_expense_claim",
	"review_date",
	"closing_date",
];

function is_sea_clearance_task(frm) {
	return frm.doc.custom_task_flow_key === SEA_FLOW_KEY;
}

function sea_task_sequence(frm) {
	return Number(frm.doc.custom_sequence_no || 0);
}

function get_sea_task_ui(frm) {
	const seq = sea_task_sequence(frm);
	if (!is_sea_clearance_task(frm)) {
		return {
			is_sea_task: false,
			show_documents: true,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: false,
		};
	}
	if (SEA_AUTO_COMPLETE_TASK_SEQS.includes(seq)) {
		return {
			is_sea_task: true,
			show_documents: true,
			documents_read_only: true,
			show_permits: false,
			show_payments: false,
			show_external_ref: false,
			show_description: true,
			auto_intake_intro: true,
			hide_mark_complete: true,
		};
	}
	if (SEA_PERMIT_APPLICATION_TASK_SEQS.includes(seq)) {
		return {
			is_sea_task: true,
			show_documents: false,
			documents_read_only: false,
			show_permits: true,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: false,
		};
	}
	if (SEA_PAYMENT_TASK_SEQS.includes(seq)) {
		return {
			is_sea_task: true,
			show_documents: true,
			documents_read_only: false,
			show_permits: seq === 6,
			show_payments: true,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: true,
		};
	}
	if (SEA_LIGHT_TASK_SEQS.includes(seq)) {
		return {
			is_sea_task: true,
			show_documents: false,
			documents_read_only: false,
			show_permits: false,
			show_payments: false,
			show_external_ref: true,
			show_description: true,
			auto_intake_intro: false,
			hide_mark_complete: false,
		};
	}
	return {
		is_sea_task: true,
		show_documents: true,
		documents_read_only: false,
		show_permits: false,
		show_payments: false,
		show_external_ref: seq >= 3,
		show_description: true,
		auto_intake_intro: false,
		hide_mark_complete: false,
	};
}

function apply_sea_task_form_layout(frm) {
	const ui = get_sea_task_ui(frm);

	const toggle = (fieldname, visible) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "hidden", visible ? 0 : 1);
		}
	};

	if (!ui.is_sea_task) {
		return;
	}

	SEA_TASK_HIDDEN_FIELDS.forEach((f) => toggle(f, false));
	toggle("custom_section_break_0gs4o", ui.show_documents);
	toggle("custom_task_documents", ui.show_documents);
	if (ui.show_documents && frm.fields_dict.custom_task_documents) {
		frm.set_df_property("custom_task_documents", "read_only", ui.documents_read_only ? 1 : 0);
	}
	toggle("custom_section_task_permits", ui.show_permits);
	toggle("custom_task_permits", ui.show_permits);
	if (ui.show_permits) {
		configure_permit_grid(frm);
	}
	toggle("custom_payment_entry", ui.show_payments);
	toggle("custom_purchase_invoice", ui.show_payments);
	toggle("custom_external_ref_no", ui.show_external_ref);
	toggle("description", ui.show_description);
	toggle("sb_timeline", false);
	toggle("sb_costing", false);
	toggle("depends_on_tab", false);
}

function permit_rows_have_invoices(frm) {
	const rows = frm.doc.custom_task_permits || [];
	if (!rows.length) {
		return false;
	}
	return rows.every((r) => r.permit_type && r.payment_invoice);
}

function configure_permit_grid(frm) {
	const grid = frm.fields_dict.custom_task_permits?.grid;
	if (!grid) {
		return;
	}
	const seq = sea_task_sequence(frm);
	const hide_finance_only = [
		"purchase_invoice",
		"payment_entry",
		"payment_receipt",
		"receipt_verified",
		"invoice_verified",
		"clearance_phase",
		"application_date",
		"approval_date",
		"issuing_body",
		"payment_date",
		"payment_reference",
	];
	hide_finance_only.forEach((fn) => {
		grid.update_docfield_property(fn, "hidden", 1);
	});
	if (seq === 5) {
		grid.update_docfield_property("payment_invoice", "read_only", 0);
		grid.update_docfield_property("permit_document", "hidden", 1);
		grid.update_docfield_property("payment_receipt", "hidden", 1);
		grid.update_docfield_property("receipt_verified", "hidden", 1);
	} else if (seq === 6) {
		["payment_invoice", "purchase_invoice", "payment_entry", "permit_document"].forEach((fn) => {
			grid.update_docfield_property(fn, "read_only", 1);
		});
		grid.update_docfield_property("payment_receipt", "hidden", 0);
		grid.update_docfield_property("payment_receipt", "read_only", user_can_upload_receipt() ? 0 : 1);
		grid.update_docfield_property("receipt_verified", "hidden", 0);
		grid.update_docfield_property("receipt_verified", "read_only", user_can_make_payment() ? 0 : 1);
	}
}

frappe.ui.form.on("Permit Register", {
	custom_task_permits_add(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const seq = sea_task_sequence(frm);
		frappe.model.set_value(
			cdt,
			cdn,
			"stage",
			seq === 15 ? "Post-clearance" : "Pre-clearance"
		);
		frappe.model.set_value(cdt, cdn, "status", "Applied");
	},

	payment_invoice(frm, cdt, cdn) {
		if (frm.doctype !== "Task") {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.payment_invoice) {
			frappe.model.set_value(cdt, cdn, "status", "Invoice Submitted");
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
	},

	payment_receipt(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || sea_task_sequence(frm) !== 6) {
			return;
		}
		const row = locals[cdt][cdn];
		if (row.payment_receipt) {
			frappe.model.set_value(cdt, cdn, "status", "Receipt Submitted");
			frappe.call({
				method: "cgm_shipping.cgm_worldwide_shipping.customizations.permit_payment_workflow.notify_finance_verify_receipts",
				args: { task_name: frm.doc.name },
			});
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
	},

	receipt_verified(frm, cdt, cdn) {
		if (frm.doctype !== "Task" || sea_task_sequence(frm) !== 6) {
			return;
		}
		if (frm.doc.status !== "Completed") {
			frm.save();
		}
	},
});

function user_can_make_payment() {
	return ["Finance Manager", "Accounts User", "Accounts Manager"].some((role) =>
		(frappe.user_roles || []).includes(role)
	);
}

function user_can_upload_receipt() {
	return [
		"Operations Manager",
		"Operations User",
		"Declaration User",
		"Declarant",
		"System Manager",
		...["Finance Manager", "Accounts User", "Accounts Manager"],
	].some((role) => (frappe.user_roles || []).includes(role));
}

function open_purchase_invoice_from_task(frm) {
	if (!frm.doc.project) {
		frappe.msgprint(__("This task must be linked to a Project first."));
		return;
	}
	localStorage.setItem("cgm_return_task", frm.doc.name);
	localStorage.setItem("cgm_pi_for_task", "1");
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.get_task_finance_defaults",
		args: { task_name: frm.doc.name },
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			// Full permit lines applied on PI onload via purchase_invoice.js
			frappe.new_doc("Purchase Invoice");
		},
	});
}

function sync_pi_project_from_task(frm) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.finance_task_link.sync_finance_docs_from_task",
		args: { task_name: frm.doc.name },
		callback(r) {
			if (!r.exc) {
				frappe.show_alert({
					message: __("Purchase Invoice updated with Project {0}", [r.message.project]),
					indicator: "green",
				});
			}
		},
	});
}

function open_payment_entry_from_task(frm) {
	const pi = frm.doc.custom_purchase_invoice;
	if (!pi) {
		frappe.msgprint(__("Link a submitted Purchase Invoice on this task first."));
		return;
	}
	localStorage.setItem("cgm_return_task", frm.doc.name);
	localStorage.setItem("cgm_pe_for_task", "1");
	frappe.call({
		method: "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
		args: {
			dt: "Purchase Invoice",
			dn: pi,
		},
		freeze: true,
		freeze_message: __("Building Payment Entry for {0}…", [pi]),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			const doclist = frappe.model.sync(r.message);
			const pe = doclist[0];
			if (pe && frm.doc.project) {
				frappe.model.set_value(pe.doctype, pe.name, "project", frm.doc.project);
				frappe.model.set_value(
					pe.doctype,
					pe.name,
					"custom_cgm_source_task",
					frm.doc.name
				);
			}
			frappe.set_route("Form", pe.doctype, pe.name);
			frappe.show_alert({
				message: __("Payment Entry prefilled against {0}", [pi]),
				indicator: "blue",
			});
		},
	});
}

function user_can_record_purchase_invoice() {
	return [
		"Finance Manager",
		"Accounts User",
		"Accounts Manager",
		"Purchase Manager",
		"Purchase User",
	].some((role) => (frappe.user_roles || []).includes(role));
}

function open_next_task_prompt(frm) {
	if (!frm.doc.project || !frm.doc.custom_task_flow_key || !frm.doc.custom_sequence_no) {
		frappe.show_alert({
			message: __("Task completed."),
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
					message: __("Task completed. No further open tasks in this sequence."),
					indicator: "green",
				});
				return;
			}

			frappe.confirm(
				__("Open next task: <b>{0}</b>?", [next.subject || next.name]),
				() => frappe.set_route("Form", "Task", next.name)
			);
		},
	});
}
