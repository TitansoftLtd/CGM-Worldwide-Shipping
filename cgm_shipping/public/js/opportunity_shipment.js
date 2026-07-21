frappe.provide("cgm_shipping.opportunity_shipment");

const CGM_RETURN_OPPORTUNITY_KEY = "cgm_return_opportunity";
const CGM_PENDING_BL_LINK_KEY = "cgm_pending_bl_link";
const CGM_PENDING_AWB_LINK_KEY = "cgm_pending_awb_link";
const CGM_PENDING_BOOKING_LINK_KEY = "cgm_pending_booking_link";
const CGM_AWB_SEED_OPPORTUNITY_KEY = "cgm_awb_seed_opportunity";

const STAGE_INTAKE = "intake";
const STAGE_AWAITING_PRIMARY = "awaiting_primary";
const STAGE_DOCUMENTS = "documents";
const STAGE_AUTHORIZATION = "authorization";

const TRANSPORT_DASHBOARD_STAGES = [
	STAGE_AWAITING_PRIMARY,
	STAGE_DOCUMENTS,
	STAGE_AUTHORIZATION,
];
const READINESS_STAGES = [STAGE_DOCUMENTS, STAGE_AUTHORIZATION];

const INTAKE_ALWAYS_VISIBLE_FIELDS = [
	"company",
	"transaction_date",
	"party_name",
	"custom_consignee",
	"custom_shipment_type",
	"custom_mode_of_transport",
	"custom_client_refrence_no",
	"custom_clearance_station",
	"custom_station_code",
];

const CLEARANCE_STATION_FIELDS = ["custom_clearance_station", "custom_station_code"];

cgm_shipping.opportunity_shipment.POST_BL_LAYOUT_FIELDS = [
	"custom_consignee",
	"custom_mode_of_transport",
	"column_break0",
	"custom_cargo_type_",
	"custom_batch_no",
	"custom_weight_uom_",
	"custom_weight_nw",
	"custom_gross_weight",
	"column_break_10",
	"custom_vessel",
	"custom_airline",
	"custom_port_of_loading",
	"custom_port_of_discharge",
	"custom_voyage_number",
	"custom_country_of_origin",
	"custom_draft_bl_number",
	"custom_eta",
	"custom_etd",
	"custom_cargo_cutoff",
	"custom_shipping_line",
	"custom_delivery_destination",
	"custom_handling_agent",
	"custom_section_break_5s7eg",
	"custom_description_of_goods",
	"custom_section_break_6qrpr",
	"custom_bill_of_lading",
	"custom_air_waybill",
	"custom_booking_confirmation",
	"custom_column_break_bbq21",
	"custom_quantity",
	"custom_number_of_packages",
	"custom_package_type",
	"custom_requested_cargo_quantity",
	"custom_section_break_idqn5",
	"custom_container_information",
	"custom_section_break_jyvyi",
	"custom_clients_documents",
];

cgm_shipping.opportunity_shipment.init_intake_wizard = function (frm, opts = {}) {
	cgm_shipping.opportunity_shipment._reset_new_opportunity_session(frm);
	cgm_shipping.opportunity_shipment._prepare_intake_defaults(frm);
	cgm_shipping.opportunity_shipment._configure_intake_form(frm);
	cgm_shipping.opportunity_shipment._ensure_intake_fields_visible(frm);
	cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	if (!opts.defer_refresh) {
		cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm).then(() => {
			cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
		});
	}
	cgm_shipping.opportunity_shipment.setup_start_shipment_button(frm);
};

/**
 * New Opportunity = clean intake session.
 * Drop leftover localStorage and stage-gated HTML from a previous BL/AWB/Booking flow.
 */
cgm_shipping.opportunity_shipment._reset_new_opportunity_session = function (frm) {
	if (!frm.is_new()) {
		return;
	}

	localStorage.removeItem(CGM_RETURN_OPPORTUNITY_KEY);
	localStorage.removeItem(CGM_PENDING_BL_LINK_KEY);
	localStorage.removeItem(CGM_PENDING_AWB_LINK_KEY);
	localStorage.removeItem(CGM_PENDING_BOOKING_LINK_KEY);

	if (frm.meta.has_field("custom_intake_stage")) {
		frm.doc.custom_intake_stage = STAGE_INTAKE;
	}
	if (frm.meta.has_field("custom_primary_doc_linked")) {
		frm.doc.custom_primary_doc_linked = 0;
	}
	if (frm.meta.has_field("custom_uses_container_tracking")) {
		frm.doc.custom_uses_container_tracking = 0;
	}

	// Paint Step 1 immediately so prior Opportunity HTML cannot flash.
	if (frm.fields_dict.custom_shipment_intake_wizard_html) {
		frm.get_field("custom_shipment_intake_wizard_html").html(
			cgm_shipping.opportunity_shipment._local_intake_wizard_html(STAGE_INTAKE)
		);
	}
	cgm_shipping.opportunity_shipment._clear_stage_gated_html(frm);
};

