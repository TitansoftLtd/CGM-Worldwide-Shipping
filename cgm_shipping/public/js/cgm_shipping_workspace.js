frappe.provide("cgm_shipping.workspace");

const CGM_START_SHIPMENT_LABEL = "Start New Shipment";
const CGM_SHIPPING_WORKSPACE = "CGM Shipping";

function cgm_shipping_workspace_slug() {
	return frappe.router.slug(CGM_SHIPPING_WORKSPACE);
}

function cgm_is_shipping_workspace_route() {
	const route = frappe.get_route() || [];
	const slug = cgm_shipping_workspace_slug();

	if (route[0] === slug || route.includes(slug)) {
		return true;
	}
	if (route[0] === "desk" && route[1] === slug) {
		return true;
	}
	if (route[0] === "Workspaces" && route[1] === slug) {
		return true;
	}
	if (frappe.workspace?._page?.name === CGM_SHIPPING_WORKSPACE) {
		return true;
	}
	return false;
}

function cgm_highlight_start_shipment_cta() {
	if (!cgm_is_shipping_workspace_route()) {
		return;
	}

	$(".shortcut-widget-box").each(function () {
		const $tile = $(this);
		const title = (
			$tile.find(".widget-title span").attr("title") ||
			$tile.find(".widget-title").text() ||
			""
		).trim();
		const is_start_cta =
			title === CGM_START_SHIPMENT_LABEL || title === __(CGM_START_SHIPMENT_LABEL);
		$tile.toggleClass("cgm-start-shipment-cta", is_start_cta);
	});

	$(".ce-header").first().find(".cgm-start-shipment-header, span b").addClass("cgm-start-shipment-header");
}

function cgm_watch_workspace_render() {
	if (!cgm_is_shipping_workspace_route()) {
		return;
	}
	const root = document.querySelector(".editor-js-container");
	if (!root || root.dataset.cgmStartWatch) {
		return;
	}
	root.dataset.cgmStartWatch = "1";
	new MutationObserver(() => cgm_highlight_start_shipment_cta()).observe(root, {
		childList: true,
		subtree: true,
	});
}

function cgm_schedule_start_shipment_highlight() {
	cgm_highlight_start_shipment_cta();
	cgm_watch_workspace_render();
	setTimeout(cgm_highlight_start_shipment_cta, 200);
	setTimeout(cgm_highlight_start_shipment_cta, 800);
	setTimeout(cgm_highlight_start_shipment_cta, 1500);
}

$(document).on("app_ready page-change", cgm_schedule_start_shipment_highlight);
frappe.router.on("change", cgm_schedule_start_shipment_highlight);
