// Copyright (c) 2026, Titansoft Limited and contributors
// For license information, please see license.txt

const STRONG_FIELDS = ["gross_pay", "total_deduction", "net_pay"];
const NUMERIC_FIELDTYPES = ["Currency", "Float", "Percent", "Int"];
// Text columns whose value must never wrap on print (e.g. the employee code EMP-GF-00062).
// Amounts are kept on one line separately via the .num rule.
const NOWRAP_FIELDS = ["employee"];

frappe.query_reports["Payroll Register"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 1,
        },
        {
            // Self-contained period presets (originally busara_ltd.get_period_filter()).
            // Picking a preset fills From/To Date; "Custom Dates" leaves them untouched.
            fieldname: "period",
            label: __("Period"),
            fieldtype: "Select",
            options: ["Custom Dates", "This Month", "Last Month", "This Year"].join("\n"),
            default: "Custom Dates",
            on_change() {
                const period = frappe.query_report.get_filter_value("period");
                if (!period || period === "Custom Dates") return;
                // frappe.datetime.month_start()/month_end() take NO argument — they always
                // resolve to the CURRENT month — so they can't express "last month". Anchor on
                // moment() instead and emit plain YYYY-MM-DD, which is what the Date control and
                // the server-side date comparison expect.
                let from_date, to_date;
                const month_of = (m) => [
                    m.clone().startOf("month").format("YYYY-MM-DD"),
                    m.clone().endOf("month").format("YYYY-MM-DD"),
                ];
                if (period === "This Month") {
                    [from_date, to_date] = month_of(moment());
                } else if (period === "Last Month") {
                    [from_date, to_date] = month_of(moment().subtract(1, "month"));
                } else if (period === "This Year") {
                    from_date = moment().startOf("year").format("YYYY-MM-DD");
                    to_date = moment().endOf("year").format("YYYY-MM-DD");
                }
                if (from_date) frappe.query_report.set_filter_value("from_date", from_date);
                if (to_date) frappe.query_report.set_filter_value("to_date", to_date);
            },
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_start(),
            reqd: 1,
            onchange: validate_date_range,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.month_end(),
            reqd: 1,
            onchange: validate_date_range,
        },
        {
            fieldname: "employee",
            label: __("Employee"),
            fieldtype: "Link",
            options: "Employee",
            get_query: () => ({
                filters: { company: frappe.query_report.get_filter_value("company") },
            }),
        },
        {
            fieldname: "payroll_entry",
            label: __("Payroll Entry"),
            fieldtype: "Link",
            options: "Payroll Entry",
            get_query: () => ({
                filters: { company: frappe.query_report.get_filter_value("company") },
            }),
        },
        {
            // Off: one row per employee, with every month in the range added together.
            // On: one row per salary slip, with a Month column saying which month it was paid for.
            fieldname: "split_by_month",
            label: __("Monthly"),
            fieldtype: "Check",
            default: 0,
        },
    ],

    onload(report) {
        inject_print_style();
        add_print_button_once(report);
        hide_default_print_menu();
        remove_report_noise();
    },

    after_datatable_render(datatable) {
        hide_default_print_menu();
        remove_report_noise();
        fit_columns_to_content(datatable);
        load_payroll_analysis();
    },

    formatter(value, row, column, data, default_formatter) {
        // Payment Days: show whole numbers without a trailing ".0" (30.0 -> 30), keep real
        // fractions (24.5 -> 24.5). Bypasses the default Float precision formatting.
        if (column.fieldname === "payment_days") {
            return format_payment_days(value);
        }

        // Amounts without the currency symbol: every figure is in the company currency, and
        // "TZS" on each cell made the columns too wide to read. The print states it once.
        if (column.fieldtype === "Currency") {
            value = is_blank(value) ? "" : `<div class="text-right">${format_amount(value)}</div>`;
        } else {
            value = default_formatter(value, row, column, data);
        }

        if (STRONG_FIELDS.includes(column.fieldname)) {
            value = `<strong>${value}</strong>`;
        }

        if (data && data.salary_slip === "Total") {
            value = `<strong>${value}</strong>`;
        }

        if (column.fieldname === "net_pay" && data && flt(data.net_pay) < 0) {
            value = `<span style="color: var(--red-500); font-weight: 700;">${value}</span>`;
        }

        return value;
    },
};

// Format Payment Days: round to the column's 1-dp precision, then drop a trailing ".0" so whole
// days read as "30" while half days stay "24.5". Blank stays blank (e.g. the Total row).
function format_payment_days(val) {
    if (val === null || val === undefined || val === "") return "";
    const n = Math.round(flt(val) * 10) / 10;
    return String(n);
}