cgm_shipping.opportunity_shipment._local_intake_wizard_html = function (stage) {
	const steps = [
		[STAGE_INTAKE, __("1. Shipment Intake"), __("Customer & shipment type")],
		[STAGE_AWAITING_PRIMARY, __("2. Transport Documents"), __("Add documents as they arrive")],
		[STAGE_DOCUMENTS, __("3. Documents"), __("Transport info & verification")],
		[STAGE_AUTHORIZATION, __("4. Start Shipment"), __("Approve & create project")],
	];
	const completed = new Set();
	if (stage !== STAGE_INTAKE) {
		completed.add(STAGE_INTAKE);
	}
	if (stage === STAGE_DOCUMENTS || stage === STAGE_AUTHORIZATION) {
		completed.add(STAGE_AWAITING_PRIMARY);
	}
	if (stage === STAGE_AUTHORIZATION) {
		completed.add(STAGE_DOCUMENTS);
	}

	const parts = ['<div class="cgm-shipment-intake-wizard">'];
	steps.forEach(([key, title, subtitle]) => {
		let cls = "cgm-wizard-step";
		if (key === stage) {
			cls += " is-active";
		} else if (completed.has(key)) {
			cls += " is-done";
		}
		parts.push(
			`<div class="${cls}"><div class="cgm-wizard-step-title">${title}</div>` +
				`<div class="cgm-wizard-step-sub">${subtitle}</div></div>`
		);
	});
	parts.push("</div>");

	let message = "";
	if (stage === STAGE_INTAKE) {
		message = __("Select the customer and shipment type, then save to continue.");
	} else if (stage === STAGE_AWAITING_PRIMARY) {
		message = __(
			"Use <b>Transport Documents</b> below to add Bill of Lading, Booking Confirmation, or other transport documents as they become available."
		);
	}
	if (message) {
		parts.push(`<div class="cgm-shipment-intake-message">${message}</div>`);
	}
	return parts.join("");
};

cgm_shipping.opportunity_shipment._clear_stage_gated_html = function (frm) {
	if (frm.fields_dict.custom_transport_documents_html) {
		frm.get_field("custom_transport_documents_html").$wrapper.empty();
		frm.toggle_display("custom_transport_documents_html", false);
	}
	if (frm.fields_dict.custom_intake_readiness_html) {
		frm.get_field("custom_intake_readiness_html").html("");
		frm.toggle_display("custom_intake_readiness_html", false);
	}
};

cgm_shipping.opportunity_shipment._current_stage = function (frm) {
	return (frm.doc.custom_intake_stage || STAGE_INTAKE).trim() || STAGE_INTAKE;
};

cgm_shipping.opportunity_shipment._prepare_intake_defaults = function (frm) {
	if (!frm.doc.opportunity_from) {
		frm.set_value("opportunity_from", "Customer");
	}
	if (frm.is_new() && frm.meta.has_field("custom_intake_stage")) {
		frm.doc.custom_intake_stage = STAGE_INTAKE;
	}
	if (frm.is_new() && !frm.doc.transaction_date) {
		frm.set_value("transaction_date", frappe.datetime.get_today());
	}
	if (frm.is_new() && !frm.doc.company) {
		const company = frappe.defaults.get_user_default("Company");
		if (company) {
			frm.set_value("company", company);
		}
	}
	// Do not inherit site default Country (e.g. Kenya) — user must choose.
	if (frm.is_new()) {
		["custom_country_of_origin", "custom_delivery_destination"].forEach((fieldname) => {
			if (frm.meta.has_field(fieldname) && frm.doc[fieldname]) {
				frm.doc[fieldname] = null;
			}
		});
	}
};

cgm_shipping.opportunity_shipment._configure_intake_form = function (frm) {
	if (frm._cgm_intake_form_configured) {
		return;
	}
	frm._cgm_intake_form_configured = true;

	if (frm.is_new()) {
		frm.page.set_title(__("New Shipment Intake"));
	} else {
		frm.page.set_title(__("Shipment Intake"));
	}

	frm.set_query("party_name", () => {
		if (frm.doc.opportunity_from === "Customer") {
			return { query: "erpnext.controllers.queries.customer_query" };
		}
		return {};
	});

	cgm_shipping.opportunity_shipment._hide_crm_tabs(frm);
	cgm_shipping.opportunity_shipment.setup_shipping_line_query(frm);
	cgm_shipping.opportunity_shipment.setup_awb_create_route(frm);
	cgm_shipping.opportunity_shipment.setup_booking_create_route(frm);
};

