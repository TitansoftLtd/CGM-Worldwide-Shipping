// Copyright (c) 2026, Titansoft Limited and contributors

function populate_containers_from_project(frm, replace = false) {
	if (!frm.doc.project || frm.doc.docstatus > 0) {
		return;
	}

	const apply_rows = (payload) => {
		const rows = payload?.containers || [];
		if (!rows.length) {
			if (replace) {
				frm.clear_table("containers");
				frm.refresh_field("containers");
			}
			frappe.msgprint(
				__(
					"No unallocated Container Trackers found on this project. Confirm port arrival or create trackers first."
				)
			);
			return;
		}
		if (replace) {
			frm.clear_table("containers");
		}
		rows.forEach((row) => {
			if (
				!replace &&
				(frm.doc.containers || []).some((existing) => existing.container_tracker === row.container_tracker)
			) {
				return;
			}
			const child = frm.add_child("containers");
			child.container_tracker = row.container_tracker;
			child.container_number = row.container_number;
			child.cargo_type = row.cargo_type;
			child.assignment_status = row.assignment_status || "Pending";
		});
		frm.refresh_field("containers");
	};

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.get_container_allocation_defaults",
		args: { project: frm.doc.project },
		callback(r) {
			if (r.exc) {
				return;
			}
			const payload = r.message || {};
			if (payload.bill_of_lading && !frm.doc.bill_of_lading) {
				frm.set_value("bill_of_lading", payload.bill_of_lading);
			}
			apply_rows(payload);
		},
	});
}

frappe.ui.form.on("Container Allocation", {
	setup(frm) {
		frm.set_query("transporter", () => ({
			filters: { is_transporter: 1 },
		}));
		frm.set_query("container_tracker", "containers", () => {
			const filters = { project: frm.doc.project || "" };
			return { filters };
		});
	},

	onload(frm) {
		if (frm.is_new() && frappe.route_options?.project && !frm.doc.project) {
			frm.set_value("project", frappe.route_options.project);
		}
	},

	project(frm) {
		if (!frm.doc.project || frm.doc.docstatus > 0) {
			return;
		}

		const has_populated_rows = (frm.doc.containers || []).some((row) => row.container_tracker);
		const populate = (replace) => populate_containers_from_project(frm, replace);

		if (has_populated_rows) {
			frappe.confirm(
				__("Replace container rows with unallocated Container Trackers from this project?"),
				() => populate(true)
			);
			return;
		}

		populate(true);
	},
});
