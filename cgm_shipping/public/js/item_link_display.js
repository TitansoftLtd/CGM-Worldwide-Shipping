/*!
 * Item Link fields: keep Item Code as the stored value, show Item Name after
 * selection (via Frappe show_title_field_in_link), and keep search results as
 * "Item Code — Item Name".
 */
frappe.provide("cgm_shipping.item_link");

const ITEM_LINK_OPTION_SUFFIX = "__link_option";

function cgm_is_item_link_control(control) {
	return control && typeof control.get_options === "function" && control.get_options() === "Item";
}

function cgm_is_link_option_row(item) {
	if (!item || item.action) {
		return true;
	}
	return typeof item.value === "string" && item.value.endsWith(ITEM_LINK_OPTION_SUFFIX);
}

function cgm_item_name_from_description(description, item_code) {
	const first = String(description || "")
		.split(",")
		.map((part) => part.trim())
		.find((part) => part && part !== item_code);
	return first || "";
}

/** Item Name only — never the combined "Code — Name" dropdown label. */
function cgm_item_link_title(label, value) {
	let title = cstr(label).trim();
	const code = cstr(value).trim();

	if (!title) {
		return code;
	}

	if (code) {
		for (const sep of [" — ", " - ", " – "]) {
			const prefix = `${code}${sep}`;
			if (title.startsWith(prefix)) {
				return title.slice(prefix.length).trim() || title;
			}
		}
	}

	if (title === code) {
		const parts = title.split(/\s[-–—]\s/);
		if (parts.length > 1) {
			return parts.slice(1).join(" - ").trim() || title;
		}
	}

	return title;
}

function cgm_format_item_search_row(item) {
	if (cgm_is_link_option_row(item)) {
		return item;
	}

	const item_code = cstr(item.value);
	if (!item_code) {
		return item;
	}

	let item_name = cgm_item_link_title(item.label, item_code);
	if (!item_name || item_name === item_code) {
		item_name = cgm_item_name_from_description(item.description, item_code);
	}

	const display =
		item_name && item_name !== item_code ? `${item_code} - ${item_name}` : item_code;
	item.html = `<strong>${frappe.utils.escape_html(display)}</strong>`;

	if (item.description) {
		item.description = String(item.description)
			.split(",")
			.map((part) => part.trim())
			.filter((part) => part && part !== item_code && part !== item_name)
			.join(", ");
	}

	return item;
}

function cgm_set_item_link_display(control, value, label) {
	if (!control || !value) {
		return;
	}
	if (!control.title_value_map) {
		control.title_value_map = {};
	}
	const display = cgm_item_link_title(label, value);
	control.translate_and_set_input_value(display, value);
	frappe.utils.add_link_title("Item", value, display);
}

function cgm_patch_item_link_search_display() {
	const proto = frappe.ui?.form?.ControlLink?.prototype;
	if (!proto || proto.__cgm_item_link_patched) {
		return;
	}

	const original_merge_duplicates = proto.merge_duplicates;
	proto.merge_duplicates = function (results) {
		const merged = original_merge_duplicates.call(this, results);
		if (!cgm_is_item_link_control(this) || !Array.isArray(merged)) {
			return merged;
		}
		return merged.map(cgm_format_item_search_row);
	};

	const original_parse_validate = proto.parse_validate_and_set_in_model;
	proto.parse_validate_and_set_in_model = function (value, e, label) {
		if (cgm_is_item_link_control(this) && value && label) {
			label = cgm_item_link_title(label, value);
		}
		const result = original_parse_validate.call(this, value, e, label);
		if (cgm_is_item_link_control(this) && value && label) {
			cgm_set_item_link_display(this, value, label);
		}
		return result;
	};

	const original_set_link_title = proto.set_link_title;
	proto.set_link_title = async function (value) {
		if (!cgm_is_item_link_control(this) || !this.is_title_link()) {
			return original_set_link_title.call(this, value);
		}

		const doctype = this.get_options();
		let link_title =
			frappe.utils.get_link_title(doctype, value) ||
			(await frappe.utils.fetch_link_title(doctype, value));

		cgm_set_item_link_display(this, value, link_title);
	};

	const original_setup_awesomeplete = proto.setup_awesomeplete;
	proto.setup_awesomeplete = function () {
		original_setup_awesomeplete.call(this);
		if (!cgm_is_item_link_control(this)) {
			return;
		}

		const control = this;
		this.$input.off("awesomplete-selectcomplete.cgm_item_link");
		this.$input.on("awesomplete-selectcomplete.cgm_item_link", function (e) {
			const suggestion = e.originalEvent?.text;
			if (!suggestion?.value || cstr(suggestion.value).endsWith(ITEM_LINK_OPTION_SUFFIX)) {
				return;
			}

			const item = control.awesomplete?.get_item(suggestion.value);
			cgm_set_item_link_display(
				control,
				suggestion.value,
				item?.label || suggestion.label
			);
		});
	};

	proto.__cgm_item_link_patched = true;
}

cgm_shipping.item_link.patch = cgm_patch_item_link_search_display;
cgm_shipping.item_link.title = cgm_item_link_title;

cgm_patch_item_link_search_display();
$(document).on("app_ready", cgm_patch_item_link_search_display);
