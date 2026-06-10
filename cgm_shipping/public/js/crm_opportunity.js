frappe.ui.form.on("Opportunity", {
    onload(frm) {
        register_clients_documents_remove_handler(frm);
        sync_opportunity_transport_and_containers(frm);
        setup_opportunity_bill_of_lading_create(frm);
        apply_pending_bl_from_submit(frm);
        sync_bl_from_clients_documents(frm);
    },

    refresh(frm) {
        hide_procurement_create_buttons(frm);
        register_clients_documents_remove_handler(frm);
        sync_opportunity_transport_and_containers(frm);
        setup_opportunity_bill_of_lading_create(frm);
        apply_pending_bl_from_submit(frm);
        sync_bl_from_clients_documents(frm);
        setup_create_shipment_project_button(frm);
    },

    custom_shipment_type(frm) {
        sync_opportunity_transport_and_containers(frm);
    },
});

frappe.ui.form.on("Shipment Document", {
    custom_clients_documents_add(frm, cdt, cdn) {
        frappe.model.set_value(cdt, cdn, "uploaded_by", frappe.session.user);
        frappe.model.set_value(cdt, cdn, "uploaded_on", frappe.datetime.now_datetime());
    },
});

function meta_has_field(doctype, fieldname) {
    const meta = doctype && frappe.get_meta(doctype);
    return Boolean(meta && (meta.fields || []).some((df) => df.fieldname === fieldname));
}

function get_shipment_documents_field(frm) {
    for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
        if (df.fieldtype !== "Table") {
            continue;
        }
        if (
            meta_has_field(df.options, "document_type") &&
            meta_has_field(df.options, "document_reference")
        ) {
            return df.fieldname;
        }
    }
    return null;
}

function get_link_field_for_doctype(frm, linked_doctype) {
    if (!linked_doctype) {
        return null;
    }
    for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
        if (df.fieldtype === "Link" && df.options === linked_doctype) {
            return df.fieldname;
        }
    }
    return null;
}

function linked_doctype_has_container_table(doctype) {
    const meta = frappe.get_meta(doctype);
    if (!meta) {
        return false;
    }
    return meta.fields.some((df) => {
        if (df.fieldtype !== "Table") {
            return false;
        }
        return meta_has_field(df.options, "container_number");
    });
}

function get_opportunity_bl_link_field(frm) {
    for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
        if (df.fieldtype !== "Link" || !df.options) {
            continue;
        }
        if (linked_doctype_has_container_table(df.options)) {
            return df.fieldname;
        }
    }
    return null;
}

function get_container_table_field(frm) {
    for (const df of frappe.meta.get_docfields(frm.doctype, frm.doc.name)) {
        if (df.fieldtype !== "Table") {
            continue;
        }
        if (meta_has_field(df.options, "container_number")) {
            return df.fieldname;
        }
    }
    return null;
}

function get_quantity_field(frm, bl_link_field) {
    if (!bl_link_field) {
        return null;
    }
    const fields = frappe.meta.get_docfields(frm.doctype, frm.doc.name);
    const start = fields.findIndex((df) => df.fieldname === bl_link_field);
    if (start < 0) {
        return null;
    }
    for (let i = start + 1; i < fields.length; i++) {
        const df = fields[i];
        if (df.fieldtype === "Section Break" || df.fieldtype === "Tab Break") {
            break;
        }
        if (df.fieldtype === "Table") {
            break;
        }
        if (["Data", "Float", "Int"].includes(df.fieldtype)) {
            return df.fieldname;
        }
    }
    return null;
}

function find_populate_containers_row(frm) {
    const docs_field = get_shipment_documents_field(frm);
    if (!docs_field) {
        return null;
    }
    return (frm.doc[docs_field] || []).find(
        (row) => cint(row.populate_containers) && row.document_reference
    );
}


// ─── Clients Documents remove handler ─────────────────────────────────────────

function register_clients_documents_remove_handler(frm) {
    const docs_field = get_shipment_documents_field(frm);
    if (!docs_field || frm.__cgm_docs_remove_registered) {
        return;
    }
    frm.__cgm_docs_remove_registered = true;

    frappe.ui.form.on("Opportunity", {
        [docs_field + "_remove"](frm) {
            on_clients_documents_removed(frm);
        },
    });
}

