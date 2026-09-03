frappe.ui.form.on("Opportunity", {
	onload(frm) {
		cgm_shipping.opportunity_shipment.init_intake_wizard(frm);
		if (!opportunity_awaiting_workflow_review(frm)) {
			run_opportunity_form_syncs(frm, { apply_pending_bl: true });
		}
		configure_opportunity_clients_documents_grid(frm);
		bind_opportunity_actions_render_complete(frm);
	},

	onload_post_render(frm) {
		cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	},

	before_save(frm) {
		if (!frm.doc.opportunity_from) {
			frm.set_value("opportunity_from", "Customer");
		}
	},

	after_save(frm) {
		cgm_shipping.opportunity_shipment.on_after_save(frm);
	},

	before_workflow_action(frm) {
		// Workflow already saved on the server; skip read-only syncs on the next refresh.
		frm._cgm_skip_readonly_sync = true;
	},

	refresh(frm) {
		if (frm.doc.docstatus > 0) {
			// Submitted Opportunity — show fields only; never run BL sync / clear logic.
			sync_opportunity_transport_and_containers(frm);
			cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
			configure_opportunity_clients_documents_grid(frm);
			setup_opportunity_batch_autocomplete(frm);
			schedule_opportunity_inner_actions_menu(frm);
			hide_procurement_create_buttons(frm);
			return;
		}

		if (opportunity_awaiting_workflow_review(frm) && !frm._cgm_skip_readonly_sync) {
			run_opportunity_workflow_review_refresh(frm);
			return;
		}

		const skip_readonly_sync = frm._cgm_skip_readonly_sync;

		if (skip_readonly_sync) {
			sync_opportunity_transport_and_containers(frm);
			setup_opportunity_bill_of_lading_create(frm);
		} else {
			run_opportunity_form_syncs(frm, {
				apply_pending_bl: !frm._cgm_skip_pending_bl_on_refresh,
			});
			frm._cgm_skip_pending_bl_on_refresh = false;
		}

		setup_opportunity_batch_autocomplete(frm);
		schedule_opportunity_inner_actions_menu(frm);
		hide_procurement_create_buttons(frm);
	},

	after_workflow_action(frm) {
		frm._cgm_skip_readonly_sync = false;
		invalidate_opportunity_bl_sync(frm);
		restore_opportunity_clean_state(frm);
		schedule_opportunity_inner_actions_menu(frm);
		hide_procurement_create_buttons(frm);
	},

	workflow_state(frm) {
		schedule_opportunity_inner_actions_menu(frm);
		hide_procurement_create_buttons(frm);
	},

	custom_shipment_type(frm) {
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},

	party_name(frm) {
		sync_opportunity_consignee_from_customer(frm, { force_show: true });
	},

	custom_cargo_type(frm) {
		sync_opportunity_transport_and_containers(frm);
	},

	party_name(frm) {
		setup_opportunity_batch_autocomplete(frm);
	},

	custom_bill_of_lading(frm) {
		sync_opportunity_transport_and_containers(frm);
		sync_bl_propagation_from_link(frm, { silent: true });
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},

	custom_air_waybill(frm) {
		cgm_shipping.opportunity_shipment.sync_from_linked_awb(frm);
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},

	custom_clearance_station(frm) {
		cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	},

	custom_station_code(frm) {
		cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	},

	custom_booking_confirmation(frm) {
		cgm_shipping.opportunity_shipment.sync_from_linked_booking(frm);
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
	},
});

function opportunity_awaiting_workflow_review(frm) {
	return (frm.doc.workflow_state || "").trim() === "Pending Approval";
}

function run_opportunity_workflow_review_refresh(frm) {
	configure_opportunity_clients_documents_grid(frm);
	cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm, { skip_writes: true });
	if (cgm_shipping?.attachment_approval?.refresh) {
		cgm_shipping.attachment_approval.refresh(frm);
	}
	setup_opportunity_batch_autocomplete(frm);
	schedule_opportunity_inner_actions_menu(frm);
	hide_procurement_create_buttons(frm);
}

const CGM_OPPORTUNITY_ACTIONS = __("Actions");

function bind_opportunity_actions_render_complete(frm) {
	if (frm._cgm_opp_actions_render_bound) {
		return;
	}
	frm._cgm_opp_actions_render_bound = true;
	$(frm.wrapper).on("render_complete.cgm_opp_inner_actions", () => {
		schedule_opportunity_inner_actions_menu(frm);
	});
}