cgm_shipping.opportunity_shipment._hide_crm_tabs = function (frm) {
	const hide = ["contacts_tab", "items_tab", "activities_tab", "notes_tab", "dashboard_tab"];
	hide.forEach((tab) => {
		frm.page.wrapper.find(`.nav-link[data-fieldname="${tab}"]`).closest("li").hide();
	});
};

cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible = function (frm) {
	CLEARANCE_STATION_FIELDS.forEach((fieldname) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		frm.set_df_property(fieldname, "depends_on", "");
		frm.set_df_property(fieldname, "read_only_depends_on", "");
		if (fieldname === "custom_clearance_station") {
			frm.set_df_property(fieldname, "read_only", 0);
		}
		frm.set_df_property(fieldname, "hidden", 0);
		frm.toggle_display(fieldname, true);
	});
};

cgm_shipping.opportunity_shipment._ensure_intake_fields_visible = function (frm) {
	const stage = frm.doc.custom_intake_stage || STAGE_INTAKE;
	if (stage !== STAGE_INTAKE && !frm.is_new()) {
		return;
	}
	INTAKE_ALWAYS_VISIBLE_FIELDS.forEach((fieldname) => {
		if (!frm.fields_dict[fieldname]) {
			return;
		}
		// Clear stage-gated depends_on so Customer / Consignee / Shipment Type stay visible on intake.
		frm.set_df_property(fieldname, "depends_on", "");
		frm.set_df_property(fieldname, "hidden", 0);
		if (fieldname === "custom_mode_of_transport") {
			frm.toggle_display(fieldname, Boolean(frm.doc.custom_shipment_type));
			return;
		}
		frm.toggle_display(fieldname, true);
	});
};

cgm_shipping.opportunity_shipment._apply_mode_from_shipment_type = function (frm, flags) {
	if (!frm.fields_dict.custom_mode_of_transport) {
		return;
	}
	const mode = (flags || {}).default_mode_of_transport;
	if (!frm.doc.custom_shipment_type) {
		if (frm.doc.custom_mode_of_transport) {
			frm.set_value("custom_mode_of_transport", "");
		}
		frm.toggle_display("custom_mode_of_transport", false);
		return;
	}
	frm.toggle_display("custom_mode_of_transport", true);
	if (mode && frm.doc.custom_mode_of_transport !== mode) {
		frm.set_value("custom_mode_of_transport", mode);
	}
};

cgm_shipping.opportunity_shipment.refresh_wizard_ui = function (frm) {
	const opportunity = frm.is_new() ? null : frm.doc.name;
	const shipment_type = frm.doc.custom_shipment_type || null;
	const request_token = (frm._cgm_wizard_request_token =
		(frm._cgm_wizard_request_token || 0) + 1);

	return frappe
		.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_intake_wizard.get_intake_wizard_context",
			args: { opportunity, shipment_type },
		})
		.then((r) => {
			// Ignore stale responses after navigating away / reopening New.
			if (request_token !== frm._cgm_wizard_request_token || cur_frm !== frm) {
				return r.message || {};
			}

			const ctx = r.message || {};
			frm._cgm_intake_context = ctx;

			if (frm.is_new()) {
				frm.doc.custom_intake_stage = STAGE_INTAKE;
				ctx.stage = STAGE_INTAKE;
				ctx.html = cgm_shipping.opportunity_shipment._local_intake_wizard_html(STAGE_INTAKE);
			}

			if (frm.fields_dict.custom_shipment_intake_wizard_html) {
				frm.get_field("custom_shipment_intake_wizard_html").html(ctx.html || "");
			}

			const stage = cgm_shipping.opportunity_shipment._current_stage(frm);
			if (frm.fields_dict.custom_intake_readiness_html) {
				if (READINESS_STAGES.includes(stage)) {
					frm.toggle_display("custom_intake_readiness_html", true);
					frm.get_field("custom_intake_readiness_html").html(
						cgm_shipping.opportunity_shipment._build_readiness_html(ctx.readiness || {})
					);
				} else {
					frm.get_field("custom_intake_readiness_html").html("");
					frm.toggle_display("custom_intake_readiness_html", false);
				}
			}

			if (ctx.stage && frm.doc.custom_intake_stage !== ctx.stage && !frm.is_new()) {
				frm.set_value("custom_intake_stage", ctx.stage);
			}

			const flags = ctx.readiness || {};
			frm._cgm_shipment_type_flags = flags;
			cgm_shipping.opportunity_shipment._apply_mode_from_shipment_type(frm, flags);
			cgm_shipping.opportunity_shipment._ensure_intake_fields_visible(frm);
			cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
			cgm_shipping.opportunity_shipment.render_transport_documents_dashboard(frm, flags);
			cgm_shipping.opportunity_shipment._apply_post_bl_layout_visibility(frm, flags);
			if (
				!frm.is_new() &&
				frm.doc.custom_bill_of_lading &&
				cgm_shipping?.bl_containers?.schedule_sync
			) {
				cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
			}
			return ctx;
		});
};