// Width each column to its widest value as it is actually drawn, measured in the grid's own font.
// The server only estimates widths; upper-case IDs such as EMP-GF-00062 run wider than any
// estimate, so the browser measures and every value shows in full. Headers wrap, so they only
// need room for their longest word.
function fit_columns_to_content(datatable) {
    if (!datatable) return;
    const data = frappe.query_report.data || [];
    const sample = datatable.wrapper.querySelector(".dt-scrollable .dt-cell__content");
    if (!sample) return;

    const style = getComputedStyle(sample);
    const ctx = document.createElement("canvas").getContext("2d");
    // Bold throughout: the totals row and the strong columns are bold, and it is the wider face.
    ctx.font = `700 ${style.fontSize} ${style.fontFamily}`;
    const measure = (text) => ctx.measureText(text).width;
    const CELL_CHROME = 26; // padding, focus border and a little air

    datatable.getColumns().forEach((col) => {
        if (!col.id || col.id.startsWith("_")) return;

        let widest = 0;
        for (const row of data) {
            widest = Math.max(widest, measure(cell_text(col, row[col.id])));
        }
        const header_word = Math.max(0, ...String(col.name || "").split(/\s+/).map(measure));

        col.width = Math.ceil(Math.max(widest, header_word) + CELL_CHROME);
        datatable.columnmanager.setColumnWidth(col.colIndex);
        datatable.columnmanager.setColumnHeaderWidth(col.colIndex);
    });
}

// The text a cell shows, matching the formatter above.
function cell_text(col, val) {
    if (is_blank(val)) return "";
    if (col.id === "payment_days") return format_payment_days(val);
    if (col.fieldtype === "Currency") return format_amount(val);
    return String(val);
}

function is_blank(val) {
    return val === null || val === undefined || val === "";
}

// 1,110,809.41: two decimals with the system's thousands separator, no currency symbol.
function format_amount(val) {
    return format_number(flt(val), null, 2);
}

