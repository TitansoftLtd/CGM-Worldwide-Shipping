# Copyright (c) 2026, Titansoft Limited and contributors
# For license information, please see license.txt

(function () {
	const DATA_FIELDS = [
		"charge_name",
		"line_type",
		"payment_kind",
		"is_active",
		"purchase_item",
		"description",
	];

	function data_field_count(doctype) {
		const map = frappe.meta.docfield_map[doctype] || {};
		return Object.keys(map).filter(function (key) {
			const ft = map[key].fieldtype;
			return ft !== "Section Break" && ft !== "Column Break" && ft !== "Tab Break";
		}).length;
	}

	function sync_docfield_map_from_locals(doctype) {
		const meta = locals.DocType && locals.DocType[doctype];
		if (!meta || !meta.fields || !meta.fields.length) {
			return false;
		}
		meta.fields.forEach(function (df) {
			frappe.meta.add_field(df);
		});
		return data_field_count(doctype) > 0;
	}

	function visible_controls(frm) {
		return frm.layout.wrapper.find(".form-page .frappe-control:not(.hide-control)").length;
	}

	function rerender_form_if_empty(frm) {
		if (frm.layout.wrapper.find(".form-page .frappe-control").length) {
			return;
		}
		const layout = frm.layout;
		layout.fields = layout.get_doctype_fields();
		layout.wrapper.find(".form-page").remove();
		layout.page = $('<div class="form-page"></div>').appendTo(layout.wrapper);
		layout.section = null;
		layout.column = null;
		layout.sections = [];
		layout.fields_list = [];
		layout.fields_dict = {};
		layout.render();
		frm.fields_dict = layout.fields_dict;
		frm.fields = layout.fields_list;
		layout.doc = frm.doc;
		layout.attach_doc_and_docfields(true);
		layout.refresh_sections();
	}

	function ensure_form_fields(frm) {
		if (visible_controls(frm) > 0) {
			return;
		}
		const existing = frm.layout.wrapper.find(".form-page .frappe-control").length;
		if (existing > 0) {
			DATA_FIELDS.forEach(function (fieldname) {
				if (frm.fields_dict[fieldname]) {
					frm.set_df_property(fieldname, "hidden", 0);
				}
			});
			return;
		}
		if (data_field_count(frm.doctype) < 1) {
			sync_docfield_map_from_locals(frm.doctype);
		}
		if (data_field_count(frm.doctype) < 1) {
			return;
		}
		rerender_form_if_empty(frm);
		DATA_FIELDS.forEach(function (fieldname) {
			if (frm.fields_dict[fieldname]) {
				frm.set_df_property(fieldname, "hidden", 0);
			}
		});
	}

	frappe.ui.form.on("Clearance Charge Item", {
		onload(frm) {
			ensure_form_fields(frm);
		},
		refresh(frm) {
			frm.set_query("purchase_item", function () {
				return {
					filters: { disabled: 0, is_purchase_item: 1 },
				};
			});
			ensure_form_fields(frm);
			if (!frm.is_new()) {
				frm.set_intro(
					__(
						"This name appears as the Item on Task finance lines. Use <b>Menu → Rename</b> to change the charge name."
					),
					"blue"
				);
			} else {
				frm.set_intro("");
			}
		},
	});
})();
