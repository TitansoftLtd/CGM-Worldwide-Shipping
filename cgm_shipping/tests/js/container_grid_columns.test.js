// The Container Updates grid rendered with the wrong columns until the page was
// reloaded. Three things combined to cause it, and these cases pin all three.
//
// 1. Frappe's update_docfield_property does nothing at all while grid.grid_rows is
//    undefined. A configurator that runs before the rows exist changes nothing yet
//    still sets its "ready" flag, so it never runs again.
// 2. update_docfield_property THROWS for a field the child table does not carry.
//    An uncaught throw abandons the rest of the layout half-applied.
// 3. The sea-sequence config arrives asynchronously and re-triggers refresh, but
//    it used to reset only two of the six ready flags.
//
// Run by cgm_shipping/tests/test_container_grid_columns.py, or directly:
//     node cgm_shipping/tests/js/container_grid_columns.test.js
const fs = require("fs");
const vm = require("vm");
const path = require("path");

const SRC =
	process.env.CGM_TASK_JS ||
	path.join(__dirname, "..", "..", "public", "js", "task.js");

const noop = () => {};

function load() {
	const ctx = {
		console,
		locals: {},
		__: (s) => s,
		setTimeout,
		clearTimeout,
		frappe: {
			ui: { form: { on: noop, ControlData: function () {} } },
			model: { set_value: noop, get_value: noop, with_doc: noop },
			meta: { get_docfield: () => null, has_field: () => false },
			utils: { escape_html: (s) => s },
			datetime: { str_to_user: (s) => s, now_datetime: () => "", get_today: () => "" },
			provide: noop, call: noop, msgprint: noop, show_alert: noop, throw: noop,
			db: { get_value: () => Promise.resolve({}), get_list: () => Promise.resolve([]) },
			user: { has_role: () => false },
			session: { user: "x" },
			realtime: { on: noop },
			router: {}, set_route: noop, confirm: noop, warn: noop, prompt: noop,
			dom: {}, views: {},
		},
		cint: (v) => parseInt(v || 0, 10),
		flt: (v) => parseFloat(v || 0),
		erpnext: { utils: {} },
		cur_frm: null,
		$: Object.assign(() => ({ on: noop, find: () => ({ on: noop }), appendTo: noop }), {
			extend: Object.assign,
		}),
	};
	vm.createContext(ctx);
	vm.runInContext(fs.readFileSync(SRC, "utf8"), ctx);
	// A top-level `const` lives in the context's lexical scope, not on the context
	// object, so read it by evaluating the name rather than via ctx.<name>.
	ctx.__read = (name) => vm.runInContext(name, ctx);
	return ctx;
}

// A grid that behaves like Frappe's: silent before rows exist, throws on unknown.
function makeGrid(fieldnames, { rendered = true } = {}) {
	const docfields = fieldnames.map((f) => ({
		fieldname: f, in_list_view: 0, hidden: 0, read_only: 0,
	}));
	return {
		docfields,
		grid_rows: rendered ? [] : undefined,
		refreshes: 0,
		update_docfield_property(fieldname, property, value) {
			if (!this.grid_rows) return; // Frappe's own early return
			const df = this.docfields.find((d) => d.fieldname === fieldname);
			if (!df) throw `field ${fieldname} not found`;
			df[property] = value;
			this.refreshes += 1;
		},
	};
}

const COLS = [
	"container_number", "cargo_size", "current_status", "deposit_amount",
	"discharging_date", "transporter", "truck_number", "driver_name",
	"driver_contact", "gate_out_date_port", "actual_empty_return", "interchange_date",
	"gate_in_date_warehouse", "offloading_date", "free_days_start_date",
];

function check(label, condition) {
	if (!condition) throw new Error("FAILED: " + label);
	console.log("  ok  " + label);
}

const ctx = load();
const KEEP = ctx.__read("SHIPPING_LINE_CONTAINER_COLUMNS");

check("the shipping-line column list is exported", Array.isArray(KEEP) && KEEP.length > 4);

// 1. the render check
check(
	"a grid with no rows yet is not ready to configure",
	ctx.container_grid_is_rendered(makeGrid(COLS, { rendered: false })) === false
);
check(
	"a rendered grid is ready, even with zero rows",
	ctx.container_grid_is_rendered(makeGrid(COLS)) === true
);
check("a missing grid is not ready", ctx.container_grid_is_rendered(null) === false);

// 2. the columns it keeps and drops
const grid = makeGrid(COLS);
ctx.restrict_container_grid_columns(grid, KEEP);
const byName = Object.fromEntries(grid.docfields.map((d) => [d.fieldname, d]));
check("the truck column is shown", byName.truck_number.in_list_view === 1);
check("the driver column is shown", byName.driver_name.in_list_view === 1);
check("the deposit column is shown", byName.deposit_amount.in_list_view === 1);
check(
	"a column belonging to another step is dropped",
	byName.free_days_start_date.in_list_view === 0
);
check(
	"the mirrored columns are read-only",
	byName.truck_number.read_only === 1 && byName.gate_out_date_port.read_only === 1
);
check(
	"the container's own identity stays editable",
	byName.container_number.read_only === 0
);

// 3. an unknown column must not abandon the rest
const partial = makeGrid(COLS.filter((c) => c !== "driver_contact"));
ctx.restrict_container_grid_columns(partial, KEEP);
const partialBy = Object.fromEntries(partial.docfields.map((d) => [d.fieldname, d]));
check(
	"a column this table lacks does not abandon the layout",
	partialBy.interchange_date.in_list_view === 1 && partialBy.truck_number.in_list_view === 1
);

// 4. nothing is attempted before the rows exist
const early = makeGrid(COLS, { rendered: false });
ctx.restrict_container_grid_columns(early, KEEP);
check(
	"configuring an unrendered grid changes nothing",
	early.docfields.every((d) => d.in_list_view === 0) && early.refreshes === 0
);

console.log("container grid column tests passed");
