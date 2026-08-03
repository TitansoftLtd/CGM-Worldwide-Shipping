function configure_project_document_grid(frm) {
	const grid = frm.fields_dict.custom_shipment_documents?.grid;
	if (!grid) {
		return;
	}

	if (cgm_has_shipment_document_versioning()) {
		let changed = false;
		const draft_field = cgm_draft_document_field();
		for (const row of frm.doc.custom_shipment_documents || []) {
			const draft = draft_field ? row[draft_field] : null;
			if (draft_field && !draft && !row.final_attachment && row.attachment) {
				if (row.status === "Missing") {
					row.attachment = "";
					changed = true;
					continue;
				}
				row[draft_field] = row.attachment;
				changed = true;
			}
			const next_draft = draft_field ? row[draft_field] : null;
			if (next_draft || row.final_attachment) {
				row.attachment = row.final_attachment || next_draft || row.attachment;
			} else if (row.attachment) {
				row.attachment = "";
				changed = true;
			}
		}
		if (changed) {
			frm.refresh_field("custom_shipment_documents");
		}
	}

	cgm_configure_shipment_document_grid(grid);
	cgm_sync_shipment_document_rows_on_refresh(frm, "custom_shipment_documents");
}

function configure_project_status_fields(frm) {
	cgm_configure_project_status_fields(frm);
	cgm_configure_document_status_grids(frm);
	cgm_configure_permit_status_grids(frm);
}

const WORKFLOW_COLOURS = {
	Success: "green",
	Warning: "orange",
	Danger: "red",
	Primary: "blue",
	Inverse: "black",
	Info: "light-blue",
};

function configure_project_container_grid(frm) {
	const grid = frm.fields_dict.custom_container_information?.grid;
	if (!grid) {
		return;
	}
	if (!frm.doc.name || frm.is_new()) {
		return;
	}
	if (frm._cgm_container_modes_loaded === frm.doc.name) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker.get_containers_for_project",
		args: { project: frm.doc.name },
		callback(r) {
			if (r.exc || frm.doc.name !== frm._cgm_container_modes_loading) {
				return;
			}
			frm._cgm_container_modes_loaded = frm.doc.name;
			const modes = new Set((r.message || []).map((row) => row.container_mode).filter(Boolean));
			const hideCharges =
				modes.size === 1 && modes.has("Export");
			["demurrage_days"].forEach((fieldname) => {
				grid.update_docfield_property(fieldname, "hidden", hideCharges ? 1 : 0);
			});
		},
	});
	frm._cgm_container_modes_loading = frm.doc.name;
}

function project_has_containers(frm) {
	return (frm.doc.custom_container_information || []).some(
		(row) => (row.container_number || "").trim()
	);
}

function project_ata_value(frm) {
	return frm.doc.custom_actual_time_of_arrival_ata || frm.doc.custom_ata || null;
}

function project_supports_container_allocation(frm) {
	if (frm.doc.custom_mode_of_transport !== "Sea") {
		return false;
	}
	return Boolean(
		frm.doc.custom_port_arrival_confirmed ||
			project_has_containers(frm) ||
			(frm.doc.custom_container_information || []).length
	);
}

/**
 * Append a custom item to the page Actions menu after workflow rebuilds it.
 * Workflow show_actions() clears the menu on render_complete — register after it finishes.
 */
function register_project_action_after_workflow(frm, eventKey, register_action) {
	const schedule_register = () => {
		const state_field = frappe.workflow.get_state_fieldname(frm.doctype);
		const append_action = () => {
			// Defer past workflow's clear_actions_menu + transition inserts.
			setTimeout(register_action, 50);
		};
		if (state_field && !frm.doc.__islocal) {
			frappe.workflow.get_transitions(frm.doc).then(append_action);
			return;
		}
		register_action();
	};

	schedule_register();
	$(frm.wrapper)
		.off(`render_complete.${eventKey}`)
		.on(`render_complete.${eventKey}`, schedule_register);
}

function mount_port_arrival_confirmation_button(frm) {
	const on_confirm = () => {
		const confirmMessage = __(
			"Confirm that the shipment has arrived at the port? Container trackers will be created for all containers on this project."
		);
		const submit = (ata) => {
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.confirm_shipment_arrival_at_port",
				args: { project_name: frm.doc.name, ata: ata || null },
				freeze: true,
				freeze_message: __("Creating container trackers..."),
				callback(r) {
					if (r.exc) {
						return;
					}
					frm.reload_doc();
					const count = r.message?.tracker_count || 0;
					frappe.show_alert({
						message: __(
							"Port arrival confirmed — {0} container tracker(s) created.",
							[count]
						),
						indicator: "green",
					});
				},
			});
		};

		frappe.prompt(
			[
				{
					fieldname: "ata",
					fieldtype: "Date",
					label: __("Actual Time of Arrival (ATA)"),
					default: project_ata_value(frm) || frappe.datetime.get_today(),
					reqd: 1,
				},
			],
			(values) => {
				frappe.confirm(confirmMessage, () => submit(values.ata));
			},
			__("Confirm Port Arrival")
		);
	};

	const register_action = () => {
		frm.page.add_action_item(
			__("Confirm Shipment Arrival at the Port"),
			on_confirm,
			true
		);
		frm.page.show_actions_menu();
	};

	register_project_action_after_workflow(frm, "cgm_port_arrival", register_action);
}

function setup_port_arrival_confirmation_button(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	if (frm.doc.custom_mode_of_transport !== "Sea") {
		return;
	}
	if (frm.doc.custom_port_arrival_confirmed) {
		return;
	}

	if (project_has_containers(frm)) {
		mount_port_arrival_confirmation_button(frm);
		return;
	}

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_tracker.project_can_confirm_port_arrival",
		args: { project: frm.doc.name },
		callback(r) {
			if (r.exc || !r.message?.can_confirm || frm.doc.name !== frm.docname) {
				return;
			}
			mount_port_arrival_confirmation_button(frm);
		},
	});
}