function on_clients_documents_removed(frm) {
    const bl_row = find_populate_containers_row(frm);
    if (bl_row) {
        fetch_and_apply_bl_data(frm, bl_row);
        return;
    }
    clear_bl_derived_opportunity_fields(frm);
}


// ─── Transport & container sync ───────────────────────────────────────────────

function sync_opportunity_transport_and_containers(frm) {
    const bl_link_field = get_opportunity_bl_link_field(frm);
    cgm_shipping.transport_reference.toggle(frm, {
        air_waybill: "custom_air_waybill",
        bill_of_lading: bl_link_field || undefined,
        section: "custom_section_break_idqn5",
    });
}


// ─── Bill of Lading create route ──────────────────────────────────────────────

function is_saved_opportunity_name(name) {
    return Boolean(name && !String(name).startsWith("new-"));
}

function setup_opportunity_bill_of_lading_create(frm) {
    const bl_link_field = get_opportunity_bl_link_field(frm);
    const df = bl_link_field && frm.get_docfield(bl_link_field);
    if (!df || frm._cgm_bl_create_route_setup) {
        return;
    }

    frm._cgm_bl_create_route_setup = true;
    df.get_route_options_for_new_doc = () => {
        const opts = {};
        if (frm.doc.name) {
            localStorage.setItem("cgm_return_opportunity", frm.doc.name);
        }
        if (is_saved_opportunity_name(frm.doc.name)) {
            const linked_doctype = df.options;
            if (linked_doctype) {
                const linked_meta = frappe.get_meta(linked_doctype);
                const opp_link_field = linked_meta?.fields?.find(
                    (field) =>
                        field.fieldtype === "Link" &&
                        field.options === frm.doctype
                );
                if (opp_link_field) {
                    opts[opp_link_field.fieldname] = frm.doc.name;
                }
            }
        }
        return opts;
    };
}


// ─── Pending BL from submit ───────────────────────────────────────────────────

function apply_pending_bl_from_submit(frm) {
    if (!frm.doc.name) {
        return;
    }

    let pending;
    try {
        pending = JSON.parse(localStorage.getItem("cgm_pending_bl_link") || "null");
    } catch {
        return;
    }

    if (!pending || pending.opportunity !== frm.doc.name) {
        return;
    }

    const bl_link_field =
        get_link_field_for_doctype(frm, pending.linked_doctype) ||
        get_opportunity_bl_link_field(frm);
    const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;
    const docs_field = get_shipment_documents_field(frm);

    if (pending.bl_name && bl_link_field && frm.doc[bl_link_field] !== pending.bl_name) {
        frm.set_value(bl_link_field, pending.bl_name);
    }
    if (pending.quantity && quantity_field) {
        frm.set_value(quantity_field, pending.quantity);
    }
    if (pending.attachment && docs_field && pending.document_type) {
        prepend_opportunity_bl_client_document(frm, pending, docs_field);
    }
    if (cgm_shipping?.bl_containers?.schedule_sync) {
        cgm_shipping.bl_containers.schedule_sync(frm, { silent: true });
    }

    localStorage.removeItem("cgm_pending_bl_link");
    frappe.show_alert({
        message: __("Bill of Lading {0} linked - continue completing this Opportunity.", [
            pending.bl_name,
        ]),
        indicator: "green",
    });
}

function prepend_opportunity_bl_client_document(frm, pending, docs_field) {
    const rows = frm.doc[docs_field] || [];

    const already_exists = rows.some(
        (row) =>
            row.document_type === pending.document_type ||
            row.attachment === pending.attachment
    );
    if (already_exists) {
        return;
    }

    frm.clear_table(docs_field);
    frm.add_child(docs_field, {
        document_type: pending.document_type,
        attachment: pending.attachment,
        status: "Uploaded",
    });
    rows.forEach((row) => {
        frm.add_child(docs_field, {
            document_type: row.document_type,
            attachment: row.attachment,
            status: row.status,
            uploaded_by: row.uploaded_by,
            uploaded_on: row.uploaded_on,
            verified_by: row.verified_by,
            verified_on: row.verified_on,
            remarks: row.remarks,
        });
    });
    frm.refresh_field(docs_field);
}


// ─── BL data sync (single API call) ───────────────────────────────────────────

