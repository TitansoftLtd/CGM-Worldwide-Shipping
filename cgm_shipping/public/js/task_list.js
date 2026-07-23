/** Task list — drop one-shot route_options from the URL so browser Back does not re-trap a project filter. */

const CGM_TASK_LIST_ROUTE_FILTER_KEYS = [
	"project",
	"status",
	"custom_task_flow_key",
	"name",
	"docstatus",
];

function clear_cgm_task_list_route_query() {
	if (!window.location.search) {
		return;
	}
	const params = new URLSearchParams(window.location.search);
	let changed = false;
	CGM_TASK_LIST_ROUTE_FILTER_KEYS.forEach((key) => {
		if (params.has(key)) {
			params.delete(key);
			changed = true;
		}
	});
	if (!changed) {
		return;
	}
	const query = params.toString();
	const new_url = `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash || ""}`;
	history.replaceState(null, "", new_url);
}

const _cgm_task_list_onload = frappe.listview_settings.Task?.onload;

frappe.listview_settings.Task = frappe.listview_settings.Task || {};
frappe.listview_settings.Task.onload = function (listview) {
	if (typeof _cgm_task_list_onload === "function") {
		_cgm_task_list_onload(listview);
	}
	if (listview._cgm_route_query_strip_patch) {
		return;
	}
	listview._cgm_route_query_strip_patch = true;
	const original_before_refresh = listview.before_refresh.bind(listview);
	listview.before_refresh = function () {
		return original_before_refresh().then(() => {
			clear_cgm_task_list_route_query();
		});
	};
};