function configure_opportunity_workflow_actions(frm) {
	if (frm._cgm_opp_workflow_actions_configured || !frm.states) {
		return;
	}
	frm._cgm_opp_workflow_actions_configured = true;

	const states = frm.states;
	const original_show_actions = states.show_actions.bind(states);
	states.show_actions = function () {
		if (this.frm.doctype !== "Opportunity") {
			return original_show_actions();
		}
		if (this.frm.doc.__islocal || this.frm.doc.__unsaved === 1) {
			return;
		}
		schedule_opportunity_inner_actions_menu(this.frm);
	};

	const original_setup_btn = states.setup_btn.bind(states);
	states.setup_btn = function (action_added) {
		if (this.frm.doctype === "Opportunity") {
			hide_opportunity_page_actions_menu(this.frm);
			return;
		}
		return original_setup_btn(action_added);
	};
}

function hide_opportunity_page_actions_menu(frm) {
	frm.page.clear_actions_menu();
	frm.page.hide_actions_menu();
	frm.page.btn_primary?.removeClass("hide");
	frm.page.clear_secondary_action();
}

function schedule_opportunity_inner_actions_menu(frm) {
	if (frm.is_new()) {
		return;
	}
	configure_opportunity_workflow_actions(frm);
	clearTimeout(frm._cgm_opp_actions_timer);
	frm._cgm_opp_actions_timer = setTimeout(() => build_opportunity_inner_actions_menu(frm), 50);
}

function is_current_opportunity_actions_build(frm, build_id) {
	return cur_frm === frm && build_id === frm._cgm_opp_actions_build_id;
}

function opportunity_workflow_transition_allowed(transition, frm) {
	const user = frappe.session.user;
	if (!frappe.user_roles.includes(transition.allowed)) {
		return false;
	}
	return (
		user === "Administrator" ||
		transition.allow_self_approval ||
		user !== frm.doc.owner
	);
}

function clear_opportunity_inner_actions_group(frm) {
	const $group = frm.page.get_inner_group_button?.(CGM_OPPORTUNITY_ACTIONS);
	if (!$group?.length) {
		return;
	}
	$group.find(".dropdown-menu .dropdown-item").remove();
	if (!$group.find(".dropdown-item").length) {
		$group.remove();
	}
}

function remove_opportunity_standalone_action_buttons(frm) {
	[
		__("Close"),
		__("Reopen"),
		__("Start Shipment"),
		__("View Project"),
		__("Approve"),
		__("Reject"),
		__("Return For Amendment"),
		__("Submit for Review"),
		__("Send for Review"),
		__("Review Documents"),
		__("Send Final Documents for Review"),
		__("Review Final Documents"),
	].forEach((label) => {
		frm.remove_custom_button(label);
		frm.remove_custom_button(label, CGM_OPPORTUNITY_ACTIONS);
	});
}

function add_opportunity_inner_action(frm, label, fn) {
	frm.add_custom_button(__(label), fn, CGM_OPPORTUNITY_ACTIONS);
}

function collect_opportunity_status_actions(frm) {
	const actions = [];
	if (!frm.perm[0]?.write || frm.doc.docstatus !== 0) {
		return actions;
	}
	if (frm.doc.status === "Open") {
		actions.push({
			label: __("Close"),
			action: () => {
				frm.set_value("status", "Closed");
				frm.save();
			},
		});
	} else {
		actions.push({
			label: __("Reopen"),
			action: () => {
				frm.set_value("lost_reasons", []);
				frm.set_value("status", "Open");
				frm.save();
			},
		});
	}
	return actions;
}

function collect_opportunity_workflow_actions(frm, transitions) {
	return transitions
		.filter((transition) => opportunity_workflow_transition_allowed(transition, frm))
		.map((transition) => ({
			label: transition.action,
			action: () => {
				if (
					frappe.workflow?.workflows?.[frm.doctype]?.enable_action_confirmation
				) {
					frappe.confirm(__("Are you sure you want to {0}?", [transition.action]), () =>
						frm.states?.handle_workflow_action(transition)
					);
					return;
				}
				frm.states?.handle_workflow_action(transition);
			},
		}));
}

