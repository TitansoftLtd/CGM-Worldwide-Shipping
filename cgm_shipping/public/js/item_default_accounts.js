// Point the Item Default account pickers at CGM's queries.
//
// ERPNext restricts Default Expense Account and Default Income Account to Profit
// and Loss accounts. CGM accrues shipping line and KPA charges to liability
// accounts and bills them on, so an item for one of those charges has nowhere
// valid to point.
//
// The override is unconditional and the server decides what to return: the query
// reads `allow_any_item_default_account` in CGM Shipping Settings, and with it off
// returns exactly what ERPNext returns. That keeps the setting in one place rather
// than having the client and the server each hold an opinion.

const CGM_ITEM_DEFAULT_QUERIES = {
	expense_account:
		"cgm_shipping.cgm_worldwide_shipping.customizations.item_default_accounts.expense_account_query",
	income_account:
		"cgm_shipping.cgm_worldwide_shipping.customizations.item_default_accounts.income_account_query",
};

function cgm_override_item_default_queries(frm, table_fieldname) {
	const table = frm.fields_dict[table_fieldname];
	if (!table || !table.grid) {
		return;
	}
	Object.entries(CGM_ITEM_DEFAULT_QUERIES).forEach(([fieldname, method]) => {
		const field = table.grid.get_field(fieldname);
		if (!field) {
			return;
		}
		// Runs after ERPNext's own setup_queries, which assigns to this same
		// property on refresh.
		field.get_query = function (doc, cdt, cdn) {
			const row = locals[cdt][cdn] || {};
			return { query: method, filters: { company: row.company } };
		};
	});
}

frappe.ui.form.on("Item", {
	refresh(frm) {
		cgm_override_item_default_queries(frm, "item_defaults");
	},
});

frappe.ui.form.on("Item Group", {
	refresh(frm) {
		cgm_override_item_default_queries(frm, "item_group_defaults");
	},
});
