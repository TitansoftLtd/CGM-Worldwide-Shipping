// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

frappe.listview_settings["License Register"] = {
	add_fields: ["status", "expiry_date", "days_to_expiry"],

	get_indicator(doc) {
		const colours = {
			Active: "green",
			"Expiring Soon": "orange",
			Expired: "red",
			"Renewal Required": "yellow",
			Ongoing: "blue",
			Disabled: "gray",
		};
		if (!doc.status) return null;
		return [__(doc.status), colours[doc.status] || "gray", "status,=," + doc.status];
	},
};
