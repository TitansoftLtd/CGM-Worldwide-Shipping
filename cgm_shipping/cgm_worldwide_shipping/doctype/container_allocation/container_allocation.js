// Copyright (c) 2026, Titansoft Limited and contributors

const CA_CREATE_METHOD =
	"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.create_allocation_for_containers";
const CA_DEFAULTS_METHOD =
	"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.get_container_allocation_defaults";
const CA_MOVE_METHOD =
	"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.reallocate_containers";
const CA_MOVE_TARGETS_METHOD =
	"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.get_project_allocations_for_move";

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
		if (replace || !cint(frm.doc.trucks_booked)) {
			frm.set_value("trucks_booked", (frm.doc.containers || []).length);
		}
	};

	frappe.call({
		method: CA_DEFAULTS_METHOD,
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

	refresh(frm) {
		render_allocation_truck_updates(frm);
		setup_cgm_assignment_actions(frm);

		if (frm.doc.docstatus === 1) {
			frm.set_df_property("offered_trucks", "cannot_add_rows", 1);
			frm.set_df_property("offered_trucks", "cannot_delete_rows", 1);
			(frm.fields_dict.offered_trucks?.grid?.grid_rows || []).forEach((grid_row) => {
				grid_row.toggle_editable("truck_number", false);
				grid_row.toggle_editable("driver_name", false);
				grid_row.toggle_editable("driver_contact", false);
			});
		}
	},
});

function setup_cgm_assignment_actions(frm) {
	frm.remove_custom_button(__("Assign Containers to Trucks"));
	frm.remove_custom_button(__("Reassign Container"));
	frm.remove_custom_button(__("Allocate Remaining Containers"));
	frm.remove_custom_button(__("Move Containers to Another Transporter"));

	if (frm.doc.docstatus !== 1 || frm.doc.status === "Completed") {
		return;
	}

	frm.add_custom_button(__("Assign Containers to Trucks"), () => open_assign_dialog(frm), __("Transport"));
	frm.add_custom_button(__("Reassign Container"), () => open_reassign_dialog(frm), __("Transport"));
	frm.add_custom_button(
		__("Allocate Remaining Containers"),
		() => open_allocate_remaining_dialog(frm),
		__("Transport")
	);
	frm.add_custom_button(
		__("Move Containers to Another Transporter"),
		() => open_move_containers_dialog(frm),
		__("Transport")
	);
}

function container_multicheck_options(rows) {
	return (rows || []).map((row) => {
		const tracker = row.container_tracker || row.name;
		const label = `${row.container_number || tracker}${row.cargo_size ? " · " + row.cargo_size : ""}${
			row.assignment_status ? " (" + row.assignment_status + ")" : ""
		}`;
		return { label, value: tracker, checked: 1 };
	});
}

function truck_option_label(truck) {
	const availability = truck.available
		? __("Available")
		: __("In use ({0})", [truck.assigned_container || "—"]);
	return `${truck.truck_number} · ${truck.driver_name} (${availability})`;
}

function fill_select_options(field, options) {
	const $select = field.$wrapper.find("select");
	$select.empty();
	(options || []).forEach((opt) => {
		$select.append(
			`<option value="${frappe.utils.escape_html(opt.value)}">${frappe.utils.escape_html(opt.label)}</option>`
		);
	});
}

