// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("License Register", {
	refresh(frm) {
		frm.trigger("set_expiry_indicator");

		if (!frm.is_new()) {
			frm.add_custom_button(__("Reminder Schedule"), () => show_reminder_schedule(frm));
			frm.add_custom_button(__("Reminder Log"), () => {
				frappe.set_route("List", "License Reminder Log", { license: frm.doc.name });
			});
		}

	},

	set_expiry_indicator(frm) {
		if (frm.is_new() || frm.doc.renewal_basis !== "Fixed Expiry Date" || !frm.doc.expiry_date) {
			return;
		}

		const days = frappe.datetime.get_day_diff(frm.doc.expiry_date, frappe.datetime.get_today());
		if (days < 0) {
			frm.dashboard.set_headline_alert(
				__("Expired {0} days ago", [Math.abs(days)]),
				"red"
			);
		} else if (days === 0) {
			frm.dashboard.set_headline_alert(__("Expires today"), "red");
		} else {
			const colour = days <= 30 ? "orange" : "green";
			frm.dashboard.set_headline_alert(__("Expires in {0} days", [days]), colour);
		}
	},

	renewal_basis(frm) {
		frm.trigger("set_expiry_indicator");
	},

	expiry_date(frm) {
		frm.trigger("set_expiry_indicator");
	},

	issue_date(frm) {
		frm.trigger("suggest_expiry_date");
	},

	license_type(frm) {
		frm.trigger("suggest_expiry_date");
	},

	async suggest_expiry_date(frm) {
		// Fill in the expiry date from the type's default validity, but never overwrite
		// a date somebody has already entered.
		if (!frm.doc.issue_date || !frm.doc.license_type || frm.doc.expiry_date) return;
		if (frm.doc.renewal_basis !== "Fixed Expiry Date") return;

		const months = await frappe.db.get_value(
			"License Type",
			frm.doc.license_type,
			"default_validity_months"
		);
		const validity = months?.message?.default_validity_months;
		if (!validity) return;

		frm.set_value("expiry_date", frappe.datetime.add_months(frm.doc.issue_date, validity));
	},
});

function show_reminder_schedule(frm) {
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.doctype.license_register.license_register.get_reminder_schedule",
		args: { license_name: frm.doc.name },
		freeze: true,
		callback: ({ message }) => {
			if (!message) return;

			let html = "";

			if (!message.enabled) {
				html += `<p class="text-danger">${__(
					"Expiry notifications are switched off in License Settings."
				)}</p>`;
			}

			if (message.schedule.length) {
				const rows = message.schedule
					.map((row) => {
						const state = row.sent
							? `<span class="text-success">${__("Sent")}</span>`
							: row.past
							? `<span class="text-muted">${__("Not sent")}</span>`
							: `<span class="text-muted">${__("Scheduled")}</span>`;
						return `<tr>
							<td>${frappe.utils.escape_html(row.label)}</td>
							<td>${row.send_on}</td>
							<td>${state}</td>
						</tr>`;
					})
					.join("");

				html += `<table class="table table-bordered small">
					<thead><tr>
						<th>${__("Period")}</th><th>${__("Sends On")}</th><th>${__("Status")}</th>
					</tr></thead>
					<tbody>${rows}</tbody>
				</table>`;
			} else {
				html += `<p class="text-muted">${__(
					"No dated reminder schedule - this licence has no fixed expiry date."
				)}</p>`;
			}

			if (message.due_today) {
				html += `<p class="text-warning"><b>${__("Due today:")}</b> ${frappe.utils.escape_html(
					message.due_label
				)}</p>`;
			}

			const recipients = message.recipients.length
				? message.recipients.map(frappe.utils.escape_html).join(", ")
				: `<span class="text-danger">${__("Nobody - set recipients in License Settings.")}</span>`;
			html += `<p class="small"><b>${__("Recipients:")}</b> ${recipients}</p>`;

			frappe.msgprint({ title: __("Reminder Schedule"), message: html, wide: true });
		},
	});
}
