frappe.ui.form.on("Shipment Document", {
	attachment: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.attachment) {
			if (!row.status || row.status === "Missing") {
				frappe.model.set_value(cdt, cdn, "status", "Uploaded");
			}
			if (!row.uploaded_by) {
				frappe.model.set_value(cdt, cdn, "uploaded_by", frappe.session.user);
			}
		} else {
			frappe.model.set_value(cdt, cdn, "status", "Missing");
			frappe.model.set_value(cdt, cdn, "uploaded_by", "");
			frappe.model.set_value(cdt, cdn, "uploaded_on", "");
			frappe.model.set_value(cdt, cdn, "verified_by", "");
			frappe.model.set_value(cdt, cdn, "verified_on", "");
		}
	},

	status: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (["Verified", "Rejected"].includes(row.status)) {
			if (!row.attachment) {
				frappe.msgprint(__("Attach a file before verification."));
				frappe.model.set_value(cdt, cdn, "status", "Missing");
				return;
			}
			frappe.model.set_value(cdt, cdn, "verified_by", frappe.session.user);
			frappe.model.set_value(cdt, cdn, "verified_on", frappe.datetime.now_datetime());
		} else if (row.status === "Uploaded") {
			frappe.model.set_value(cdt, cdn, "verified_by", "");
			frappe.model.set_value(cdt, cdn, "verified_on", "");
		}
	},
});

const WORKFLOW_COLOURS = {
	Success: "green",
	Warning: "orange",
	Danger: "red",
	Primary: "blue",
	Inverse: "black",
	Info: "light-blue",
};

function is_clearance_project(frm) {
	return ["Sea", "Air", "Road"].includes(frm.doc.custom_mode_of_transport);
}

function open_project_clearance_tasks(frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}
	frappe.route_options = {
		project: frm.doc.name,
		custom_task_flow_key: "SEA_IMPORT_E2E",
		status: ["in", ["Open", "Working", "Pending Review", "Overdue", "Completed"]],
	};
	frappe.set_route("List", "Task");
}

function setup_clearance_tasks_toolbar_button(frm) {
	if (frm.is_new() || !frm.doc.name) {
		return;
	}
	if (frm._cgm_clearance_tasks_btn) {
		return;
	}
	frm._cgm_clearance_tasks_btn = frm.page.add_inner_button(__("Clearance Tasks"), () =>
		open_project_clearance_tasks(frm)
	);
}

function sync_consignee_from_customer(frm) {
	if (!frm.doc.customer || !frm.fields_dict.custom_consignee) {
		return;
	}
	frappe.db.get_value("Customer", frm.doc.customer, "customer_name", (values) => {
		frm.set_value("custom_consignee", values?.customer_name || frm.doc.customer);
	});
}

function toggle_project_transport_reference_fields(frm) {
	cgm_shipping.transport_reference.toggle(frm, {
		air_waybill: "custom_awb_number",
		bill_of_lading: "custom_bill_of_lading",
		container_table: "custom_container_information",
	});
	cgm_shipping.transport_reference.toggle_container_type(frm);
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

function render_shipment_progress_chart(frm) {
	const field = frm.get_field("custom_shipment_progress_html");
	if (!field || !frm.doc.name) {
		return;
	}
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
				let nextHint = __("Create UCR (IDF)");
				if (d.first_open_task) {
					nextHint = `Task ${d.first_open_task.seq}: ${d.first_open_task.subject}`;
				}
				taskLine = `<div class="cgm-progress-meta"><b>${d.tasks_completed}/${d.tasks_total}</b> sea tasks completed - next open: <b>${frappe.utils.escape_html(nextHint)}</b></div>`;
			}
			const berth = frappe.utils.escape_html(d.berth_phase || "Before Vessel Berth");
			const wfNote =
				d.workflow_behind && d.workflow_status
					? ` · ${__("Workflow field")}: <b>${frappe.utils.escape_html(d.workflow_status)}</b> (${__("syncing")})`
					: "";
			field.$wrapper.html(`
				<div class="cgm-shipment-progress">
					<h4>${__("Shipment clearance workflow")}</h4>
					<div class="cgm-progress-steps">${steps}</div>
					${taskLine}
					<div class="cgm-tracking-legend">
						${__("Berth phase")}: <b>${berth}</b> ·
						${__("Green")} = passed · <b>${frappe.utils.escape_html(d.current_status)}</b> = current${wfNote}
					</div>
				</div>
			`);
			if (d.workflow_behind && frm.doc.custom_shipment_status !== d.current_status) {
				frm.set_value("custom_shipment_status", d.current_status);
				const indicator = project_clearance_indicator({ custom_shipment_status: d.current_status });
				if (indicator) {
					frm.page.set_indicator(indicator[0], indicator[1]);
				}
			}
			render_container_tracking_table(frm, d);
		},
	});
}