function collect_opportunity_attachment_actions(state) {
	const actions = [];
	if (state.can_send) {
		const label =
			state.profiles?.length === 1
				? state.profiles[0].send_button_label
				: __("Send for Review");
		actions.push({
			label,
			action: (frm) => cgm_shipping.attachment_approval.open_send_dialog(frm),
		});
	}
	if (state.can_review) {
		const label =
			state.profiles?.find((profile) => profile.pending_count)?.review_button_label ||
			__("Review Documents");
		actions.push({
			label,
			action: (frm) => cgm_shipping.attachment_approval.open_review_dialog(frm),
		});
	}
	return actions;
}

async function collect_opportunity_start_shipment_actions(frm) {
	if (!frm.doc.name || frm.doc.opportunity_from !== "Customer") {
		return [];
	}
	const r = await frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment.get_start_shipment_readiness",
		args: { opportunity: frm.doc.name },
	});
	if (r.exc || !r.message) {
		return [];
	}
	const readiness = r.message;
	if (readiness.existing_project) {
		return [
			{
				label: __("View Project"),
				action: () => frappe.set_route("Form", "Project", readiness.existing_project),
			},
		];
	}
	const stage = (frm.doc.custom_intake_stage || "").trim();
	if (
		stage !== "authorization" &&
		stage !== "documents" &&
		stage !== "awaiting_primary"
	) {
		return [];
	}
	return [
		{
			label: __("Start Shipment"),
			action: () => cgm_shipping.opportunity_shipment.start_shipment(frm),
		},
	];
}

function paint_opportunity_inner_actions(frm, actions) {
	clear_opportunity_inner_actions_group(frm);
	actions.forEach(({ label, action }) => {
		add_opportunity_inner_action(frm, label, () => action(frm));
	});
	const $actions = frm.page.get_inner_group_button?.(CGM_OPPORTUNITY_ACTIONS);
	if ($actions?.length) {
		frm.page.inner_toolbar?.removeClass("hide");
		reposition_opportunity_actions_button(frm);
	}
}

function reposition_opportunity_actions_button(frm) {
	const $toolbar = frm.page.inner_toolbar;
	if (!$toolbar?.length) {
		return;
	}
	const fetchLabel = encodeURIComponent(__("Fetch Latest Exchange Rate"));
	const $fetch = $toolbar.find(`button[data-label="${fetchLabel}"]`);
	const $actions = frm.page.get_inner_group_button?.(CGM_OPPORTUNITY_ACTIONS);
	if ($fetch.length && $actions?.length) {
		$actions.insertAfter($fetch);
	}
}

async function build_opportunity_inner_actions_menu(frm) {
	if (cur_frm !== frm || frm.is_new() || frm.doc.__unsaved) {
		return;
	}

	const build_id = (frm._cgm_opp_actions_build_id || 0) + 1;
	frm._cgm_opp_actions_build_id = build_id;

	remove_opportunity_standalone_action_buttons(frm);
	hide_opportunity_page_actions_menu(frm);

	const transitions = await frappe.workflow.get_transitions(frm.doc);
	if (!is_current_opportunity_actions_build(frm, build_id)) {
		return;
	}

	const attachment_state = frm.__cgm_attachment_state_promise
		? await frm.__cgm_attachment_state_promise
		: {};
	if (!is_current_opportunity_actions_build(frm, build_id)) {
		return;
	}

	const start_shipment_actions = await collect_opportunity_start_shipment_actions(frm);
	if (!is_current_opportunity_actions_build(frm, build_id)) {
		return;
	}

	const actions = [
		...collect_opportunity_workflow_actions(frm, transitions),
		...collect_opportunity_status_actions(frm),
		...collect_opportunity_attachment_actions(attachment_state),
		...start_shipment_actions,
	];

	paint_opportunity_inner_actions(frm, actions);
}

frappe.ui.form.on("Shipment Document", {
	custom_clients_documents_add(frm, cdt, cdn) {
		// Upload metadata is stamped when draft/final attachments change.
	},
});