function open_assign_dialog(frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.get_assignment_board",
		args: { allocation_name: frm.doc.name },
		freeze: true,
		callback(r) {
			if (r.exc) {
				return;
			}
			const board = r.message || {};
			const pending = board.pending_containers || [];
			const trucks = (board.offered_trucks || []).filter((t) => t.available);

			if (!pending.length) {
				frappe.msgprint(__("All containers already have trucks assigned."));
				return;
			}
			if (!trucks.length) {
				frappe.msgprint(
					__(
						"No available offered trucks. Ask the transporter to offer trucks first, or reassign an existing truck."
					)
				);
				return;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("Assign Containers to Trucks"),
				fields: [
					{
						fieldname: "help",
						fieldtype: "HTML",
						options: `<div class="text-muted" style="margin-bottom: var(--margin-sm);">
							${__("Select a pending container and an available offered truck. One truck can only carry one container.")}
						</div>`,
					},
					{
						fieldname: "item_name",
						fieldtype: "Select",
						label: __("Container"),
						reqd: 1,
						options: pending.map((c) => c.name).join("\n"),
					},
					{
						fieldname: "offered_truck_name",
						fieldtype: "Select",
						label: __("Offered Truck"),
						reqd: 1,
						options: trucks.map((t) => t.name).join("\n"),
					},
				],
				primary_action_label: __("Assign"),
				primary_action(values) {
					frappe.call({
						method:
							"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.assign_container_to_truck",
						args: {
							allocation_name: frm.doc.name,
							item_name: values.item_name,
							offered_truck_name: values.offered_truck_name,
						},
						freeze: true,
						callback(res) {
							if (res.exc) {
								return;
							}
							dialog.hide();
							frappe.show_alert({
								message: res.message?.message || __("Container assigned."),
								indicator: "green",
							});
							frm.reload_doc();
						},
					});
				},
			});

			fill_select_options(
				dialog.fields_dict.item_name,
				pending.map((c) => ({
					value: c.name,
					label: `${c.container_number || c.container_tracker}${c.cargo_size ? " · " + c.cargo_size : ""}`,
				}))
			);
			fill_select_options(
				dialog.fields_dict.offered_truck_name,
				trucks.map((t) => ({ value: t.name, label: truck_option_label(t) }))
			);
			dialog.show();
		},
	});
}

function open_reassign_dialog(frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.get_assignment_board",
		args: { allocation_name: frm.doc.name },
		freeze: true,
		callback(r) {
			if (r.exc) {
				return;
			}
			const board = r.message || {};
			const assigned = board.assigned_containers || [];
			const trucks = (board.offered_trucks || []).filter((t) => t.available);

			if (!assigned.length) {
				frappe.msgprint(__("No containers are ready for reassignment."));
				return;
			}
			if (!trucks.length) {
				frappe.msgprint(
					__(
						"No available offered trucks for reassignment. Ask the transporter to offer more trucks."
					)
				);
				return;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("Reassign Container"),
				fields: [
					{
						fieldname: "item_name",
						fieldtype: "Select",
						label: __("Container"),
						reqd: 1,
						options: assigned.map((c) => c.name).join("\n"),
					},
					{
						fieldname: "offered_truck_name",
						fieldtype: "Select",
						label: __("New Offered Truck"),
						reqd: 1,
						options: trucks.map((t) => t.name).join("\n"),
					},
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Reason"),
						reqd: 1,
					},
				],
				primary_action_label: __("Reassign"),
				primary_action(values) {
					frappe.call({
						method:
							"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.reassign_container_truck",
						args: {
							allocation_name: frm.doc.name,
							item_name: values.item_name,
							offered_truck_name: values.offered_truck_name,
							reason: values.reason,
						},
						freeze: true,
						callback(res) {
							if (res.exc) {
								return;
							}
							dialog.hide();
							frappe.show_alert({
								message: res.message?.message || __("Container reassigned."),
								indicator: "green",
							});
							frm.reload_doc();
						},
					});
				},
			});

			fill_select_options(
				dialog.fields_dict.item_name,
				assigned.map((c) => ({
					value: c.name,
					label: `${c.container_number || c.container_tracker} → ${c.truck_number || "—"}`,
				}))
			);
			fill_select_options(
				dialog.fields_dict.offered_truck_name,
				trucks.map((t) => ({ value: t.name, label: truck_option_label(t) }))
			);
			dialog.show();
		},
	});
}