function format_currency_amount(value) {
	if (value == null || value === "") {
		return "";
	}
	return frappe.format(value, {
		fieldtype: "Currency",
		options: frappe.defaults.get_default("currency"),
	});
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

function container_card_detail(c) {
	const parts = [];
	const status = c.status || "";
	const today = frappe.datetime.get_today();

	if (["Vessel Berthed", "Discharged / At Port"].includes(status) && !c.gate_out_date_port) {
		const berth_ref = c.discharging_date || c.ata;
		if (berth_ref) {
			const days = frappe.datetime.get_diff(today, berth_ref);
			parts.push(
				`${__("No movement dates yet")} — ${__(
					"vessel berthed"
				)} ${days} ${__("days ago")}`
			);
		} else {
			parts.push(__("No movement dates recorded yet"));
		}
	}

	if (c.discharging_date) {
		parts.push(`${__("Discharged")}: ${frappe.datetime.str_to_user(c.discharging_date)}`);
	}
	if (c.gate_out_date_port) {
		parts.push(`${__("Gate Out")}: ${frappe.datetime.str_to_user(c.gate_out_date_port)}`);
	}
	if (c.offloading_date) {
		parts.push(`${__("Offloaded")}: ${frappe.datetime.str_to_user(c.offloading_date)}`);
	}
	if (c.free_days != null && c.discharging_date && !c.gate_out_date_port) {
		const days_in_port = frappe.datetime.get_diff(today, c.discharging_date);
		const remaining = (c.free_days || 0) - days_in_port;
		parts.push(
			`${__("Free days")}: ${c.free_days} | ${__("Days in port")}: ${days_in_port} | ${remaining} ${__("remaining")}`
		);
	}
	if (
		c.expected_empty_return &&
		["Released / In Transit", "At Warehouse", "Cargo Offloaded", "Empty Returned"].includes(status)
	) {
		const remaining = frappe.datetime.get_diff(c.expected_empty_return, today);
		const remaining_label =
			remaining > 0
				? `${remaining} ${__("days remaining")}`
				: remaining === 0
					? __("due today")
					: `${Math.abs(remaining)} ${__("days overdue")}`;
		parts.push(
			`${__("Expected return")}: ${frappe.datetime.str_to_user(
				c.expected_empty_return
			)} (${remaining_label})`
		);
	}
	if (parts.length) {
		return parts.join(" | ");
	}
	if (!c.free_days && c.discharging_date) {
		return __("Free days not set — enter from guarantee form");
	}
	return __("No movement dates recorded yet");
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
	const ref = frappe.utils.escape_html(dashboard.cgm_ref_no || frm.doc.name);

	let cards = "";
	if (!rows.length) {
		cards = `<div class="text-muted cgm-container-empty">${__(
			"No containers yet. Complete Task 11 (Create Entry) to create Container Trackers."
		)}</div>`;
	} else {
		cards = rows
			.map((c) => {
				const dot = container_status_dot(c.status, c.alert_status);
				const alert = c.alert_status
					? `<div class="cgm-container-card-alert">${frappe.utils.escape_html(c.alert_status)}</div>`
					: "";
				return `<div class="cgm-container-card">
					<div class="cgm-container-card-head">
						<span>${dot} <b>${frappe.utils.escape_html(c.container_number || c.name)}</b>
						<span class="text-muted">${frappe.utils.escape_html(c.type_of_container || "")}</span></span>
						<span class="indicator-pill ${container_status_badge_class(
							c.status
						)} cgm-container-card-status">${frappe.utils.escape_html(c.status || "")}</span>
					</div>
					<div class="cgm-container-card-body text-muted">${frappe.utils.escape_html(
						container_card_detail(c)
					)}</div>
					${alert}
					<div class="cgm-container-card-actions">
						<button type="button" class="btn btn-xs btn-default cgm-view-tracker" data-tracker="${frappe.utils.escape_html(
							c.name
						)}">${__("View Details")}</button>
					</div>
				</div>`;
			})
			.join("");
	}

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
				<span>${__("Alerts")}: <b class="${dashboard.containers_alerts ? "cgm-rag-red" : ""}">${
					dashboard.containers_alerts || 0
				}</b></span>
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

frappe.ui.form.on("Project", {
	onload(frm) {
		if (frm.is_new() && frm.fields_dict.custom_opened_date && !frm.doc.custom_opened_date) {
			frm.set_value("custom_opened_date", frappe.datetime.get_today());
		}
		if (frm.doc.customer && !frm.doc.custom_consignee) {
			sync_consignee_from_customer(frm);
		}
		toggle_project_transport_reference_fields(frm);
	},

	customer(frm) {
		sync_consignee_from_customer(frm);
	},

	refresh(frm) {
		toggle_project_transport_reference_fields(frm);

		if (frm.doc.custom_shipment_status) {
			const indicator = project_clearance_indicator(frm.doc);
			if (indicator) {
				frm.page.set_indicator(indicator[0], indicator[1]);
			}
		}

		render_shipment_progress_chart(frm);

		setup_clearance_tasks_toolbar_button(frm);

		if (frm.doc.name && !frm.is_new()) {
			frm.add_custom_button(__("Clearance Tasks"), () => open_project_clearance_tasks(frm)).addClass("btn-primary");
			frm.add_custom_button(__("Container Tracker"), () => {
				frappe.set_route("List", "Container Tracker", { project: frm.doc.name });
			}, __("View"));
			frm.add_custom_button(__("Container Tracking Report"), () => {
				frappe.set_route("query-report", "Container Tracking Detail", {
					project: frm.doc.name,
				});
			}, __("View"));
			frm.add_custom_button(__("Daily Status"), () => {
				frappe.new_doc("Daily Status Update");
			}, __("View"));
			frm.add_custom_button(__("Seal Record"), () => {
				frappe.new_doc("Seal Record", { project: frm.doc.name });
			}, __("View"));
			frm.page.set_inner_btn_group_as_primary(__("View"));
		}

		if (frm.is_new() && frm.doc.project_name && frm.fields_dict.custom_cgm_ref_no) {
			if (!frm.doc.custom_cgm_ref_no) {
				frm.set_value("custom_cgm_ref_no", frm.doc.project_name);
			}
		}

	},

	project_name(frm) {
		if (frm.fields_dict.custom_cgm_ref_no && !frm.doc.custom_cgm_ref_no) {
			frm.set_value("custom_cgm_ref_no", frm.doc.project_name);
		}
	},

	custom_mode_of_transport(frm) {
		toggle_project_transport_reference_fields(frm);
	},

	custom_shipment_type(frm) {
		toggle_project_transport_reference_fields(frm);
	},

	custom_bill_of_lading(frm) {
		toggle_project_transport_reference_fields(frm);
	},
});