function setup_create_container_allocation_button(frm) {
	if (frm.is_new() || !frm.doc.name || !project_supports_container_allocation(frm)) {
		return;
	}

	frm.add_custom_button(
		__("Create Container Allocation"),
		() => open_project_create_allocation_dialog(frm.doc.name),
		__("Actions")
	);
}

function open_project_create_allocation_dialog(project) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.get_container_allocation_defaults",
		args: { project },
		freeze: true,
		callback(r) {
			if (r.exc) {
				return;
			}
			const payload = r.message || {};
			const containers = payload.containers || [];
			if (!containers.length) {
				frappe.msgprint(
					__(
						"No unallocated containers on this project. Containers already on an allocation stay there until you move them from Container Allocation (Allocate Remaining / Move Containers)."
					)
				);
				return;
			}

			const dialog = new frappe.ui.Dialog({
				title: __("Create Container Allocation"),
				fields: [
					{
						fieldname: "help",
						fieldtype: "HTML",
						options: `<div class="text-muted" style="margin-bottom: var(--margin-sm);">
							${__("Unallocated containers")}: <b>${containers.length}</b>
							${
								payload.bill_of_lading
									? " · " + __("BL") + ": " + frappe.utils.escape_html(payload.bill_of_lading)
									: ""
							}
						</div>`,
					},
					{
						fieldname: "container_trackers",
						fieldtype: "MultiCheck",
						label: __("Containers"),
						reqd: 1,
						columns: 1,
						options: containers.map((c) => ({
							label: `${c.container_number || c.container_tracker}${
								c.cargo_size ? " · " + c.cargo_size : ""
							}`,
							value: c.container_tracker,
							checked: 1,
						})),
					},
					{
						fieldname: "transporter",
						fieldtype: "Link",
						label: __("Transporter"),
						options: "Supplier",
						reqd: 1,
						get_query: () => ({ filters: { is_transporter: 1 } }),
					},
					{
						fieldname: "trucks_booked",
						fieldtype: "Int",
						label: __("Number of Trucks Booked"),
						default: containers.length,
					},
				],
				primary_action_label: __("Create & Submit"),
				primary_action(values) {
					const trackers = values.container_trackers || [];
					if (!trackers.length) {
						frappe.msgprint(__("Select at least one container."));
						return;
					}
					frappe.call({
						method:
							"cgm_shipping.cgm_worldwide_shipping.customizations.container_allocation.create_allocation_for_containers",
						args: {
							project,
							transporter: values.transporter,
							container_trackers: trackers,
							trucks_booked: values.trucks_booked || trackers.length,
							submit: 1,
						},
						freeze: true,
						freeze_message: __("Creating allocation…"),
						callback(res) {
							if (res.exc) {
								return;
							}
							dialog.hide();
							frappe.show_alert({
								message: res.message?.message || __("Allocation created."),
								indicator: "green",
							});
							if (res.message?.name) {
								frappe.set_route("Form", "Container Allocation", res.message.name);
							}
						},
					});
				},
			});
			dialog.show();
		},
	});
}

function is_clearance_project(frm) {
	return ["Sea", "Air", "Road"].includes(frm.doc.custom_mode_of_transport);
}

function open_project_clearance_tasks(frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.workflow_tasks.get_project_workflow_flow_keys_api",
		args: { project: frm.doc.name },
		callback(r) {
			const flowKeys = (r.message || []).filter(Boolean);
			frappe.route_options = {
				project: frm.doc.name,
				status: ["in", ["Open", "Working", "Pending Review", "Overdue", "Completed"]],
			};
			if (flowKeys.length === 1) {
				frappe.route_options.custom_task_flow_key = flowKeys[0];
			} else if (flowKeys.length > 1) {
				frappe.route_options.custom_task_flow_key = ["in", flowKeys];
			}
			frappe.set_route("List", "Task");
		},
	});
}

function sync_consignee_from_customer(frm) {
	if (!frm.doc.customer || !frm.fields_dict.custom_consignee) {
		return;
	}
	frappe.db.get_value("Customer", frm.doc.customer, "customer_name", (values) => {
		frm.set_value("custom_consignee", values?.customer_name || frm.doc.customer);
	});
}

function setup_customer_batch_autocomplete(frm) {
	const fieldname = "custom_batch_no";
	if (!frm.fields_dict[fieldname] || !frm.doc.customer) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.get_customer_batch_numbers",
		args: { customer: frm.doc.customer },
		callback(r) {
			const options = (r.message || []).join("\n");
			frm.set_df_property(fieldname, "options", options);
			const df = frm.get_field(fieldname)?.df;
			if (df && df.fieldtype === "Data") {
				frm.set_df_property(fieldname, "fieldtype", "Autocomplete");
			}
			frm.set_df_property(fieldname, "read_only", 0);
			frm.refresh_field(fieldname);
		},
	});
}

function toggle_project_transport_reference_fields(frm) {
	const transportToggle = cgm_shipping.transport_reference.toggle(frm, {
		air_waybill: "custom_awb_number",
		bill_of_lading: "custom_bill_of_lading",
		container_table: "custom_container_information",
	});
	const cargoTypeToggle = cgm_shipping.transport_reference.toggle_cargo_type(frm, {
		booking_confirmation: "custom_booking_confirmation",
	});
	toggle_project_cargo_fields(frm);
	return Promise.all([transportToggle, cargoTypeToggle]).then(([category]) => {
		toggle_project_document_stage_fields(frm, category);
	});
}

function project_cargo_type_code(frm) {
	return (frm.doc.custom_cargo_type || "").trim().toUpperCase();
}