cgm_shipping.opportunity_shipment._build_readiness_html = function (readiness) {
	if (!readiness || readiness.existing_project) {
		return "";
	}
	const items = [];
	const transport_docs = readiness.transport_documents || [];
	const startAlternates = new Set(["Bill of Lading", "Booking Confirmation"]);
	const alternateDocs = transport_docs.filter((doc) =>
		startAlternates.has(doc.transport_document)
	);
	const alternateLinked = alternateDocs.some((doc) => doc.linked_name);
	if (alternateDocs.length >= 2 && !alternateLinked) {
		items.push(
			__("Link Bill of Lading or Booking Confirmation (whichever was provided first).")
		);
	} else if (!alternateDocs.length) {
		const missing_required = transport_docs.filter(
			(doc) => doc.is_required_for_start && !doc.linked_name
		);
		if (missing_required.length) {
			items.push(
				__("Link required transport document(s): {0}", [
					missing_required.map((doc) => doc.transport_document).join(", "),
				])
			);
		} else if (!readiness.transport_docs_linked && transport_docs.length) {
			items.push(__("Attach at least one transport document"));
		}
	} else if (!alternateLinked && !readiness.required_transport_linked) {
		items.push(__("Attach at least one transport document"));
	}
	(readiness.missing_documents || []).forEach((doc) => {
		items.push(__("Upload: {0}", [doc]));
	});
	(readiness.unverified_documents || []).forEach((doc) => {
		items.push(__("Verify: {0}", [doc]));
	});
	if (readiness.workflow_state && readiness.workflow_state !== "Approved") {
		items.push(__("Submit for approval (current: {0})", [readiness.workflow_state]));
	}
	if (!items.length) {
		return `<div class="cgm-intake-readiness text-success">${__(
			"Ready to start shipment after approval."
		)}</div>`;
	}
	return `<div class="cgm-intake-readiness"><strong>${__(
		"Before Start Shipment"
	)}</strong><ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul></div>`;
};

cgm_shipping.opportunity_shipment._apply_post_bl_layout_visibility = function (frm, flags) {
	const readiness = flags || frm._cgm_intake_context?.readiness || {};
	const stage = cgm_shipping.opportunity_shipment._current_stage(frm);
	const show =
		!frm.is_new() &&
		(Boolean(readiness.transport_docs_linked) ||
			Boolean(readiness.primary_linked) ||
			frm.doc.custom_primary_doc_linked ||
			[STAGE_DOCUMENTS, STAGE_AUTHORIZATION].includes(stage));

	if (!show) {
		return;
	}

	["column_break0", "column_break_10"].forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, true);
		}
	});

	cgm_shipping.opportunity_shipment.POST_BL_LAYOUT_FIELDS.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, true);
		}
	});

	if (frm.fields_dict.custom_section_transport_info) {
		frm.toggle_display("custom_section_transport_info", false);
	}
};

cgm_shipping.opportunity_shipment.on_after_save = function (frm) {
	return cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
};