function sync_opportunity_consignee_from_customer(frm, opts = {}) {
	if (!frm.fields_dict.custom_consignee) {
		return;
	}
	if (opts.force_show || frm.doc.party_name) {
		frm.set_df_property("custom_consignee", "hidden", 0);
		frm.toggle_display("custom_consignee", true);
	}
	if ((frm.doc.opportunity_from || "Customer") !== "Customer" || !frm.doc.party_name) {
		return;
	}
	frappe.db.get_value("Customer", frm.doc.party_name, "customer_name", (values) => {
		const label = values?.customer_name || frm.doc.party_name;
		if (frm.doc.custom_consignee !== label) {
			frm.set_value("custom_consignee", label);
		}
	});
}

function run_opportunity_form_syncs(frm, opts = {}) {
	register_clients_documents_remove_handler(frm);
	configure_opportunity_clients_documents_grid(frm);
	setup_opportunity_bill_of_lading_create(frm);
	cgm_shipping.opportunity_shipment.init_intake_wizard(frm, { defer_refresh: true });
	sync_opportunity_consignee_from_customer(frm, { force_show: true });

	// Pending transport-doc redirects only apply to the saved Opportunity they came from.
	if (!frm.is_new()) {
		if (opts.apply_pending_bl) {
			apply_pending_bl_from_submit(frm);
		}
		cgm_shipping.opportunity_shipment.apply_pending_awb_from_submit(frm);
		cgm_shipping.opportunity_shipment.apply_pending_booking_from_submit(frm);
		cgm_shipping.opportunity_shipment.sync_from_linked_booking(frm);
		cgm_shipping.opportunity_shipment.sync_from_linked_awb(frm);
		sync_bl_from_clients_documents(frm, { silent: true });
		const bl_link_field = get_opportunity_bl_link_field(frm);
		if (frm.doc[bl_link_field]) {
			sync_bl_propagation_from_link(frm, { silent: true });
			sync_opportunity_transport_and_containers(frm);
			if (cgm_shipping?.bl_containers?.schedule_sync) {
				cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
			}
		}
	}

	cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm).then(() => {
		cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	});
}

function row_has_shipment_document_file(row) {
	if (!row) {
		return false;
	}
	const draft_field = typeof cgm_draft_document_field === "function" ? cgm_draft_document_field() : null;
	const draft = draft_field ? row[draft_field] : null;
	return Boolean(row.final_attachment || draft || row.attachment);
}

function configure_opportunity_clients_documents_grid(frm) {
	const docs_field = get_clients_documents_field(frm);
	if (!docs_field || !frm.fields_dict[docs_field]?.grid) {
		return;
	}
	if (cgm_hydrate_legacy_document_rows(frm, docs_field)) {
		frm.refresh_field(docs_field);
	}
	cgm_configure_shipment_document_grid(frm.fields_dict[docs_field].grid);
	cgm_sync_shipment_document_rows_on_refresh(frm, docs_field);
}

function invalidate_opportunity_bl_sync(frm) {
	frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1;
}

function restore_opportunity_clean_state(frm) {
	cgm_shipping.bl_containers.restore_clean_form_state?.(frm);
}

function meta_has_field(doctype, fieldname) {
	const meta = doctype && frappe.get_meta(doctype);
	return Boolean(meta && (meta.fields || []).some((df) => df.fieldname === fieldname));
}

function get_clients_documents_field(frm) {
	if (frm.meta.has_field("custom_clients_documents")) {
		return "custom_clients_documents";
	}
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype === "Table" && df.options === "Shipment Document") {
			return df.fieldname;
		}
	}
	return null;
}

function is_bl_document_type(document_type) {
	if (!document_type) {
		return false;
	}
	const name = String(document_type).toLowerCase();
	return name === "bl" || name.includes("bill of lading");
}

function find_bl_clients_document_row(frm) {
	const docs_field = get_clients_documents_field(frm);
	if (!docs_field) {
		return null;
	}
	const rows = frm.doc[docs_field] || [];
	return (
		rows.find((row) => row_has_shipment_document_file(row) && is_bl_document_type(row.document_type)) ||
		rows.find((row) => row_has_shipment_document_file(row)) ||
		null
	);
}

function get_link_field_for_doctype(frm, linked_doctype) {
	if (!linked_doctype) {
		return null;
	}
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype === "Link" && df.options === linked_doctype) {
			return df.fieldname;
		}
	}
	return null;
}

function linked_doctype_has_container_table(doctype) {
	const meta = frappe.get_meta(doctype);
	if (!meta) {
		return false;
	}
	return meta.fields.some((df) => {
		if (df.fieldtype !== "Table") {
			return false;
		}
		return meta_has_field(df.options, "container_number");
	});
}

