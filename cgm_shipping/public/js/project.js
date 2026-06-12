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
	const mode = frm.doc.custom_mode_of_transport;
	const hide_awb = mode === "Sea";
	const hide_bl = mode === "Air";

	if (frm.fields_dict.custom_awb_number) {
		frm.toggle_display("custom_awb_number", !hide_awb);
	}
	if (frm.fields_dict.custom_bill_of_lading) {
		frm.toggle_display("custom_bill_of_lading", !hide_bl);
	}
	if (frm.fields_dict.custom_container_information) {
		frm.toggle_display(
			"custom_container_information",
			!hide_bl && Boolean(frm.doc.custom_bill_of_lading)
		);
	}
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

function render_container_tracking_table(frm, dashboard) {
	const field = frm.get_field("custom_container_tracking_html");
	if (!field || !frm.doc.name) {
		return;
	}
	const rows = dashboard.containers || [];
	const overdue = dashboard.containers_overdue || 0;
	const pending = dashboard.containers_pending_empty || 0;
	const demurrage_total = dashboard.total_demurrage_amount || 0;
	const detention_total = dashboard.total_detention_amount || 0;

	let tableBody = "";
	if (!rows.length) {
		tableBody = `<tr><td colspan="12" class="text-muted">${__(
			"No containers yet. Create Container Tracker rows linked to this Project."
		)}</td></tr>`;
	} else {
		tableBody = rows
			.map((c) => {
				const statusClass =
					c.status === "Overdue"
						? "cgm-rag-red"
						: c.status === "Empty Returned"
							? "cgm-rag-green"
							: "cgm-rag-yellow";
				return `<tr>
					<td><a href="/app/container-tracker/${encodeURIComponent(c.name)}">${frappe.utils.escape_html(
						c.container_number || c.name
					)}</a></td>
					<td>${frappe.utils.escape_html(c.bl_number || "")}</td>
					<td title="${frappe.utils.escape_html(c.current_location || "")}">${frappe.utils.escape_html(
						(c.current_location || "").slice(0, 28)
					)}${(c.current_location || "").length > 28 ? "…" : ""}</td>
					<td><span class="${statusClass}">${frappe.utils.escape_html(c.status || "")}</span></td>
					<td class="text-right">${c.free_days != null ? c.free_days : ""}</td>
					<td class="text-right">${c.demurrage_days != null ? c.demurrage_days : ""}</td>
					<td class="text-right">${format_currency_amount(c.demurrage_amount)}</td>
					<td class="text-right">${c.detention_days != null ? c.detention_days : ""}</td>
					<td class="text-right">${format_currency_amount(c.detention_amount)}</td>
					<td>${frappe.utils.escape_html(c.gate_out_date_port || "")}</td>
					<td>${frappe.utils.escape_html(c.expected_empty_return || "")}</td>
					<td>${frappe.utils.escape_html(c.actual_empty_return || "")}</td>
				</tr>`;
			})
			.join("");
	}

	const exposureLine =
		demurrage_total || detention_total
			? `<span>${__("Est. demurrage")}: <b>${format_currency_amount(demurrage_total)}</b> · ${__(
					"Est. detention"
				)}: <b>${format_currency_amount(detention_total)}</b></span>`
			: "";

	field.$wrapper.html(`
		<div class="cgm-container-summary">
			<div class="cgm-container-summary-head">
				<span>${__("Container tracking")}</span>
				<span class="cgm-container-stats">
					${pending ? `<b>${pending}</b> ${__("empty pending")} · ` : ""}
					${overdue ? `<span class="cgm-rag-red"><b>${overdue}</b> ${__("overdue")}</span> · ` : ""}
					${exposureLine}
				</span>
				<button type="button" class="btn btn-default btn-xs cgm-open-tracking-report">${__(
					"Full Report"
				)}</button>
				<button type="button" class="btn btn-default btn-xs cgm-add-container">${__(
					"New Container"
				)}</button>
			</div>
			<div class="cgm-container-table-scroll">
				<table class="table table-bordered table-condensed">
					<thead>
						<tr>
							<th>${__("Container")}</th>
							<th>${__("B/L")}</th>
							<th>${__("Location")}</th>
							<th>${__("Status")}</th>
							<th>${__("Free")}</th>
							<th>${__("Dem. Days")}</th>
							<th>${__("Dem. Amt")}</th>
							<th>${__("Det. Days")}</th>
							<th>${__("Det. Amt")}</th>
							<th>${__("Gate Out")}</th>
							<th>${__("Expected")}</th>
							<th>${__("Returned")}</th>
						</tr>
					</thead>
					<tbody>${tableBody}</tbody>
				</table>
			</div>
		</div>
	`);

	field.$wrapper.find(".cgm-open-tracking-report").on("click", () => {
		frappe.set_route("query-report", "Container Tracking Detail", { project: frm.doc.name });
	});

	field.$wrapper.find(".cgm-add-container").on("click", () => {
		frappe.new_doc("Container Tracker", {
			project: frm.doc.name,
			bl_number: frm.doc.custom_bill_of_lading || frm.doc.custom_bl_number,
			eta: frm.doc.custom_eta,
			shipping_line: frm.doc.custom_shipping_line,
		});
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

	custom_bill_of_lading(frm) {
		toggle_project_transport_reference_fields(frm);
	},
});
