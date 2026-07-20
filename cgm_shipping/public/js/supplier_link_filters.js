/*!
 * Link filters for Supplier fields used as Shipping Line vs Transporter.
 *
 * Shipping Line → custom_is_shipping_line = 1
 * Transporter   → is_transporter = 1
 */
frappe.provide("cgm_shipping.supplier_filters");

const SHIPPING_LINE_FIELDNAMES = new Set(["shipping_line", "custom_shipping_line"]);
const TRANSPORTER_FIELDNAMES = new Set(["transporter", "custom_transporter"]);

cgm_shipping.supplier_filters.shipping_line_query = function () {
	return {
		filters: {
			disabled: 0,
			custom_is_shipping_line: 1,
		},
	};
};

cgm_shipping.supplier_filters.transporter_query = function () {
	return {
		filters: {
			disabled: 0,
			is_transporter: 1,
		},
	};
};

function _label_kind(df) {
	const label = ((df && df.label) || "").trim().toLowerCase();
	if (label === "shipping line" || label.endsWith(" shipping line")) {
		return "shipping_line";
	}
	if (label === "transporter") {
		return "transporter";
	}
	return null;
}

function _field_kind(fieldname, df) {
	if (SHIPPING_LINE_FIELDNAMES.has(fieldname)) {
		return "shipping_line";
	}
	if (TRANSPORTER_FIELDNAMES.has(fieldname)) {
		return "transporter";
	}
	return _label_kind(df);
}

cgm_shipping.supplier_filters.apply = function (frm) {
	if (!frm || !frm.meta || !frm.fields_dict) {
		return;
	}

	(frm.meta.fields || []).forEach((df) => {
		if (df.fieldtype !== "Link" || df.options !== "Supplier") {
			return;
		}
		const kind = _field_kind(df.fieldname, df);
		if (!kind || !frm.fields_dict[df.fieldname]) {
			return;
		}
		const query =
			kind === "shipping_line"
				? cgm_shipping.supplier_filters.shipping_line_query
				: cgm_shipping.supplier_filters.transporter_query;
		frm.set_query(df.fieldname, query);
	});

	// Child table Supplier links (e.g. allocation rows).
	(frm.meta.fields || []).forEach((df) => {
		if (df.fieldtype !== "Table") {
			return;
		}
		const child_meta = frappe.get_meta(df.options);
		if (!child_meta) {
			return;
		}
		(child_meta.fields || []).forEach((cdf) => {
			if (cdf.fieldtype !== "Link" || cdf.options !== "Supplier") {
				return;
			}
			const kind = _field_kind(cdf.fieldname, cdf);
			if (!kind) {
				return;
			}
			const query =
				kind === "shipping_line"
					? cgm_shipping.supplier_filters.shipping_line_query
					: cgm_shipping.supplier_filters.transporter_query;
			frm.set_query(cdf.fieldname, df.fieldname, query);
		});
	});
};

$(document).on("form-refresh", (_e, frm) => {
	cgm_shipping.supplier_filters.apply(frm);
});