function toggle_project_cargo_fields(frm) {
	const is_lcl = project_cargo_type_code(frm) === "LCL";
	const show_fcl = !is_lcl;
	const show_packages = is_lcl;
	const showRequestedCargo = show_fcl && !frm.doc.custom_bill_of_lading;

	[
		["custom_requested_cargo_quantity", showRequestedCargo],
		["custom_number_of_packages", show_packages],
		["custom_package_type", show_packages],
	].forEach(([fieldname, show]) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		frm.set_df_property(fieldname, "hidden", show ? 0 : 1);
	});

	if (frm.fields_dict.custom_booking_confirmation) {
		frm.set_df_property("custom_booking_confirmation", "hidden", 0);
	}
	if (frm.fields_dict.custom_cargo_type) {
		frm.set_df_property("custom_cargo_type", "hidden", 0);
	}

	if (showRequestedCargo) {
		frm.refresh_field("custom_requested_cargo_quantity");
	}
	if (show_packages) {
		frm.refresh_field("custom_number_of_packages");
		frm.refresh_field("custom_package_type");
	}
}

function toggle_project_document_stage_fields(frm, category) {
	const hasBillOfLading = Boolean(frm.doc.custom_bill_of_lading);
	if (category !== "sea") {
		return;
	}

	const is_lcl = project_cargo_type_code(frm) === "LCL";
	const showBookingCargo = !hasBillOfLading && !is_lcl;
	const showContainerSection = hasBillOfLading || is_lcl;
	const showContainers = hasBillOfLading && !is_lcl;

	[
		["custom_section_break_yqqmp", hasBillOfLading],
		["custom_bill_of_lading", hasBillOfLading],
		["custom_section_break_amabs", showContainerSection],
		["custom_container_information", showContainers],
		["custom_section_break_is8hz", showBookingCargo],
		["custom_requested_cargo_quantity", showBookingCargo],
	].forEach(([fieldname, show]) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, show);
		}
	});
}

function setup_add_bill_of_lading_button(frm) {
	frm.remove_custom_button(__("Add Bill of Lading"), __("Shipment"));
	frm.remove_custom_button(__("Add Bill of Lading"), __("Actions"));
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	// Only when shipment started without a BL (typically Booking-first).
	if (frm.doc.custom_bill_of_lading) {
		return;
	}
	if (!frm.doc.custom_source_opportunity && !frm.doc.custom_booking_confirmation) {
		return;
	}

	frm.add_custom_button(
		__("Add Bill of Lading"),
		() => open_bill_of_lading_from_project(frm),
		__("Actions")
	);
}

function open_bill_of_lading_from_project(frm) {
	const opportunity = frm.doc.custom_source_opportunity;
	if (opportunity) {
		localStorage.setItem("cgm_return_opportunity", opportunity);
		localStorage.setItem("cgm_bl_seed_opportunity", opportunity);
	}

	const seed = {
		linked_opportunity: opportunity || undefined,
		booking_confirmation: frm.doc.custom_booking_confirmation || undefined,
		customer: frm.doc.customer || undefined,
		shipment_type: frm.doc.custom_shipment_type || undefined,
		client_refrence_no: frm.doc.custom_client_refrence_no || undefined,
		cargo_type: frm.doc.custom_cargo_type || undefined,
		batch_no: frm.doc.custom_batch_no || undefined,
	};

	frappe.route_options = seed;
	frappe.model.with_doctype("Bill of Lading", () => {
		frappe.new_doc("Bill of Lading");
	});
}

function project_clearance_indicator(doc) {
	const status = doc.custom_shipment_status;
	if (!status) return null;
	let colour = frappe.utils.guess_colour(status);
	const wf = locals["Workflow State"] && locals["Workflow State"][status];
	if (wf && wf.style && WORKFLOW_COLOURS[wf.style]) {
		colour = WORKFLOW_COLOURS[wf.style];
	}
	return [__(status), colour];
}

function ensure_project_form_layout_visible(frm) {
	if (!frm?.layout?.wrapper || frm.is_new()) {
		return;
	}
	const visible_controls = frm.layout.wrapper.find(".frappe-control:not(.hide-control)").length;
	if (visible_controls > 0) {
		return;
	}
	frm.layout.doc = frm.doc;
	if (typeof frm.layout.refresh === "function") {
		frm.layout.refresh(frm.doc);
	}
	frm.layout.wrapper.find(".form-section").each(function () {
		const $section = $(this);
		if ($section.find(".frappe-control").length) {
			$section.removeClass("empty-section").addClass("visible-section");
		}
	});
	(frm.layout.tabs || []).forEach((tab) => {
		if (tab.toggle) {
			tab.toggle(true);
		}
	});
	const tabs = frm.layout.tabs || [];
	const has_active = tabs.some((tab) => tab.is_active?.());
	if (!has_active) {
		const first_visible = tabs.find((tab) => !tab.is_hidden?.());
		first_visible?.set_active?.();
	}
	const after_fix = frm.layout.wrapper.find(".frappe-control:not(.hide-control)").length;
	if (!after_fix) {
		console.warn("CGM Project form still has no visible fields after layout recovery", frm.doc.name);
	}
}

