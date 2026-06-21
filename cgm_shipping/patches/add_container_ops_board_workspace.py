"""Ensure Container Ops Board appears on CGM Shipping workspace and sidebar."""
from __future__ import annotations

import json

import frappe


def execute():
	if not frappe.db.exists("Workspace", "CGM Shipping"):
		return

	ws = frappe.get_doc("Workspace", "CGM Shipping")
	link_labels = [l.label for l in ws.links if l.type == "Link"]
	if "Container Ops Board" not in link_labels:
		new_links = []
		for link in ws.links:
			new_links.append(link.as_dict())
			if link.label == "Container Tracker" and link.type == "Link":
				new_links.append(
					{
						"type": "Link",
						"label": "Container Ops Board",
						"link_to": "container-ops-board",
						"link_type": "Page",
						"link_count": 0,
						"hidden": 0,
						"is_query_report": 0,
						"onboard": 0,
					}
				)
		ws.links = []
		for row in new_links:
			ws.append("links", row)

	for link in ws.links:
		if link.type == "Card Break" and link.label == "Transport & Containers":
			link.link_count = 5

	if not any(s.label == "Container Ops Board" for s in ws.shortcuts):
		ws.append(
			"shortcuts",
			{
				"type": "Page",
				"label": "Container Ops Board",
				"link_to": "container-ops-board",
				"color": "Red",
			},
		)

	blocks = json.loads(ws.content or "[]")
	has_tile = any(
		b.get("data", {}).get("shortcut_name") == "Container Ops Board"
		for b in blocks
		if b.get("type") == "shortcut"
	)
	if not has_tile:
		for idx, block in enumerate(blocks):
			if (
				block.get("type") == "shortcut"
				and block.get("data", {}).get("shortcut_name") == "Container Tracker"
			):
				blocks.insert(
					idx + 1,
					{
						"id": "cgmOpsBrd01",
						"type": "shortcut",
						"data": {"shortcut_name": "Container Ops Board", "col": 3},
					},
				)
				break
		ws.content = json.dumps(blocks)

	ws.save(ignore_permissions=True)

	if not frappe.db.exists("Workspace Sidebar", "CGM Shipping"):
		return

	sb = frappe.get_doc("Workspace Sidebar", "CGM Shipping")
	if any(i.label == "Container Ops Board" for i in sb.items):
		return

	new_items = []
	for item in sb.items:
		new_items.append(item.as_dict())
		if item.label == "Container Tracker":
			new_items.append(
				{
					"type": "Link",
					"label": "Container Ops Board",
					"link_to": "container-ops-board",
					"link_type": "Page",
					"icon": "layout-dashboard",
					"child": 1,
					"indent": 0,
					"collapsible": 0,
					"keep_closed": 0,
					"show_arrow": 0,
				}
			)
	sb.items = []
	for row in new_items:
		sb.append("items", row)
	sb.save(ignore_permissions=True)