cgm_shipping.opportunity_shipment.render_transport_documents_dashboard = function (frm, flags) {
	const field = frm.fields_dict.custom_transport_documents_html;
	if (!field) {
		return;
	}

	const stage = cgm_shipping.opportunity_shipment._current_stage(frm);
	const docs = (flags || frm._cgm_intake_context?.readiness || {}).transport_documents || [];
	const show_dashboard =
		!frm.is_new() && TRANSPORT_DASHBOARD_STAGES.includes(stage) && docs.length > 0;

	if (!show_dashboard) {
		field.$wrapper.empty();
		frm.toggle_display("custom_transport_documents_html", false);
		return;
	}

	frm.toggle_display("custom_transport_documents_html", true);

	const parts = ['<div class="cgm-transport-documents">'];
	parts.push(`<div class="cgm-transport-documents-title">${__("Transport Documents")}</div>`);
	parts.push('<div class="cgm-transport-doc-actions">');

	docs.forEach((doc) => {
		const label = frappe.utils.escape_html(doc.transport_document || "");
		const linked = doc.linked_name;
		const required = doc.is_required_for_start ? " cgm-transport-doc-required" : "";
		if (linked) {
			parts.push(
				`<button type="button" class="btn btn-sm btn-default cgm-transport-doc-linked${required}" ` +
					`data-action="open" data-doctype="${frappe.utils.escape_html(doc.doctype)}" ` +
					`data-name="${frappe.utils.escape_html(linked)}">` +
					`<span class="cgm-transport-doc-check">✓</span> ${label}</button>`
			);
			return;
		}
		if (!doc.doctype || !doc.opp_field) {
			return;
		}
		parts.push(
			`<button type="button" class="btn btn-sm btn-primary cgm-add-transport-doc${required}" ` +
				`data-doctype="${frappe.utils.escape_html(doc.doctype)}" ` +
				`data-label="${label}" data-opp-field="${frappe.utils.escape_html(doc.opp_field)}">` +
				`+ ${__("Add {0}", [label])}</button>`
		);
	});

	parts.push("</div></div>");
	field.$wrapper.html(parts.join(""));

	field.$wrapper
		.off("click.cgmTransportDocs")
		.on("click.cgmTransportDocs", ".cgm-add-transport-doc", (event) => {
			const $btn = $(event.currentTarget);
			cgm_shipping.opportunity_shipment._open_transport_document(frm, {
				doctype: $btn.data("doctype"),
				transport_document: $btn.data("label"),
				opp_field: $btn.data("opp-field"),
			});
		})
		.on("click.cgmTransportDocs", ".cgm-transport-doc-linked", (event) => {
			const $btn = $(event.currentTarget);
			frappe.set_route("Form", $btn.data("doctype"), $btn.data("name"));
		});
};

cgm_shipping.opportunity_shipment._open_transport_document = function (frm, doc) {
	if (!doc?.doctype) {
		return;
	}

	const seed = cgm_shipping.opportunity_shipment._build_transport_document_seed(frm, doc);
	frappe.route_options = seed;

	frappe.model.with_doctype(doc.doctype, () => {
		frappe.new_doc(doc.doctype);
	});
};

cgm_shipping.opportunity_shipment._build_awb_route_options = function (frm) {
	const opts = {};
	if (frm.doc.name && !String(frm.doc.name).startsWith("new-")) {
		opts.linked_opportunity = frm.doc.name;
	}
	if (frm.doc.party_name) {
		opts.customer = frm.doc.party_name;
	}
	if (frm.doc.custom_shipment_type) {
		opts.shipment_type = frm.doc.custom_shipment_type;
	}
	if (frm.doc.custom_client_refrence_no) {
		opts.client_reference_no = frm.doc.custom_client_refrence_no;
	}
	if (frm.doc.custom_description_of_goods) {
		opts.description = frm.doc.custom_description_of_goods;
	}
	if (frm.doc.custom_airline) {
		opts.airline = frm.doc.custom_airline;
	}
	if (frm.doc.custom_eta) {
		opts.eta = frm.doc.custom_eta;
	}
	if (frm.doc.custom_etd) {
		opts.etd = frm.doc.custom_etd;
	}
	if (frm.doc.custom_weight_uom_) {
		opts.weight_uom = frm.doc.custom_weight_uom_;
	}
	if (frm.doc.custom_weight_nw != null && frm.doc.custom_weight_nw !== "") {
		opts.net_weight = frm.doc.custom_weight_nw;
	}
	if (frm.doc.custom_gross_weight != null && frm.doc.custom_gross_weight !== "") {
		opts.gross_weight = frm.doc.custom_gross_weight;
	}
	if (frm.doc.custom_port_of_loading) {
		opts.port_of_loading = frm.doc.custom_port_of_loading;
	}
	if (frm.doc.custom_port_of_discharge) {
		opts.port_of_discharge = frm.doc.custom_port_of_discharge;
	}
	return opts;
};

