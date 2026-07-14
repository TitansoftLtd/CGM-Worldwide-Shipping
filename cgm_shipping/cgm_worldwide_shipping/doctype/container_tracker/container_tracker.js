// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const CGM_CONTAINER_TRACKING_TASK_KEY = "cgm_container_tracking_task";
const CGM_CONTAINER_TRACKING_PROJECT_KEY = "cgm_container_tracking_project";

const MODE_SECTIONS = {
	"Mombasa Port": [
		"section_identity",
		"section_dates",
		"section_mombasa",
		"section_warehouse",
		"section_transport",
		"section_shipping_line_free_days",
		"section_kpa_free_days",
		"section_empty_return",
	],
	"ICD Nairobi": [
		"section_identity",
		"section_dates",
		"section_icd",
		"section_warehouse",
		"section_transport",
		"section_shipping_line_free_days",
		"section_kpa_free_days",
		"section_empty_return",
	],
	"Transit Kenya→Border": [
		"section_identity",
		"section_dates",
		"section_transit",
		"section_warehouse",
		"section_transport",
		"section_shipping_line_free_days",
		"section_kpa_free_days",
		"section_empty_return",
	],
	"Transit Border→Kenya": [
		"section_identity",
		"section_dates",
		"section_transit",
		"section_warehouse",
		"section_transport",
		"section_shipping_line_free_days",
		"section_kpa_free_days",
		"section_empty_return",
	],
	Export: [
		"section_identity",
		"section_dates",
		"section_transport",
		"section_shipping_line_free_days",
		"section_kpa_free_days",
		"section_empty_return",
	],
};

function lock_transport_assignment_fields(frm) {
	const can_override =
		frappe.user.has_role("System Manager") || frappe.user.has_role("Operations Manager");
	["transporter", "truck_number", "driver_name", "driver_contact"].forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "read_only", can_override ? 0 : 1);
		}
	});
}

function apply_container_mode_layout(frm) {
	const mode = frm.doc.container_mode || "Mombasa Port";
	const show = new Set(MODE_SECTIONS[mode] || MODE_SECTIONS["Mombasa Port"]);
	Object.keys(frm.fields_dict).forEach((fn) => {
		const f = frm.fields_dict[fn];
		if (!f || f.df.fieldtype !== "Section Break") {
			return;
		}
		if (fn.startsWith("section_")) {
			frm.set_df_property(fn, "hidden", show.has(fn) ? 0 : 1);
		}
	});
}

function fetch_bl_container_options(bill_of_lading) {
	return new Promise((resolve, reject) => {
		if (!bill_of_lading) {
			resolve([]);
			return;
		}
		frappe.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_bl_container_select_options",
			args: { bill_of_lading },
			callback(r) {
				if (r.exc) {
					reject(r.exc);
					return;
				}
				resolve(r.message || []);
			},
			error: reject,
		});
	});
}

function update_bl_container_select_options(frm, options) {
	if (!frm.fields_dict.custom_bl_container_select) {
		return false;
	}

	const values = (options || []).map((o) => o.value).filter(Boolean);
	const options_str = ["", ...values].join("\n");
	const df = frappe.meta.get_docfield(frm.doctype, "custom_bl_container_select", frm.doc.name);
	if (df) {
		df.options = options_str;
	}

	frm.set_df_property("custom_bl_container_select", "options", options_str);
	frm.refresh_field("custom_bl_container_select");

	if (!values.length) {
		frappe.show_alert({
			message: __("No containers found on this Bill of Lading"),
			indicator: "orange",
		});
	}
	return true;
}

function render_bl_containers_preview(frm, options) {
	const field = frm.get_field("custom_bl_container_select");
	if (!field?.$wrapper) {
		return;
	}

	field.$wrapper.find(".cgm-bl-containers-preview").remove();
	if (!options?.length) {
		return;
	}

	const rows = options
		.map(
			(o) =>
				`<tr data-container="${frappe.utils.escape_html(o.value)}"><td><a href="#" class="cgm-pick-container">${frappe.utils.escape_html(o.label)}</a></td></tr>`
		)
		.join("");

	const html = `<div class="cgm-bl-containers-preview" style="margin-top:8px;">
		<label class="control-label">${__("Containers on this B/L")}</label>
		<table class="table table-bordered table-sm"><tbody>${rows}</tbody></table>
	</div>`;

	field.$wrapper.append(html);
	field.$wrapper.find(".cgm-pick-container").on("click", (e) => {
		e.preventDefault();
		const container = $(e.currentTarget).closest("tr").data("container");
		frm.set_value("custom_bl_container_select", container);
	});
}

function when_bl_container_field_ready(frm, callback) {
	if (frm.fields_dict.custom_bl_container_select) {
		callback();
		return;
	}
	if (!frm.doc.custom_bill_of_lading) {
		return;
	}

	let attempts = 0;
	const try_ready = () => {
		// Stop retrying if the user has navigated away from this form.
		if (cur_frm !== frm) {
			return;
		}
		attempts += 1;
		frm.refresh_field("custom_bl_container_select");
		if (frm.fields_dict.custom_bl_container_select) {
			callback();
			return;
		}
		if (attempts < 12) {
			setTimeout(try_ready, 100);
		}
	};
	setTimeout(try_ready, 50);
}