function get_opportunity_bl_link_field(frm) {
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype !== "Link" || !df.options) {
			continue;
		}
		if (linked_doctype_has_container_table(df.options)) {
			return df.fieldname;
		}
	}
	return null;
}

function get_container_table_field(frm) {
	for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
		if (df.fieldtype !== "Table") {
			continue;
		}
		if (meta_has_field(df.options, "container_number")) {
			return df.fieldname;
		}
	}
	return null;
}

function get_quantity_field(frm, bl_link_field) {
	if (!bl_link_field) {
		return null;
	}
	const fields = frappe.meta.get_docfields(frm.doctype, frm.doc.name);
	const start = fields.findIndex((df) => df.fieldname === bl_link_field);
	if (start < 0) {
		return null;
	}
	for (let i = start + 1; i < fields.length; i++) {
		const df = fields[i];
		if (df.fieldtype === "Section Break" || df.fieldtype === "Tab Break") {
			break;
		}
		if (df.fieldtype === "Table") {
			break;
		}
		if (["Data", "Float", "Int"].includes(df.fieldtype)) {
			return df.fieldname;
		}
	}
	return null;
}

function find_populate_containers_row(frm) {
	return find_bl_clients_document_row(frm);
}

function get_opportunity_cargo_type_field(frm) {
	if (frm.fields_dict.custom_cargo_type) {
		return "custom_cargo_type";
	}
	if (frm.fields_dict.custom_cargo_type_) {
		return "custom_cargo_type_";
	}
	return null;
}

function set_opportunity_bl_field(frm, fieldname, value) {
	if (value == null || value === "") {
		return;
	}
	if (frm.fields_dict[fieldname]) {
		frm.set_value(fieldname, value);
		frm.refresh_field(fieldname);
		return;
	}
	frm.doc[fieldname] = value;
	if (frm.doc.name && !frm.is_new()) {
		frappe.model.set_value(frm.doctype, frm.doc.name, fieldname, value);
	}
}

function apply_bl_classification_fields(frm, data) {
	if (!data) {
		return;
	}
	if (data.shipment_type) {
		set_opportunity_bl_field(frm, "custom_shipment_type", data.shipment_type);
	}
	if (data.default_mode_of_transport) {
		set_opportunity_bl_field(frm, "custom_mode_of_transport", data.default_mode_of_transport);
	}
	const cargo_type_field = get_opportunity_cargo_type_field(frm);
	if (data.cargo_type && cargo_type_field) {
		set_opportunity_bl_field(frm, cargo_type_field, data.cargo_type);
	}

	const tracking_fields = [
		["client_refrence_no", "custom_client_refrence_no"],
		["batch_no", "custom_batch_no"],
	];
	for (const [src, dest] of tracking_fields) {
		if (data[src] != null && data[src] !== "") {
			set_opportunity_bl_field(frm, dest, data[src]);
		}
	}

	const detail_fields = [
		"custom_description_of_goods",
		"custom_number_of_packages",
		"custom_package_type",
		// Confirmed shipping / cargo — Opportunity stays the latest shipment record.
		"custom_shipping_line",
		"custom_vessel",
		"custom_etd",
		"custom_eta",
		"custom_port_of_loading",
		"custom_port_of_discharge",
		"custom_voyage_number",
		"custom_gross_weight",
		"custom_weight_nw",
		"custom_weight_uom_",
	];
	detail_fields.forEach((fieldname) => {
		if (data[fieldname] != null && data[fieldname] !== "") {
			set_opportunity_bl_field(frm, fieldname, data[fieldname]);
		}
	});
}

function apply_bl_propagation_data(frm, data) {
	if (!data) {
		return;
	}
	const bl_link_field = get_opportunity_bl_link_field(frm);
	const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;

	apply_bl_classification_fields(frm, data);
	if (
		quantity_field &&
		data.quantity != null &&
		String(frm.doc[quantity_field] ?? "") !== String(data.quantity ?? "")
	) {
		set_opportunity_bl_field(frm, quantity_field, data.quantity || "");
	}
}

