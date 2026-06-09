frappe.provide("cgm_shipping.transport_reference");

const CGM_SEA_SHIPMENT_TYPES = new Set(["Sea FCL", "Sea LCL"]);
const CGM_AIR_SHIPMENT_TYPES = new Set(["Air Import"]);

/**
 * Resolve Sea vs Air from operational shipment type (Sea FCL, Sea LCL, Air Import).
 */
cgm_shipping.transport_reference.resolve_category = function (doc) {
	const shipmentType = (doc.custom_shipment_type || "").trim();

	if (CGM_SEA_SHIPMENT_TYPES.has(shipmentType)) {
		return "sea";
	}
	if (CGM_AIR_SHIPMENT_TYPES.has(shipmentType)) {
		return "air";
	}
	return null;
};

/**
 * Show B/L for Sea, AWB for Air (Project uses custom_awb_number; Opportunity uses custom_air_waybill).
 */
cgm_shipping.transport_reference.toggle = function (frm, options = {}) {
	const category = cgm_shipping.transport_reference.resolve_category(frm.doc);
	const blField = options.bill_of_lading || "custom_bill_of_lading";
	const awbField = options.air_waybill || "custom_awb_number";
	const showBl = category === "sea";
	const showAwb = category === "air";

	if (frm.fields_dict[blField]) {
		frm.toggle_display(blField, showBl);
	}
	if (frm.fields_dict[awbField]) {
		frm.toggle_display(awbField, showAwb);
	}
	// Container grid visibility is driven by depends_on + cgm_bl_containers.js
	if (options.section && frm.fields_dict[options.section]) {
		frm.toggle_display(options.section, showBl || showAwb);
	}
};
