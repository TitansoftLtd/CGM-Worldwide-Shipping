const MODE_SECTIONS = {
	"Mombasa Port": ["section_mombasa", "section_warehouse", "section_transport", "section_empty_return", "section_calculations"],
	"ICD Nairobi": [
		"section_mombasa",
		"section_icd",
		"section_warehouse",
		"section_transport",
		"section_empty_return",
		"section_calculations",
	],
	"Transit Kenya→Border": [
		"section_transit",
		"section_warehouse",
		"section_transport",
		"section_empty_return",
		"section_calculations",
	],
	"Transit Border→Kenya": [
		"section_transit",
		"section_warehouse",
		"section_transport",
		"section_empty_return",
		"section_calculations",
	],
	Export: ["section_mombasa", "section_transport", "section_empty_return", "section_calculations"],
};

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

frappe.ui.form.on("Container Tracker", {
	refresh(frm) {
		apply_container_mode_layout(frm);
		if (frm.doc.project) {
			frm.add_custom_button(__("Open Project"), () => {
				frappe.set_route("Form", "Project", frm.doc.project);
			});
		}
	},
	container_mode(frm) {
		apply_container_mode_layout(frm);
	},
});
