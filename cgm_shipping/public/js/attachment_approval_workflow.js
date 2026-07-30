// Parent-form attachment approval workflow (Send for Review / Review Documents).

frappe.provide("cgm_shipping.attachment_approval");

const CGM_ATTACHMENT_APPROVAL_PARENT_DOCTYPES = ["Task", "Project", "Opportunity"];

cgm_shipping.attachment_approval = {
	refresh(frm) {
		if (!frm.doc.name || frm.doc.__islocal) {
			return;
		}
		// Frappe fires `refresh` many times per form load and clears custom buttons each
		// time, so the buttons must always be rebuilt — but the server state only changes
		// when the document does. Fetch once per revision and replay the cached state.
		const key = `${frm.doctype}:${frm.doc.name}:${frm.doc.modified}`;
		if (frm.__cgm_attachment_state_key !== key) {
			frm.__cgm_attachment_state_key = key;
			frm.__cgm_attachment_state_promise = frappe
				.call({
					method:
						"cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow.get_parent_attachment_approval_state",
					args: {
						parent_doctype: frm.doctype,
						parent_name: frm.doc.name,
					},
				})
				.then((r) => r.message || {})
				.catch(() => {
					// Let the next refresh retry rather than caching a failure.
					frm.__cgm_attachment_state_key = null;
					return {};
				});
		}
		frm.__cgm_attachment_state_promise.then((state) => {
			// Ignore a response that a newer revision has already superseded.
			if (frm.__cgm_attachment_state_key === key) {
				cgm_shipping.attachment_approval.configure_buttons(frm, state);
			}
		});
	},

	configure_buttons(frm, state) {
		frm.remove_custom_button(__("Send Final Documents for Review"));
		frm.remove_custom_button(__("Review Final Documents"));
		frm.remove_custom_button(__("Send for Review"));

		if (state.can_send) {
			const label =
				state.profiles?.length === 1
					? state.profiles[0].send_button_label
					: __("Send for Review");
			frm.add_custom_button(label, () => cgm_shipping.attachment_approval.open_send_dialog(frm), __("Actions"));
		}

		if (state.can_review) {
			const label =
				state.profiles?.find((profile) => profile.pending_count)?.review_button_label ||
				__("Review Documents");
			frm.add_custom_button(
				label,
				() => cgm_shipping.attachment_approval.open_review_dialog(frm),
				__("Actions")
			);
		}
	},

	open_send_dialog(frm) {
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow.get_sendable_attachment_rows",
			args: {
				parent_doctype: frm.doctype,
				parent_name: frm.doc.name,
			},
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) {
					frappe.msgprint(__("No documents are ready to send for review."));
					return;
				}
				cgm_shipping.attachment_approval.show_send_dialog(frm, rows);
			},
		});
	},

	show_send_dialog(frm, rows) {
		const fields = [
			{
				fieldtype: "HTML",
				fieldname: "help",
				options: `<p class="text-muted">${__(
					"Select the documents to submit for review."
				)}</p>`,
			},
		];

		rows.forEach((row, index) => {
			fields.push({
				fieldtype: "Check",
				fieldname: `row_${index}`,
				label: `${row.profile_label}: ${row.label}`,
				default: 1,
			});
		});

		const dialog = new frappe.ui.Dialog({
			title: __("Send for Review"),
			fields,
			primary_action_label: __("Send for Review"),
			primary_action() {
				const selections = [];
				rows.forEach((row, index) => {
					if (dialog.get_value(`row_${index}`)) {
						selections.push({
							profile_key: row.profile_key,
							table_field: row.table_field,
							row_name: row.row_name,
						});
					}
				});
				if (!selections.length) {
					frappe.msgprint(__("Select at least one document."));
					return;
				}
				frappe.call({
					method:
						"cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow.send_attachments_for_review",
					args: {
						parent_doctype: frm.doctype,
						parent_name: frm.doc.name,
						selections_json: JSON.stringify(selections),
					},
					freeze: true,
					callback(res) {
						dialog.hide();
						frm.reload_doc().then(() => {
							cgm_shipping.attachment_approval.configure_buttons(frm, res.message || {});
							frappe.show_alert({
								message: __("Documents sent for review"),
								indicator: "green",
							});
						});
					},
				});
			},
		});
		dialog.show();
	},

	open_review_dialog(frm) {
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow.get_pending_attachment_review_rows",
			args: {
				parent_doctype: frm.doctype,
				parent_name: frm.doc.name,
			},
			callback(r) {
				const rows = r.message || [];
				if (!rows.length) {
					frappe.msgprint(__("No documents are awaiting review."));
					return;
				}
				cgm_shipping.attachment_approval.show_review_dialog(frm, rows);
			},
		});
	},

	show_review_dialog(frm, rows) {
		const wrapper = $('<div class="cgm-attachment-review-dialog"></div>');
		const table = $(`
			<table class="table table-bordered table-sm cgm-review-documents-table">
				<thead>
					<tr>
						<th>${__("Document")}</th>
						<th>${__("Type")}</th>
						<th>${__("Attachment")}</th>
						<th>${__("Decision")}</th>
					</tr>
				</thead>
				<tbody></tbody>
			</table>
		`);
		const $tbody = table.find("tbody");
		const $reasons_panel = $(`
			<div class="cgm-review-reasons-panel" style="display:none;margin-top:12px;">
				<div class="text-muted small" style="margin-bottom:8px;">${__(
					"Reason for rejection"
				)}</div>
			</div>
		`);

		rows.forEach((row, index) => {
			const attachment = row.attachment
				? `<a href="#" class="cgm-grid-attach-link" data-file-url="${frappe.utils.escape_html(
						row.attachment
				  )}">${__("View")}</a>`
				: "";
			$tbody.append(`
				<tr data-index="${index}">
					<td>${frappe.utils.escape_html(row.label || "")}</td>
					<td>${frappe.utils.escape_html(row.profile_label || "")}</td>
					<td>${attachment}</td>
					<td>
						<div class="btn-group" role="group">
							<button type="button" class="btn btn-xs btn-success cgm-review-approve">${__(
								"Approve"
							)}</button>
							<button type="button" class="btn btn-xs btn-danger cgm-review-reject">${__(
								"Reject"
							)}</button>
						</div>
					</td>
				</tr>
			`);
		});

		wrapper.append(table).append($reasons_panel);

		const decisions = rows.map(() => ({ action: null, rejection_reason: "" }));

		const refresh_rejection_reasons = () => {
			const $fields = $reasons_panel.find(".cgm-review-reason-field");
			$fields.remove();
			const rejected = decisions
				.map((decision, index) => ({ decision, index }))
				.filter(({ decision }) => decision.action === "Reject");

			if (!rejected.length) {
				$reasons_panel.hide();
				return;
			}

			rejected.forEach(({ decision, index }) => {
				const row = rows[index];
				const label = `${row.profile_label}: ${row.label}`;
				const $field = $(`
					<div class="cgm-review-reason-field" data-index="${index}" style="margin-bottom:10px;">
						<label class="small text-muted" style="display:block;margin-bottom:4px;"></label>
						<textarea class="form-control input-sm" rows="2" placeholder="${__(
							"Reason for rejection"
						)}"></textarea>
					</div>
				`);
				$field.find("label").text(label);
				$field.find("textarea").val(decision.rejection_reason || "").on("input", function () {
					decisions[index].rejection_reason = $(this).val();
				});
				$reasons_panel.append($field);
			});
			$reasons_panel.show();
		};

		const dialog = new frappe.ui.Dialog({
			title: __("Review Documents"),
			fields: [{ fieldtype: "HTML", fieldname: "review_html", options: "" }],
			primary_action_label: __("Submit Decisions"),
			primary_action() {
				const payload = [];
				let missing_reason = false;
				decisions.forEach((decision, index) => {
					if (!decision.action) {
						return;
					}
					const row = rows[index];
					if (decision.action === "Reject" && !(decision.rejection_reason || "").trim()) {
						missing_reason = true;
						return;
					}
					payload.push({
						action: decision.action,
						profile_key: row.profile_key,
						table_field: row.table_field,
						row_name: row.row_name,
						rejection_reason: decision.rejection_reason || "",
					});
				});
				if (missing_reason) {
					frappe.msgprint(__("Enter a rejection reason for each rejected document."));
					return;
				}
				if (!payload.length) {
					frappe.msgprint(__("Approve or reject at least one document."));
					return;
				}
				frappe.call({
					method:
						"cgm_shipping.cgm_worldwide_shipping.customizations.attachment_approval_workflow.apply_attachment_review_decisions",
					args: {
						parent_doctype: frm.doctype,
						parent_name: frm.doc.name,
						decisions_json: JSON.stringify(payload),
					},
					freeze: true,
					callback(res) {
						dialog.hide();
						frm.reload_doc().then(() => {
							cgm_shipping.attachment_approval.configure_buttons(frm, res.message || {});
							frappe.show_alert({
								message: __("Review decisions saved"),
								indicator: "green",
							});
						});
					},
				});
			},
		});

		dialog.show();
		const $content = dialog.fields_dict.review_html.$wrapper;
		$content.empty().append(wrapper);

		$content.on("click.cgm_review", ".cgm-grid-attach-link", function (e) {
			e.preventDefault();
			const $link = $(this);
			if (typeof cgm_schedule_attach_preview === "function") {
				cgm_schedule_attach_preview($link, $link.data("file-url"));
			} else if (typeof cgm_open_attachment_file === "function") {
				cgm_open_attachment_file($link.data("file-url"));
			}
		});
		$content.on("dblclick.cgm_review", ".cgm-grid-attach-link", function (e) {
			e.preventDefault();
			const $link = $(this);
			if (typeof cgm_clear_attach_click_timer === "function") {
				cgm_clear_attach_click_timer($link);
			}
			if (typeof cgm_download_attachment_file === "function") {
				cgm_download_attachment_file($link.data("file-url"));
			}
		});

		$content.on("click.cgm_review", ".cgm-review-approve", function () {
			const index = $(this).closest("tr").data("index");
			decisions[index].action = "Approve";
			decisions[index].rejection_reason = "";
			$(this).closest("tr").find(".btn-group button").removeClass("active");
			$(this).addClass("active");
			refresh_rejection_reasons();
		});
		$content.on("click.cgm_review", ".cgm-review-reject", function () {
			const index = $(this).closest("tr").data("index");
			decisions[index].action = "Reject";
			$(this).closest("tr").find(".btn-group button").removeClass("active");
			$(this).addClass("active");
			refresh_rejection_reasons();
			const $textarea = $reasons_panel.find(`.cgm-review-reason-field[data-index="${index}"] textarea`);
			if ($textarea.length) {
				$textarea.trigger("focus");
			}
		});
	},
};

CGM_ATTACHMENT_APPROVAL_PARENT_DOCTYPES.forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			cgm_shipping.attachment_approval.refresh(frm);
		},
	});
});