function sync_bl_propagation_from_link(frm, opts = {}) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const bl_link_field = get_opportunity_bl_link_field(frm);
	const bl_name = bl_link_field && frm.doc[bl_link_field];
	if (!bl_name) {
		return;
	}

	const sync_id = (frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1);

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_containers_for_bl_attachment",
		args: { attachment: bl_name },
		callback(r) {
			if (sync_id !== frm._cgm_bl_sync_id || cur_frm !== frm) {
				return;
			}
			if (r.exc || !r.message) {
				return;
			}
			apply_bl_propagation_data(frm, r.message);
			if (opts.silent) {
				restore_opportunity_clean_state(frm);
			}
		},
	});
}


// ─── Clients Documents remove handler ─────────────────────────────────────────

function register_clients_documents_remove_handler(frm) {
	const docs_field = get_clients_documents_field(frm);
	if (!docs_field || frm.__cgm_docs_remove_registered) {
		return;
	}
	frm.__cgm_docs_remove_registered = true;

	frappe.ui.form.on("Opportunity", {
		[docs_field + "_remove"](frm) {
			on_clients_documents_removed(frm);
		},
	});
}

function on_clients_documents_removed(frm) {
	const bl_row = find_populate_containers_row(frm);
	if (bl_row) {
		fetch_and_apply_bl_data(frm, bl_row);
		return;
	}
	clear_bl_derived_opportunity_fields(frm);
}


// ─── Transport & container sync ───────────────────────────────────────────────

function sync_opportunity_transport_and_containers(frm) {
	const bl_link_field = get_opportunity_bl_link_field(frm);
	cgm_shipping.transport_reference.toggle_cargo_type(frm, {
		bill_of_lading: bl_link_field || "custom_bill_of_lading",
		container_type: "custom_container_type_",
	});
}

function setup_opportunity_batch_autocomplete(frm) {
	const fieldname = "custom_batch_no";
	if (!frm.fields_dict[fieldname]) {
		return;
	}
	const customer =
		frm.doc.opportunity_from === "Customer" ? frm.doc.party_name : frm.doc.customer;
	if (!customer) {
		return;
	}
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.doctype.bill_of_lading.bill_of_lading.get_customer_batch_numbers",
		args: { customer },
		callback(r) {
			const options = (r.message || []).join("\n");
			frm.set_df_property(fieldname, "options", options);
			const df = frm.get_field(fieldname)?.df;
			if (df && df.fieldtype === "Data") {
				frm.set_df_property(fieldname, "fieldtype", "Autocomplete");
			}
			frm.refresh_field(fieldname);
		},
	});
}


// ─── Bill of Lading create route ──────────────────────────────────────────────

function is_saved_opportunity_name(name) {
	return Boolean(name && !String(name).startsWith("new-"));
}

function setup_opportunity_bill_of_lading_create(frm) {
	const bl_link_field = get_opportunity_bl_link_field(frm);
	const df = bl_link_field && frm.get_docfield(bl_link_field);
	if (!df || frm._cgm_bl_create_route_setup) {
		return;
	}

	frm._cgm_bl_create_route_setup = true;
	df.get_route_options_for_new_doc = () => {
		const opts = {};
		if (frm.doc.name) {
			localStorage.setItem("cgm_return_opportunity", frm.doc.name);
			localStorage.setItem("cgm_bl_seed_opportunity", frm.doc.name);
		}
		if (is_saved_opportunity_name(frm.doc.name)) {
			const linked_doctype = df.options;
			if (linked_doctype) {
				const linked_meta = frappe.get_meta(linked_doctype);
				const opp_link_field = linked_meta?.fields?.find(
					(field) =>
						field.fieldtype === "Link" &&
						field.options === frm.doctype
				);
				if (opp_link_field) {
					opts[opp_link_field.fieldname] = frm.doc.name;
				}
			}
			opts.linked_opportunity = frm.doc.name;
			// FCL batch is allocated on Booking/BL save — not from Opportunity.
			if (frm.doc.party_name) {
				opts.customer = frm.doc.party_name;
			}
			if (frm.doc.custom_shipment_type) {
				opts.shipment_type = frm.doc.custom_shipment_type;
			}
			const cargo_field = get_opportunity_cargo_type_field(frm);
			if (cargo_field && frm.doc[cargo_field]) {
				opts.cargo_type = frm.doc[cargo_field];
			}
			// Prefill planned → confirmed path when Booking already exists.
			if (frm.doc.custom_booking_confirmation) {
				opts.booking_confirmation = frm.doc.custom_booking_confirmation;
			}
		}
		return opts;
	};
}