function open_allocate_remaining_dialog(frm) {
	const pending = (frm.doc.containers || []).filter(
		(row) => row.container_tracker && (row.assignment_status || "Pending") === "Pending"
	);

	if (!pending.length) {
		frappe.msgprint(
			__(
				"No pending containers on this allocation. Only containers still waiting for a truck can be sent to another transporter here."
			)
		);
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Allocate Remaining Containers"),
		fields: [
			{
				fieldname: "help",
				fieldtype: "HTML",
				options: `<div class="text-muted" style="margin-bottom: var(--margin-sm);">
					${__(
						"Select containers that still need a truck, then choose another transporter. A new allocation is created and these containers are moved. This allocation is kept for records."
					)}
					<br><br>${__("Pending on this allocation")}: <b>${pending.length}</b>
				</div>`,
			},
			{
				fieldname: "container_trackers",
				fieldtype: "MultiCheck",
				label: __("Containers"),
				reqd: 1,
				columns: 1,
				options: container_multicheck_options(pending),
			},
			{
				fieldname: "transporter",
				fieldtype: "Link",
				label: __("New Transporter"),
				options: "Supplier",
				reqd: 1,
				get_query: () => ({
					filters: {
						is_transporter: 1,
						name: ["!=", frm.doc.transporter || ""],
					},
				}),
			},
			{
				fieldname: "trucks_booked",
				fieldtype: "Int",
				label: __("Number of Trucks Booked"),
				default: pending.length,
			},
			{
				fieldname: "reason",
				fieldtype: "Small Text",
				label: __("Reason"),
				default: __("Remaining containers allocated to another transporter"),
				reqd: 1,
			},
		],
		primary_action_label: __("Create Allocation & Move"),
		primary_action(values) {
			const trackers = values.container_trackers || [];
			if (!trackers.length) {
				frappe.msgprint(__("Select at least one container."));
				return;
			}
			if (values.transporter === frm.doc.transporter) {
				frappe.msgprint(__("Choose a different transporter than the one on this allocation."));
				return;
			}

			frappe.call({
				method: CA_MOVE_METHOD,
				args: {
					source_allocation: frm.doc.name,
					container_trackers: trackers,
					reason: values.reason,
					transporter: values.transporter,
					target_allocation: null,
					trucks_booked: values.trucks_booked || trackers.length,
				},
				freeze: true,
				freeze_message: __("Moving remaining containers…"),
				callback(res) {
					if (res.exc) {
						return;
					}
					dialog.hide();
					const target = res.message?.target_allocation;
					frappe.show_alert({
						message: res.message?.message || __("Containers moved."),
						indicator: "green",
					});
					frm.reload_doc().then(() => {
						if (target) {
							frappe.set_route("Form", "Container Allocation", target);
						}
					});
				},
			});
		},
	});

	dialog.show();
}