function render_shipment_progress_chart(frm) {
	const field = frm.get_field("custom_shipment_progress_html");
	if (!field || !frm.doc.name) {
		return;
	}
	frappe.require("/assets/cgm_shipping/css/project_tracking.css");
	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.project_layout.get_project_tracking_dashboard",
		args: { project: frm.doc.name },
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			const d = r.message;
			const steps = (d.states || [])
				.map((state, i) => {
					let cls = "cgm-progress-step";
					if (i < d.current_index) cls += " is-done";
					if (state === d.current_status) cls += " is-current";
					return `<span class="${cls}" title="${frappe.utils.escape_html(state)}">${frappe.utils.escape_html(state)}</span>`;
				})
				.join("");
			let taskLine = `<div class="cgm-progress-meta">${__(
				"No clearance tasks on this project yet."
			)}</div>`;
			if (d.tasks_total > 0) {
				let nextHint = __("Next open task");
				if (d.first_open_task) {
					nextHint = `Task ${d.first_open_task.seq}: ${d.first_open_task.subject}`;
				}
				const taskLabel = d.task_progress_label || __("workflow tasks");
				taskLine = `<div class="cgm-progress-meta"><b>${d.tasks_completed}/${d.tasks_total}</b> ${frappe.utils.escape_html(taskLabel)} completed - next open: <b>${frappe.utils.escape_html(nextHint)}</b></div>`;
			}
			const berth = frappe.utils.escape_html(d.berth_phase || "Before Vessel Berth");
			const wfNote =
				d.workflow_behind && d.workflow_status
					? ` · ${__("Workflow field")}: <b>${frappe.utils.escape_html(d.workflow_status)}</b> (${__("syncing")})`
					: d.workflow_ahead && d.workflow_status
						? ` · ${__("Workflow field was ahead — correcting to tasks")}`
						: "";
			const legendLine = d.uses_clearance_states
				? `<div class="cgm-tracking-legend">
						${__("Berth phase")}: <b>${berth}</b> ·
						${__("Green")} = passed · <b>${frappe.utils.escape_html(d.current_status)}</b> = current${wfNote}
					</div>`
				: `<div class="cgm-tracking-legend">
						${__("Green")} = passed · <b>${frappe.utils.escape_html(d.current_status)}</b> = current
					</div>`;
			let inspectionLine = "";
			if (d.inspection_notification_status === "Notified" && d.inspection_notified_on) {
				inspectionLine = `<div class="cgm-inspection-notified">${__(
					"Client notified for inspection"
				)} · ${frappe.datetime.str_to_user(d.inspection_notified_on)}</div>`;
			} else if (d.inspection_notification_status === "Confirmed" && d.inspection_confirmed_on) {
				const by = d.inspection_confirmed_by
					? ` · ${frappe.utils.escape_html(d.inspection_confirmed_by)}`
					: "";
				inspectionLine = `<div class="cgm-inspection-confirmed">${__(
					"Inspection confirmed"
				)} · ${frappe.datetime.str_to_user(d.inspection_confirmed_on)}${by}</div>`;
			}
			let portArrivalLine = "";
			if (d.port_arrival_confirmed && d.port_arrival_confirmed_on) {
				const by = d.port_arrival_confirmed_by
					? ` · ${frappe.utils.escape_html(d.port_arrival_confirmed_by)}`
					: "";
				portArrivalLine = `<div class="cgm-port-arrival-confirmed">${__(
					"Port arrival confirmed"
				)} · ${frappe.datetime.str_to_user(d.port_arrival_confirmed_on)}${by}</div>`;
			}
			field.$wrapper
				.closest('[data-fieldname="custom_shipment_progress_html"]')
				.addClass("cgm-shipment-progress-field");
			field.$wrapper.html(`
				<div class="cgm-shipment-progress">
					<h4>${__("Shipment clearance workflow")}</h4>
					<div class="cgm-progress-steps">${steps}</div>
					${taskLine}
					${inspectionLine}
					${portArrivalLine}
					${legendLine}
				</div>
			`);
			if (
				d.uses_clearance_states &&
				d.current_status &&
				frm.doc.custom_shipment_status !== d.current_status
			) {
				// Keep UI in sync without dirtying — unsaved docs hide workflow Actions.
				frm.set_value("custom_shipment_status", d.current_status, false, true);
				const indicator = project_clearance_indicator({
					custom_shipment_status: d.current_status,
				});
				if (indicator) {
					frm.page.set_indicator(indicator[0], indicator[1]);
				}
			}
			render_container_tracking_table(frm, d);
		},
	});
}

function format_currency_amount(value, currency) {
	if (value == null || value === "") {
		return "";
	}
	const resolvedCurrency =
		currency ||
		frappe.defaults.get_default("currency") ||
		frappe.boot.sysdefaults.currency;
	return format_currency(flt(value), resolvedCurrency);
}

function sum_amounts_by_currency(rows, amountField, currencyField) {
	const totals = {};
	(rows || []).forEach((row) => {
		const amount = flt(row[amountField]);
		if (!amount) {
			return;
		}
		const currency =
			row[currencyField] ||
			frappe.defaults.get_default("currency") ||
			frappe.boot.sysdefaults.currency;
		totals[currency] = (totals[currency] || 0) + amount;
	});
	return totals;
}

function format_currency_totals_label(totals) {
	return Object.entries(totals || {})
		.filter(([, amount]) => flt(amount) > 0)
		.map(([currency, amount]) => format_currency_amount(amount, currency))
		.join(" · ");
}

function container_status_dot(status, alert_status) {
	const alert = alert_status || "";
	if (alert.includes("🔴") || alert.includes("🚨") || status === "Return Overdue") {
		return "🔴";
	}
	if (alert.includes("⚠️")) {
		return "🟡";
	}
	if (status === "Interchange Received" || alert.includes("✅")) {
		return "🟢";
	}
	if (["At Warehouse", "Cargo Offloaded", "Empty Returned"].includes(status)) {
		return "🟢";
	}
	if (["Discharged / At Port", "Vessel Berthed"].includes(status)) {
		return "🟡";
	}
	if (status === "Released / In Transit") {
		return "🟠";
	}
	return "⚪";
}

function container_card_escape(value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
}

function container_card_format_date(value) {
	if (!value) {
		return "";
	}
	return frappe.datetime.str_to_user(value);
}

function container_card_row(label, value, options = {}) {
	if (value == null || value === "") {
		return "";
	}
	const valueClass = options.warn ? "cgm-container-card-value cgm-rag-red" : "cgm-container-card-value";
	return `<div class="cgm-container-card-row">
		<span class="cgm-container-card-label">${container_card_escape(label)}</span>
		<span class="${valueClass}">${container_card_escape(value)}</span>
	</div>`;
}

function container_card_days_label(count, suffix) {
	if (count == null || count === "") {
		return "";
	}
	const n = cint(count);
	return n === 1 ? `1 ${suffix}` : `${n} ${suffix}`;
}

function container_card_return_countdown(expected_return) {
	if (!expected_return) {
		return "";
	}
	const today = frappe.datetime.get_today();
	const remaining = frappe.datetime.get_diff(expected_return, today);
	if (remaining > 0) {
		return __("{0} days remaining", [remaining]);
	}
	if (remaining === 0) {
		return __("due today");
	}
	return __("overdue by {0} days", [Math.abs(remaining)]);
}