cgm_shipping.opportunity_shipment._build_transport_document_seed = function (frm, doc) {
	const seed = {};
	if (frm.doc.name && !String(frm.doc.name).startsWith("new-")) {
		localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, frm.doc.name);
		seed.linked_opportunity = frm.doc.name;
	}
	if (frm.doc.party_name) {
		seed.customer = frm.doc.party_name;
	}
	if (frm.doc.custom_shipment_type) {
		seed.shipment_type = frm.doc.custom_shipment_type;
	}
	if (frm.doc.custom_client_refrence_no) {
		seed.client_reference_no = frm.doc.custom_client_refrence_no;
		// Legacy aliases consumed by older AWB onload handlers.
		seed.client_ref = frm.doc.custom_client_refrence_no;
		seed.client_refrence_no = frm.doc.custom_client_refrence_no;
	}

	const opp_field = doc.opp_field;
	const df = opp_field && frm.get_docfield(opp_field);
	if (df && df.get_route_options_for_new_doc) {
		Object.assign(seed, df.get_route_options_for_new_doc() || {});
	}

	if (doc.doctype === "Bill of Lading") {
		if (frm.doc.custom_draft_bl_number) {
			seed.bl_number = frm.doc.custom_draft_bl_number;
		}
		// Batch is allocated on save (FCL key) — do not seed from Opportunity.
		// Link Booking so BL onload can expand FCL container stubs / LCL packages.
		if (frm.doc.custom_booking_confirmation) {
			seed.booking_confirmation = frm.doc.custom_booking_confirmation;
		}
		// Flag for BL form to fetch the full Opportunity/Booking seed (incl. child rows).
		if (frm.doc.name && !String(frm.doc.name).startsWith("new-")) {
			localStorage.setItem("cgm_bl_seed_opportunity", frm.doc.name);
		}
	}

	if (doc.doctype === "Air Waybill") {
		Object.assign(seed, cgm_shipping.opportunity_shipment._build_awb_route_options(frm));
		if (frm.doc.name && !String(frm.doc.name).startsWith("new-")) {
			localStorage.setItem(CGM_AWB_SEED_OPPORTUNITY_KEY, frm.doc.name);
		}
	}

	return seed;
};

cgm_shipping.opportunity_shipment._open_primary_document = function (frm, flags) {
	const doctype = flags.primary_transport_doctype;
	const opp_field = flags.primary_transport_opp_field;
	if (!doctype) {
		return;
	}
	cgm_shipping.opportunity_shipment._open_transport_document(frm, {
		doctype,
		opp_field,
		transport_document: flags.primary_transport_document,
	});
};

cgm_shipping.opportunity_shipment.setup_awb_create_route = function (frm) {
	const df = frm.fields_dict.custom_air_waybill && frm.get_docfield("custom_air_waybill");
	if (!df || frm._cgm_awb_create_route_setup) {
		return;
	}
	frm._cgm_awb_create_route_setup = true;
	df.get_route_options_for_new_doc = () => {
		if (frm.doc.name) {
			localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, frm.doc.name);
		}
		if (frm.doc.name && !String(frm.doc.name).startsWith("new-")) {
			localStorage.setItem(CGM_AWB_SEED_OPPORTUNITY_KEY, frm.doc.name);
		}
		return cgm_shipping.opportunity_shipment._build_awb_route_options(frm);
	};
};

cgm_shipping.opportunity_shipment.setup_booking_create_route = function (frm) {
	const df =
		frm.fields_dict.custom_booking_confirmation &&
		frm.get_docfield("custom_booking_confirmation");
	if (!df || frm._cgm_booking_create_route_setup) {
		return;
	}
	frm._cgm_booking_create_route_setup = true;
	df.get_route_options_for_new_doc = () => {
		const opts = {};
		if (frm.doc.name) {
			localStorage.setItem(CGM_RETURN_OPPORTUNITY_KEY, frm.doc.name);
		}
		if (frm.doc.name && !String(frm.doc.name).startsWith("new-")) {
			opts.linked_opportunity = frm.doc.name;
			if (frm.doc.custom_shipment_type) {
				opts.shipment_type = frm.doc.custom_shipment_type;
			}
			if (frm.doc.party_name) {
				opts.customer = frm.doc.party_name;
			}
		}
		return opts;
	};
};

cgm_shipping.opportunity_shipment.apply_awb_payload = function (frm, pending) {
	if (!pending || !frm) {
		return;
	}

	const set_if = (fieldname, value) => {
		if (value == null || value === "" || !frm.fields_dict[fieldname]) {
			return;
		}
		if (String(frm.doc[fieldname] ?? "") === String(value ?? "")) {
			return;
		}
		frm.set_value(fieldname, value);
	};

	if (pending.awb_name) {
		set_if("custom_air_waybill", pending.awb_name);
	}
	set_if("custom_shipment_type", pending.shipment_type);
	set_if(
		"custom_mode_of_transport",
		pending.default_mode_of_transport || (pending.shipment_type ? null : "Air")
	);
	set_if("custom_client_refrence_no", pending.custom_client_refrence_no || pending.client_reference_no || pending.client_ref);
	set_if("custom_description_of_goods", pending.custom_description_of_goods || pending.description);
	set_if("custom_airline", pending.custom_airline || pending.airline);
	set_if("custom_eta", pending.custom_eta || pending.eta);
	set_if("custom_etd", pending.custom_etd || pending.etd);
	set_if("custom_gross_weight", pending.custom_gross_weight || pending.gross_weight);
	set_if("custom_weight_nw", pending.custom_weight_nw || pending.net_weight);
	set_if("custom_weight_uom_", pending.custom_weight_uom_ || pending.weight_uom);
	set_if("custom_port_of_loading", pending.custom_port_of_loading || pending.port_of_loading);
	set_if("custom_port_of_discharge", pending.custom_port_of_discharge || pending.port_of_discharge);
};

