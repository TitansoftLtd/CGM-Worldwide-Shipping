frappe.provide("cgm_shipping.bl_containers");

const BL_CONTAINER_FIELD = "custom_container_information";
const BL_LINK_FIELD = "custom_bill_of_lading";
const BL_CONTAINER_DOCTYPES = ["Lead", "Project", "Opportunity"];
const BL_CONTAINER_SYNC_FIELDS = [
	"container_number",
	"type_of_container",
	"no_container",
	"seal_no",
];

function bl_container_rows(rows) {
	return (rows || []).map((row) => {
		const out = {};
		BL_CONTAINER_SYNC_FIELDS.forEach((field) => {
			out[field] = row[field] ?? "";
		});
		return out;
	});
}

function container_rows_match(existing, from_bl) {
	const current = bl_container_rows(existing);
	const next = bl_container_rows(from_bl);
	if (current.length !== next.length) {
		return false;
	}
	return current.every((row, i) =>
		BL_CONTAINER_SYNC_FIELDS.every((field) => String(row[field]) === String(next[i][field]))
	);
}

function apply_bl_containers(frm, bl_rows) {
	frm.clear_table(BL_CONTAINER_FIELD);
	(bl_rows || []).forEach((row) => {
		const child = frm.add_child(BL_CONTAINER_FIELD);
		BL_CONTAINER_SYNC_FIELDS.forEach((field) => {
			child[field] = row[field];
		});
	});
	frm.refresh_field(BL_CONTAINER_FIELD);
}

function restore_clean_form_state(frm) {
	frappe.after_ajax(() => {
		frm.dirty(false);
		frm.toolbar?.set_indicator?.();
		frm.states?.refresh?.();
	});
}

function is_readonly_bl_container_form(frm) {
	return frm.doctype === "Opportunity" || frm.doctype === "Lead";
}

function show_container_field(frm) {
	if (!frm.doc[BL_LINK_FIELD]) {
		return;
	}
	if (frm.fields_dict[BL_CONTAINER_FIELD]) {
		frm.set_df_property(BL_CONTAINER_FIELD, "hidden", 0);
	}
}

function fetch_bl_container_rows(bill_of_lading) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method: "cgm_shipping.cgm_worldwide_shipping.customizations.bill_of_lading_sync.get_container_rows_for_bill_of_lading",
			args: { bill_of_lading },
			callback(r) {
				if (r.exc) {
					reject(r.exc);
					return;
				}
				resolve(r.message || []);
			},
			error(r) {
				reject(r);
			},
		});
	});
}

/**
 * Wait until depends_on has rendered the container grid (often one tick after link change).
 */
cgm_shipping.bl_containers.schedule_sync = function (frm, opts = {}) {
	const run = () => cgm_shipping.bl_containers.sync_from_bl(frm, opts);

	if (frm.fields_dict[BL_CONTAINER_FIELD]) {
		return run();
	}

	if (!frm.doc[BL_LINK_FIELD]) {
		return Promise.resolve();
	}

	// Re-evaluate depends_on so the table field is mounted in the DOM.
	if (frm.refresh_field) {
		frm.refresh_field(BL_CONTAINER_FIELD);
	}

	return new Promise((resolve) => {
		let attempts = 0;
		const try_sync = () => {
			// Stop retrying if the user has navigated away from this form.
			if (cur_frm !== frm) {
				resolve();
				return;
			}
			attempts += 1;
			if (frm.fields_dict[BL_CONTAINER_FIELD]) {
				run().then(resolve).catch(() => resolve());
				return;
			}
			if (attempts < 8) {
				setTimeout(try_sync, 120);
				return;
			}
			resolve();
		};
		setTimeout(try_sync, 80);
	});
};

/**
 * Copy container rows from linked Bill of Lading into custom_container_information.
 */
cgm_shipping.bl_containers.sync_from_bl = function (frm, opts = {}) {
	const silent = Boolean(opts.silent);

	if (!frm.fields_dict[BL_CONTAINER_FIELD]) {
		return Promise.resolve();
	}

	const existing = frm.doc[BL_CONTAINER_FIELD] || [];

	if (!frm.doc[BL_LINK_FIELD]) {
		if (!existing.length) {
			return Promise.resolve();
		}
		apply_bl_containers(frm, []);
		if (silent) {
			restore_clean_form_state(frm);
		}
		return Promise.resolve();
	}

	show_container_field(frm);

	return fetch_bl_container_rows(frm.doc[BL_LINK_FIELD])
		.then((bl_rows) => {
			if (container_rows_match(existing, bl_rows)) {
				return;
			}
			apply_bl_containers(frm, bl_rows);
			if (silent) {
				restore_clean_form_state(frm);
			} else if (!bl_rows.length) {
				frappe.show_alert({
					message: __("No containers on this Bill of Lading"),
					indicator: "orange",
				});
			}
		})
		.catch((err) => {
			console.error("CGM: failed to load B/L containers", err);
			frappe.show_alert({
				message: __("Could not load containers for this Bill of Lading"),
				indicator: "red",
			});
		});
};

BL_CONTAINER_DOCTYPES.forEach((doctype) => {
	const handlers = {
		custom_bill_of_lading(frm) {
			if (is_readonly_bl_container_form(frm)) {
				// Server syncs containers on save; preview without leaving the form dirty.
				cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
				return;
			}
			cgm_shipping.bl_containers.schedule_sync(frm);
		},
		custom_mode_of_transport(frm) {
			if (is_readonly_bl_container_form(frm)) {
				return;
			}
			cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
		},
	};

	if (doctype === "Project") {
		handlers.refresh = function (frm) {
			cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
		};
	}

	frappe.ui.form.on(doctype, handlers);
});