function inject_print_style() {
    if (document.getElementById("payroll-register-print-style")) return;

    const style = document.createElement("style");
    style.id = "payroll-register-print-style";
    style.innerHTML = `
        .report-footer,
        .report-message,
        .result-info,
        .dt-info,
        .datatable-info,
        .datatable-hint,
        .dt-filter-hint,
        .dt-row-filter,
        [class*="hint"],
        [class*="execution"],
        [class*="result-info"] {
            display: none !important;
        }

        /* A smaller grid on screen so the whole register fits across without scrolling.
           Scoped to this report's route so other reports keep the standard size. */
        body[data-route="query-report/Payroll Register"] .dt-cell__content,
        body[data-route="query-report/Payroll Register"] .dt-cell__content strong {
            font-size: 11.5px;
        }
        body[data-route="query-report/Payroll Register"] .dt-cell__content {
            padding: 6px 8px;
        }

        /* Headers wrap instead of being cut off, so "Medical Allowance (Employer)" reads in full
           on two lines while the amount columns stay narrow. Frappe fixes every row at 35px,
           so the header row is released to grow with its text. */
        body[data-route="query-report/Payroll Register"] .dt-header .dt-row-header,
        body[data-route="query-report/Payroll Register"] .dt-cell--header,
        body[data-route="query-report/Payroll Register"] .dt-cell--header .dt-cell__content {
            height: auto !important;
        }
        body[data-route="query-report/Payroll Register"] .dt-cell--header .dt-cell__content {
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            line-height: 1.3;
            font-weight: 600 !important;
        }

        /* The report name, filters and toolbar buttons at the same size as the grid. */
        body[data-route="query-report/Payroll Register"] .page-head .title-area,
        body[data-route="query-report/Payroll Register"] .page-head .title-area *,
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control,
        body[data-route="query-report/Payroll Register"] .page-form input,
        body[data-route="query-report/Payroll Register"] .page-form select,
        body[data-route="query-report/Payroll Register"] .page-form .control-input,
        body[data-route="query-report/Payroll Register"] .page-head .page-actions .btn,
        body[data-route="query-report/Payroll Register"] .page-head .page-actions button {
            font-size: 11.5px !important;
        }
        body[data-route="query-report/Payroll Register"] .page-head .title-area {
            font-weight: 600;
        }
        body[data-route="query-report/Payroll Register"] .page-form input:not([type="checkbox"]),
        body[data-route="query-report/Payroll Register"] .page-form select {
            height: 26px !important;
        }

        /* Filters fill the whole row. Each starts from a width that fits its usual content and
           shares the spare space by weight, so company and employee names get the most room. */
        body[data-route="query-report/Payroll Register"] .page-form {
            flex-wrap: nowrap !important;
            align-items: center;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname] {
            max-width: none !important;
            min-width: 0;
            padding-right: 6px;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="company"] {
            flex: 3 1 220px !important;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="employee"] {
            flex: 3 1 180px !important;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="payroll_entry"] {
            flex: 2 1 140px !important;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="period"] {
            flex: 1.4 1 115px !important;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="from_date"],
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="to_date"] {
            flex: 1 1 100px !important;
        }
        /* "Monthly" sits at the end of the same line, centred against the inputs. */
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="split_by_month"] {
            flex: 0 0 auto !important;
            width: auto !important;
            white-space: nowrap;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="split_by_month"] .checkbox {
            margin: 0 !important;
        }
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="split_by_month"] label {
            display: flex;
            align-items: center;
            gap: 4px;
            height: 26px;
            margin: 0;
            font-size: 11.5px;
        }
        /* Frappe gives a checkbox's text its own 13px medium style, so it is set here too. */
        body[data-route="query-report/Payroll Register"] .page-form .frappe-control[data-fieldname="split_by_month"] .label-area {
            font-size: 11.5px !important;
            font-weight: 400 !important;
            line-height: 1;
        }

        /* Toolbar buttons as compact as the filters, with the icon sitting beside the label. */
        body[data-route="query-report/Payroll Register"] .page-head .page-actions .btn,
        body[data-route="query-report/Payroll Register"] .page-head .page-actions button {
            height: 26px !important;
            padding: 0 10px !important;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        /* "This report was generated ... ago": the register is re-run on every filter change,
           so the note only adds noise. */
        body[data-route="query-report/Payroll Register"] .page-form + .form-message {
            display: none !important;
        }

        /* ---- Payroll Analysis: a centred panel below the grid; optional in print ---- */
        .payroll-analysis {
            max-width: 1180px;
            margin: 28px auto 16px;
            padding: 14px 18px 4px;
            border: 1px solid var(--border-color, #e5e7eb);
            border-radius: 8px;
            background: var(--card-bg, #fff);
            font-size: 11.5px;
            color: var(--text-color, #1f2937);
        }
        /* The line that marks where the analysis starts, with the period it covers. */
        .payroll-analysis .pa-divider {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
        }
        .payroll-analysis .pa-divider::before,
        .payroll-analysis .pa-divider::after {
            content: "";
            flex: 1;
            border-top: 2px solid #b8122c;
        }
        .payroll-analysis .pa-title {
            font-size: 13px;
            font-weight: 700;
            color: #b8122c;
            white-space: nowrap;
        }
        .payroll-analysis .pa-muted {
            color: var(--text-muted, #6b7280);
            font-weight: 400;
        }
        .payroll-analysis .pa-tiles {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 8px;
            margin-bottom: 14px;
        }
        .payroll-analysis .pa-tile {
            border: 1px solid var(--border-color, #d1d5db);
            border-radius: 6px;
            padding: 8px 10px;
            background: var(--card-bg, #fff);
        }
        .payroll-analysis .pa-tile-total {
            border-color: #b8122c;
            background: #ffe8ec;
        }
        .payroll-analysis .pa-tile-label {
            color: var(--text-muted, #6b7280);
            font-size: 10.5px;
            margin-bottom: 3px;
        }
        .payroll-analysis .pa-tile-value {
            font-weight: 700;
            font-size: 13px;
            font-variant-numeric: tabular-nums;
        }
        /* One section after another, each the full width of the panel. */
        .payroll-analysis .pa-grid {
            display: block;
        }
        @media (max-width: 1100px) {
            .payroll-analysis .pa-tiles { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        }
        .payroll-analysis .pa-block {
            margin: 0 0 16px;
            padding-top: 12px;
            border-top: 1px solid var(--border-color, #e5e7eb);
            overflow-x: auto;
        }
        .payroll-analysis .pa-block-title {
            font-weight: 700;
            margin-bottom: 2px;
        }
        .payroll-analysis .pa-note {
            color: var(--text-muted, #6b7280);
            font-size: 10.5px;
            margin-bottom: 6px;
        }
        .payroll-analysis .pa-table {
            width: 100%;
            border-collapse: collapse;
            table-layout: fixed;
        }
        /* Names and labels wrap; figures never do, so no amount is ever cut off. */
        .payroll-analysis .pa-table th,
        .payroll-analysis .pa-table td {
            border-bottom: 1px solid var(--border-color, #e5e7eb);
            padding: 4px 6px;
            text-align: left;
            white-space: normal;
            font-size: 11px;
        }
        .payroll-analysis .pa-table th {
            font-weight: 600;
            color: var(--text-muted, #6b7280);
            white-space: normal;
            vertical-align: bottom;
        }
        .payroll-analysis .pa-table .num {
            text-align: right;
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
        }
        .payroll-analysis .pa-table tfoot td {
            font-weight: 700;
            border-top: 2px solid #b8122c;
            border-bottom: none;
        }

        /* Own page by default; kept on the register's page when it fits (see fit_print_table_to_page). */
        #payroll-print-area .print-analysis {
            break-before: page;
            page-break-before: always;
            font-size: 9px !important;
        }
        #payroll-print-area .print-analysis.same-page {
            break-before: auto;
            page-break-before: auto;
            margin-top: 14px;
        }
        #payroll-print-area .print-analysis .pa-divider {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }
        #payroll-print-area .print-analysis .pa-divider::before,
        #payroll-print-area .print-analysis .pa-divider::after {
            content: "";
            flex: 1;
            border-top: 1.5px solid #b8122c;
        }
        #payroll-print-area .print-analysis .pa-table td:not(.num) {
            white-space: normal !important;
        }
        #payroll-print-area .print-analysis .payroll-analysis,
        #payroll-print-area .print-analysis {
            color: #111827;
        }
        #payroll-print-area .print-analysis .pa-tiles {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: 6px;
            margin-bottom: 10px;
        }
        #payroll-print-area .print-analysis .pa-heading { margin: 0 0 8px; }
        #payroll-print-area .print-analysis .pa-title { font-size: 12px; font-weight: 700; color: #b8122c; }
        #payroll-print-area .print-analysis .pa-muted { color: #6b7280; }
        #payroll-print-area .print-analysis .pa-tile { border: 1px solid #9ca3af; border-radius: 4px; padding: 5px 7px; }
        #payroll-print-area .print-analysis .pa-tile-total { border-color: #b8122c; background: #ffe8ec !important; }
        #payroll-print-area .print-analysis .pa-tile-label { color: #6b7280; font-size: 8px; }
        #payroll-print-area .print-analysis .pa-tile-value { font-weight: 700; font-size: 10px; }
        #payroll-print-area .print-analysis .pa-grid { display: block; }
        #payroll-print-area .print-analysis .pa-block { margin-bottom: 10px; break-inside: avoid; }
        #payroll-print-area .print-analysis .pa-block-title { font-weight: 700; }
        #payroll-print-area .print-analysis .pa-note { color: #6b7280; font-size: 8px; margin-bottom: 4px; }
        #payroll-print-area .print-analysis .pa-table { width: 100%; border-collapse: collapse; table-layout: fixed; }
        #payroll-print-area .print-analysis .pa-table th {
            background: #b8122c !important;
            color: #fff !important;
            font-weight: 700;
            white-space: normal !important;
        }
        #payroll-print-area .print-analysis .pa-table th,
        #payroll-print-area .print-analysis .pa-table td {
            border: 1px solid #9ca3af;
            padding: 2px 4px;
            text-align: left;
            white-space: nowrap;
        }
        #payroll-print-area .print-analysis .pa-table .num { text-align: right; }
        #payroll-print-area .print-analysis .pa-table tfoot td {
            font-weight: 700;
            color: #b8122c;
            background: #ffe8ec !important;
        }

        /* Actions only offers chart and dashboard tools, which this register has no use for. */
        body[data-route="query-report/Payroll Register"] .inner-group-button[data-label="Actions"],
        body[data-route="query-report/Payroll Register"] .page-head .actions-btn-group {
            display: none !important;
        }

        /* ---- Print block visual styling (ALWAYS applied, not @media-print gated) ----
           The block is display:none on screen so it never shows, but the borders,
           padding, fonts and letterhead sizing below must exist off-screen too — the
           auto-fit in fit_print_table_to_page() renders the block off-screen to MEASURE
           its true height. If these lived inside @media print they wouldn't apply during
           that measurement, the block would measure far shorter than it prints, and the
           font would never shrink — spilling the printout onto a second page. */
        #payroll-print-area {
            display: none;
            width: 100%;
            background: #fff;
            color: #000;
            font-family: Arial, sans-serif;
            font-size: 6px;
            line-height: 1.0;
            /* Force background colours to print even when the browser's "Print backgrounds"
               option is OFF — otherwise the teal header (white text) prints white-on-white
               and the whole header row is invisible on paper. */
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
        }

        #payroll-print-area .print-letterhead {
            text-align: center;
            border-bottom: 2px solid #b8122c;
            padding-bottom: 2px;
            margin-bottom: 4px;
        }

        #payroll-print-area .print-letterhead-img {
            margin-bottom: 2px;
        }

        #payroll-print-area .print-letterhead-img img {
            max-height: 46px;
            max-width: 100%;
            object-fit: contain;
        }

        #payroll-print-area .print-company {
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.3px;
            color: #b8122c;
        }

        #payroll-print-area .print-title {
            font-size: 10px;
            font-weight: 700;
            margin-top: 1px;
            letter-spacing: 0.5px;
            color: #8c0e22;
        }

        #payroll-print-area .print-period {
            font-size: 9px;
            margin-top: 1px;
        }

        #payroll-print-area .print-table-wrap {
            width: 100%;
            overflow: hidden !important;
        }

        /* Columns take the width of their data: names and amounts stay on one line, and a
           long header such as "Medical Allowance (Employer)" wraps over its column instead
           of widening it (see size_print_columns). Centred under the title. */
        #payroll-print-area table {
            width: auto;
            margin: 0 auto;
            border-collapse: collapse;
            table-layout: auto;
        }

        #payroll-print-area thead {
            display: table-header-group;
        }

        #payroll-print-area tfoot {
            display: table-footer-group;
        }

        #payroll-print-area tr {
            page-break-inside: avoid !important;
            break-inside: avoid !important;
        }

        #payroll-print-area th,
        #payroll-print-area td {
            border: 1px solid #777;
            padding: 1px 3px;
            vertical-align: middle;
            word-break: normal;
            overflow-wrap: normal;
        }

        #payroll-print-area td {
            white-space: nowrap !important;
        }

        #payroll-print-area th {
            background: #b8122c !important;
            color: #fff !important;
            font-weight: 700;
            text-align: center;
            vertical-align: middle;
            white-space: normal !important;
            writing-mode: horizontal-tb !important;
            text-orientation: mixed !important;
            transform: none !important;
            min-width: 0 !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
            color-adjust: exact !important;
        }

        #payroll-print-area td.num {
            text-align: right;
            white-space: nowrap !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
        }

        #payroll-print-area td.txt {
            text-align: left;
        }

        #payroll-print-area td.nowrap {
            white-space: nowrap !important;
            word-break: normal !important;
            overflow-wrap: normal !important;
        }

        #payroll-print-area .strong-col {
            font-weight: 700;
        }

        #payroll-print-area .negative {
            color: #7f1d1d;
            font-weight: 700;
        }

        #payroll-print-area .totals-row td {
            font-weight: 700;
            color: #b8122c;
            border-top: 2px solid #8c0e22;
            background: #ffe8ec !important;
        }

        #payroll-print-area .print-signatures {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            margin-top: 10px;
            page-break-inside: avoid !important;
            break-inside: avoid !important;
        }

        #payroll-print-area .sign-box {
            flex: 1;
        }

        #payroll-print-area .sign-label {
            font-size: 9px;
            font-weight: 700;
            margin-bottom: 10px;
        }

        #payroll-print-area .sign-line {
            border-bottom: 1px solid #000;
            margin-bottom: 2px;
            height: 1px;
        }

        #payroll-print-area .sign-note {
            font-size: 8px;
            color: #666;
        }

        .page-actions .btn[data-label="Print%20Register"],
        .page-actions .btn[data-label="Print Register"] {
            background: #8c0e22 !important;
            color: #fff !important;
            border-color: #b8122c !important;
            font-weight: 700 !important;
            box-shadow: 0 2px 8px rgba(13, 148, 136, 0.30) !important;
        }

        .page-actions .btn[data-label="Print%20Register"]:hover,
        .page-actions .btn[data-label="Print Register"]:hover {
            background: #b8122c !important;
            filter: none;
        }

        @media print {
            @page {
                size: A4 landscape;
                margin: 0.35cm;
            }

            html, body {
                overflow: visible !important;
                background: #fff !important;
                height: auto !important;
                min-height: 0 !important;
            }

            /* Remove the whole desk (report page, datatable, toolbars) from the
               printed layout. Using display:none — not visibility:hidden — so the
               hidden desk keeps NO layout height; otherwise its tall height spills
               the printout onto a blank second page even when nothing is visible. */
            body > *:not(#payroll-print-area) {
                display: none !important;
            }

            #payroll-print-area {
                display: block !important;
                position: static !important;
                overflow: visible !important;
                page-break-after: avoid !important;
                break-after: avoid-page !important;
            }
        }
    `;
    document.head.appendChild(style);
}