cgm_shipping.opportunity_shipment.apply_pending_awb_from_submit = function (frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}
	let pending;
	try {
		pending = JSON.parse(localStorage.getItem(CGM_PENDING_AWB_LINK_KEY) || "null");
	} catch {
		return;
	}
	if (!pending || pending.opportunity !== frm.doc.name) {
		return;
	}

	cgm_shipping.opportunity_shipment.apply_awb_payload(frm, pending);

	localStorage.removeItem(CGM_PENDING_AWB_LINK_KEY);
	cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm).then(() => {
		cgm_shipping.opportunity_shipment._ensure_clearance_station_fields_visible(frm);
	});
	frappe.show_alert({
		message: __("Air Waybill {0} linked — fields synced; continue completing this Opportunity.", [
			pending.awb_name,
		]),
		indicator: "green",
	});
};

cgm_shipping.opportunity_shipment.sync_from_linked_awb = function (frm) {
	const awb = frm.doc.custom_air_waybill;
	if (!awb || frm.is_new() || frm.doc.docstatus !== 0) {
		return Promise.resolve();
	}
	return frappe
		.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.doctype.air_waybill.air_waybill.get_awb_fields_for_opportunity",
			args: { air_waybill: awb },
		})
		.then((r) => {
			if (r.exc || !r.message) {
				return;
			}
			cgm_shipping.opportunity_shipment.apply_awb_payload(frm, {
				awb_name: awb,
				...r.message,
			});
		});
};

cgm_shipping.opportunity_shipment.apply_booking_payload = function (frm, pending) {
	if (!pending || !frm) {
		return;
	}

	const set_if = (fieldname, value) => {
		if (value == null || value === "" || !frm.fields_dict[fieldname]) {
			return;
		}
		if (String(frm.doc[fieldname] ?? "") === String(value ?? "")) {
			return;
		}
		frm.set_value(fieldname, value);
	};

	if (pending.booking_name) {
		set_if("custom_booking_confirmation", pending.booking_name);
	}
	set_if("custom_booking_ref", pending.booking_number);
	set_if("custom_shipping_order_ref", pending.booking_number);
	set_if("custom_shipment_type", pending.shipment_type);
	set_if("custom_mode_of_transport", pending.default_mode_of_transport);
	set_if("custom_shipping_line", pending.shipping_line);
	set_if("custom_vessel", pending.vessel);
	set_if("custom_etd", pending.etd);
	set_if("custom_eta", pending.eta);
	set_if("custom_client_refrence_no", pending.client_ref);
	set_if("custom_description_of_goods", pending.commodity);
	set_if("custom_gross_weight", pending.gross_weight);
	set_if("custom_weight_nw", pending.net_weight);
	set_if("custom_weight_uom_", pending.weight_uom);
	set_if("custom_quantity", pending.quantity);
	set_if("custom_batch_no", pending.batch_no);
	set_if("custom_port_of_loading", pending.port_of_loading);
	set_if("custom_port_of_discharge", pending.port_of_discharge);
	set_if("custom_voyage_number", pending.voyage_number);
	set_if("custom_cargo_cutoff", pending.cargo_cut_off);
	set_if("custom_number_of_packages", pending.number_of_packages);
	set_if("custom_package_type", pending.package_type);

	const cargo_type = pending.requested_cargo_type || pending.cargo_type || null;
	if (cargo_type) {
		if (frm.fields_dict.custom_cargo_type) {
			set_if("custom_cargo_type", cargo_type);
		} else if (frm.fields_dict.custom_cargo_type_) {
			set_if("custom_cargo_type_", cargo_type);
		}
	}

	[
		"custom_weight_uom_",
		"custom_weight_nw",
		"custom_gross_weight",
		"custom_quantity",
		"custom_number_of_packages",
		"custom_package_type",
		"custom_requested_cargo_quantity",
	].forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.toggle_display(fieldname, true);
		}
	});

	const table_field = "custom_requested_cargo_quantity";
	const rows = Array.isArray(pending.requested_cargo_quantity)
		? pending.requested_cargo_quantity
		: null;
	if (frm.fields_dict[table_field] && rows) {
		frm.clear_table(table_field);
		rows.forEach((row) => {
			const child = frm.add_child(table_field);
			child.cargo_size = row.cargo_size || "";
			child.quantity = row.quantity || "";
		});
		const show_requested =
			String(cargo_type || "").toUpperCase() === "FCL" || rows.length > 0;
		frm.set_df_property(table_field, "hidden", show_requested ? 0 : 1);
		frm.refresh_field(table_field);
	}
};

