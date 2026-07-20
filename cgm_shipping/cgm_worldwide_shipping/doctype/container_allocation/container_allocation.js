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
			child.cargo_size = row.cargo_size || row.cargo_type;
			child.assignment_status = row.assignment_status || "Pending";
		});
		frm.refresh_field("containers");
		if (
			replace
			|| !cint(frm.doc.trucks_booked)
		) {
			frm.set_value("trucks_booked", (frm.doc.containers || []).length);
		}
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
		frm.set_query("transporter", () =>
			cgm_shipping.supplier_filters?.transporter_query?.() || {
				filters: { disabled: 0, is_transporter: 1 },
			}
		);
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

	refresh(frm) {
		render_allocation_truck_updates(frm);
	},
});

function render_allocation_truck_updates(frm) {
	const field = frm.get_field("transporter_updates_html");
	if (!field || !field.$wrapper) {
		return;
	}

	if (frm.doc.docstatus !== 1 || !frm.doc.name) {
		field.$wrapper.html(
			`<div class="text-muted">${__("Submit the allocation to see updates.")}</div>`
		);
		return;
	}

	field.$wrapper.html(`<div class="text-muted">${__("Loading updates…")}</div>`);

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_allocation_truck_updates",
		args: { allocation_name: frm.doc.name },
		callback(r) {
			if (r.exc) {
				field.$wrapper.html(
					`<div class="text-danger">${__("Could not load updates.")}</div>`
				);
				return;
			}
			field.$wrapper.html(build_allocation_updates_html(frm, r.message || []));
			if (window.cgm && cgm.updates) {
				cgm.updates.bindListClicks(field.$wrapper);
			}
		},
	});
}

function build_allocation_updates_html(frm, rows) {
	const list_route = `/app/update?allocation=${encodeURIComponent(frm.doc.name)}`;
	const header = `
		<div class="flex justify-between align-items-center flex-wrap" style="gap: var(--margin-sm); margin-bottom: var(--margin-md);">
			<div class="text-muted small">
				${__("Updates linked to this allocation and its containers.")}
			</div>
			<a class="btn btn-xs btn-default" href="${list_route}">${__("Open full update log")}</a>
		</div>`;

	if (!rows.length) {
		return `${header}<div class="text-muted" style="padding: var(--padding-md); border: 1px dashed var(--border-color); border-radius: var(--border-radius);">
			${__("No updates yet. Transporter, customer, and internal updates appear here when linked to this allocation.")}
		</div>`;
	}

	if (!(window.cgm && cgm.updates && cgm.updates.renderList)) {
		return `${header}<div class="text-danger">${__("Updates UI failed to load. Refresh the page.")}</div>`;
	}

	return `${header}${cgm.updates.renderList(rows)}`;
}