function render_container_card_body(c) {
	const status = c.status || "";
	const today = frappe.datetime.get_today();
	const demurrageDays = cint(c.demurrage_days);
	const kpaDays = cint(c.kpa_days);
	const sections = [];

	const movementRows = [
		container_card_row(__("Current location"), c.current_location),
		container_card_row(__("ATA"), container_card_format_date(c.ata)),
		container_card_row(__("Discharged"), container_card_format_date(c.discharging_date)),
		container_card_row(__("Gate out (Mombasa)"), container_card_format_date(c.gate_out_date_port)),
		container_card_row(__("Offloaded"), container_card_format_date(c.offloading_date)),
		container_card_row(__("Empty return"), container_card_format_date(c.actual_empty_return)),
		container_card_row(__("Interchange"), container_card_format_date(c.interchange_date)),
	];
	if (c.port_days_used != null && !c.gate_out_date_port && c.discharging_date) {
		movementRows.push(
			container_card_row(__("Days in port"), container_card_days_label(c.port_days_used, __("days")))
		);
	}
	if (
		c.expected_empty_return &&
		["Released / In Transit", "At Warehouse", "Cargo Offloaded", "Empty Returned", "Return Overdue"].includes(
			status
		)
	) {
		movementRows.push(
			container_card_row(
				__("Expected empty return"),
				`${container_card_format_date(c.expected_empty_return)} (${container_card_return_countdown(
					c.expected_empty_return
				)})`
			)
		);
	}
	if (c.days_outstanding > 0) {
		movementRows.push(
			container_card_row(
				__("Return overdue"),
				container_card_days_label(c.days_outstanding, __("days")),
				{ warn: true }
			)
		);
	}
	const movementHtml = movementRows.filter(Boolean).join("");
	if (movementHtml) {
		sections.push(`
			<div class="cgm-container-card-section">
				<div class="cgm-container-card-section-title">${__("Movement")}</div>
				${movementHtml}
			</div>
		`);
	}

	const slFreeEnd = container_card_format_date(c.free_days_end_date);
	let slFreeEndDisplay = slFreeEnd;
	if (slFreeEnd && !c.gate_out_date_port && c.free_days_end_date) {
		const slRemaining = frappe.datetime.get_diff(c.free_days_end_date, today);
		if (slRemaining >= 0) {
			slFreeEndDisplay = `${slFreeEnd} (${__("{0} days left", [slRemaining])})`;
		} else if (demurrageDays <= 0) {
			slFreeEndDisplay = `${slFreeEnd} (${__("free period ended")})`;
		}
	}

	const shippingRows = [
		container_card_row(__("Free start"), container_card_format_date(c.free_days_start_date)),
		container_card_row(__("Free end"), slFreeEndDisplay),
		container_card_row(__("Free days"), c.free_days != null ? String(c.free_days) : ""),
		container_card_row(
			__("Demurrage/Detention days"),
			demurrageDays > 0 ? container_card_days_label(demurrageDays, __("days")) : demurrageDays === 0 ? "0" : "",
			{ warn: demurrageDays > 0 }
		),
	];
	if (c.demurrage_amount > 0) {
		shippingRows.push(
			container_card_row(
				__("Demurrage amount"),
				format_currency_amount(c.demurrage_amount, c.demurrage_rate_currency),
				{ warn: true }
			)
		);
	} else if (demurrageDays > 0) {
		shippingRows.push(
			container_card_row(
				__("Demurrage amount"),
				format_currency_amount(c.demurrage_amount || 0, c.demurrage_rate_currency)
			)
		);
	}
	if (!c.free_days_end_date && c.discharging_date) {
		shippingRows.push(
			container_card_row(__("Shipping line free days"), __("Not set — enter on tracker"), { warn: true })
		);
	}
	sections.push(`
		<div class="cgm-container-card-section">
			<div class="cgm-container-card-section-title">${__("Shipping line")}${
				c.shipping_line ? ` · ${container_card_escape(c.shipping_line)}` : ""
			}</div>
			${shippingRows.filter(Boolean).join("")}
		</div>
	`);

	const kpaFreeEnd = container_card_format_date(c.kpa_free_days_end_date);
	let kpaFreeEndDisplay = kpaFreeEnd;
	if (kpaFreeEnd && !c.gate_out_date_port && c.kpa_free_days_end_date) {
		const kpaRemaining = frappe.datetime.get_diff(c.kpa_free_days_end_date, today);
		if (kpaRemaining >= 0) {
			kpaFreeEndDisplay = `${kpaFreeEnd} (${__("{0} days left", [kpaRemaining])})`;
		} else if (kpaDays <= 0) {
			kpaFreeEndDisplay = `${kpaFreeEnd} (${__("free period ended")})`;
		}
	}

	const kpaRows = [
		container_card_row(__("KPA free start"), container_card_format_date(c.kpa_free_days_start_date)),
		container_card_row(__("KPA free end"), kpaFreeEndDisplay),
		container_card_row(__("KPA free days"), c.kpa_free_days != null ? String(c.kpa_free_days) : ""),
		container_card_row(
			__("KPA chargeable days"),
			kpaDays > 0 ? container_card_days_label(kpaDays, __("days")) : kpaDays === 0 ? "0" : "",
			{ warn: kpaDays > 0 }
		),
	];
	if (c.kpa_amount > 0) {
		kpaRows.push(
			container_card_row(
				__("KPA port amount"),
				format_currency_amount(c.kpa_amount, c.kpa_rate_currency),
				{ warn: true }
			)
		);
	} else if (kpaDays > 0) {
		kpaRows.push(
			container_card_row(
				__("KPA port amount"),
				format_currency_amount(c.kpa_amount || 0, c.kpa_rate_currency)
			)
		);
	}
	sections.push(`
		<div class="cgm-container-card-section">
			<div class="cgm-container-card-section-title">${__("KPA port")}</div>
			${kpaRows.filter(Boolean).join("")}
		</div>
	`);

	if (!movementHtml && !c.discharging_date && !c.ata) {
		return `<div class="cgm-container-card-empty">${__(
			"Awaiting vessel arrival and discharge dates."
		)}</div><div class="cgm-container-card-grid">${sections.join("")}</div>`;
	}

	return `<div class="cgm-container-card-grid">${sections.join("")}</div>`;
}