cgm_shipping.opportunity_shipment.sync_from_linked_booking = function (frm) {
	const booking = frm.doc.custom_booking_confirmation;
	if (!booking || frm.is_new() || frm.doc.docstatus !== 0) {
		return Promise.resolve();
	}
	return frappe
		.call({
			method:
				"cgm_shipping.cgm_worldwide_shipping.doctype.booking_confirmation.booking_confirmation.get_booking_fields_for_opportunity",
			args: { booking_confirmation: booking },
		})
		.then((r) => {
			if (r.exc || !r.message) {
				return;
			}
			cgm_shipping.opportunity_shipment.apply_booking_payload(frm, {
				booking_name: booking,
				...r.message,
			});
		});
};

cgm_shipping.opportunity_shipment.apply_pending_booking_from_submit = function (frm) {
	if (!frm.doc.name || frm.is_new()) {
		return;
	}
	let pending;
	try {
		pending = JSON.parse(localStorage.getItem(CGM_PENDING_BOOKING_LINK_KEY) || "null");
	} catch {
		return;
	}
	if (!pending || pending.opportunity !== frm.doc.name) {
		return;
	}

	cgm_shipping.opportunity_shipment.apply_booking_payload(frm, pending);

	localStorage.removeItem(CGM_PENDING_BOOKING_LINK_KEY);
	frappe.show_alert({
		message: __(
			"Booking Confirmation {0} linked — fields synced; continue verifying documents.",
			[pending.booking_name]
		),
		indicator: "green",
	});
};

cgm_shipping.opportunity_shipment.setup_shipping_line_query = function (frm) {
	if (!frm.fields_dict.custom_shipping_line || frm._cgm_shipping_line_query_setup) {
		return;
	}
	frm._cgm_shipping_line_query_setup = true;
	const supplier_meta = frappe.get_meta("Supplier");
	const has_flag = supplier_meta?.fields?.some((f) => f.fieldname === "is_shipping_line");
	frm.set_query("custom_shipping_line", () => {
		if (has_flag) {
			return { filters: { is_shipping_line: 1 } };
		}
		return { filters: { supplier_group: "Shipping Line" } };
	});
};

cgm_shipping.opportunity_shipment.setup_start_shipment_button = function (frm) {
	frm.remove_custom_button?.(__("Start Shipment"));
	frm.remove_custom_button?.(__("View Project"));

	if (frm.is_new() || !frm.doc.name || frm.doc.opportunity_from !== "Customer") {
		return;
	}

	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment.get_start_shipment_readiness",
		args: { opportunity: frm.doc.name },
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			const readiness = r.message;
			if (readiness.existing_project) {
				frm.add_custom_button(__("View Project"), () => {
					frappe.set_route("Form", "Project", readiness.existing_project);
				}).addClass("btn-primary");
				return;
			}

			const stage = frm.doc.custom_intake_stage;
			if (
				stage !== "authorization" &&
				stage !== "documents" &&
				stage !== STAGE_AWAITING_PRIMARY
			) {
				return;
			}

			const btn = frm.add_custom_button(__("Start Shipment"), () => {
				cgm_shipping.opportunity_shipment.start_shipment(frm);
			});
			if (readiness.ok && frm.doc.workflow_state === "Approved") {
				btn.addClass("btn-primary");
			}
		},
	});
};

cgm_shipping.opportunity_shipment.start_shipment = function (frm) {
	frappe.call({
		method:
			"cgm_shipping.cgm_worldwide_shipping.customizations.opportunity_shipment.start_shipment_from_opportunity",
		args: { opportunity: frm.doc.name },
		freeze: true,
		freeze_message: __("Starting shipment…"),
		callback(r) {
			if (r.exc || !r.message) {
				return;
			}
			frappe.show_alert({
				message: __("Project {0} created — shipment started.", [r.message]),
				indicator: "green",
			});
			frappe.set_route("Form", "Project", r.message);
		},
	});
};

// Backward-compatible no-ops for crm_opportunity.js call sites.
cgm_shipping.opportunity_shipment.apply_shipment_type_visibility = function (frm) {
	return cgm_shipping.opportunity_shipment.refresh_wizard_ui(frm);
};

cgm_shipping.opportunity_shipment.offer_primary_document_redirect = function () {};
cgm_shipping.opportunity_shipment.setup_transport_document_section = function () {};
