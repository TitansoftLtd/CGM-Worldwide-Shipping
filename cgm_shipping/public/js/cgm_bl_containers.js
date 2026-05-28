frappe.provide("cgm_shipping.bl_containers");

cgm_shipping.bl_containers.sync_from_bl = function (frm) {
	if (!frm.fields_dict.custom_container_information) {
		return;
	}

	if (!frm.doc.custom_bill_of_lading) {
		frm.clear_table("custom_container_information");
		frm.refresh_field("custom_container_information");
		return;
	}

	frappe.db.get_doc("Bill of Lading", frm.doc.custom_bill_of_lading).then((bl) => {
		frm.clear_table("custom_container_information");
		(bl.container_information || []).forEach((row) => {
			const child = frm.add_child("custom_container_information");
			child.container_number = row.container_number;
			child.type_of_container = row.type_of_container;
		});
		frm.refresh_field("custom_container_information");
	});
};