function hide_default_print_menu() {
    const page = frappe.query_report.page;
    if (!page || !page.menu) return;

    const labels = [
        '[data-label="Print"]',
        '[data-label="Print%20Report"]',
        '[data-label="Print%20Preview"]',
        '[data-label="Print%20Settings"]'
    ];

    labels.forEach(selector => {
        page.menu.find(selector).each(function () {
            $(this).closest("li").remove();
            $(this).closest(".menu-item").remove();
        });
    });

    page.menu.find("a, span, button").each(function () {
        const txt = ($(this).text() || "").trim().toLowerCase();
        if (txt === "print" || txt === "print report" || txt === "print preview" || txt === "print settings") {
            $(this).closest("li").remove();
            $(this).closest(".menu-item").remove();
        }
    });
}

function add_print_button_once(report) {
    const existing = report.page.inner_toolbar.find(
        '[data-label="Print%20Register"], [data-label="Print Register"]'
    );
    if (existing.length) return;

    const $button = report.page.add_inner_button(__("Print Register"), function () {
        const data = frappe.query_report.data || [];
        const columns = frappe.query_report.columns || [];

        if (!data.length) {
            frappe.msgprint(__("No Records to Print"));
            return;
        }

        const dialog = new frappe.ui.Dialog({
            title: __("Print Register"),
            size: "small",
            fields: [
                {
                    fieldname: "include_analysis",
                    fieldtype: "Check",
                    label: __("Include Payroll Analysis"),
                    default: 0,
                },
            ],
            primary_action_label: __("Print"),
            primary_action(values) {
                dialog.hide();
                const company = frappe.query_report.get_filter_value("company");
                get_letterhead_html(company).then((letterheadHtml) => {
                    build_print_html(columns, data, letterheadHtml, !!values.include_analysis);
                    print_when_ready();
                });
            },
        });
        dialog.show();
    });

    report.page.change_inner_button_type(__("Print Register"), null, "primary");
    $button.prepend(frappe.utils.icon("printer", "xs"));
}

