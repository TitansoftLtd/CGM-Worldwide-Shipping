// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const METHOD_PREFIX =
    "cgm_shipping.cgm_worldwide_shipping.doctype.additional_salary_tool.additional_salary_tool";

// Browser-local autosave key — survives an offline reload / crash without needing the server.
const LOCAL_KEY = "ast_local_draft";

frappe.ui.form.on("Additional Salary Tool", {
    setup(frm) {
        const wrapper = $(frm.fields_dict.employees_html.wrapper);

        // Banner (top): offers to resume a draft saved in a previous session.
        frm.banner_area = $("<div class='ast-banner'>").appendTo(wrapper);

        // Toolbar sits directly above the table so "Get Employees" is easy to find.
        // The two template actions are grouped under a single "Template" dropdown.
        frm.toolbar_area = $(`
            <div class="ast-toolbar">
                <button class="btn btn-sm ast-btn ast-get-employees">
                    ${frappe.utils.icon("users", "sm")} ${__("Get Employees")}
                </button>
                <div class="btn-group">
                    <button type="button" class="btn btn-sm ast-btn ast-template-toggle dropdown-toggle"
                        data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
                        ${frappe.utils.icon("exchange", "sm")} ${__("Import / Export")}
                        ${frappe.utils.icon("select", "xs")}
                    </button>
                    <ul class="dropdown-menu">
                        <li><a class="dropdown-item ast-download-template" href="#">
                            ${frappe.utils.icon("download", "sm")} ${__("Download")}
                        </a></li>
                        <li><a class="dropdown-item ast-upload-template" href="#">
                            ${frappe.utils.icon("upload", "sm")} ${__("Upload")}
                        </a></li>
                    </ul>
                </div>
                <button class="btn btn-sm ast-btn ast-save-draft">
                    ${frappe.utils.icon("save", "sm")} ${__("Save Draft")}
                </button>
            </div>
        `).appendTo(wrapper);

        frm.toolbar_area.find(".ast-get-employees").on("click", () => frm.events.load_employees(frm));
        frm.toolbar_area.find(".ast-download-template").on("click", (e) => {
            e.preventDefault();
            frm.events.download_template(frm);
        });
        frm.toolbar_area.find(".ast-upload-template").on("click", (e) => {
            e.preventDefault();
            frm.events.upload_template(frm);
        });
        frm.toolbar_area.find(".ast-save-draft").on("click", () => frm.events.save_draft(frm));

        frm.grid_area = $("<div class='ast-grid-area'>").appendTo(wrapper);

        // Compact styling so all component columns fit without wrapping cells/rows.
        // Always replace any previous copy so style tweaks take effect without a hard refresh.
        $("#ast-grid-style").remove();
        {
            $(`<style id="ast-grid-style">
                .ast-draft-banner {
                    display: flex; align-items: center; gap: 10px;
                    background: #eef2ff; border: 1px solid #c7d2fe; color: #3730a3;
                    border-radius: 8px; padding: 8px 12px; margin-bottom: 12px; font-size: 12px;
                }
                .ast-draft-banner .icon { width: 14px; height: 14px; }
                .ast-toolbar { display: flex; gap: 10px; margin-bottom: 12px; align-items: center; }
                .ast-toolbar .ast-btn {
                    display: inline-flex; align-items: center; gap: 6px;
                    font-weight: 600; border-radius: 8px; border: none; color: #fff;
                    padding: 7px 16px; box-shadow: 0 2px 5px rgba(0,0,0,0.15);
                    transition: transform 0.12s ease, box-shadow 0.12s ease, filter 0.12s ease;
                }
                .ast-toolbar .ast-btn:hover, .ast-toolbar .ast-btn:focus {
                    color: #fff; filter: brightness(1.06);
                    transform: translateY(-1px); box-shadow: 0 4px 10px rgba(0,0,0,0.22);
                }
                .ast-toolbar .ast-btn:active { transform: translateY(0); }
                /* Get Employees — indigo/violet */
                .ast-toolbar .ast-get-employees {
                    background: linear-gradient(135deg, #6366f1, #8b5cf6);
                }
                /* Import / Export — teal/green */
                .ast-toolbar .ast-template-toggle {
                    background: linear-gradient(135deg, #0ea5e9, #10b981);
                }
                /* Save Draft — amber */
                .ast-toolbar .ast-save-draft {
                    background: linear-gradient(135deg, #f59e0b, #f97316);
                }
                .ast-toolbar .ast-btn .icon { width: 14px; height: 14px; fill: #fff; }
                .ast-toolbar .dropdown-menu .dropdown-item {
                    display: flex; align-items: center; gap: 8px;
                }
                .ast-toolbar .dropdown-menu .ast-download-template .icon { color: #0ea5e9; }
                .ast-toolbar .dropdown-menu .ast-upload-template .icon { color: #10b981; }
                .ast-grid-area .ast-grid-controls {
                    display: flex; align-items: center; gap: 10px; margin-bottom: 6px;
                }
                .ast-grid-area .ast-summary { font-size: 12px; }
                .ast-grid-area .ast-remove-selected {
                    display: none; align-items: center; gap: 6px;
                    font-weight: 600; border-radius: 6px; border: none; color: #fff;
                    background: linear-gradient(135deg, #ef4444, #dc2626);
                }
                .ast-grid-area .ast-remove-selected:hover { color: #fff; filter: brightness(1.06); }
                /* Auto layout + width:auto so the table sizes to its CONTENT instead of
                   stretching every column to fill the container. Frappe's default .table CSS is
                   width:100% with an even column spread — the !important overrides win that, so
                   each column (No., Employee, Employee Name, delete) hugs its own data. */
                .ast-grid-area .table {
                    font-size: 13px;
                    width: auto !important;
                    table-layout: auto !important;
                }
                .ast-grid-area .table th,
                .ast-grid-area .table td {
                    padding: 5px 12px;
                    white-space: nowrap;
                    vertical-align: middle;
                    width: 1%; /* with auto layout this just means "shrink to fit content" */
                }
                /* Select column hugs its checkbox, the same as the No. column. */
                .ast-grid-area .table th.ast-col-check,
                .ast-grid-area .table td.ast-row-check {
                    text-align: center;
                    padding: 4px 8px;
                }
                .ast-grid-area .ast-amount {
                    height: 28px;
                    padding: 2px 6px;
                    font-size: 13px;
                    width: 100%;          /* fill the column cell */
                    min-width: 80px;
                }
                /* Search lives above the table (not in a header cell), so it never
                   stretches the label columns — every column hugs its own content. */
                .ast-grid-area .ast-search {
                    height: 28px; font-size: 13px; width: 260px; flex: 0 0 260px;
                }
                /* Clickable sort headers. */
                .ast-grid-area .ast-sortable { cursor: pointer; user-select: none; }
                .ast-grid-area .ast-sortable:hover { background: rgba(0,0,0,0.04); }
                .ast-grid-area .ast-sort-ind { font-size: 9px; color: #6366f1; }
                /* Component header: fill icon | name | delete ✕, each in its own slot (flex) so the
                   ✕ never overlaps long component names. */
                .ast-grid-area .ast-comp-inner {
                    display: flex; align-items: center; gap: 6px; white-space: nowrap;
                }
                .ast-grid-area .ast-comp-name { flex: 1 1 auto; text-align: right; }
                /* Fill-down icon in component headers. */
                .ast-grid-area .ast-fill { cursor: pointer; color: #10b981; font-weight: bold; }
                .ast-grid-area .ast-fill:hover { color: #059669; }
                /* Per-column (salary component) delete button in the headers. */
                .ast-grid-area .ast-col-del { cursor: pointer; color: #cbd5e1; font-weight: bold; }
                .ast-grid-area .ast-col-del:hover { color: #ef4444; }
                /* Base column (toggled by the "Show base" checkbox). */
                .ast-grid-area .ast-hide-base .ast-base-head,
                .ast-grid-area .ast-hide-base .ast-base-cell { display: none; }
                .ast-grid-area .ast-base { height: 28px; font-size: 13px; width: 100%; min-width: 90px; }
                /* Employees with no Salary Structure Assignment stand out (amber). */
                .ast-grid-area .ast-base[data-assigned="0"] {
                    background: #fff7ed; border-color: #fdba74;
                }
                .ast-grid-area .ast-base[data-assigned="0"]::placeholder { color: #c2410c; }
                .ast-grid-area .ast-show-base {
                    display: inline-flex; align-items: center; gap: 5px;
                    font-size: 12px; font-weight: 600; color: #475569; cursor: pointer;
                    margin: 0 0 0 auto;  /* push to the extreme right of the controls row */
                    white-space: nowrap;
                }
                /* Clickable employee id (opens the Employee record in a new tab). */
                .ast-grid-area .ast-emp-link { color: #6366f1; font-weight: 600; }
                .ast-grid-area .ast-emp-link:hover { color: #4f46e5; text-decoration: underline; }
            </style>`).appendTo("head");
        }
    },

    onload(frm) {
        frm.disable_save();
        // Only components that take a manually-entered amount: enabled, with no fixed amount
        // and no formula. Uses a NULL-safe server query (see manual_amount_salary_components).
        frm.set_query("salary_components", () => ({
            query: `${METHOD_PREFIX}.manual_amount_salary_components`,
        }));

        if (!frm.doc.is_once && !frm.doc.is_recurring) {
            frm.set_value("is_once", 1);
        }
        if (!frm.doc.payroll_date) {
            frm.set_value("payroll_date", frappe.datetime.get_today());
        }
        if (!frm.doc.company) {
            frappe.db
                .get_value("Employee", { user_id: frappe.session.user }, "company")
                .then((r) => {
                    const company =
                        (r.message && r.message.company) ||
                        frappe.defaults.get_user_default("Company");
                    if (company) frm.set_value("company", company);
                });
        }

        // Recover unsaved local work first (e.g. after a disconnection); otherwise offer the
        // server-side draft saved in a previous session.
        const localSnap = frm.events.local_get();
        if (localSnap && localSnap.rows && localSnap.rows.length) {
            frm.events.show_local_banner(frm);
        } else {
            frappe.call({
                method: `${METHOD_PREFIX}.get_draft`,
                callback: (r) => {
                    if (r.message && r.message.data) frm.events.show_draft_banner(frm);
                },
            });
        }
    },

    show_draft_banner(frm) {
        if (!frm.banner_area) return;
        frm.banner_area.html(`
            <div class="ast-draft-banner">
                ${frappe.utils.icon("history", "sm")}
                <span>${__("You have a saved draft from a previous session.")}</span>
                <button class="btn btn-xs btn-primary ast-banner-resume">${__("Resume")}</button>
                <button class="btn btn-xs ast-banner-dismiss">${__("Dismiss")}</button>
            </div>
        `);
        frm.banner_area.find(".ast-banner-resume").on("click", () => {
            frm.banner_area.empty();
            frm.events.restore_draft(frm);
        });
        frm.banner_area.find(".ast-banner-dismiss").on("click", () => frm.banner_area.empty());
    },

    refresh(frm) {
        frm.disable_save();

        // Critical sizing rules, re-injected on EVERY visit. setup() runs only once per cached
        // form instance, so its <style> can go stale after a code change; this fresh copy is
        // appended last with !important so it always wins (keeps the table content-width and the
        // select/delete columns narrow).
        $("#ast-grid-style-fix").remove();
        $(`<style id="ast-grid-style-fix">
            .ast-grid-area .table { width: auto !important; table-layout: auto !important; }
            .ast-grid-area .table th.ast-col-check,
            .ast-grid-area .table td.ast-row-check { text-align: center; }
            /* Lively primary action button (the page-header button isn't inside .ast-grid-area). */
            .btn-primary.ast-primary-action {
                background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
                border-color: transparent !important;
                font-weight: 600;
                box-shadow: 0 2px 6px rgba(99,102,241,0.45) !important;
                transition: filter 0.12s ease, box-shadow 0.12s ease, transform 0.12s ease;
            }
            .btn-primary.ast-primary-action:hover,
            .btn-primary.ast-primary-action:focus {
                filter: brightness(1.08); transform: translateY(-1px);
                box-shadow: 0 4px 12px rgba(99,102,241,0.55) !important;
            }
            .btn-primary.ast-primary-action:active { transform: translateY(0); }
            .btn-primary.ast-primary-action .icon { fill: #fff; }
            /* Branded dialogs (results popup + allocation dialog). */
            .ast-dialog .modal-header {
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border-bottom: none;
            }
            .ast-dialog .modal-header .modal-title,
            .ast-dialog .modal-header .indicator-pill,
            .ast-dialog .modal-header .btn-modal-close { color: #fff !important; }
            .ast-dialog .modal-header .btn-modal-close .icon { stroke: #fff; fill: #fff; }
            .ast-dialog .modal-header .indicator-pill::before { display: none; }
            .ast-dialog .modal-footer .btn-primary {
                background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
                border-color: transparent !important; font-weight: 600;
                box-shadow: 0 2px 6px rgba(99,102,241,0.4) !important;
            }
            .ast-dialog .modal-footer .btn-primary:hover { filter: brightness(1.08); }
        </style>`).appendTo("head");

        // Toolbar actions (Get Employees / Import-Export / Save Draft) live in setup.
        frm.page.set_primary_action(
            __("Create Additional Salaries"),
            () => frm.events.create_additional_salaries(frm),
            "add"
        );
        frm.page.btn_primary.addClass("ast-primary-action");

        // Warn before closing/reloading the tab with un-created amounts still in the grid.
        $(window)
            .off("beforeunload.ast")
            .on("beforeunload.ast", function (e) {
                if (
                    frm.grid_rendered &&
                    frm.grid_area &&
                    document.body.contains(frm.grid_area[0]) &&
                    frm.events.collect_rows(frm).length
                ) {
                    const msg = __("You have unsaved amounts that haven't been submitted yet.");
                    e.returnValue = msg;
                    return msg;
                }
            });
    },


    is_once(frm) {
        if (frm.doc.is_once && frm.doc.is_recurring) {
            frm.set_value("is_recurring", 0);
        } else if (!frm.doc.is_once && !frm.doc.is_recurring) {
            frm.set_value("is_once", 1); // never allow both off
        }
    },

    is_recurring(frm) {
        if (frm.doc.is_recurring && frm.doc.is_once) {
            frm.set_value("is_once", 0);
        } else if (!frm.doc.is_recurring && !frm.doc.is_once) {
            frm.set_value("is_recurring", 1);
        }
    },

    company: (frm) => frm.events.maybe_reload(frm),
    payroll_date: (frm) => frm.events.maybe_reload(frm),
    from_date: (frm) => frm.events.maybe_reload(frm),
    to_date: (frm) => frm.events.maybe_reload(frm),
    // Fires when a component tag is ADDED (the Table MultiSelect runs set_model_value, which also
    // triggers this field event). Tag REMOVAL does NOT fire this — see the child-doctype handlers
    // below, which catch both add and remove.
    salary_components: (frm) => frm.events.components_changed(frm),

    maybe_reload(frm) {
        // Auto-load the employee grid as soon as the filters are complete — e.g. right after a
        // Salary Component is picked, without having to click "Get Employees" first. Silent, so
        // picking a component before a Company/date is set doesn't pop validation dialogs.
        if (frm.events.tool_args(frm, true)) frm.events.load_employees(frm, true);
    },

    // React to the Salary Components picker changing. Once a grid is on screen, columns are
    // added/removed IN PLACE so amounts already entered in the other columns are never lost — no
    // reload. Only the very first component (no grid yet) triggers a load.
    //
    // Deferred a tick: the Table MultiSelect's change events can fire BEFORE the row is actually
    // added/removed from frm.doc, so we read the settled picker on the next tick. Idempotent, so
    // multiple firing events (salary_components / _add / _remove) are harmless.
    components_changed(frm) {
        setTimeout(() => {
            if (!frm.grid_rendered) {
                if (frm.events.tool_args(frm, true)) frm.events.load_employees(frm, true);
                return;
            }

            const want = (frm.doc.salary_components || [])
                .map((r) => r.salary_component)
                .filter(Boolean);
            const have = frm.grid_area
                .find("th.ast-comp-head")
                .map(function () {
                    return String($(this).data("component"));
                })
                .get();
            const added = want.filter((c) => !have.includes(c));
            const removed = have.filter((c) => !want.includes(c));

            removed.forEach((c) => frm.events.drop_column_dom(frm, c));
            added.forEach((c) => frm.events.add_column_dom(frm, c));
        }, 0);
    },

    // Validate inputs and return the shared filter args, or null if invalid. When `silent` is
    // true the validation dialogs are suppressed (used by the auto-load on component pick).
    tool_args(frm, silent) {
        const components = (frm.doc.salary_components || [])
            .map((r) => r.salary_component)
            .filter(Boolean);
        const alert = (msg) => {
            if (!silent) frappe.msgprint(msg);
        };

        if (!frm.doc.company) {
            alert(__("Please select a Company."));
            return null;
        }
        if (!components.length) {
            alert(__("Please select at least one Salary Component."));
            return null;
        }
        if (frm.doc.is_recurring && !(frm.doc.from_date && frm.doc.to_date)) {
            alert(__("Please set From Date and To Date."));
            return null;
        }
        if (frm.doc.is_once && !frm.doc.payroll_date) {
            alert(__("Please set the Payroll Date."));
            return null;
        }

        return {
            company: frm.doc.company,
            salary_components: components,
            is_recurring: frm.doc.is_recurring ? 1 : 0,
            payroll_date: frm.doc.payroll_date,
            from_date: frm.doc.from_date,
            to_date: frm.doc.to_date,
        };
    },

    load_employees(frm, silent) {
        const args = frm.events.tool_args(frm, silent);
        if (!args) return;

        frm.grid_area.html(
            `<div class="text-muted" style="padding: 2rem 0">${__("Fetching employees…")}</div>`
        );

        frappe.call({
            method: `${METHOD_PREFIX}.get_employees`,
            args: args,
            callback: (r) => {
                if (!r.message) return;
                frm._grid_meta = {
                    total: r.message.total_active || 0,
                    skipped: r.message.skipped_no_assignment || 0,
                };
                frm.events.render_grid(frm, r.message.employees, r.message.components);
            },
        });
    },

    download_template(frm) {
        const args = frm.events.tool_args(frm);
        if (!args) return;
        open_url_post("/", {
            cmd: `${METHOD_PREFIX}.download_template`,
            company: args.company,
            salary_components: JSON.stringify(args.salary_components),
            is_recurring: args.is_recurring,
            payroll_date: args.payroll_date || "",
            from_date: args.from_date || "",
            to_date: args.to_date || "",
        });
    },

    upload_template(frm) {
        const args = frm.events.tool_args(frm);
        if (!args) return;

        const input = document.createElement("input");
        input.type = "file";
        input.accept = ".xlsx";
        input.onchange = () => {
            const file = input.files && input.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = () => {
                frappe.call({
                    method: `${METHOD_PREFIX}.parse_template`,
                    freeze: true,
                    freeze_message: __("Reading uploaded template…"),
                    args: {
                        filedata: reader.result,
                        salary_components: args.salary_components,
                    },
                    callback: (r) => {
                        if (r.message) frm.events.apply_uploaded_rows(frm, r.message.rows);
                    },
                });
            };
            reader.readAsDataURL(file);
        };
        input.click();
    },

    // Fill the on-screen grid from parsed rows so the user can review before submitting.
    apply_uploaded_rows(frm, rows) {
        if (!frm.grid_rendered)
            return frappe.msgprint(
                __("Please load employees first using 'Get Employees', then upload.")
            );

        let matched = 0;
        let filled = 0;
        (rows || []).forEach((row) => {
            const $row = frm.grid_area.find(`tbody tr[data-employee="${row.employee}"]`);
            if (!$row.length) return;
            matched += 1;
            $row.find(".ast-amount").each(function () {
                const comp = $(this).data("component");
                if (row.amounts && row.amounts[comp] != null) {
                    $(this).val(row.amounts[comp]);
                    filled += 1;
                }
            });
        });

        frm.events.recompute_totals(frm);
        frm.events.recompute_column_widths(frm);
        frm.events.local_save(frm);

        frappe.show_alert({
            message: __("Filled {0} amount(s) for {1} matched employee(s).", [filled, matched]),
            indicator: matched ? "green" : "orange",
        });
    },

    // Collect entered amounts from the grid as [{employee, amounts}] (non-zero only).
    collect_rows(frm) {
        const rows = [];
        frm.grid_area.find("tbody tr").each(function () {
            const $row = $(this);
            const amounts = {};
            let has_amount = false;
            $row.find(".ast-amount").each(function () {
                const val = flt($(this).val());
                if (val) {
                    amounts[$(this).data("component")] = val;
                    has_amount = true;
                }
            });
            // String() — jQuery .data() coerces numeric IDs to numbers, which then mismatch the
            // string-keyed lookups on the server.
            if (has_amount) rows.push({ employee: String($row.data("employee")), amounts });
        });
        return rows;
    },

    save_draft(frm) {
        // Don't save an empty draft — there must be at least one amount entered in the grid.
        const entered = frm.grid_rendered ? frm.events.collect_rows(frm) : [];
        if (!entered.length) {
            return frappe.msgprint(
                __("Nothing to save yet - please enter at least one amount before saving a draft.")
            );
        }

        const draft = {
            filters: {
                company: frm.doc.company,
                salary_components: (frm.doc.salary_components || [])
                    .map((r) => r.salary_component)
                    .filter(Boolean),
                is_once: frm.doc.is_once ? 1 : 0,
                is_recurring: frm.doc.is_recurring ? 1 : 0,
                payroll_date: frm.doc.payroll_date || null,
                from_date: frm.doc.from_date || null,
                to_date: frm.doc.to_date || null,
            },
            rows: entered,
        };

        frappe.call({
            method: `${METHOD_PREFIX}.save_draft`,
            args: { data: JSON.stringify(draft) },
            callback: (r) => {
                if (!r.message) return;
                frm.events.local_clear(); // work is now safely on the server
                frappe.show_alert({
                    message: __(
                        "Draft saved at {0}. It will be offered for resume next time you open this tool.",
                        [r.message.saved_on]
                    ),
                    indicator: "green",
                });
            },
        });
    },

    restore_draft(frm) {
        // Drafts are per-user; fetch the current user's own draft from the server.
        frappe.call({
            method: `${METHOD_PREFIX}.get_draft`,
            callback: (r) => {
                const raw = r.message && r.message.data;
                if (!raw) return frappe.msgprint(__("No saved draft to resume."));

                let draft;
                try {
                    draft = JSON.parse(raw);
                } catch (e) {
                    return frappe.msgprint(__("The saved draft is corrupted and cannot be read."));
                }

                const f = draft.filters || {};
                frm.set_value("company", f.company);
                frm.set_value(
                    "salary_components",
                    (f.salary_components || []).map((c) => ({ salary_component: c }))
                );
                frm.set_value("is_once", f.is_once ? 1 : 0);
                frm.set_value("is_recurring", f.is_recurring ? 1 : 0);
                frm.set_value("payroll_date", f.payroll_date || null);
                frm.set_value("from_date", f.from_date || null);
                frm.set_value("to_date", f.to_date || null);

                // Re-fetch the employee grid, then overlay the saved amounts once it renders.
                frm._pending_draft_rows = draft.rows || [];
                frm.events.load_employees(frm);
            },
        });
    },

    clear_draft(frm) {
        frappe.call({ method: `${METHOD_PREFIX}.clear_draft` });
    },

    // ---- Browser-local autosave (no server needed) ----------------------------------------------
    // Snapshots the filters + entered amounts to localStorage as HR types, so a disconnection, tab
    // close, reload or crash never loses their work. Complements the server-side draft.

    local_filters(frm) {
        return {
            company: frm.doc.company,
            salary_components: (frm.doc.salary_components || [])
                .map((r) => r.salary_component)
                .filter(Boolean),
            is_once: frm.doc.is_once ? 1 : 0,
            is_recurring: frm.doc.is_recurring ? 1 : 0,
            payroll_date: frm.doc.payroll_date || null,
            from_date: frm.doc.from_date || null,
            to_date: frm.doc.to_date || null,
        };
    },

    // Debounced so rapid typing writes at most ~once/second. Best-effort (ignores storage errors).
    local_save(frm) {
        clearTimeout(frm._local_timer);
        frm._local_timer = setTimeout(() => {
            if (!frm.grid_rendered) return;
            const rows = frm.events.collect_rows(frm);
            if (!rows.length) return frm.events.local_clear();
            try {
                localStorage.setItem(
                    LOCAL_KEY,
                    JSON.stringify({
                        filters: frm.events.local_filters(frm),
                        rows: rows,
                        saved_on: frappe.datetime.now_datetime(),
                    })
                );
            } catch (e) {
                /* storage full/disabled — best-effort only */
            }
        }, 800);
    },

    local_get() {
        try {
            const raw = localStorage.getItem(LOCAL_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch (e) {
            return null;
        }
    },

    local_clear() {
        try {
            localStorage.removeItem(LOCAL_KEY);
        } catch (e) {
            /* ignore */
        }
    },

    show_local_banner(frm) {
        const snap = frm.events.local_get();
        if (!snap || !(snap.rows && snap.rows.length) || !frm.banner_area) return;
        frm.banner_area.html(`
            <div class="ast-draft-banner">
                ${frappe.utils.icon("history", "sm")}
                <span>${__("Unsaved amounts from {0} were recovered (e.g. after a disconnection).", [
                    snap.saved_on || "",
                ])}</span>
                <button class="btn btn-xs btn-primary ast-local-resume">${__("Restore")}</button>
                <button class="btn btn-xs ast-local-discard">${__("Discard")}</button>
            </div>
        `);
        frm.banner_area.find(".ast-local-resume").on("click", () => {
            frm.banner_area.empty();
            frm.events.local_restore(frm);
        });
        frm.banner_area.find(".ast-local-discard").on("click", () => {
            frm.events.local_clear();
            frm.banner_area.empty();
        });
    },

    local_restore(frm) {
        const snap = frm.events.local_get();
        if (!snap) return;
        const f = snap.filters || {};
        frm.set_value("company", f.company);
        frm.set_value(
            "salary_components",
            (f.salary_components || []).map((c) => ({ salary_component: c }))
        );
        frm.set_value("is_once", f.is_once ? 1 : 0);
        frm.set_value("is_recurring", f.is_recurring ? 1 : 0);
        frm.set_value("payroll_date", f.payroll_date || null);
        frm.set_value("from_date", f.from_date || null);
        frm.set_value("to_date", f.to_date || null);

        // Re-fetch the grid (needs the connection back), then overlay the recovered amounts.
        frm._pending_draft_rows = snap.rows || [];
        frm.events.load_employees(frm);
    },

    render_grid(frm, employees, components) {
        employees = employees || [];
        components = components || [];

        if (!employees.length) {
            frm.grid_rendered = false;
            frm.grid_area.html(
                `<div class="text-center text-muted" style="line-height: 100px;">${__(
                    "No active employees found for this company."
                )}</div>`
            );
            return;
        }

        const esc = frappe.utils.escape_html;

        const header = components
            .map(
                (c) =>
                    `<th class="ast-comp-head ast-sortable" data-component="${esc(c)}"
                        data-sort="num" data-key="comp">
                        <span class="ast-comp-inner">
                            <span class="ast-fill" title="${__("Set this value for all shown rows")}">⤓</span>
                            <span class="ast-comp-name">${esc(c)}<span class="ast-sort-ind"></span></span>
                            <span class="ast-col-del" title="${__("Remove this column")}">✕</span>
                        </span></th>`
            )
            .join("");

        const body = employees
            .map((emp) => {
                const school = emp.school || __("Unassigned");

                const cells = components
                    .map((c) => {
                        const val = (emp.amounts && emp.amounts[c]) || "";
                        return `<td><input type="number" step="0.01" min="0"
                            class="form-control input-sm ast-amount text-right"
                            data-component="${esc(c)}" value="${val}"></td>`;
                    })
                    .join("");
                const search_key =
                    `${emp.employee} ${emp.employee_name || ""} ${school}`.toLowerCase();
                const assigned = emp.has_assignment ? 1 : 0;
                const base_val = assigned && emp.base != null ? emp.base : "";
                return `<tr data-employee="${esc(emp.employee)}" data-search="${esc(search_key)}">
                    <td class="ast-row-check"><input type="checkbox" class="ast-row-select"></td>
                    <td class="ast-no text-muted"></td>
                    <td><a href="/app/employee/${encodeURIComponent(emp.employee)}"
                        target="_blank" rel="noopener" class="ast-emp-link"
                        title="${__("Open employee")}">${esc(emp.employee)}</a></td>
                    <td class="ast-name">${esc(emp.employee_name || "")}</td>
                    <td class="ast-base-cell"><input type="number" min="0" step="0.01"
                        class="form-control input-sm ast-base text-right"
                        data-employee="${esc(emp.employee)}" data-assigned="${assigned}"
                        data-orig="${base_val}" value="${base_val}"
                        placeholder="${assigned ? "" : __("No assignment")}"
                        title="${assigned ? "" : __("No Salary Structure Assignment. Enter a base to create one.")}"></td>
                    ${cells}
                </tr>`;
            })
            .join("");

        // Totals row: one cell per component (filled in by recompute_totals).
        const total_cells = components
            .map((c) => `<td class="text-right ast-total" data-component="${esc(c)}">0.00</td>`)
            .join("");

        frm.grid_area.html(`
            <div class="ast-grid-controls">
                <input type="text" class="form-control input-sm ast-search"
                    placeholder="${__("Search employee, school or amount…")}">
                <button class="btn btn-xs ast-remove-selected">
                    ${frappe.utils.icon("delete", "sm")}
                    ${__("Remove selected")} (<span class="ast-sel-count">0</span>)
                </button>
                <div class="ast-summary text-muted"></div>
                <label class="ast-show-base">
                    <input type="checkbox" class="ast-show-base-cb" checked> ${__("Show base")}
                </label>
            </div>
            <div class="ast-table-wrap" style="overflow-x:auto;">
                <table class="table table-bordered"
                    style="margin-bottom:0; width:auto !important; table-layout:auto !important;">
                    <thead>
                        <tr>
                            <th class="ast-col-check">
                                <input type="checkbox" class="ast-check-all"
                                    title="${__("Select all shown rows")}"></th>
                            <th class="ast-col-no">${__("No.")}</th>
                            <th class="ast-sortable ast-col-emp" data-sort="str" data-key="emp">
                                ${__("Employee")}<span class="ast-sort-ind"></span></th>
                            <th class="ast-sortable ast-col-name" data-sort="str" data-key="name">
                                ${__("Employee Name")}<span class="ast-sort-ind"></span></th>
                            <th class="ast-base-head ast-sortable text-right" data-sort="num" data-key="base">
                                ${__("Base")}<span class="ast-sort-ind"></span></th>
                            ${header}
                        </tr>
                    </thead>
                    <tbody>${body}</tbody>
                    <tfoot>
                        <tr style="font-weight:bold;">
                            <td colspan="4" class="text-right">${__("Total")}</td>
                            <td class="text-right ast-base-cell ast-base-total">0.00</td>
                            ${total_cells}
                        </tr>
                    </tfoot>
                </table>
            </div>
        `);

        frm.grid_area.find(".ast-search").on("input", () => frm.events.apply_search(frm));
        frm.grid_area.find(".ast-sortable").on("click", function () {
            frm.events.sort_by(frm, $(this));
        });
        // Fill-down: clicking the header icon sets the whole (visible) column. Stop the click
        // from also triggering the column sort.
        frm.grid_area.find(".ast-fill").on("click", function (e) {
            e.stopPropagation();
            frm.events.fill_column(frm, $(this).closest("th").data("component"));
        });
        // Remove a whole salary-component column (also drops it from the picker). Stop the click
        // from triggering the column sort.
        frm.grid_area.find(".ast-col-del").on("click", function (e) {
            e.stopPropagation();
            frm.events.remove_column(frm, $(this).closest("th").data("component"));
        });

        // Row selection: header toggles all shown rows; per-row checkboxes drive the bulk action.
        frm.grid_area.find(".ast-check-all").on("change", function () {
            const checked = $(this).prop("checked");
            frm.grid_area.find("tbody tr:visible .ast-row-select").prop("checked", checked);
            frm.events.update_selection(frm);
        });
        frm.grid_area.find(".ast-remove-selected").on("click", () => frm.events.remove_selected(frm));

        // "Show base" toggles the Base column.
        frm.grid_area.find(".ast-show-base-cb").on("change", function () {
            frm.grid_area.find(".ast-table-wrap").toggleClass("ast-hide-base", !$(this).prop("checked"));
        });

        // Delegated handlers live on frm.grid_area, which PERSISTS across re-renders (render_grid
        // only replaces its inner HTML). Clear the namespace first so they don't stack up on every
        // reload — otherwise a single edit fires the handler (and its dialog) once per past render.
        frm.grid_area.off(".astg");
        frm.grid_area.on("change.astg", ".ast-row-select", () => frm.events.update_selection(frm));
        // Editing a Base creates the Salary Structure Assignment for that employee (with confirm).
        frm.grid_area.on("change.astg", ".ast-base", function () {
            frm.events.assign_base(frm, $(this));
        });

        // Keyboard entry: Enter / ↓ move down the column, ↑ moves up (across visible rows).
        frm.grid_area.on("keydown.astg", ".ast-amount", function (e) {
            if (!["Enter", "ArrowDown", "ArrowUp"].includes(e.key)) return;
            const $cur = $(this);
            const idx = $cur.closest("tr").find(".ast-amount").index($cur);
            const $row = $cur.closest("tr");
            const $target =
                e.key === "ArrowUp"
                    ? $row.prevAll("tr:visible").first()
                    : $row.nextAll("tr:visible").first();
            const $next = $target.find(".ast-amount").eq(idx);
            if ($next.length) {
                e.preventDefault();
                $next.trigger("focus").trigger("select");
            }
        });

        // Keep totals + filter + column widths in sync as amounts are edited.
        // apply_search re-filters (an amount may now match/stop matching) and then recomputes totals.
        frm.grid_area.on("input.astg", ".ast-amount", function () {
            frm.events.recompute_column_widths(frm);
            frm.events.apply_search(frm);
            frm.events.local_save(frm); // browser-local autosave (offline-safe)
        });
        frm.events.recompute_totals(frm);
        frm.events.recompute_column_widths(frm);
        frm.events.renumber_rows(frm);

        frm.grid_rendered = true;

        // Overlay a resumed draft's amounts now that the grid exists.
        if (frm._pending_draft_rows) {
            const rows = frm._pending_draft_rows;
            frm._pending_draft_rows = null;
            frm.events.apply_uploaded_rows(frm, rows);
        }
    },

    recompute_totals(frm) {
        const grand = {};
        const shown = {};
        frm.grid_area.find(".ast-amount").each(function () {
            const comp = $(this).data("component");
            const v = flt($(this).val());
            grand[comp] = (grand[comp] || 0) + v;
            if ($(this).closest("tr").css("display") !== "none")
                shown[comp] = (shown[comp] || 0) + v;
        });

        const filtered = frm.grid_area.find("tbody tr:hidden").length > 0;
        const subtotal = (g, s) =>
            filtered
                ? `${format_number(g || 0, null, 2)}<br><span class="text-muted" style="font-weight:normal">${__(
                      "shown"
                  )}: ${format_number(s || 0, null, 2)}</span>`
                : format_number(g || 0, null, 2);

        frm.grid_area.find(".ast-total").each(function () {
            const c = $(this).data("component");
            $(this).html(subtotal(grand[c], shown[c]));
        });

        // Base column total.
        let baseGrand = 0;
        let baseShown = 0;
        frm.grid_area.find(".ast-base").each(function () {
            const v = flt($(this).val());
            baseGrand += v;
            if ($(this).closest("tr").css("display") !== "none") baseShown += v;
        });
        frm.grid_area.find(".ast-base-total").html(subtotal(baseGrand, baseShown));

        frm.events.update_summary(frm);
    },

    // Summary line above the grid: employees / without-structure / to-be-paid / grand total of all
    // amounts (updates on every edit, across all component columns) / showing-when-filtered.
    update_summary(frm) {
        const $rows = frm.grid_area.find("tbody tr");
        const loaded = $rows.length;
        const showing = $rows.filter(function () {
            return $(this).css("display") !== "none";
        }).length;

        let toPay = 0;
        let grandTotal = 0;
        $rows.each(function () {
            let has = false;
            $(this)
                .find(".ast-amount")
                .each(function () {
                    const v = flt($(this).val());
                    if (v) {
                        has = true;
                        grandTotal += v;
                    }
                });
            if (has) toPay += 1;
        });

        // Counted live from the DOM so it drops as HR allocates assignments inline.
        const noAssignment = frm.grid_area.find('tbody tr .ast-base[data-assigned="0"]').length;

        const parts = [__("{0} employees", [loaded])];
        if (noAssignment) parts.push(__("{0} without salary structure", [noAssignment]));
        parts.push(__("{0} to be paid additional", [toPay]));
        if (grandTotal) parts.push(__("total {0}", [format_number(grandTotal, null, 2)]));
        if (showing !== loaded) parts.push(__("showing {0}", [showing]));
        frm.grid_area.find(".ast-summary").text(parts.join("  ·  "));
    },

    // Size each amount column to the widest value in it (and at least its header), so the
    // input fills the cell and large numbers are never clipped.
    recompute_column_widths(frm) {
        const maxlen = {};
        frm.grid_area.find(".ast-amount").each(function () {
            const c = $(this).data("component");
            maxlen[c] = Math.max(maxlen[c] || 0, String($(this).val() || "").length);
        });
        frm.grid_area.find("th.ast-comp-head").each(function () {
            const c = $(this).data("component");
            // Name length, plus headroom for the fill-down + delete icons and their gaps.
            $(this).css("width", Math.max(String(c).length, maxlen[c] || 0) + 7 + "ch");
        });
    },

    // Set one component column to a single value across all currently-visible rows.
    fill_column(frm, comp) {
        const d = frappe.prompt(
            [
                {
                    fieldname: "value",
                    label: __("Amount"),
                    fieldtype: "Float",
                },
            ],
            (v) => {
                const val = flt(v.value);
                frm.grid_area.find("tbody tr").each(function () {
                    const $row = $(this);
                    if ($row.css("display") === "none") return; // respect the current search
                    $row.find(".ast-amount").each(function () {
                        if ($(this).data("component") === comp) $(this).val(val || "");
                    });
                });
                frm.events.recompute_totals(frm);
                frm.events.recompute_column_widths(frm);
                frm.events.apply_search(frm);
                frm.events.local_save(frm);
            },
            __("Set {0} for all Employees", [comp]),
            __("Apply")
        );
        frm.events.brand_dialog(d);
    },

    // Editing a Base in the grid creates a Salary Structure Assignment for that employee (with a
    // confirm), using the company's latest active structure. Reverts on cancel/error.
    assign_base(frm, $input) {
        const employee = String($input.data("employee"));
        const base = flt($input.val());
        const orig = flt($input.attr("data-orig"));
        const revert = () => $input.val($input.attr("data-orig") || "");

        if (base === orig) return; // nothing changed
        if (!(base > 0)) {
            // A blank/zero base can't create an assignment — restore the previous value.
            revert();
            return;
        }

        const name = $input.closest("tr").find("td.ast-name").text() || employee;
        const escName = frappe.utils.escape_html(name);
        const ref = frm.doc.payroll_date || frm.doc.from_date || frappe.datetime.get_today();
        const first_of_month = ref.substring(0, 8) + "01";

        // Hold the open confirm so we can guarantee it closes from the server callback, rather than
        // relying solely on frappe.confirm's own auto-hide (which can be left stuck on screen).
        let dlg = null;
        const closeDlg = () => {
            if (dlg) {
                dlg.hide();
                dlg = null;
            }
        };

        const doCall = (replace) => {
            frappe.call({
                method: `${METHOD_PREFIX}.assign_structure_with_base`,
                args: {
                    company: frm.doc.company,
                    employee: employee,
                    base: base,
                    from_date: first_of_month,
                    replace: replace ? 1 : 0,
                },
                callback: (r) => {
                    const res = r.message;
                    if (!res) {
                        closeDlg();
                        return revert();
                    }

                    // An assignment already exists on that date — close this one and ask to replace.
                    if (res.needs_replace) {
                        closeDlg();
                        askConfirm(
                            __(
                                "{0} already has a Salary Structure Assignment dated {1}. Cancel it and create a new one with base {2}?",
                                [escName, res.from_date, format_number(base, null, 2)]
                            ),
                            true
                        );
                        return;
                    }

                    closeDlg();
                    $input.attr("data-assigned", "1").attr("data-orig", res.base).val(res.base);
                    frappe.show_alert({
                        message: __("Assignment created for {0} (base {1}, from {2}).", [
                            name,
                            format_number(res.base, null, 2),
                            res.from_date,
                        ]),
                        indicator: "green",
                    });
                    frm.events.recompute_totals(frm); // refresh the Base total (also updates summary)
                },
                error: () => {
                    closeDlg();
                    revert();
                },
            });
        };

        const askConfirm = (message, replace) => {
            dlg = frappe.confirm(message, () => doCall(replace), revert);
            frm.events.brand_dialog(dlg);
        };

        askConfirm(
            __(
                "Create a Salary Structure Assignment for <b>{0}</b> with base <b>{1}</b> from <b>{2}</b>?",
                [escName, format_number(base, null, 2), first_of_month]
            ) +
                `<br><span class="text-muted" style="font-size:12px;">${__(
                    "Uses the company's latest active Salary Structure. New hires start from their joining date."
                )}</span>`,
            false
        );
    },

    // Remove every checked row at once (excludes them from creation; nothing is saved).
    remove_selected(frm) {
        const $checked = frm.grid_area.find("tbody tr").has(".ast-row-select:checked");
        if (!$checked.length) return;
        $checked.remove();
        frm.grid_area.find(".ast-check-all").prop("checked", false);
        frm.events.renumber_rows(frm);
        frm.events.recompute_totals(frm);
        frm.events.update_selection(frm);
    },

    // Sync the bulk-remove button (label count + visibility) and the header checkbox state with
    // the current row selection. Count/remove act on ALL checked rows; the header checkbox tracks
    // only the rows currently shown (so you can bulk-select a filtered subset).
    update_selection(frm) {
        const nChecked = frm.grid_area.find("tbody tr .ast-row-select:checked").length;
        frm.grid_area.find(".ast-sel-count").text(nChecked);
        frm.grid_area.find(".ast-remove-selected").css("display", nChecked ? "inline-flex" : "none");

        const $vis = frm.grid_area.find("tbody tr:visible .ast-row-select");
        const nVis = $vis.filter(":checked").length;
        const $head = frm.grid_area.find(".ast-check-all");
        $head.prop("checked", $vis.length > 0 && nVis === $vis.length);
        $head.prop("indeterminate", nVis > 0 && nVis < $vis.length);
    },

    // Strip a single component column (header, body cells, total) from the grid in place. Other
    // columns' entered amounts are untouched.
    drop_column_dom(frm, comp) {
        if (!comp) return;
        // Header (th) and total (td) carry data-component directly; amount inputs sit inside a td.
        frm.grid_area.find(`[data-component="${comp}"]`).each(function () {
            const $el = $(this);
            ($el.is("input") ? $el.closest("td") : $el).remove();
        });
        frm.events.recompute_totals(frm);
        frm.events.recompute_column_widths(frm);
        frm.events.local_save(frm); // a dropped column removes its amounts from the snapshot
    },

    // Append a new component column (header + empty inputs + total) to the existing grid WITHOUT
    // reloading, so amounts already entered in other columns are preserved.
    add_column_dom(frm, comp) {
        if (!comp || frm.grid_area.find(`th.ast-comp-head[data-component="${comp}"]`).length) return;
        const esc = frappe.utils.escape_html;

        const $th = $(`<th class="ast-comp-head ast-sortable" data-component="${esc(comp)}"
            data-sort="num" data-key="comp">
            <span class="ast-comp-inner">
                <span class="ast-fill" title="${__("Set this value for all shown rows")}">⤓</span>
                <span class="ast-comp-name">${esc(comp)}<span class="ast-sort-ind"></span></span>
                <span class="ast-col-del" title="${__("Remove this column")}">✕</span>
            </span></th>`);
        frm.grid_area.find("thead tr").append($th);

        // Header is added after the initial render, so wire its handlers here (those bindings are
        // not delegated). Amount input/keydown handlers ARE delegated, so new inputs just work.
        $th.on("click", () => frm.events.sort_by(frm, $th));
        $th.find(".ast-fill").on("click", (e) => {
            e.stopPropagation();
            frm.events.fill_column(frm, comp);
        });
        $th.find(".ast-col-del").on("click", (e) => {
            e.stopPropagation();
            frm.events.remove_column(frm, comp);
        });

        frm.grid_area.find("tbody tr").each(function () {
            $(this).append(`<td><input type="number" step="0.01" min="0"
                class="form-control input-sm ast-amount text-right"
                data-component="${esc(comp)}" value=""></td>`);
        });
        frm.grid_area
            .find("tfoot tr")
            .append(`<td class="text-right ast-total" data-component="${esc(comp)}">0.00</td>`);

        frm.events.recompute_totals(frm);
        frm.events.recompute_column_widths(frm);
    },

    // Column-header ✕: also remove the component from the picker so it won't return on reload or be
    // created. refresh_field doesn't fire the change event, so we drop the column ourselves.
    remove_column(frm, comp) {
        if (!comp) return;
        frm.doc.salary_components = (frm.doc.salary_components || []).filter(
            (r) => r.salary_component !== comp
        );
        frm.refresh_field("salary_components");
        frm.events.drop_column_dom(frm, comp);
    },

    // Filter rows by employee, school OR any entered amount.
    apply_search(frm) {
        const q = (frm.grid_area.find(".ast-search").val() || "").toLowerCase().trim();
        frm.grid_area.find("tbody tr").each(function () {
            const $row = $(this);
            let hay = String($row.data("search") || "");
            $row.find(".ast-amount").each(function () {
                const v = $(this).val();
                if (v) hay += " " + v;
            });
            const baseVal = $row.find(".ast-base").val();
            if (baseVal) hay += " " + baseVal;
            $row.toggle(!q || hay.indexOf(q) !== -1);
        });
        frm.events.renumber_rows(frm);
        frm.events.recompute_totals(frm); // refresh visible subtotals + summary counts
        frm.events.update_selection(frm); // header checkbox state tracks the now-visible rows
    },

    // Number the visible rows 1..N (blank for hidden rows).
    renumber_rows(frm) {
        let n = 0;
        frm.grid_area.find("tbody tr").each(function () {
            const $row = $(this);
            if ($row.css("display") !== "none") {
                n += 1;
                $row.find(".ast-no").text(n);
            } else {
                $row.find(".ast-no").text("");
            }
        });
    },

    // Sort visible rows by the clicked column; toggles asc/desc on repeat clicks.
    sort_by(frm, $th) {
        const key = $th.data("key");
        const type = $th.data("sort");
        const comp = $th.data("component");
        const asc = frm._sort_col === $th[0] ? !frm._sort_asc : true;
        frm._sort_col = $th[0];
        frm._sort_asc = asc;

        const value = ($row) => {
            if (key === "emp") return $row.data("employee");
            if (key === "name") return $row.find("td.ast-name").text();
            if (key === "base") return flt($row.find(".ast-base").val());
            return flt($row.find(`.ast-amount[data-component="${comp}"]`).val()); // comp
        };

        const $tbody = frm.grid_area.find("tbody");
        const rows = $tbody.children("tr").get();
        rows.sort((a, b) => {
            let va = value($(a));
            let vb = value($(b));
            let cmp;
            if (type === "num") cmp = (va || 0) - (vb || 0);
            else cmp = String(va).localeCompare(String(vb), undefined, { numeric: true });
            return asc ? cmp : -cmp;
        });
        $tbody.append(rows);

        // Update sort indicators.
        frm.grid_area.find(".ast-sort-ind").text("");
        $th.find(".ast-sort-ind").text(asc ? " ▲" : " ▼");

        frm.events.renumber_rows(frm);
    },

    // Scope the brand styling (gradient header + primary button) to our own dialogs only.
    brand_dialog(dialog) {
        if (dialog && dialog.$wrapper) dialog.$wrapper.addClass("ast-dialog");
    },

    // Build the "Create Additional Salaries" result popup: count badges, plus colour-coded boxes
    // for employees missing a Salary Structure and for any errors. No long dashes.
    result_summary_html(m) {
        const esc = frappe.utils.escape_html;
        const missing = m.missing_assignment || [];
        const errs = m.errors || [];

        const badge = (label, val, bg, color) =>
            `<span style="display:inline-block; background:${bg}; color:${color};
                padding:3px 12px; border-radius:14px; font-weight:600; font-size:12px;
                margin:0 6px 6px 0;">${label}: ${val}</span>`;

        let html = `<div>
            ${badge(__("Created"), m.created || 0, "#dcfce7", "#166534")}
            ${badge(__("Skipped"), m.skipped || 0, "#f1f5f9", "#475569")}`;
        if (m.adjusted || m.cancelled) {
            html += badge(__("Adjusted"), m.adjusted || 0, "#e0e7ff", "#3730a3");
            html += badge(__("Cancelled"), m.cancelled || 0, "#fee2e2", "#991b1b");
        }
        html += `</div>`;

        if (missing.length) {
            const lines = missing
                .map((e) => {
                    const name = esc(e.employee_name || "");
                    const id = esc(e.employee);
                    return name
                        ? `<div>${name} <span style="opacity:0.6;">(${id})</span></div>`
                        : `<div>${id}</div>`;
                })
                .join("");
            html += `<div style="background:#fff7ed; border:1px solid #fed7aa; border-radius:8px;
                padding:12px 14px; margin-top:12px;">
                <div style="font-weight:600; color:#9a3412; margin-bottom:6px;">
                    ${__("No Salary Structure Assignment ({0})", [missing.length])}</div>
                <div style="color:#7c2d12; font-size:13px; line-height:1.7;">${lines}</div>
                <div style="margin-top:8px; color:#9a3412; font-size:12px;">
                    ${__("Assign these employees a Salary Structure first, then create their additional salaries.")}</div>
            </div>`;
        }

        if (errs.length) {
            html += `<div style="background:#fef2f2; border:1px solid #fecaca; border-radius:8px;
                padding:12px 14px; margin-top:12px;">
                <div style="font-weight:600; color:#991b1b; margin-bottom:6px;">${__("Errors")}</div>
                <div style="color:#7f1d1d; font-size:12px; line-height:1.6;">
                    ${errs.map(esc).join("<br>")}</div>
            </div>`;
        }
        return html;
    },

    // Bulk-assign a Salary Structure to the employees who have none, so they become payable and
    // can then be processed by this tool. Opened from the result popup's "Allocate Salary Structure".
    open_assignment_dialog(frm, missing) {
        // The results popup is still on screen behind us — close it so only this dialog shows.
        if (frappe.msg_dialog) frappe.msg_dialog.hide();

        const esc = frappe.utils.escape_html;
        // Default From Date = first day of the payroll month.
        const ref = frm.doc.payroll_date || frm.doc.from_date || frappe.datetime.get_today();
        const first_of_month = ref.substring(0, 8) + "01";

        // One editable Base input per employee.
        const rows_html = missing
            .map(
                (e) => `<tr>
                    <td>${esc(e.employee)}</td>
                    <td>${esc(e.employee_name || "")}</td>
                    <td><input type="number" min="0" step="0.01" style="height:26px;"
                        class="form-control input-sm ast-emp-base"
                        data-employee="${esc(e.employee)}"></td>
                </tr>`
            )
            .join("");

        const d = new frappe.ui.Dialog({
            title: __("Allocate Salary Structure"),
            size: "large",
            fields: [
                {
                    fieldname: "salary_structure",
                    label: __("Salary Structure"),
                    fieldtype: "Link",
                    options: "Salary Structure",
                    reqd: 1,
                    get_query: () => ({
                        filters: { company: frm.doc.company, docstatus: 1, is_active: "Yes" },
                    }),
                },
                {
                    fieldname: "from_date",
                    label: __("From Date"),
                    fieldtype: "Date",
                    reqd: 1,
                    default: first_of_month,
                    description: __(
                        "New employees who joined after this date are assigned from their joining date."
                    ),
                },
                { fieldtype: "Section Break" },
                {
                    fieldname: "employees_html",
                    fieldtype: "HTML",
                    options: `<div style="max-height:300px; overflow:auto;">
                        <table class="table table-bordered" style="font-size:12px; margin-bottom:0;">
                            <thead><tr>
                                <th>${__("Employee")}</th>
                                <th>${__("Employee Name")}</th>
                                <th style="width:160px;">${__("Base")}</th>
                            </tr></thead>
                            <tbody>${rows_html}</tbody>
                        </table></div>`,
                },
            ],
            primary_action_label: __("Create Assignments"),
            primary_action(values) {
                const emp_rows = [];
                d.$wrapper.find(".ast-emp-base").each(function () {
                    emp_rows.push({
                        employee: String($(this).data("employee")),
                        base: flt($(this).val()) || 0,
                    });
                });

                d.disable_primary_action();
                frappe.call({
                    method: `${METHOD_PREFIX}.assign_salary_structure`,
                    freeze: true,
                    freeze_message: __("Creating Salary Structure Assignments…"),
                    args: {
                        company: frm.doc.company,
                        salary_structure: values.salary_structure,
                        from_date: values.from_date,
                        employees: emp_rows,
                    },
                    callback: (r) => {
                        if (!r.message) {
                            d.enable_primary_action();
                            return;
                        }
                        const res = r.message;
                        const errs = res.errors || [];
                        let m = `<span style="display:inline-block; background:#dcfce7;
                            color:#166534; padding:3px 12px; border-radius:14px; font-weight:600;
                            font-size:12px;">${__("Created")}: ${res.created || 0}</span>`;
                        if (errs.length) {
                            m += `<div style="background:#fef2f2; border:1px solid #fecaca;
                                border-radius:8px; padding:12px 14px; margin-top:12px;">
                                <div style="font-weight:600; color:#991b1b; margin-bottom:6px;">
                                    ${__("Errors")}</div>
                                <div style="color:#7f1d1d; font-size:12px; line-height:1.6;">
                                    ${errs.map(frappe.utils.escape_html).join("<br>")}</div></div>`;
                        }
                        d.hide();
                        frappe.msgprint({
                            title: __("Salary Structure Assignment"),
                            message: m,
                            indicator: errs.length ? "orange" : "green",
                        });
                        frm.events.brand_dialog(frappe.msg_dialog);
                        // Reload so the now-payable employees pick up amounts and can be created.
                        frm.events.load_employees(frm);
                    },
                });
            },
        });

        // Auto-pick the latest active Salary Structure for the company.
        frappe.db
            .get_list("Salary Structure", {
                filters: { company: frm.doc.company, is_active: "Yes", docstatus: 1 },
                fields: ["name"],
                order_by: "creation desc",
                limit: 1,
            })
            .then((res) => {
                if (res && res.length) d.set_value("salary_structure", res[0].name);
            });

        frm.events.brand_dialog(d);
        d.show();
    },

    create_additional_salaries(frm) {
        if (!frm.grid_rendered)
            return frappe.msgprint(__("Please load employees first using 'Get Employees'."));

        const rows = [];
        frm.grid_area.find("tbody tr").each(function () {
            const $row = $(this);
            const amounts = {};
            let has_amount = false;
            $row.find(".ast-amount").each(function () {
                const val = flt($(this).val());
                if (val) {
                    amounts[$(this).data("component")] = val;
                    has_amount = true;
                }
            });
            // String() — jQuery .data() coerces numeric IDs to numbers, which then mismatch the
            // string-keyed lookups on the server.
            if (has_amount) rows.push({ employee: String($row.data("employee")), amounts });
        });

        if (!rows.length) return frappe.msgprint(__("Please enter at least one amount."));

        const components = (frm.doc.salary_components || [])
            .map((r) => r.salary_component)
            .filter(Boolean);

        const confirmDialog = frappe.confirm(
            __("Create & submit Additional Salaries for {0} employee(s)?", [rows.length]),
            () => {
                frappe.call({
                    method: `${METHOD_PREFIX}.create_additional_salaries`,
                    freeze: true,
                    freeze_message: __("Creating Additional Salaries…"),
                    args: {
                        company: frm.doc.company,
                        salary_components: components,
                        rows: rows,
                        is_recurring: frm.doc.is_recurring ? 1 : 0,
                        payroll_date: frm.doc.payroll_date,
                        from_date: frm.doc.from_date,
                        to_date: frm.doc.to_date,
                    },
                    callback: (r) => {
                        if (!r.message) return;
                        const m = r.message;
                        const missing = m.missing_assignment || [];
                        const errs = m.errors || [];

                        frappe.msgprint({
                            title: __("Additional Salary Tool"),
                            message: frm.events.result_summary_html(m),
                            indicator: errs.length ? "red" : missing.length ? "orange" : "green",
                            primary_action: missing.length
                                ? {
                                      label: __("Allocate Salary Structure"),
                                      action() {
                                          frm.events.open_assignment_dialog(frm, missing);
                                      },
                                  }
                                : undefined,
                        });
                        frm.events.brand_dialog(frappe.msg_dialog);

                        if (m.created) {
                            frm.events.clear_draft(frm); // server draft is now applied
                            frm.events.local_clear(); // local recovery no longer needed
                        }
                        frm.events.load_employees(frm); // refresh prefilled amounts
                    },
                });
            }
        );
        frm.events.brand_dialog(confirmDialog);
    },
});

// The Salary Components picker is a Table MultiSelect. Its add/remove events fire on the CHILD
// doctype (Frappe triggers `<fieldname>_add` / `<fieldname>_remove` with df.options as the doctype),
// passing the PARENT frm — and tag REMOVAL fires ONLY here, not the parent `salary_components`
// field event. Register here so removing a tag drops its grid column.
frappe.ui.form.on("Additional Salary Tool Component", {
    salary_components_add: (frm) => frm.events.components_changed(frm),
    salary_components_remove: (frm) => frm.events.components_changed(frm),
});