// ─── Pending BL from submit ───────────────────────────────────────────────────

function apply_pending_bl_from_submit(frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}

	let pending;
	try {
		pending = JSON.parse(localStorage.getItem("cgm_pending_bl_link") || "null");
	} catch {
		return;
	}

	if (!pending || pending.opportunity !== frm.doc.name) {
		return;
	}

	const bl_link_field =
		get_link_field_for_doctype(frm, pending.linked_doctype) ||
		get_opportunity_bl_link_field(frm);
	const docs_field = get_clients_documents_field(frm);

	if (pending.bl_name && bl_link_field && frm.doc[bl_link_field] !== pending.bl_name) {
		frm.set_value(bl_link_field, pending.bl_name);
	}
	apply_bl_propagation_data(frm, pending);
	if (pending.attachment && docs_field && pending.document_type) {
		prepend_opportunity_bl_client_document(frm, pending, docs_field);
	}
	if (cgm_shipping?.bl_containers?.schedule_sync) {
		cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
	}

	localStorage.removeItem("cgm_pending_bl_link");
	frappe.show_alert({
		message: __("Bill of Lading {0} linked - continue completing this Opportunity.", [
			pending.bl_name,
		]),
		indicator: "green",
	});
}

function prepend_opportunity_bl_client_document(frm, pending, docs_field) {
	const rows = frm.doc[docs_field] || [];

	const draft_field = typeof cgm_draft_document_field === "function" ? cgm_draft_document_field() : null;
	const already_exists = rows.some((row) => {
		const draft = draft_field ? row[draft_field] : null;
		return (
			row.document_type === pending.document_type ||
			draft === pending.attachment ||
			row.attachment === pending.attachment
		);
	});
	if (already_exists) {
		return;
	}

	const bl_row = {
		document_type: pending.document_type,
		status: "Uploaded",
	};
	if (cgm_has_shipment_document_versioning()) {
		const draft_field = cgm_draft_document_field();
		if (draft_field) {
			bl_row[draft_field] = pending.attachment;
		}
		bl_row.attachment = pending.attachment;
		bl_row.version_status = "Awaiting Final";
	} else {
		bl_row.attachment = pending.attachment;
	}

	frm.clear_table(docs_field);
	frm.add_child(docs_field, bl_row);
	rows.forEach((row) => {
		frm.add_child(docs_field, {
			document_type: row.document_type,
			attachment: row.attachment,
			draft_documents: row.draft_documents,
			final_attachment: row.final_attachment,
			draft_documents_uploaded_on: row.draft_documents_uploaded_on,
			draft_documents_uploaded_by: row.draft_documents_uploaded_by,
			final_document_uploaded_on: row.final_document_uploaded_on,
			final_document_uploaded_by: row.final_document_uploaded_by,
			version_status: row.version_status,
			status: row.status,
			uploaded_by: row.uploaded_by,
			uploaded_on: row.uploaded_on,
			verified_by: row.verified_by,
			verified_on: row.verified_on,
			remarks: row.remarks,
		});
	});
	frm.refresh_field(docs_field);
}


// ─── BL data sync (single API call) ───────────────────────────────────────────

function sync_bl_from_clients_documents(frm, opts = {}) {
	if (frm.doc.docstatus !== 0) {
		return;
	}

	const bl_link_field = get_opportunity_bl_link_field(frm);
	const bl_row = find_bl_clients_document_row(frm);

	if (!bl_row) {
		if (!bl_link_field || !frm.doc[bl_link_field]) {
			clear_bl_derived_opportunity_fields(frm);
		}
		return;
	}

	if (bl_link_field && frm.doc[bl_link_field]) {
		sync_bl_propagation_from_link(frm, opts);
		if (cgm_shipping?.bl_containers?.schedule_sync) {
			cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
		}
		return;
	}

	fetch_and_apply_bl_data(frm, bl_row, null, null, opts);
}

