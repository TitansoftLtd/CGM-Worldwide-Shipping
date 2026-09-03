// County picker on Job Applicant. The list is limited to counties inside the
// selected Country of Residence, so picking Kenya offers Kenya's 47 counties and
// nothing else. Territory Type lives on the Territory master, not here.
const CGM_COUNTY_QUERY =
	"cgm_shipping.cgm_worldwide_shipping.customizations.recruitment.county_query";

frappe.ui.form.on("Job Applicant", {
	setup(frm) {
		frm.set_query("custom_territory", () => ({
			query: CGM_COUNTY_QUERY,
			filters: { country: frm.doc.country || "" },
		}));
	},

	country(frm) {
		// Drop a county that no longer belongs to the country above it.
		if (!frm.doc.custom_territory) return;

		if (!frm.doc.country) {
			frm.set_value("custom_territory", null);
			return;
		}

		frappe.db
			.get_value("Territory", frm.doc.custom_territory, ["lft", "rgt"])
			.then((r) => {
				const county = r && r.message;
				if (!county) return;
				frappe.db
					.get_value(
						"Territory",
						{ name: frm.doc.country, custom_territory_type: "Country" },
						["lft", "rgt"]
					)
					.then((c) => {
						const country = c && c.message;
						const inside =
							country && country.lft <= county.lft && county.rgt <= country.rgt;
						if (!inside) frm.set_value("custom_territory", null);
					});
			});
	},
});
