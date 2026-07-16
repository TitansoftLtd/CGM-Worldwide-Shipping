// Copyright (c) 2026, Titansoft Limited and contributors
/**
 * Operational Updates — shared list cards + standard Frappe Dialog (Desk + portal).
 */
frappe.provide("cgm.updates");

(() => {
	const DETAIL_METHOD =
		"cgm_shipping.cgm_worldwide_shipping.customizations.operational_updates.get_update_detail";

	function cintSafe(value) {
		if (typeof cint === "function") {
			return cint(value);
		}
		const n = parseInt(value, 10);
		return Number.isNaN(n) ? 0 : n;
	}

	function esc(value) {
		if (frappe.utils && frappe.utils.escape_html) {
			return frappe.utils.escape_html(value == null ? "" : String(value));
		}
		return String(value == null ? "" : value)
			.replace(/&/g, "&amp;")
			.replace(/</g, "&lt;")
			.replace(/>/g, "&gt;")
			.replace(/"/g, "&quot;");
	}

	function relativeTime(postedOn) {
		if (!postedOn) {
			return "";
		}
		if (frappe.datetime && frappe.datetime.prettyDate) {
			return frappe.datetime.prettyDate(postedOn);
		}
		if (frappe.datetime && frappe.datetime.str_to_user) {
			return frappe.datetime.str_to_user(postedOn);
		}
		return String(postedOn);
	}

	function previewMessage(message, maxLines = 3, maxLen = 180) {
		const text = (message || "").trim();
		if (!text) {
			return "";
		}
		const rawLines = text.split(/\r?\n/).filter(Boolean);
		const joined = rawLines.slice(0, maxLines).join(" ");
		const truncated =
			joined.length > maxLen || rawLines.length > maxLines
				? `${joined.slice(0, maxLen).trim()}…`
				: joined;
		return truncated;
	}

	function sourcePillClass(source) {
		const map = {
			Customer: "blue",
			Transporter: "orange",
			Internal: "gray",
			Customs: "cyan",
			Finance: "yellow",
			Other: "gray",
		};
		return map[source] || "gray";
	}

	function summaryMetaLines(row, options = {}) {
		const lines = [];
		if (!options.hideShipment && (row.project_ref || row.project)) {
			lines.push({
				label: __("Shipment"),
				value: row.project_ref || row.project,
			});
		}
		if (!options.hideCustomer && (row.customer_name || row.customer)) {
			lines.push({
				label: __("Customer"),
				value: row.customer_name || row.customer,
			});
		}
		if (row.container_number) {
			lines.push({
				label: __("Container"),
				value: row.container_number,
			});
		}
		return lines;
	}

	function renderMetaLines(lines) {
		if (!lines.length) {
			return "";
		}
		return `<div class="cgm-updates-meta">${lines
			.map(
				(line) =>
					`<div class="cgm-updates-meta-line">
						<span class="cgm-updates-meta-label">${esc(line.label)}:</span>
						<span class="cgm-updates-meta-value">${esc(line.value)}</span>
					</div>`
			)
			.join("")}</div>`;
	}

	function sectionsToDialogFields(sections) {
		const fields = [];
		const values = {};

		(sections || []).forEach((section, sidx) => {
			if (section.label || sidx > 0) {
				fields.push({
					fieldtype: "Section Break",
					fieldname: `section_${sidx}`,
					label: section.label || "",
				});
			}

			(section.fields || []).forEach((f, fidx) => {
				if (f.fieldtype === "Column Break") {
					fields.push({
						fieldtype: "Column Break",
						fieldname: f.fieldname || `column_${sidx}_${fidx}`,
					});
					return;
				}

				const fieldname = f.fieldname || `field_${sidx}_${fidx}`;
				const fieldtype = f.fieldtype || "Data";
				fields.push({
					fieldname,
					label: f.label,
					fieldtype: fieldtype === "Attach" ? "Data" : fieldtype,
					options: fieldtype === "Attach" ? undefined : f.options || undefined,
					read_only: 1,
				});
				if (f.value != null && f.value !== "") {
					values[fieldname] = f.value;
				}
			});
		});

		return { fields, values };
	}

	function stripControlFieldnameTips(dialog) {
		// Website does not load desk form.scss (opacity:0 for .tooltip-content).
		// Same cleanup as portal FieldGroup forms — remove Control fieldname tips.
		Object.values(dialog.fields_dict || {}).forEach((ctrl) => {
			if (!ctrl) {
				return;
			}
			if (ctrl.tooltip && ctrl.tooltip.remove) {
				ctrl.tooltip.remove();
			}
			if (ctrl.$wrapper) {
				ctrl.$wrapper.find(".tooltip-content").remove();
			}
		});
		if (dialog.$wrapper) {
			dialog.$wrapper.find(".tooltip-content").remove();
		}
	}

	function showDialogDetail(detail) {
		const title = detail.subject || __("Update");
		const { fields, values } = sectionsToDialogFields(detail.sections);
		if (!fields.length) {
			frappe.msgprint(__("No details available."));
			return;
		}
		const d = new frappe.ui.Dialog({
			title,
			fields,
			size: "large",
			primary_action_label: __("Close"),
			primary_action() {
				d.hide();
			},
		});
		// Tooltips are created in Control.make() during Dialog construction.
		stripControlFieldnameTips(d);
		d.set_values(values);
		d.show();
		stripControlFieldnameTips(d);
	}

	cgm.updates.renderListItem = function (row, options = {}) {
		const unread = !cintSafe(row.is_read);
		const subject = row.subject || row.update_type || __("Update");
		const source = options.showSource === false ? "" : row.update_source || "";
		const when = relativeTime(row.posted_on);
		const preview = previewMessage(row.message);
		const name = row.name || "";
		const metaLines = summaryMetaLines(row, options);

		return `<div class="list-row-container${unread ? " is-unread" : ""}" data-update="${esc(name)}">
			<div class="cgm-updates-head">
				<div class="cgm-updates-badges">
					<span class="indicator-pill red no-indicator-dot cgm-upd-subject">${esc(subject)}</span>
					${
						source
							? `<span class="indicator-pill ${sourcePillClass(source)} no-indicator-dot cgm-upd-source">${esc(source.toUpperCase())}</span>`
							: ""
					}
				</div>
				${when ? `<span class="cgm-updates-when text-muted small">${esc(when)}</span>` : ""}
			</div>
			<div class="cgm-updates-body">
				<div class="list-row-left">
					${renderMetaLines(metaLines)}
					${preview ? `<div class="cgm-updates-preview">${esc(preview)}</div>` : ""}
				</div>
				<div class="list-row-right">
					<button type="button" class="btn btn-xs btn-default cgm-upd-view-more" data-update="${esc(name)}">
						${__("View More")}
					</button>
				</div>
			</div>
		</div>`;
	};

	cgm.updates.renderCard = cgm.updates.renderListItem;

	cgm.updates.renderList = function (rows, options = {}) {
		const items = (rows || []).map((row) => cgm.updates.renderListItem(row, options));
		return `<div class="cgm-updates-list">${items.join("")}</div>`;
	};

	cgm.updates.openDetail = function (name, options = {}) {
		if (!name) {
			return;
		}

		const portal = options.showSource === false;
		const open = (detail) => {
			const run = () => {
				showDialogDetail(detail);
				if (typeof options.onOpened === "function") {
					options.onOpened(detail);
				}
			};
			if (frappe.ui && frappe.ui.Dialog) {
				run();
			} else {
				frappe.require("dialog.bundle.js", run);
			}
		};

		frappe.call({
			method: options.method || DETAIL_METHOD,
			args: {
				name,
				include_source: portal ? 0 : 1,
			},
			freeze: true,
			callback(r) {
				if (r.exc) {
					return;
				}
				open(r.message || {});
			},
		});
	};

	cgm.updates.markListItemRead = function ($root, name) {
		if (!$root || !name) {
			return;
		}
		const root = $root.jquery ? $root : $($root);
		root
			.find(`.list-row-container[data-update="${esc(name)}"]`)
			.removeClass("is-unread");
	};

	cgm.updates.bindListClicks = function ($root, options = {}) {
		const root = $root && $root.jquery ? $root : $($root || document);
		root.off("click.cgmUpdates").on("click.cgmUpdates", ".cgm-upd-view-more", function (e) {
			e.preventDefault();
			e.stopPropagation();
			const name = $(this).data("update");
			cgm.updates.openDetail(name, {
				showSource: options.showSource,
				method: options.method,
				onOpened(detail) {
					cgm.updates.markListItemRead(root, name);
					if (typeof options.onOpened === "function") {
						options.onOpened(detail, name);
					}
				},
			});
		});
	};

	cgm.updates.mount = function (root, rows, options = {}) {
		const $root = root && root.jquery ? root : $(root);
		if (!$root.length) {
			return;
		}
		$root.html(cgm.updates.renderList(rows || [], options));
		cgm.updates.bindListClicks($root, options);
	};

	cgm.updates.bindCardClicks = cgm.updates.bindListClicks;
})();
