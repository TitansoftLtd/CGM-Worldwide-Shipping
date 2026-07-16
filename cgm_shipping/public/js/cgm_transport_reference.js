frappe.provide("cgm_shipping.transport_reference");

cgm_shipping.transport_reference._profiles = null;
cgm_shipping.transport_reference._load_promise = null;

cgm_shipping.transport_reference.ensure_profiles = function () {
	if (cgm_shipping.transport_reference._profiles) {
		return Promise.resolve(cgm_shipping.transport_reference._profiles);
	}
	if (!cgm_shipping.transport_reference._load_promise) {
		cgm_shipping.transport_reference._load_promise = frappe
			.call({
				method:
					"cgm_shipping.cgm_worldwide_shipping.customizations.shipment.get_shipment_type_profiles",
				type: "GET",
			})
			.then((r) => {
				cgm_shipping.transport_reference._profiles = r.message || {};
				return cgm_shipping.transport_reference._profiles;
			});
	}
	return cgm_shipping.transport_reference._load_promise;
};

cgm_shipping.transport_reference.invalidate_profiles = function () {
	cgm_shipping.transport_reference._profiles = null;
	cgm_shipping.transport_reference._load_promise = null;
};

function shipment_type_from_doc(doc) {
	return (doc.custom_shipment_type || doc.shipment_type || "").trim();
}

function mode_from_doc(doc) {
	return (doc.custom_mode_of_transport || "").trim();
}

/**
 * Resolve sea / air / road from Shipment Type master (cached) with mode fallback.
 */
cgm_shipping.transport_reference.resolve_category = function (doc, profiles) {
	const shipmentType = shipment_type_from_doc(doc);
	const mode = mode_from_doc(doc);

	if (profiles && shipmentType && profiles[shipmentType]) {
		return profiles[shipmentType].category || null;
	}
	if (mode) {
		const key = mode.toLowerCase();
		if (key === "sea") return "sea";
		if (key === "air") return "air";
		if (key === "road") return "road";
	}
	return null;
};

cgm_shipping.transport_reference.apply_toggle = function (frm, category, options = {}) {
	const blField = options.bill_of_lading || "custom_bill_of_lading";
	const awbField = options.air_waybill || "custom_air_waybill";
	const containerField = options.container_table || "custom_container_information";
	const showBl = category === "sea";
	const showAwb = category === "air";

	if (frm.fields_dict[blField]) {
		frm.toggle_display(blField, showBl);
	}
	if (frm.fields_dict[awbField]) {
		frm.toggle_display(awbField, showAwb);
	}
	if (frm.fields_dict[containerField]) {
		frm.toggle_display(containerField, showBl && Boolean(frm.doc[blField]));
	}
	if (options.section && frm.fields_dict[options.section]) {
		frm.toggle_display(options.section, showBl || showAwb);
	}
};

/**
 * Show B/L for Sea, AWB for Air (Project uses custom_awb_number; Opportunity uses custom_air_waybill).
 */
cgm_shipping.transport_reference.toggle = function (frm, options = {}) {
	return cgm_shipping.transport_reference.ensure_profiles().then((profiles) => {
		const category = cgm_shipping.transport_reference.resolve_category(frm.doc, profiles);
		cgm_shipping.transport_reference.apply_toggle(frm, category, options);
		return category;
	});
};

cgm_shipping.transport_reference.shipment_type_names_for_category = function (
	profiles,
	category
) {
	return Object.keys(profiles || {}).filter(
		(name) => (profiles[name] || {}).category === category
	);
};

/**
 * Show container type when cargo is FCL (or empty), shipment type uses unit tracking,
 * and a B/L is linked. Hide for LCL / Breakbulk / Project Cargo unless a value exists.
 */
cgm_shipping.transport_reference.toggle_cargo_type = function (frm, options = {}) {
	const field = options.cargo_type || "custom_cargo_type";
	if (!frm.fields_dict[field]) {
		return Promise.resolve();
	}

	const blField = options.bill_of_lading || "custom_bill_of_lading";
	const cargoField = options.cargo_type || "custom_cargo_type";
	const cargoType = (frm.doc[cargoField] || "").trim();
	const nonFclCargo = ["LCL", "Breakbulk", "Project Cargo"].includes(cargoType);

	return cgm_shipping.transport_reference.ensure_profiles().then((profiles) => {
		const shipmentType = (
			frm.doc.custom_shipment_type ||
			frm.doc.shipment_type ||
			""
		).trim();
		const profile = shipmentType ? profiles[shipmentType] : null;
		const hasValue = Boolean(frm.doc[field]);
		const hasBl = Boolean(frm.doc[blField]);
		const masterAllows =
			!profile ||
			profile.uses_unit_tracking ||
			profile.requires_bill_of_lading ||
			profile.category === "sea";
		const cargoAllows = !cargoType || cargoType === "FCL" || !nonFclCargo;
		frm.toggle_display(field, hasValue || (hasBl && masterAllows && cargoAllows));
	});
};
