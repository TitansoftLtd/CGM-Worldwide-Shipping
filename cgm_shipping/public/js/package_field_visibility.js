frappe.provide("cgm_shipping.package_visibility");

cgm_shipping.package_visibility.get_config = function () {
	const boot = (frappe.boot && frappe.boot.cgm_package_visibility) || {};
	return {
		modes: (boot.modes || [])
			.map((value) => String(value || "").trim().toLowerCase())
			.filter(Boolean),
		cargo_types: (boot.cargo_types || [])
			.map((value) => String(value || "").trim().toUpperCase())
			.filter(Boolean),
	};
};

cgm_shipping.package_visibility.should_show = function (frm) {
	const cfg = cgm_shipping.package_visibility.get_config();
	const mode = String(frm.doc.custom_mode_of_transport || "").trim().toLowerCase();
	const cargo = String(frm.doc.custom_cargo_type_ || frm.doc.custom_cargo_type || "")
		.trim()
		.toUpperCase();
	const hasPackages = Boolean(frm.doc.custom_number_of_packages || frm.doc.custom_package_type);
	const hasAwb = Boolean(frm.doc.custom_air_waybill);
	return cfg.modes.includes(mode) || cfg.cargo_types.includes(cargo) || hasAwb || hasPackages;
};