// Fetch the company's Letter Head HTML (logo + branding) so the printout carries the real company
// letterhead instead of a plain company name. Resolves to null when there is none.
function get_letterhead_html(company) {
    if (!company) return Promise.resolve(null);
    return frappe.db
        .get_value("Company", company, "default_letter_head")
        .then((r) => {
            const lh = r && r.message && r.message.default_letter_head;
            if (!lh) return null;
            return frappe.db.get_value("Letter Head", lh, "content").then((r2) => {
                return (r2 && r2.message && r2.message.content) || null;
            });
        })
        .catch(() => null);
}

// Print only after the letterhead logo (and any other image) has loaded, so it isn't missing on
// the first print; falls back after 1.5s so a slow/broken image never blocks printing.
function print_when_ready() {
    const area = document.getElementById("payroll-print-area");
    const imgs = area ? Array.prototype.slice.call(area.querySelectorAll("img")) : [];
    const pending = imgs.filter((im) => !im.complete);

    const go = () => {
        fit_print_table_to_page();
        window.print();
    };

    if (!pending.length) {
        setTimeout(go, 150);
        return;
    }

    let done = 0;
    let fired = false;
    const fire = () => {
        if (!fired) {
            fired = true;
            go();
        }
    };
    pending.forEach((im) => {
        const tick = () => {
            done += 1;
            if (done >= pending.length) fire();
        };
        im.addEventListener("load", tick);
        im.addEventListener("error", tick);
    });
    setTimeout(fire, 1500);
}