function render_container_card_subtitle(c) {
	const parts = [];
	if (c.cargo_size || c.cargo_type) {
		parts.push(c.cargo_size || c.cargo_type);
	}
	if (c.seal_no) {
		parts.push(`${__("Seal")}: ${c.seal_no}`);
	}
	if (c.shipping_line && !c.free_days_start_date) {
		parts.push(c.shipping_line);
	}
	return parts.join(" · ");
}

function container_allocation_detail(c) {
	if (!c.allocation) {
		return "";
	}
	const transporter = c.allocation_transporter || "";
	const status = c.assignment_status || __("Pending");
	let text = `${__("Allocated to")} ${transporter} (${status})`;
	if (c.allocation_pending_alert) {
		text += ` — ${__("Truck not assigned yet")}`;
	}
	return text;
}

function container_status_badge_class(status) {
	if (!status) {
		return "gray";
	}
	if (status.includes("Overdue")) {
		return "red";
	}
	if (status === "Interchange Received" || status === "Empty Returned") {
		return "green";
	}
	if (["At Warehouse", "Cargo Offloaded"].includes(status)) {
		return "blue";
	}
	if (status === "Released / In Transit") {
		return "orange";
	}
	if (["Vessel Berthed", "Discharged / At Port"].includes(status)) {
		return "yellow";
	}
	return "gray";
}

