// Copyright (c) 2026, Titansoft Limited and contributors
/**
 * Portal update forms — standard Frappe FieldGroup controls (transporter + customer).
 */
frappe.provide("cgm.updates");

(() => {
	function subjectOptions(updateTypes) {
		const opts = (updateTypes || []).filter(Boolean);
		return [""].concat(opts).join("\n");
	}

	function normalizeFields(fields) {
		return fields.map((df, idx) => {
			const next = { ...df };
			if (
				(next.fieldtype === "Column Break" || next.fieldtype === "Section Break") &&
				!next.fieldname
			) {
				next.fieldname = `${next.fieldtype.replace(/ /g, "_").toLowerCase()}_${idx}`;
			}
			if (next.fieldtype === "Section Break" || next.fieldtype === "Column Break") {
				next.label = next.label || "";
			}
			return next;
		});
	}

	function getTransporterFieldDefs(updateTypes, options = {}) {
		const fields = [];
		if (options.containerOptions) {
			fields.push({
				fieldname: "allocation_item",
				label: __("Container"),
				fieldtype: "Select",
				options: [""]
					.concat(
						(options.containerOptions || []).map((c) =>
							typeof c === "object" ? c.value || c.name || "" : c
						)
					)
					.filter((v, i, arr) => v || i === 0)
					.join("\n"),
				reqd: 1,
			});
			fields.push({ fieldtype: "Section Break" });
		}

		fields.push(
			{
				fieldname: "subject",
				label: __("Subject"),
				fieldtype: "Select",
				options: subjectOptions(updateTypes),
				reqd: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "event_date",
				label: __("Event Date"),
				fieldtype: "Date",
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "truck_number",
				label: __("Truck Number"),
				fieldtype: "Data",
				depends_on: "eval:doc.subject=='Truck Changed'",
				mandatory_depends_on: "eval:doc.subject=='Truck Changed'",
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "driver_name",
				label: __("Driver Name"),
				fieldtype: "Data",
				depends_on: "eval:doc.subject=='Truck Changed'",
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "driver_contact",
				label: __("Driver Contact"),
				fieldtype: "Data",
				depends_on: "eval:doc.subject=='Truck Changed'",
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "message",
				label: __("Message"),
				fieldtype: "Small Text",
				mandatory_depends_on: "eval:doc.subject=='Delayed' || doc.subject=='Other'",
			},
			{
				fieldname: "attachment",
				label: __("Attachment"),
				fieldtype: "Attach",
			}
		);
		return fields;
	}

	function getCustomerFieldDefs() {
		return [
			{
				fieldname: "subject",
				label: __("Subject"),
				fieldtype: "Data",
				reqd: 1,
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "message",
				label: __("Message"),
				fieldtype: "Small Text",
				reqd: 1,
			},
		];
	}

	function applyAttachOptions(fg, options = {}) {
		const attach = fg.fields_dict && fg.fields_dict.attachment;
		if (!attach) {
			return;
		}
		const original = attach.set_upload_options.bind(attach);
		attach.set_upload_options = function () {
			original();
			this.upload_options = Object.assign({}, this.upload_options || {}, {
				doctype: options.doctype || "Container Allocation",
				docname: options.docname || undefined,
				restrictions: Object.assign({}, (this.upload_options && this.upload_options.restrictions) || {}, {
					allowed_file_types: [".pdf", ".jpg", ".jpeg", ".png", "image/*"],
				}),
			});
		};
	}

	function hideEmptySectionHeads($root) {
		$root.find(".section-head, .section-head.collapsible").each(function () {
			const text = ($(this).text() || "").trim();
			if (!text) {
				$(this).hide();
			}
		});
		$root.find(".tooltip-content").remove();
		$root.find(".help-box, .description").hide();
	}

	function applyContainerLabels(fg, containerOptions) {
		const control = fg.fields_dict && fg.fields_dict.allocation_item;
		if (!control || !control.$input || !(containerOptions || []).length) {
			return;
		}
		const labelByValue = {};
		(containerOptions || []).forEach((c) => {
			const value = (c && (c.value || c.name)) || c;
			const label = (c && (c.label || c.container_number)) || value;
			labelByValue[value] = label;
		});
		control.$input.find("option").each(function () {
			const val = this.value;
			if (val && labelByValue[val]) {
				$(this).text(labelByValue[val]);
			}
		});
	}

	function buildFieldGroup(wrapper, fields, options = {}) {
		const $wrapper = $(wrapper);
		$wrapper.empty().addClass("tp-update-form-wrap");

		if (!(frappe.ui && frappe.ui.FieldGroup)) {
			$wrapper.html(
				`<div class="text-danger">${__("Form controls failed to load. Please refresh the page.")}</div>`
			);
			return null;
		}

		const fieldsRoot = $('<div class="tp-update-field-group form-layout">').appendTo($wrapper);
		const fg = new frappe.ui.FieldGroup({
			fields: normalizeFields(fields),
			body: fieldsRoot,
		});
		fg.make();
		applyAttachOptions(fg, options);
		applyContainerLabels(fg, options.containerOptions);
		fg.refresh_dependency();
		hideEmptySectionHeads(fieldsRoot);

		if (fg.fields_dict.subject) {
			fg.fields_dict.subject.df.change = () => {
				fg.refresh_dependency();
				hideEmptySectionHeads(fieldsRoot);
			};
		}

		return { fg, fieldsRoot, $wrapper };
	}

	cgm.updates.buildTransporterForm = function (wrapper, options = {}) {
		const built = buildFieldGroup(
			wrapper,
			getTransporterFieldDefs(options.updateTypes || [], options),
			options
		);
		if (!built) {
			return null;
		}
		const { fg, fieldsRoot, $wrapper } = built;

		const actions = $('<div class="tp-update-actions">').appendTo($wrapper);
		const $btn = $(
			`<button type="button" class="cp-btn tp-post-update">
				<span class="tp-btn-label">${__("Post Update")}</span>
			</button>`
		).appendTo(actions);

		return {
			field_group: fg,
			$btn,
			getValues() {
				const values = fg.get_values(true) || {};
				return {
					allocation_item: (values.allocation_item || "").trim(),
					subject: (values.subject || "").trim(),
					event_date: values.event_date || "",
					message: (values.message || "").trim(),
					attachment: values.attachment || "",
					truck_number: (values.truck_number || "").trim(),
					driver_name: (values.driver_name || "").trim(),
					driver_contact: (values.driver_contact || "").trim(),
				};
			},
			validate() {
				const values = this.getValues();
				if (options.containerOptions && !values.allocation_item) {
					frappe.msgprint({
						title: __("Container"),
						indicator: "orange",
						message: __("Select a container."),
					});
					return null;
				}
				if (!values.subject) {
					frappe.msgprint({
						title: __("Subject"),
						indicator: "orange",
						message: __("Select a subject."),
					});
					return null;
				}
				if (values.subject === "Truck Changed" && !values.truck_number) {
					frappe.msgprint({
						title: __("Truck Number"),
						indicator: "orange",
						message: __("Enter the new truck number."),
					});
					return null;
				}
				if ((values.subject === "Delayed" || values.subject === "Other") && !values.message) {
					frappe.msgprint({
						title: __("Message"),
						indicator: "orange",
						message: __("Add a short message for this update."),
					});
					return null;
				}
				return values;
			},
			clear() {
				const blank = {
					subject: "",
					event_date: "",
					message: "",
					attachment: "",
					truck_number: "",
					driver_name: "",
					driver_contact: "",
				};
				if (options.containerOptions) {
					blank.allocation_item = "";
				}
				fg.set_values(blank);
				fg.refresh_dependency();
				hideEmptySectionHeads(fieldsRoot);
			},
		};
	};

	cgm.updates.buildCustomerForm = function (wrapper, options = {}) {
		const built = buildFieldGroup(wrapper, getCustomerFieldDefs(), options);
		if (!built) {
			return null;
		}
		const { fg, fieldsRoot, $wrapper } = built;

		const actions = $('<div class="tp-update-actions">').appendTo($wrapper);
		const $btn = $(
			`<button type="button" class="cp-btn cp-btn-primary" id="cgm-post-update-btn">
				<span class="tp-btn-label">${__("Send update")}</span>
			</button>`
		).appendTo(actions);

		return {
			field_group: fg,
			$btn,
			getValues() {
				const values = fg.get_values(true) || {};
				return {
					subject: (values.subject || "").trim(),
					message: (values.message || "").trim(),
				};
			},
			validate() {
				const values = this.getValues();
				if (!values.subject) {
					frappe.msgprint({
						title: __("Subject"),
						indicator: "orange",
						message: __("Enter a subject."),
					});
					return null;
				}
				if (!values.message) {
					frappe.msgprint({
						title: __("Message"),
						indicator: "orange",
						message: __("Enter a message."),
					});
					return null;
				}
				return values;
			},
			clear() {
				fg.set_values({ subject: "", message: "" });
				fg.refresh_dependency();
				hideEmptySectionHeads(fieldsRoot);
			},
		};
	};

	cgm.updates.mountTransporterForms = function (root, options = {}) {
		const page = root && root.jquery ? root[0] : root;
		if (!page) {
			return;
		}
		page.querySelectorAll(".tp-update-form-mount").forEach((el) => {
			const form = cgm.updates.buildTransporterForm(el, {
				...options,
				doctype: options.doctype || "Container Allocation",
				docname: options.docname || page.dataset.allocation || "",
			});
			if (form) {
				el._cgmUpdateForm = form;
			}
		});
	};

	cgm.updates.mountCustomerForm = function (root, options = {}) {
		const el = root && root.jquery ? root[0] : root;
		if (!el) {
			return null;
		}
		const form = cgm.updates.buildCustomerForm(el, options);
		if (form) {
			el._cgmUpdateForm = form;
		}
		return form;
	};
})();
