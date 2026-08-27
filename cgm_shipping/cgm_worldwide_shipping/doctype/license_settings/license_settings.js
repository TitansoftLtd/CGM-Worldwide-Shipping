// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.ui.form.on("License Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Licence Register"), () => {
			frappe.set_route("List", "License Register");
		});

		frm.add_custom_button(__("Preview Today's Reminders"), () => preview_due_reminders());
		frm.add_custom_button(__("Send Reminders Now"), () => run_reminders_now(frm));
	},
});

function preview_due_reminders() {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.license_reminders.preview_due_reminders",
		freeze: true,
		callback: ({ message }) => {
			if (!message) return;

			let html = "";
			if (!message.enabled) {
				html += `<p class="text-danger">${__(
					"Expiry notifications are switched off, so nothing would be sent."
				)}</p>`;
			}

			if (!message.reminders.length) {
				html += `<p class="text-muted">${__("No reminders are due today.")}</p>`;
			} else {
				const rows = message.reminders
					.map(
						(row) => `<tr>
							<td>${frappe.utils.escape_html(row.license_name || row.license)}</td>
							<td>${frappe.utils.escape_html(row.label)}</td>
							<td>${row.expiry_date ? frappe.datetime.str_to_user(row.expiry_date) : ""}</td>
							<td>${
								row.recipients.length
									? row.recipients.map(frappe.utils.escape_html).join(", ")
									: `<span class="text-danger">${__("Nobody")}</span>`
							}</td>
						</tr>`
					)
					.join("");

				html += `<table class="table table-bordered small">
					<thead><tr>
						<th>${__("Licence")}</th><th>${__("Reminder")}</th>
						<th>${__("Expiry Date")}</th><th>${__("Recipients")}</th>
					</tr></thead>
					<tbody>${rows}</tbody>
				</table>`;
			}

			frappe.msgprint({ title: __("Due Today"), message: html, wide: true });
		},
	});
}

function run_reminders_now(frm) {
	frappe.confirm(
		__("Send every reminder that is due today? Recipients will receive these for real."),
		() => {
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.license_reminders.run_reminders_now",
				freeze: true,
				freeze_message: __("Sending reminders..."),
				callback: ({ message }) => {
					frappe.msgprint({
						title: __("Reminders Sent"),
						message: __("{0} reminder(s) logged.", [message?.sent ?? 0]),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		}
	);
}