function sync_bl_from_clients_documents(frm) {
    if (frm.doc.docstatus !== 0) {
        return;
    }
    const bl_row = find_populate_containers_row(frm);
    if (!bl_row) {
        const bl_link_field = get_opportunity_bl_link_field(frm);
        if (!bl_link_field || !frm.doc[bl_link_field]) {
            clear_bl_derived_opportunity_fields(frm);
        }
        return;
    }
    fetch_and_apply_bl_data(frm, bl_row);
}

function fetch_and_apply_bl_data(frm, row, cdt, cdn) {
    if (!row.document_reference) {
        return;
    }

    frappe.call({
        method:
            "cgm_shipping.cgm_worldwide_shipping.customizations.bl_containers.get_containers_for_bl_attachment",
        args: { attachment: row.document_reference },
        callback(r) {
            if (r.exc || !r.message) {
                return;
            }
            apply_bl_data_from_response(frm, row, cdt, cdn, r.message);
        },
    });
}

function apply_bl_data_from_response(frm, row, cdt, cdn, data) {
    const bl_link_field = get_link_field_for_doctype(frm, row.linked_doctype);
    const container_field = get_container_table_field(frm);
    const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;

    if (cdt && cdn) {
        frappe.model.set_value(cdt, cdn, "attachment", data.attachment || "");
    } else if (row.name) {
        frappe.model.set_value(row.doctype, row.name, "attachment", data.attachment || "");
    }

    if (bl_link_field) {
        frm.set_value(bl_link_field, row.document_reference);
    }
    if (quantity_field) {
        frm.set_value(quantity_field, data.quantity || "");
    }

    if (container_field && !container_rows_match(frm.doc[container_field], data.containers)) {
        frm.clear_table(container_field);
        (data.containers || []).forEach((container) => {
            Object.assign(frm.add_child(container_field), container);
        });
        frm.refresh_field(container_field);
    }
}

function container_rows_match(existing, incoming) {
    existing = existing || [];
    incoming = incoming || [];
    if (existing.length !== incoming.length) {
        return false;
    }
    return incoming.every((row, i) =>
        Object.keys(row).every(
            (key) => (existing[i]?.[key] ?? "") === (row[key] ?? "")
        )
    );
}

function clear_bl_derived_opportunity_fields(frm) {
    const bl_link_field = get_opportunity_bl_link_field(frm);
    const container_field = get_container_table_field(frm);
    const quantity_field = bl_link_field ? get_quantity_field(frm, bl_link_field) : null;

    if (container_field && (frm.doc[container_field] || []).length) {
        frm.clear_table(container_field);
        frm.refresh_field(container_field);
    }
    if (quantity_field && frm.doc[quantity_field]) {
        frm.set_value(quantity_field, "");
    }
    if (bl_link_field && frm.doc[bl_link_field]) {
        frm.set_value(bl_link_field, "");
    }
}

function setup_create_shipment_project_button(frm) {
    if (
        frm.doc.workflow_state !== "Approved" ||
        frm.doc.opportunity_from !== "Customer"
    ) {
        return;
    }

    frappe.db
        .get_value("Project", { custom_source_opportunity: frm.doc.name }, "name")
        .then((r) => {
            const existing = r?.message?.name;
            if (existing) {
                frm.add_custom_button(
                    __("View Project"),
                    () => frappe.set_route("Form", "Project", existing),
                    __("Create")
                );
            } else {
                frm.add_custom_button(
                    __("Create Shipment Project"),
                    () => {
                        frappe.call({
                            method:
                                "cgm_shipping.cgm_worldwide_shipping.customizations.project.create_project_from_opportunity",
                            args: { opportunity: frm.doc.name },
                            freeze: true,
                            callback(r) {
                                if (!r.exc && r.message) {
                                    frappe.show_alert({
                                        message: __("Shipment Project created"),
                                        indicator: "green",
                                    });
                                    frappe.set_route("Form", "Project", r.message);
                                }
                            },
                        });
                    },
                    __("Create")
                );
            }
            frm.page.set_inner_btn_group_as_primary(__("Create"));
        });
}

function hide_procurement_create_buttons(frm) {
    const remove = () => {
        frm.remove_custom_button(__("Supplier Quotation"), __("Create"));
        frm.remove_custom_button(__("Request For Quotation"), __("Create"));
    };
    remove();
    [50, 200, 600].forEach((delay) => setTimeout(remove, delay));
}