function render_container_tracking_table(frm, dashboard) {
	const field = frm.get_field("custom_container_tracking_html");
	if (!field || !frm.doc.name) {
		return;
	}
	const rows = dashboard.containers || [];
	const ref = frappe.utils.escape_html(
		dashboard.project_reference || dashboard.cgm_ref_no || frm.doc.custom_project_reference || frm.doc.project_name || frm.doc.name
	);

	let cards = "";
	if (!rows.length) {
		cards = `<div class="text-muted cgm-container-empty">${__(
			"No containers yet. Use Actions → Confirm Shipment Arrival at the Port, or complete Task 11 (Create Entry), to create Container Trackers."
		)}</div>`;
	} else {
		cards = rows
			.map((c) => {
				const dot = container_status_dot(c.status, c.alert_status);
				const subtitle = render_container_card_subtitle(c);
				const alert = c.alert_status
					? `<div class="cgm-container-card-alert">${frappe.utils.escape_html(c.alert_status)}</div>`
					: "";
				const allocationLine = container_allocation_detail(c);
				const allocationHtml = allocationLine
					? `<div class="cgm-container-card-alert${
							c.allocation_pending_alert ? " cgm-rag-red" : ""
						}">${frappe.utils.escape_html(allocationLine)}${
							c.allocation
								? ` <button type="button" class="btn btn-xs btn-link cgm-open-allocation" data-allocation="${frappe.utils.escape_html(
										c.allocation
									)}">${__("View Allocation")}</button>`
								: ""
						}</div>`
					: "";
				const chargeBadge =
					cint(c.demurrage_days) > 0 || cint(c.kpa_days) > 0
						? `<span class="cgm-container-card-charge-badge">${__(
								"Incurring charges"
							)}</span>`
						: "";
				return `<div class="cgm-container-card${
					cint(c.demurrage_days) > 0 || cint(c.kpa_days) > 0 ? " cgm-container-card--charges" : ""
				}">
					<div class="cgm-container-card-head">
						<span class="cgm-container-card-id">${dot} <b>${frappe.utils.escape_html(
							c.container_number || c.name
						)}</b>${
							subtitle
								? `<span class="text-muted cgm-container-card-subtitle">${frappe.utils.escape_html(
										subtitle
									)}</span>`
								: ""
						}${chargeBadge}</span>
						<span class="indicator-pill ${container_status_badge_class(
							c.status
						)} cgm-container-card-status">${frappe.utils.escape_html(c.status || "")}</span>
					</div>
					<div class="cgm-container-card-body">${render_container_card_body(c)}</div>
					${alert}
					${allocationHtml}
					<div class="cgm-container-card-actions">
						<button type="button" class="btn btn-xs btn-default cgm-view-tracker" data-tracker="${frappe.utils.escape_html(
							c.name
						)}">${__("Open Container Tracker")}</button>
					</div>
				</div>`;
			})
			.join("");
	}

	const demurrageKpiClass = dashboard.containers_in_demurrage ? "cgm-rag-red" : "";
	const kpaKpiClass = dashboard.containers_in_kpa_charges ? "cgm-rag-red" : "";
	const demurrageAmountLabel = format_currency_totals_label(
		sum_amounts_by_currency(rows, "demurrage_amount", "demurrage_rate_currency")
	);
	const kpaAmountLabel = format_currency_totals_label(
		sum_amounts_by_currency(rows, "kpa_amount", "kpa_rate_currency")
	);
	const demurrageAmountKpi = demurrageAmountLabel
		? `<span>${__("Demurrage accrued")}: <b>${demurrageAmountLabel}</b></span>`
		: "";
	const kpaAmountKpi = kpaAmountLabel
		? `<span>${__("KPA port accrued")}: <b>${kpaAmountLabel}</b></span>`
		: "";

	field.$wrapper.html(`
		<div class="cgm-container-dashboard">
			<div class="cgm-container-dashboard-head">
				<div>
					<h4 class="cgm-container-dashboard-title">${__("Container Tracking")}</h4>
					<div class="text-muted">${ref}</div>
				</div>
				<div class="cgm-container-dashboard-actions">
					<button type="button" class="btn btn-default btn-xs cgm-resync-containers">${__(
						"Resync Status"
					)}</button>
					<button type="button" class="btn btn-default btn-xs cgm-open-tracking-report">${__(
						"Full Report"
					)}</button>
				</div>
			</div>
			<div class="cgm-container-kpis">
				<span>${__("Total")}: <b>${dashboard.container_total || 0}</b></span>
				<span>${__("Released")}: <b>${dashboard.containers_released || 0}</b></span>
				<span>${__("Warehouse")}: <b>${dashboard.containers_at_warehouse || 0}</b></span>
				<span>${__("Returned")}: <b>${dashboard.containers_returned || 0}</b></span>
				<span>${__("In demurrage")}: <b class="${demurrageKpiClass}">${
					dashboard.containers_in_demurrage || 0
				}</b> <span class="text-muted">(${dashboard.total_demurrage_days || 0} ${__("days")})</span></span>
				<span>${__("KPA chargeable")}: <b class="${kpaKpiClass}">${
					dashboard.containers_in_kpa_charges || 0
				}</b> <span class="text-muted">(${dashboard.total_kpa_days || 0} ${__("days")})</span></span>
				<span>${__("Alerts")}: <b class="${dashboard.containers_alerts ? "cgm-rag-red" : ""}">${
					dashboard.containers_alerts || 0
				}</b></span>
				${demurrageAmountKpi}
				${kpaAmountKpi}
			</div>
			<div class="cgm-container-cards">${cards}</div>
		</div>
	`);

	field.$wrapper.find(".cgm-view-tracker").on("click", function () {
		const tracker = $(this).data("tracker");
		if (tracker) {
			frappe.set_route("Form", "Container Tracker", tracker);
		}
	});

	field.$wrapper.find(".cgm-open-allocation").on("click", function () {
		const allocation = $(this).data("allocation");
		if (allocation) {
			frappe.set_route("Form", "Container Allocation", allocation);
		}
	});

	field.$wrapper.find(".cgm-resync-containers").on("click", () => {
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.doctype.container_tracker.container_tracker.resync_project_container_child_rows",
			args: { project: frm.doc.name },
			callback() {
				render_shipment_progress_chart(frm);
				frappe.show_alert({ message: __("Container statuses resynced"), indicator: "green" });
			},
		});
	});

	field.$wrapper.find(".cgm-open-tracking-report").on("click", () => {
		frappe.set_route("query-report", "Container Tracking Report", { project: frm.doc.name });
	});
}

function apply_project_costing_display_fields(frm, values) {
	// Display-only rollups — never mark the form dirty (that hides workflow Actions).
	Object.entries(values || {}).forEach(([fieldname, value]) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		const next = value || "";
		if ((frm.doc[fieldname] || "") === next) {
			return;
		}
		frm.set_value(fieldname, next, false, true);
	});
}

function refresh_project_costing_currency_display(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	if (
		!frm.fields_dict.custom_demurrage_accrued_total_display &&
		!frm.fields_dict.custom_finance_cost_total_display
	) {
		return;
	}
	if (frm._cgm_costing_display_loaded === frm.doc.name) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_charges.refresh_project_costing_display",
		args: { project: frm.doc.name },
		callback(r) {
			if (r.exc || frm.doc.name !== frm.docname) {
				return;
			}
			frm._cgm_costing_display_loaded = frm.doc.name;
			apply_project_costing_display_fields(frm, r.message || {});
		},
	});
}

function manual_refresh_finance_costs(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.container_charges.refresh_project_costing_display",
		args: { project: frm.doc.name },
		freeze: true,
		freeze_message: __("Refreshing billed amount..."),
		callback(r) {
			if (r.exc) {
				return;
			}
			frm._cgm_costing_display_loaded = frm.doc.name;
			apply_project_costing_display_fields(frm, r.message || {});
			frappe.show_alert({
				message: __("Billed amount refreshed from journal entries."),
				indicator: "green",
			});
		},
	});
}

function post_container_charge_accrual(frm) {
	if (frm.is_new()) {
		return;
	}
	frappe.confirm(
		__(
			"Post new demurrage and KPA port charge accruals to a Journal Entry for this project?"
		),
		() => {
			frappe.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.container_charges.post_container_charge_accrual",
				args: { project: frm.doc.name },
				freeze: true,
				freeze_message: __("Posting container charge accrual..."),
				callback(r) {
					const result = r.message || {};
					if (result.journal_entry) {
						frappe.show_alert({
							message: __("Accrual posted: {0}", [result.journal_entry]),
							indicator: "green",
						});
						frappe.set_route("Form", "Journal Entry", result.journal_entry);
					} else {
						frappe.msgprint(result.message || __("No new accrual amount to post."));
					}
					frm._cgm_costing_display_loaded = null;
					refresh_project_costing_currency_display(frm);
					render_shipment_progress_chart(frm);
				},
			});
		}
	);
}

function open_project_finance_journal_entries(frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.finance_cost_ledger.get_project_finance_journal_entry_names",
		args: { project: frm.doc.name },
		callback(r) {
			const names = r.message || [];
			if (!names.length) {
				frappe.msgprint(__("No submitted journal entries are linked to this project yet."));
				return;
			}
			frappe.route_options = { name: ["in", names], docstatus: 1 };
			frappe.set_route("List", "Journal Entry");
		},
	});
}

frappe.realtime.on("cgm_project_tracking_refresh", (data) => {
	if (
		cur_frm &&
		cur_frm.doctype === "Project" &&
		cur_frm.doc.name === data.project &&
		!cur_frm.is_new()
	) {
		render_shipment_progress_chart(cur_frm);
	}
});

function render_project_operational_updates(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	let section = frm.layout.wrapper.find(".cgm-project-updates");
	if (!section.length) {
		section = $(`
			<div class="cgm-project-updates form-section" style="margin:1rem 0;">
				<div class="section-head">${__("Operational Updates")}</div>
				<div class="cgm-project-updates-toolbar" style="display:flex;justify-content:space-between;gap:0.75rem;flex-wrap:wrap;margin:0.5rem 0 0.75rem;">
					<div class="text-muted" style="font-size:0.85rem;">
						${__("Transporter and customer updates linked to this shipment.")}
					</div>
					<a class="btn btn-xs btn-default" href="/app/update?project=${encodeURIComponent(frm.doc.name)}">${__("Open full update log")}</a>
				</div>
				<div class="cgm-project-updates-body text-muted">${__("Loading…")}</div>
			</div>
		`);
		const after =
			frm.fields_dict.custom_shipment_progress_html ||
			frm.fields_dict.custom_project_details ||
			frm.fields_dict.project_name;
		if (after && after.$wrapper) {
			section.insertAfter(after.$wrapper.closest(".form-section").length
				? after.$wrapper.closest(".form-section")
				: after.$wrapper);
		} else {
			section.prependTo(frm.layout.wrapper);
		}
	}

	frappe.call({
		method: "cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_project_updates",
		args: { project: frm.doc.name },
		callback(r) {
			const rows = r.message || [];
			const body = section.find(".cgm-project-updates-body");
			if (!rows.length) {
				body.html(`<div class="text-muted">${__("No operational updates yet.")}</div>`);
				return;
			}
			body.html(cgm.updates.renderList(rows.slice(0, 25)));
			cgm.updates.bindListClicks(body);
		},
	});
}

function setup_project_toolbar_buttons(frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}

	setup_port_arrival_confirmation_button(frm);
	setup_create_container_allocation_button(frm);
	setup_add_bill_of_lading_button(frm);

	frm.add_custom_button(__("Clearance Tasks"), () => open_project_clearance_tasks(frm)).addClass(
		"btn-primary"
	);
	frm.add_custom_button(__("Container Tracker"), () => {
		frappe.set_route("List", "Container Tracker", { project: frm.doc.name });
	}, __("View"));
	frm.add_custom_button(__("Container Tracking Report"), () => {
		frappe.set_route("query-report", "Container Tracking Detail", {
			project: frm.doc.name,
		});
	}, __("View"));
	frm.add_custom_button(__("Container Ops Board"), () => {
		frappe.route_options = { project: frm.doc.name };
		frappe.set_route("container-ops-board");
	}, __("View"));
	frm.add_custom_button(__("Post Container Charge Accrual"), () => {
		post_container_charge_accrual(frm);
	}, __("Shipment"));
	frm.add_custom_button(__("View Journal Entries"), () => {
		open_project_finance_journal_entries(frm);
	}, __("View"));
	frm.add_custom_button(__("Daily Status"), () => {
		frappe.new_doc("Daily Status Update");
	}, __("View"));
	frm.add_custom_button(__("Seal Record"), () => {
		frappe.new_doc("Seal Record", { project: frm.doc.name });
	}, __("View"));
	frm.page.set_inner_btn_group_as_primary(__("View"));
}

frappe.ui.form.on("Project", {
	onload(frm) {
		try {
			if (frm.is_new() && frm.fields_dict.custom_opened_date && !frm.doc.custom_opened_date) {
				frm.set_value("custom_opened_date", frappe.datetime.get_today());
			}
			if (frm.doc.customer && !frm.doc.custom_consignee) {
				sync_consignee_from_customer(frm);
			}
		} catch (err) {
			console.error("CGM Project onload failed", err);
		}
	},

	onload_post_render(frm) {
		ensure_project_form_layout_visible(frm);
		setTimeout(() => ensure_project_form_layout_visible(frm), 0);
	},

	customer(frm) {
		sync_consignee_from_customer(frm);
		setup_customer_batch_autocomplete(frm);
	},

	refresh(frm) {
		// Toolbar buttons first — other setup must not prevent these from appearing.
		try {
			setup_project_toolbar_buttons(frm);
		} catch (err) {
			console.error("CGM Project toolbar setup failed", err);
		}

		try {
			toggle_project_transport_reference_fields(frm);
			setup_customer_batch_autocomplete(frm);

			if (frm.doc.custom_shipment_status) {
				const indicator = project_clearance_indicator(frm.doc);
				if (indicator) {
					frm.page.set_indicator(indicator[0], indicator[1]);
				}
			}

			render_shipment_progress_chart(frm);
			refresh_project_costing_currency_display(frm);
			configure_project_document_grid(frm);
			configure_project_status_fields(frm);
			configure_project_container_grid(frm);

			// Sync auto business name to Project Reference only — never CGM Ref No
			// (company-entered, independent of project_name).
			if (
				frm.is_new() &&
				frm.doc.project_name &&
				frm.fields_dict.custom_project_reference &&
				!frm.doc.custom_project_reference
			) {
				frm.set_value("custom_project_reference", frm.doc.project_name);
			}

			ensure_project_form_layout_visible(frm);
			setTimeout(() => ensure_project_form_layout_visible(frm), 0);
		} catch (err) {
			console.error("CGM Project refresh failed", err);
			ensure_project_form_layout_visible(frm);
		}
	},

	project_name(frm) {
		if (
			frm.fields_dict.custom_project_reference &&
			frm.doc.project_name &&
			!frm.doc.custom_project_reference
		) {
			frm.set_value("custom_project_reference", frm.doc.project_name);
		}
	},

	custom_mode_of_transport(frm) {
		toggle_project_transport_reference_fields(frm);
	},

	custom_shipment_type(frm) {
		toggle_project_transport_reference_fields(frm);
	},

	custom_cargo_type(frm) {
		toggle_project_transport_reference_fields(frm);
	},

	custom_booking_confirmation(frm) {
		toggle_project_transport_reference_fields(frm);
	},

	custom_bill_of_lading(frm) {
		toggle_project_transport_reference_fields(frm);
		setup_add_bill_of_lading_button(frm);
	},

	custom_shipment_status(frm) {
		cgm_configure_project_status_fields(frm);
	},

	custom_inspection_notification_status(frm) {
		cgm_configure_project_status_fields(frm);
	},
});
