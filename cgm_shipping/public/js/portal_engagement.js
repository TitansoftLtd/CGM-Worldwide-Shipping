// Copyright (c) 2026, Titansoft Limited and contributors
/**
 * Desk hooks for portal engagement on Project and Container Tracker:
 * post an update to the customer / transporter portal, and read (and answer)
 * the feedback those parties have left.
 *
 * The dialogs themselves live in operational_updates_ui.js so the ops board
 * and the forms open exactly the same publish flow.
 */
frappe.provide("cgm.portal_engagement");

(() => {
	const FEEDBACK_NS = "cgm_shipping.cgm_worldwide_shipping.customizations.portal_feedback.";

	function esc(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	function stars(count) {
		// Ratings come in half steps, so show the halves rather than rounding.
		const value = Math.max(0, Math.min(5, count || 0));
		const full = Math.floor(value);
		const half = value - full >= 0.5;
		return (
			`<span style="color:#f59e0b;letter-spacing:1px;">${"★".repeat(full)}${half ? "⯨" : ""}</span>` +
			`<span style="color:#d1d5db;letter-spacing:1px;">${"★".repeat(5 - full - (half ? 1 : 0))}</span>` +
			`<span class="text-muted small" style="margin-left:.35rem;">${value}/5</span>`
		);
	}

	function statusPill(status) {
		const tone = { New: "orange", Acknowledged: "blue", Resolved: "green" }[status] || "gray";
		return `<span class="indicator-pill ${tone} no-indicator-dot">${esc(status || "New")}</span>`;
	}

	function feedbackRowHtml(row) {
		const who =
			row.submitted_by_party === "Transporter"
				? row.transporter || __("Transporter")
				: row.customer || __("Customer");
		return `<div class="cgm-feedback-row" data-feedback="${esc(row.name)}"
				style="border:1px solid var(--border-color);border-radius:8px;padding:.75rem .9rem;margin-bottom:.6rem;">
			<div style="display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;">
				${stars(row.stars)}
				<b>${esc(who)}</b>
				${row.container_number ? `<span class="text-muted">${esc(row.container_number)}</span>` : ""}
				<span class="text-muted small">${esc(row.category || "")}</span>
				<span style="margin-left:auto;">${statusPill(row.status)}</span>
			</div>
			${
				(row.container_numbers || []).length
					? `<div style="margin-top:.4rem;" class="text-muted small">
							${__("Containers")}: ${row.container_numbers.map(esc).join(", ")}
						</div>`
					: ""
			}
			${
				row.comments
					? `<div style="margin-top:.5rem;white-space:pre-wrap;">${esc(row.comments)}</div>`
					: ""
			}
			${
				row.response
					? `<div style="margin-top:.5rem;padding:.5rem .65rem;background:var(--bg-light-gray);border-radius:6px;">
							<div class="text-muted small">${__("CGM response")}</div>
							<div style="white-space:pre-wrap;">${esc(row.response)}</div>
						</div>`
					: ""
			}
			<div style="margin-top:.5rem;">
				<button type="button" class="btn btn-xs btn-default cgm-feedback-respond" data-feedback="${esc(row.name)}">
					${row.response ? __("Edit response") : __("Respond")}
				</button>
				<a class="btn btn-xs btn-default" href="/app/portal-feedback/${encodeURIComponent(row.name)}">
					${__("Open")}
				</a>
			</div>
		</div>`;
	}

	function openRespondDialog(name, existing, onSaved) {
		const d = new frappe.ui.Dialog({
			title: __("Respond to feedback"),
			fields: [
				{
					fieldname: "response",
					label: __("Response"),
					fieldtype: "Small Text",
					reqd: 1,
					default: existing || "",
				},
				{
					fieldname: "status",
					label: __("Status"),
					fieldtype: "Select",
					options: ["Acknowledged", "Resolved"].join("\n"),
					default: "Acknowledged",
				},
			],
			primary_action_label: __("Save response"),
			primary_action(values) {
				frappe.call({
					method: FEEDBACK_NS + "respond_to_feedback",
					args: { name, response: values.response, status: values.status },
					freeze: true,
					callback(r) {
						if (r.exc) {
							return;
						}
						d.hide();
						frappe.show_alert({ message: __("Response saved."), indicator: "green" });
						if (typeof onSaved === "function") {
							onSaved();
						}
					},
				});
			},
		});
		d.show();
	}

	function openFeedbackDialog(method, args, title) {
		const d = new frappe.ui.Dialog({
			title,
			size: "large",
			fields: [{ fieldtype: "HTML", fieldname: "body" }],
			primary_action_label: __("Close"),
			primary_action() {
				d.hide();
			},
		});

		function load() {
			frappe.call({
				method,
				args,
				freeze: true,
				callback(r) {
					if (r.exc) {
						return;
					}
					const data = r.message || {};
					const rows = data.rows || [];
					const summary = data.summary || {};
					const header = rows.length
						? `<div style="margin-bottom:.85rem;">
								${stars(summary.average_stars)}
								<b style="margin-left:.5rem;">${esc(summary.average_display || "")}</b>
								<span class="text-muted"> · ${__("{0} response(s)", [summary.count || 0])}</span>
							</div>`
						: `<div class="text-muted">${__("No portal feedback yet.")}</div>`;
					d.fields_dict.body.$wrapper.html(header + rows.map(feedbackRowHtml).join(""));
					d.fields_dict.body.$wrapper
						.off("click.cgmFeedback")
						.on("click.cgmFeedback", ".cgm-feedback-respond", function () {
							const name = $(this).data("feedback");
							const row = rows.find((x) => x.name === name);
							openRespondDialog(name, row && row.response, load);
						});
				},
			});
		}

		d.show();
		load();
	}

	cgm.portal_engagement.addProjectButtons = function (frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(
			__("Post Update"),
			() => {
				cgm.updates.openPublishDialog({ project: frm.doc.name });
			},
			__("Portal")
		);
		frm.add_custom_button(
			__("Portal Feedback"),
			() => {
				openFeedbackDialog(
					FEEDBACK_NS + "get_project_feedback",
					{ project: frm.doc.name },
					__("Feedback on this shipment")
				);
			},
			__("Portal")
		);
	};

	cgm.portal_engagement.addContainerButtons = function (frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(
			__("Post Update"),
			() => {
				cgm.updates.openPublishDialog({
					project: frm.doc.project,
					container_tracker: frm.doc.name,
				});
			},
			__("Portal")
		);
		if (frm.doc.project) {
			// Feedback is a shipment-level record; send ops to the shipment's.
			frm.add_custom_button(
				__("Portal Feedback"),
				() => {
					openFeedbackDialog(
						FEEDBACK_NS + "get_project_feedback",
						{ project: frm.doc.project },
						__("Feedback on this shipment")
					);
				},
				__("Portal")
			);
		}
	};

	frappe.ui.form.on("Project", {
		refresh(frm) {
			cgm.portal_engagement.addProjectButtons(frm);
		},
	});

	frappe.ui.form.on("Container Tracker", {
		refresh(frm) {
			cgm.portal_engagement.addContainerButtons(frm);
		},
	});
})();