function build_print_html(columns, data, letterheadHtml, include_analysis = false) {
    const old = document.getElementById("payroll-print-area");
    if (old) old.remove();

    const company = frappe.query_report.get_filter_value("company") || "";
    const fromRaw = frappe.query_report.get_filter_value("from_date") || "";
    const toRaw = frappe.query_report.get_filter_value("to_date") || "";

    function fmtDate(str) {
        if (!str) return "";
        const d = new Date(str + "T00:00:00");
        return d.toLocaleDateString("en-GB", {
            day: "2-digit",
            month: "long",
            year: "numeric",
        });
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function formatValue(col, val, row) {
        if (val === null || val === undefined || val === "") return "";

        // Payment Days: whole numbers without a trailing ".0" (30.0 -> 30), fractions kept (24.5).
        if (col.fieldname === "payment_days") {
            return format_payment_days(val);
        }

        // Money columns are all fieldtype "Currency": plain amounts, the currency is in the heading.
        if (col.fieldtype === "Currency") {
            return format_amount(val);
        }

        // Other numeric columns (e.g. Payment Days = Float) are plain numbers, no currency symbol.
        if (NUMERIC_FIELDTYPES.includes(col.fieldtype)) {
            return format_number(flt(val), null, cint(col.precision) || null);
        }

        if (col.fieldtype === "Date" && val) {
            return frappe.datetime.str_to_user(val);
        }

        return escapeHtml(val);
    }

    const fromFmt = fmtDate(fromRaw);
    const toFmt = fmtDate(toRaw);
    const period = fromFmt && toFmt ? `${fromFmt} – ${toFmt}` : "";
    const currency = (data[0] && data[0].currency) || frappe.defaults.get_default("currency") || "";

    const printableColumns = columns.filter(col => col.fieldname && col.label);

    const headerHtml = printableColumns
        .map(col => `<th>${escapeHtml(__(col.label))}</th>`)
        .join("");

    const bodyHtml = data
        .map(row => {
            const isTotalRow = row.salary_slip === "Total";

            const cells = printableColumns.map(col => {
                const rawVal = row[col.fieldname];
                const formatted = formatValue(col, rawVal, row);

                const isNum = NUMERIC_FIELDTYPES.includes(col.fieldtype);
                const isStrong = STRONG_FIELDS.includes(col.fieldname) || isTotalRow;
                const isNegativeNet = col.fieldname === "net_pay" && flt(rawVal) < 0;
                const isNoWrap = NOWRAP_FIELDS.includes(col.fieldname);

                const classes = [
                    isNum ? "num" : "txt",
                    isNoWrap ? "nowrap" : "",
                    isStrong ? "strong-col" : "",
                    isNegativeNet ? "negative" : ""
                ].filter(Boolean).join(" ");

                return `<td class="${classes}">${formatted}</td>`;
            }).join("");

            return `<tr class="${isTotalRow ? "totals-row" : ""}">${cells}</tr>`;
        })
        .join("");

    const wrapper = document.createElement("div");
    wrapper.id = "payroll-print-area";
    wrapper.innerHTML = `
        <div class="print-letterhead">
            ${letterheadHtml
                ? `<div class="print-letterhead-img">${letterheadHtml}</div>`
                : `<div class="print-company">${escapeHtml(company)}</div>`}
            <div class="print-title">Payroll Register</div>
            ${period ? `<div class="print-period">Period: <strong>${escapeHtml(period)}</strong>${currency ? ` &nbsp;|&nbsp; Amounts in <strong>${escapeHtml(currency)}</strong>` : ""}</div>` : ""}
        </div>

        <div class="print-table-wrap">
            <table id="payroll-print-table">
                <thead>
                    <tr>${headerHtml}</tr>
                </thead>
                <tbody>
                    ${bodyHtml}
                </tbody>
            </table>
        </div>

        <div class="print-signatures">
            <div class="sign-box">
                <div class="sign-label">Prepared By:</div>
                <div class="sign-line"></div>
                <div class="sign-note">Name, Signature & Date</div>
            </div>
            <div class="sign-box">
                <div class="sign-label">Confirmed By:</div>
                <div class="sign-line"></div>
                <div class="sign-note">Name, Signature & Date</div>
            </div>
            <div class="sign-box">
                <div class="sign-label">Approved By:</div>
                <div class="sign-line"></div>
                <div class="sign-note">Name, Signature & Date</div>
            </div>
        </div>

        ${include_analysis && payroll_analysis ? `<div class="print-analysis payroll-analysis-print">${analysis_html(payroll_analysis)}</div>` : ""}
    `;

    document.body.appendChild(wrapper);
}

// A4 landscape printable area in CSS px at 96dpi, minus the @page margin (0.35cm each side).
// Browsers lay out print at 96 CSS px/inch, so these map directly to the physical page.
//   width:  29.7cm - 0.70cm = 29.0cm ≈ 1096px  |  height: 21.0cm - 0.70cm = 20.3cm ≈ 767px
// Small safety margins keep the auto-fit from riding the very edge and spilling to page 2.
const PRINT_PAGE_WIDTH_PX = 1088;
const PRINT_PAGE_HEIGHT_PX = 752;
const PRINT_FONT_MAX = 9;    // compact by default; the fit below only ever shrinks it
const PRINT_FONT_MIN = 4;    // readability floor

function fit_print_table_to_page() {
    const area = document.getElementById("payroll-print-area");
    const wrap = area?.querySelector(".print-table-wrap");
    const table = area?.querySelector("#payroll-print-table");

    if (!area || !wrap || !table) return;

    // Body cells never wrap and each column is as wide as its widest value, with long headers
    // wrapping over it (size_print_columns). We render the block at the true page width
    // off-screen, then shrink the font from PRINT_FONT_MAX until the whole block (header, every
    // row, signatures) fits one page's height and the table fits its width, so the register
    // prints on one A4 landscape page on any monitor or printer.
    wrap.style.transform = "none";
    wrap.style.width = "100%";

    // Force the block measurable at the real print width (it is display:none on screen).
    const saved = {
        display: area.style.display,
        position: area.style.position,
        left: area.style.left,
        top: area.style.top,
        width: area.style.width,
        visibility: area.style.visibility,
    };
    area.style.display = "block";
    area.style.position = "absolute";
    area.style.left = "-10000px";
    area.style.top = "0";
    area.style.visibility = "hidden";
    area.style.width = PRINT_PAGE_WIDTH_PX + "px";

    // A no-wrap cell overflows when its single line is wider than the column's content box.
    // 1px tolerance absorbs sub-pixel rounding so we don't shrink forever chasing a phantom.
    const nowrap_cells = area.querySelectorAll("td.num, td.nowrap");
    const has_nowrap_overflow = () => {
        for (const cell of nowrap_cells) {
            if (cell.scrollWidth > cell.clientWidth + 1) return true;
        }
        return false;
    };

    // The analysis is left out while the register's font is fitted; it is placed afterwards.
    const analysis = area.querySelector(".print-analysis");
    if (analysis) analysis.style.display = "none";

    let fontSize = PRINT_FONT_MAX;
    area.style.fontSize = fontSize + "px";
    size_print_columns(table, fontSize);
    // Step down until the block fits one page height, the table fits the page width (cells no
    // longer wrap, so a long name widens its column) and no amount / employee code overflows.
    while (
        fontSize > PRINT_FONT_MIN &&
        (area.offsetHeight > PRINT_PAGE_HEIGHT_PX ||
            table.offsetWidth > PRINT_PAGE_WIDTH_PX ||
            has_nowrap_overflow())
    ) {
        fontSize -= 0.25;
        area.style.fontSize = fontSize + "px";
    }

    // With the register's font settled, see whether the analysis also fits on this page.
    if (analysis) {
        analysis.style.display = "";
        analysis.classList.add("same-page");
        if (area.offsetHeight > PRINT_PAGE_HEIGHT_PX) analysis.classList.remove("same-page");
    }

    // Restore the print-managed layout; keep only the computed font size.
    area.style.display = saved.display;
    area.style.position = saved.position;
    area.style.left = saved.left;
    area.style.top = saved.top;
    area.style.width = saved.width;
    area.style.visibility = saved.visibility;
    area.style.fontSize = fontSize + "px";
}

// Give each header the width of its column's widest value, so the header wraps over the data
// rather than stretching the column to fit itself on one line. In em, so the widths hold as the
// fit above shrinks the font.
function size_print_columns(table, fontSize) {
    const headers = table.querySelectorAll("thead th");
    const widest = Array.from(headers, () => 0);
    const range = document.createRange();

    table.querySelectorAll("tbody tr").forEach((tr) => {
        Array.from(tr.children).forEach((td, i) => {
            range.selectNodeContents(td);
            widest[i] = Math.max(widest[i] || 0, range.getBoundingClientRect().width);
        });
    });

    headers.forEach((th, i) => {
        // Cell padding (3px each side) plus a hair for rounding.
        th.style.width = (widest[i] + 8) / fontSize + "em";
    });
}

// ---------------------------------------------------------------- payroll analysis

// The last analysis loaded for the current filters, reused by Print Register.
let payroll_analysis = null;

function load_payroll_analysis() {
    const filters = frappe.query_report.get_filter_values();
    frappe.call({
        method: "cgm_shipping.cgm_worldwide_shipping.report.payroll_register.payroll_register.get_payroll_analysis",
        args: { filters },
        callback: (r) => {
            payroll_analysis = r.message && r.message.summary ? r.message : null;
            render_payroll_analysis();
        },
    });
}

function render_payroll_analysis() {
    const $report = frappe.query_report.$report;
    if (!$report) return;
    $report.siblings("#payroll-analysis").remove();
    if (!payroll_analysis) return;
    $(`<div id="payroll-analysis" class="payroll-analysis">${analysis_html(payroll_analysis)}</div>`).insertAfter($report);
}

// "2215 - PAYE Payable - CWSCL" reads as "PAYE Payable (2215)".
function account_label(account) {
    const parts = String(account || "").split(" - ");
    if (parts.length >= 3) return `${parts.slice(1, -1).join(" - ")} (${parts[0]})`;
    return account;
}

// "1 Oct 2026 to 31 Oct 2026", from the report's own date filters.
function period_label() {
    const from = frappe.query_report.get_filter_value("from_date");
    const to = frappe.query_report.get_filter_value("to_date");
    if (!from || !to) return "";
    const fmt = (d) => moment(d).format("D MMM YYYY");
    return __("{0} to {1}", [fmt(from), fmt(to)]);
}

function analysis_html(a) {
    const esc = frappe.utils.escape_html;
    const amt = (v) => format_amount(v);
    const sum = (rows, key) => rows.reduce((t, r) => t + flt(r[key]), 0);
    const s = a.summary;

    const tiles = [
        [__("People Paid"), String(s.people)],
        [__("Gross Pay"), amt(s.gross_pay)],
        [__("Deductions"), amt(s.total_deduction)],
        [__("Net Pay to Bank"), amt(s.net_pay)],
        [__("Employer Contributions"), amt(s.employer_contributions)],
        [__("Total Cost to Company"), amt(s.cost_to_company)],
    ]
        .map(([label, value], i) => `
            <div class="pa-tile${i === 5 ? " pa-tile-total" : ""}">
                <div class="pa-tile-label">${label}</div>
                <div class="pa-tile-value">${value}</div>
            </div>`)
        .join("");

    // Fixed column widths: the label columns share 34%, every amount column gets the same
    // share of the rest, so figures sit in straight right-aligned columns.
    const colgroup = (head) => {
        const text = head.filter(([, num]) => !num).length;
        const nums = head.length - text;
        const text_share = text > 1 ? 44 : 30;
        return `<colgroup>${head
            .map(([, num]) => `<col style="width:${num ? (100 - text_share) / nums : text_share / text}%">`)
            .join("")}</colgroup>`;
    };

    const table = (title, note, head, rows, foot) => `
        <div class="pa-block">
            <div class="pa-block-title">${title}</div>
            ${note ? `<div class="pa-note">${note}</div>` : ""}
            <table class="pa-table">
                ${colgroup(head)}
                <thead><tr>${head.map(([h, num]) => `<th class="${num ? "num" : ""}">${h}</th>`).join("")}</tr></thead>
                <tbody>${rows.map((cells) => `<tr>${cells.map(([v, num]) => `<td class="${num ? "num" : ""}">${v}</td>`).join("")}</tr>`).join("")}</tbody>
                ${foot ? `<tfoot><tr>${foot.map(([v, num]) => `<td class="${num ? "num" : ""}">${v}</td>`).join("")}</tr></tfoot>` : ""}
            </table>
        </div>`;

    const roles = table(
        __("Cost by Role"),
        __("What each role costs, employer contributions included. Monthly cost is per person per payslip."),
        [[__("Role")], [__("People"), 1], [__("Gross Pay"), 1], [__("Employer Contributions"), 1], [__("Total Cost"), 1], [__("Monthly Cost per Person"), 1]],
        a.by_role.map((r) => [[esc(r.designation)], [r.people, 1], [amt(r.gross_pay), 1], [amt(r.employer_contributions), 1], [amt(r.cost), 1], [amt(r.monthly_cost_per_person), 1]]),
        [[__("Total")], [s.people, 1], [amt(sum(a.by_role, "gross_pay")), 1], [amt(sum(a.by_role, "employer_contributions")), 1], [amt(sum(a.by_role, "cost")), 1], [""]]
    );

    const payables = table(
        __("Statutory Payables"),
        __("Amounts to remit, by the account they are posted to: the share taken from staff pay and the share CGM pays on top."),
        [[__("Payable")], [__("Components")], [__("From Staff"), 1], [__("From CGM"), 1], [__("Total to Remit"), 1]],
        a.payables.map((r) => [[esc(account_label(r.account))], [esc(r.components.join(", "))], [amt(r.staff), 1], [amt(r.employer), 1], [amt(r.total), 1]]),
        [[__("Total")], [""], [amt(sum(a.payables, "staff")), 1], [amt(sum(a.payables, "employer")), 1], [amt(sum(a.payables, "total")), 1]]
    );

    const part_month = a.part_month.length
        ? table(
              __("Part-Month Pay"),
              __("Paid for fewer days than the month's working days, such as a mid-month start or exit."),
              [[__("Employee")], [__("Month")], [__("Days Paid"), 1], [__("Working Days"), 1], [__("Full-Month Gross"), 1], [__("Gross Paid"), 1]],
              a.part_month.map((r) => [[`${esc(r.employee_name)} <span class="pa-muted">${esc(r.employee)}</span>`], [esc(r.month)], [format_payment_days(r.payment_days), 1], [format_payment_days(r.working_days), 1], [amt(r.full_month_gross), 1], [amt(r.gross_pay), 1]])
          )
        : "";

    return `
        <div class="pa-divider">
            <span class="pa-title">${__("Payroll Analysis")}${period_label() ? ` &middot; ${esc(period_label())}` : ""}</span>
            <span class="pa-muted">${__("Amounts in {0}", [esc(a.currency || "")])}</span>
        </div>
        <div class="pa-tiles">${tiles}</div>
        <div class="pa-grid">${roles}${payables}</div>
        ${part_month}`;
}

function remove_report_noise() {
    [
        ".report-footer",
        ".report-message",
        ".result-info",
        ".dt-info",
        ".datatable-info",
        ".datatable-hint",
        ".dt-filter-hint",
        ".dt-row-filter"
    ].forEach(selector => {
        $(document).find(selector).remove();
    });
}

function validate_date_range() {
    const from = frappe.query_report.get_filter_value("from_date");
    const to = frappe.query_report.get_filter_value("to_date");
    if (from && to && from > to) {
        frappe.msgprint(__("From Date cannot be after To Date."));
    }
}