function open_move_containers_dialog(frm) {
	const movable = (frm.doc.containers || []).filter(
		(row) => row.container_tracker && row.assignment_status !== "Interchange Uploaded"
	);
	if (!movable.length) {
		frappe.msgprint(
			__("No containers can be moved. Interchange-uploaded containers stay on this allocation.")
		);
		return;
	}

	frappe.call({
		method: CA_MOVE_TARGETS_METHOD,
		args: {
			project: frm.doc.project,
			exclude_allocation: frm.doc.name,
		},
		freeze: true,
		callback(r) {
			if (r.exc) {
				return;
			}
			const targets = r.message || [];

			const dialog = new frappe.ui.Dialog({
				title: __("Move Containers to Another Transporter"),
				fields: [
					{
						fieldname: "help",
						fieldtype: "HTML",
						options: `<div class="text-muted" style="margin-bottom: var(--margin-sm);">
							${__(
								"Move selected containers without cancelling this allocation. Truck assignments on moved containers are cleared."
							)}
						</div>`,
					},
					{
						fieldname: "container_trackers",
						fieldtype: "MultiCheck",
						label: __("Containers"),
						reqd: 1,
						columns: 1,
						options: container_multicheck_options(movable),
					},
					{
						fieldname: "mode",
						fieldtype: "Select",
						label: __("Move to"),
						reqd: 1,
						options: targets.length
							? "New transporter allocation\nExisting allocation"
							: "New transporter allocation",
						default: "New transporter allocation",
						onchange() {
							const is_new = dialog.get_value("mode") !== "Existing allocation";
							dialog.set_df_property("transporter", "hidden", is_new ? 0 : 1);
							dialog.set_df_property("target_allocation_display", "hidden", is_new ? 1 : 0);
						},
					},
					{
						fieldname: "transporter",
						fieldtype: "Link",
						label: __("New Transporter"),
						options: "Supplier",
						get_query: () => ({ filters: { is_transporter: 1 } }),
					},
					{
						fieldname: "target_allocation_display",
						fieldtype: "Select",
						label: __("Existing Allocation"),
						options: targets
							.map(
								(t) =>
									`${t.name} · ${t.transporter_name || t.transporter} (${t.container_count || 0})`
							)
							.join("\n"),
						hidden: 1,
					},
					{
						fieldname: "reason",
						fieldtype: "Small Text",
						label: __("Reason"),
						reqd: 1,
					},
				],
				primary_action_label: __("Move Containers"),
				primary_action(values) {
					const trackers = values.container_trackers || [];
					if (!trackers.length) {
						frappe.msgprint(__("Select at least one container."));
						return;
					}

					let target_allocation = null;
					let transporter = null;
					if (values.mode === "Existing allocation") {
						if (!targets.length) {
							frappe.msgprint(
								__("No other active allocations on this project. Choose a new transporter.")
							);
							return;
						}
						const display = values.target_allocation_display || "";
						const match = targets.find((t) => display.startsWith(t.name));
						if (!match) {
							frappe.msgprint(__("Select a target allocation."));
							return;
						}
						target_allocation = match.name;
					} else {
						transporter = values.transporter;
						if (!transporter) {
							frappe.msgprint(__("Select a transporter."));
							return;
						}
					}

					frappe.call({
						method: CA_MOVE_METHOD,
						args: {
							source_allocation: frm.doc.name,
							container_trackers: trackers,
							reason: values.reason,
							target_allocation,
							transporter,
						},
						freeze: true,
						freeze_message: __("Moving containers…"),
						callback(res) {
							if (res.exc) {
								return;
							}
							dialog.hide();
							frappe.show_alert({
								message: res.message?.message || __("Containers moved."),
								indicator: "green",
							});
							const target = res.message?.target_allocation;
							frm.reload_doc().then(() => {
								if (target) {
									frappe.msgprint({
										title: __("Containers moved"),
										message: __(
											"Moved to {0}. This allocation was kept for records.",
											[
												`<a href="/app/container-allocation/${encodeURIComponent(
													target
												)}">${frappe.utils.escape_html(target)}</a>`,
											]
										),
										indicator: "green",
									});
								}
							});
						},
					});
				},
			});

			dialog.show();
		},
	});
}

/**
 * `operational_updates_ui.js` ships via `app_include_js`, which the desk serves
 * as a plain unversioned path - a browser holding the previous build keeps
 * serving it, and the tab dead-ends on "refresh the page". Doctype JS like this
 * file is embedded in the DocType meta and so is always fresh, which makes it
 * the right place to force the stale asset past the cache.
 */
function cgm_with_updates_ui(on_ready, on_fail) {
	if (window.cgm && cgm.updates && cgm.updates.mountConversations) {
		on_ready();
		return;
	}
	frappe.require(
		`/assets/cgm_shipping/js/operational_updates_ui.js?v=${Date.now()}`,
		() => {
			if (window.cgm && cgm.updates && cgm.updates.mountConversations) {
				on_ready();
			} else {
				on_fail();
			}
		}
	);
}

function render_allocation_truck_updates(frm) {
	const field = frm.get_field("transporter_updates_html");
	if (!field || !field.$wrapper) {
		return;
	}

	if (frm.doc.docstatus !== 1 || !frm.doc.name) {
		field.$wrapper.html(
			`<div class="cgm-conv-empty">${__(
				"Submit the allocation to see the conversations on it."
			)}</div>`
		);
		return;
	}

	cgm_with_updates_ui(
		() => {
			cgm.updates.mountConversations(field.$wrapper, {
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_allocation_conversations",
				args: { allocation_name: frm.doc.name },
				emptyText: __(
					"No shipment updates yet. Transporter, customer, and internal conversations on this allocation, its containers, and its shipment appear here."
				),
				postDefaults: { project: frm.doc.project },
				logRoute: `/app/shipment-update?allocation=${encodeURIComponent(frm.doc.name)}`,
			});
		},
		() => {
			field.$wrapper.html(
				`<div class="text-danger">${__("Updates UI failed to load. Refresh the page.")}</div>`
			);
		}
	);
}
