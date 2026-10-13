// The Material Request items grid is decided by JavaScript, not by `in_list_view`.
//
// `apply_item_grid_layout` holds the app's default column list and replaces
// `grid.setup_user_defined_columns`. That makes it the only thing that decides
// which columns appear on this form, so it is worth testing for real rather than
// by reading the source: a Custom Field, a Property Setter and a column added by
// hand from the gear are all overridden by it.
//
// The app list is a default. A layout the user saved from the gear wins, and
// "Reset to default" in that dialog brings the app list back. These four cases
// pin that down.
//
// Run by cgm_shipping/tests/test_material_request_grid.py, or directly:
//     node cgm_shipping/tests/js/material_request_grid.test.js
const fs = require("fs");
const vm = require("vm");

const path = require("path");
const SRC =
	process.env.CGM_MATERIAL_REQUEST_JS ||
	path.join(__dirname, "..", "..", "public", "js", "material_request.js");

function makeContext(savedUserColumns) {
	const handlers = {};
	const ctx = {
		console,
		locals: {},
		__: (s) => s,
		frappe: {
			ui: { form: { on: (dt, h) => { handlers[dt] = Object.assign(handlers[dt] || {}, h); } } },
			model: { set_value: () => {}, get_value: () => {} },
			meta: { get_docfield: () => null },
			get_user_settings: () => (savedUserColumns ? { "Material Request Item": savedUserColumns } : null),
			utils: { escape_html: (s) => s },
			show_alert: () => {},
			msgprint: () => {},
			call: () => {},
			provide: () => {},
			db: { get_value: () => Promise.resolve({}) },
		},
		cint: (v) => parseInt(v || 0, 10),
		flt: (v) => parseFloat(v || 0),
		erpnext: { utils: {} },
		$: Object.assign(() => ({ on: () => {} }), { extend: Object.assign }),
	};
	vm.createContext(ctx);
	vm.runInContext(fs.readFileSync(SRC, "utf8"), ctx);
	ctx.__handlers = handlers;
	return ctx;
}

const DOCFIELDS = [
	"item_code", "qty", "uom", "custom_currency", "rate", "amount",
	"expense_account", "schedule_date", "warehouse", "from_warehouse", "description",
];

function makeGrid() {
	const fields = {};
	DOCFIELDS.forEach((f) => (fields[f] = { fieldname: f, columns: 1, in_list_view: 0, hidden: 0 }));
	return {
		doctype: "Material Request Item",
		frm: { doctype: "Material Request" },
		user_defined_columns: [],
		get_docfield: (f) => fields[f],
		update_docfield_property: (f, p, v) => { fields[f][p] = v; },
		setup_user_defined_columns() {
			// Frappe's own: honours a saved layout when one exists.
			const saved = this.frm.__saved;
			if (saved && saved.length) {
				this.user_defined_columns = saved.map((r) => Object.assign({}, fields[r.fieldname], { in_list_view: 1 }));
			}
		},
		_fields: fields,
	};
}

function run(name, fn) {
	try { fn(); console.log("  PASS  " + name); }
	catch (e) { console.log("  FAIL  " + name + "\n        " + e.message); process.exitCode = 1; }
}

const ctx = makeContext(null);
const apply = ctx.apply_item_grid_layout;
if (typeof apply !== "function") { console.log("could not reach apply_item_grid_layout"); process.exit(1); }

run("no saved layout -> the app default is used, Currency included", () => {
	const grid = makeGrid();
	const frm = { doctype: "Material Request", doc: { material_request_type: "Operational Expense" }, fields_dict: { items: { grid } } };
	grid.frm = frm;
	apply(frm);
	grid.setup_user_defined_columns();
	const names = grid.user_defined_columns.map((c) => c.fieldname);
	if (!names.includes("custom_currency")) throw new Error("Currency missing: " + names.join(","));
	if (!names.includes("expense_account")) throw new Error("Expense Account missing: " + names.join(","));
});

run("a layout the user saved from the gear wins", () => {
	const grid = makeGrid();
	const frm = { doctype: "Material Request", doc: { material_request_type: "Operational Expense" }, fields_dict: { items: { grid } } };
	grid.frm = frm;
	frm.__saved = [{ fieldname: "item_code" }, { fieldname: "amount" }];
	apply(frm);
	grid.setup_user_defined_columns();
	const names = grid.user_defined_columns.map((c) => c.fieldname);
	if (names.join(",") !== "item_code,amount") throw new Error("user layout ignored, got: " + names.join(","));
});

run("a user-chosen column is not forced out of the list view", () => {
	const grid = makeGrid();
	const frm = { doctype: "Material Request", doc: { material_request_type: "Operational Expense" }, fields_dict: { items: { grid } } };
	grid.frm = frm;
	frm.__saved = [{ fieldname: "description" }];
	apply(frm);
	grid.setup_user_defined_columns();
	const col = grid.user_defined_columns[0];
	if (!col || col.in_list_view !== 1) throw new Error("user column was suppressed");
});

run("clearing the saved layout falls back to the app default", () => {
	const grid = makeGrid();
	const frm = { doctype: "Material Request", doc: { material_request_type: "Operational Expense" }, fields_dict: { items: { grid } } };
	grid.frm = frm;
	frm.__saved = [{ fieldname: "item_code" }];
	apply(frm);
	grid.setup_user_defined_columns();
	frm.__saved = [];                       // "Reset to default" in the gear dialog
	grid.setup_user_defined_columns();
	const names = grid.user_defined_columns.map((c) => c.fieldname);
	if (!names.includes("custom_currency")) throw new Error("did not fall back: " + names.join(","));
});