function sync_bl_container_pick_list(frm) {
	const bl = frm.doc.custom_bill_of_lading;
	if (!bl) {
		return Promise.resolve();
	}

	return fetch_bl_container_options(bl).then((options) => {
		when_bl_container_field_ready(frm, () => {
			update_bl_container_select_options(frm, options);
			render_bl_containers_preview(frm, options);
			if (
				frm.doc.custom_bl_container_select &&
				!options.some((o) => o.value === frm.doc.custom_bl_container_select)
			) {
				frm.set_value("custom_bl_container_select", null);
			}
		});
	});
}

function apply_selected_bl_container(frm) {
	const picked = frm.doc.custom_bl_container_select;
	if (!picked) {
		return;
	}
	if (frm.doc.container_number !== picked) {
		frm.set_value("container_number", picked);
	}
	if (frm.doc.custom_bill_of_lading && frm.doc.bl_number !== frm.doc.custom_bill_of_lading) {
		frm.set_value("bl_number", frm.doc.custom_bill_of_lading);
	}
}

function apply_container_tracker_route_defaults(frm) {
	const opts = frappe.route_options || {};
	if (opts.project && !frm.doc.project) {
		frm.set_value("project", opts.project);
	}
	if (opts.custom_bill_of_lading && !frm.doc.custom_bill_of_lading) {
		frm.set_value("custom_bill_of_lading", opts.custom_bill_of_lading);
	}
	if (opts.eta && !frm.doc.eta) {
		frm.set_value("eta", opts.eta);
	}
	frappe.route_options = null;
}

function prompt_track_next_container(frm) {
	const project = frm.doc.project || localStorage.getItem(CGM_CONTAINER_TRACKING_PROJECT_KEY);
	const bl = frm.doc.custom_bill_of_lading;
	const task_name = localStorage.getItem(CGM_CONTAINER_TRACKING_TASK_KEY);

	const open_another = () => {
		frappe.model.with_doctype("Container Tracker", () => {
			const doc = frappe.model.get_new_doc("Container Tracker");
			doc.project = project;
			doc.custom_bill_of_lading = bl;
			doc.bl_number = bl;
			doc.eta = frm.doc.eta;
			frappe.set_route("Form", "Container Tracker", doc.name);
		});
	};

	const return_to_task = () => {
		if (task_name) {
			localStorage.removeItem(CGM_CONTAINER_TRACKING_TASK_KEY);
			localStorage.removeItem(CGM_CONTAINER_TRACKING_PROJECT_KEY);
			frappe.set_route("Form", "Task", task_name);
			return;
		}
		if (project) {
			frappe.set_route("Form", "Project", project);
		}
	};

	frappe.confirm(
		__(
			"Container <b>{0}</b> saved. Track another container from the same Bill of Lading?",
			[frm.doc.container_number]
		),
		open_another,
		return_to_task
	);
}

function render_container_tracker_alerts(frm) {
	frm.dashboard.clear_comment();
	const d = frm.doc;
	let alert = null;

	if ((d.free_days_end_date || d.free_days_start_date) && !d.gate_out_date_port) {
		const today = frappe.datetime.get_today();
		if (d.free_days_end_date) {
			const remaining = frappe.datetime.get_diff(d.free_days_end_date, today);
			if (remaining < 0) {
				const overdue = Math.abs(remaining);
				alert = {
					msg: __(
						"Demurrage accruing — {0} day(s) past the free period end date",
						[overdue]
					),
					color: "red",
				};
			} else if (remaining <= 2) {
				alert = {
					msg: __(
						"Free days expiring — only {0} day(s) remaining before demurrage starts",
						[remaining]
					),
					color: "orange",
				};
			}
		} else {
			alert = {
				msg: __(
					"Enter <b>Shipping Line Free Day End Date</b> after discharge so demurrage/detention can be tracked."
				),
				color: "orange",
			};
		}
	}

	const return_done = d.interchange_date || d.actual_empty_return;
	if (d.expected_empty_return && !return_done) {
		const diff = frappe.datetime.get_diff(
			frappe.datetime.get_today(),
			d.expected_empty_return
		);
		if (diff > 0) {
			alert = {
				msg: __(
					"Return overdue by {0} day(s) — contact transporter immediately. Demurrage/detention charges may be accruing.",
					[diff]
				),
				color: "red",
			};
		} else if (diff >= -3) {
			alert = {
				msg: __(
					"Container return due in {0} day(s) — arrange empty return now",
					[Math.abs(diff)]
				),
				color: "orange",
			};
		}
	} else if (d.expected_empty_return && return_done) {
		let effective_return = d.interchange_date || d.actual_empty_return;
		if (d.interchange_date && d.actual_empty_return) {
			effective_return =
				frappe.datetime.get_diff(d.interchange_date, d.actual_empty_return) >= 0
					? d.interchange_date
					: d.actual_empty_return;
		}
		const late = frappe.datetime.get_diff(effective_return, d.expected_empty_return);
		if (late > 0) {
			alert = {
				msg: __(
					"Returned late — {0} day(s) past the shipping-line free period end date",
					[late]
				),
				color: "orange",
			};
		}
	}

	if (alert) {
		frm.dashboard.add_comment(alert.msg, alert.color, true);
	}
}