function fetch_and_apply_bl_data(frm, row, cdt, cdn, opts = {}) {
	const draft_field = typeof cgm_draft_document_field === "function" ? cgm_draft_document_field() : null;
	const draft = draft_field ? row[draft_field] : null;
	const file_ref = row.final_attachment || draft || row.attachment;
	if (!file_ref) {
		return;
	}

	const sync_id = (frm._cgm_bl_sync_id = (frm._cgm_bl_sync_id || 0) + 1);

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_containers_for_bl_attachment",
		args: { attachment: file_ref },
		callback(r) {
			if (sync_id !== frm._cgm_bl_sync_id || cur_frm !== frm) {
				return;
			}
			if (r.exc || !r.message) {
				return;
			}
			apply_bl_data_from_response(frm, row, cdt, cdn, r.message, opts);
		},
	});
}

const BL_CONTAINER_COMPARE_FIELDS = [
	"container_number",
	"cargo_size",
	"no_container",
	"seal_no",
];

function opportunity_container_rows_match(existing, incoming) {
	existing = existing || [];
	incoming = incoming || [];
	if (existing.length !== incoming.length) {
		return false;
	}
	return incoming.every((row, i) =>
		BL_CONTAINER_COMPARE_FIELDS.every(
			(field) => String(existing[i]?.[field] ?? "") === String(row[field] ?? "")
		)
	);
}

function apply_bl_data_from_response(frm, row, cdt, cdn, data, opts = {}) {
	const silent = Boolean(opts.silent);
	const bl_link_field = get_link_field_for_doctype(frm, row.linked_doctype);
	const container_field = get_container_table_field(frm);
	const bl_name = data.bl_name || "";
	const attachment = data.attachment || "";

	if (cdt && cdn) {
		const child = locals[cdt]?.[cdn];
		if (child && child.attachment !== attachment) {
			if (cgm_has_shipment_document_versioning()) {
				const draft_field = cgm_draft_document_field();
				if (draft_field) {
					frappe.model.set_value(cdt, cdn, draft_field, attachment);
				}
			}
			frappe.model.set_value(cdt, cdn, "attachment", attachment);
		}
	} else if (row.name) {
		const child = locals[row.doctype]?.[row.name];
		if (child && child.attachment !== attachment) {
			if (cgm_has_shipment_document_versioning()) {
				const draft_field = cgm_draft_document_field();
				if (draft_field) {
					frappe.model.set_value(row.doctype, row.name, draft_field, attachment);
				}
			}
			frappe.model.set_value(row.doctype, row.name, "attachment", attachment);
		}
	}

	if (bl_link_field && bl_name && frm.doc[bl_link_field] !== bl_name) {
		frm.set_value(bl_link_field, bl_name);
	}
	apply_bl_propagation_data(frm, data);

	if (
		container_field &&
		!opportunity_container_rows_match(frm.doc[container_field], data.containers)
	) {
		frm.clear_table(container_field);
		(data.containers || []).forEach((container) => {
			Object.assign(frm.add_child(container_field), container);
		});
		frm.refresh_field(container_field);
	}

	if (silent) {
		restore_opportunity_clean_state(frm);
	}
}

function clear_bl_derived_opportunity_fields(frm) {
	const bl_link_field = get_opportunity_bl_link_field(frm);
	const container_field = get_container_table_field(frm);
	const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;
	const tracking_fields = [
		"custom_client_refrence_no",
		"custom_batch_no",
	];

	if (container_field && (frm.doc[container_field] || []).length) {
		frm.clear_table(container_field);
		frm.refresh_field(container_field);
	}
	if (quantity_field && frm.doc[quantity_field]) {
		frm.set_value(quantity_field, "");
	}
	for (const fieldname of tracking_fields) {
		if (frm.fields_dict[fieldname] && frm.doc[fieldname]) {
			frm.set_value(fieldname, "");
		}
	}
	if (bl_link_field && frm.doc[bl_link_field]) {
		frm.set_value(bl_link_field, "");
	}
}

function hide_procurement_create_buttons(frm) {
	const remove = () => {
		frm.remove_custom_button(__("Supplier Quotation"), __("Create"));
		frm.remove_custom_button(__("Request For Quotation"), __("Create"));
	};
	remove();
	[50, 200, 600, 1000, 1500].forEach((delay) => setTimeout(remove, delay));
}

frappe.provide("cgm_shipping.opportunity_menu");

cgm_shipping.opportunity_menu = {
	paint: schedule_opportunity_inner_actions_menu,
	hide_procurement: hide_procurement_create_buttons,
};