function container_tracker_status_color(status) {
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

function apply_container_tracker_status_indicator(frm) {
	if (!frm.doc.status) {
		return;
	}
	frm.page.set_indicator(frm.doc.status, container_tracker_status_color(frm.doc.status));
}

frappe.ui.form.on("Container Tracker", {
	onload(frm) {
		apply_container_tracker_route_defaults(frm);
		if (frm.doc.custom_bill_of_lading) {
			sync_bl_container_pick_list(frm);
		}
		if (frm.is_new() && localStorage.getItem(CGM_CONTAINER_TRACKING_TASK_KEY)) {
			frm.set_intro(
				__(
					"Select the <b>Bill of Lading</b>, choose a <b>container</b> from the list, then fill in tracking dates and save."
				),
				"blue"
			);
		}
	},

	refresh(frm) {
		apply_container_mode_layout(frm);
		lock_transport_assignment_fields(frm);
		render_container_tracker_alerts(frm);
		apply_container_tracker_status_indicator(frm);
		render_container_tracker_truck_updates(frm);
		if (frm.doc.custom_bill_of_lading) {
			sync_bl_container_pick_list(frm);
		}
		if (frm.doc.project) {
			frm.add_custom_button(__("Open Project"), () => {
				frappe.set_route("Form", "Project", frm.doc.project);
			}).addClass("btn-primary");
		}
		const task_name = localStorage.getItem(CGM_CONTAINER_TRACKING_TASK_KEY);
		if (task_name) {
			frm.add_custom_button(__("Back to Task"), () => {
				frappe.set_route("Form", "Task", task_name);
			}, __("CGM"));
			frm.page.set_inner_btn_group_as_primary(__("CGM"));
		}
	},

	project(frm) {
		if (!frm.doc.project || frm.doc.custom_bill_of_lading) {
			return;
		}
		frappe.db.get_value("Project", frm.doc.project, "custom_bill_of_lading", (values) => {
			if (values?.custom_bill_of_lading) {
				frm.set_value("custom_bill_of_lading", values.custom_bill_of_lading);
			}
		});
	},

	custom_bill_of_lading(frm) {
		frm.set_value("custom_bl_container_select", null);
		const field = frm.get_field("custom_bl_container_select");
		field?.$wrapper?.find(".cgm-bl-containers-preview")?.remove();

		if (frm.doc.custom_bill_of_lading) {
			frm.set_value("bl_number", frm.doc.custom_bill_of_lading);
			sync_bl_container_pick_list(frm);
		} else if (frm.fields_dict.custom_bl_container_select) {
			update_bl_container_select_options(frm, []);
		}
	},

	custom_bl_container_select(frm) {
		apply_selected_bl_container(frm);
	},

	container_mode(frm) {
		apply_container_mode_layout(frm);
	},

	discharging_date(frm) {
		const discharge = frm.doc.discharging_date;
		if (!discharge) {
			return;
		}
		if (!frm.doc.free_days_start_date) {
			frm.set_value("free_days_start_date", discharge);
		}
		if (!frm.doc.kpa_free_days_start_date) {
			frm.set_value("kpa_free_days_start_date", discharge);
		}
	},

	before_save(frm) {
		frm._cgm_container_tracker_was_new = Boolean(frm.doc.__islocal);
	},

	after_save(frm) {
		if (!frm._cgm_container_tracker_was_new) {
			return;
		}
		if (
			!localStorage.getItem(CGM_CONTAINER_TRACKING_TASK_KEY) &&
			!localStorage.getItem(CGM_CONTAINER_TRACKING_PROJECT_KEY)
		) {
			return;
		}
		prompt_track_next_container(frm);
	},
});

function render_container_tracker_truck_updates(frm) {
	if (!frm.doc.name || frm.doc.__islocal) {
		return;
	}
	let section = frm.layout.wrapper.find(".cgm-tracker-truck-updates");
	if (!section.length) {
		section = $(`
			<div class="cgm-tracker-truck-updates form-section">
				<div class="section-head">${__("Transporter truck updates")}</div>
				<div class="cgm-tracker-truck-updates-body text-muted">${__("Loading…")}</div>
			</div>
		`);
		const transportSection = frm.fields_dict.section_transport;
		if (transportSection && transportSection.$wrapper) {
			section.insertAfter(transportSection.$wrapper);
		} else {
			section.prependTo(frm.layout.wrapper);
		}
	}

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_tracker_truck_updates",
		args: { container_tracker: frm.doc.name },
		callback(r) {
			const rows = r.message || [];
			const body = section.find(".cgm-tracker-truck-updates-body");
			if (!rows.length) {
				body.html(`<p class="text-muted" style="margin:0;">${__("No transporter updates yet.")}</p>`);
				return;
			}
			body.html(cgm.updates.renderList(rows));
			cgm.updates.bindListClicks(body);
		},
	});
}
