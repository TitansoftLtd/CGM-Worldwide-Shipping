"""Seed data for CGM Task Template and Container Tracker Mode masters."""

from __future__ import annotations

from cgm_shipping.cgm_worldwide_shipping.customizations.sea_settings_seed_data import (
	DEFAULT_SEA_WORKFLOW_TASK_GATES,
)
from cgm_shipping.cgm_worldwide_shipping.customizations.task_template_registry import (
	AIR_EXPORT_TEMPLATE,
	AIR_IMPORT_TEMPLATE,
	ROAD_TRANSIT_INBOUND_TEMPLATE,
	ROAD_TRANSIT_OUTBOUND_TEMPLATE,
	SEA_EXPORT_TEMPLATE,
	SEA_IMPORT_TEMPLATE,
	SEA_TRANSIT_EXPORT_TEMPLATE,
	SEA_TRANSIT_IMPORT_TEMPLATE,
	SHIPMENT_TYPE_TEMPLATE_MAP,
	SHIPMENT_TYPE_TRACKER_MODE_MAP,
)


def _row(
	seq: int,
	subject: str,
	dept: str,
	*,
	depends: str | int | None = None,
	finance: int = 0,
	doc: int = 0,
	permit: int = 0,
	auto: int = 0,
	condition: str = "",
	description: str = "",
	role: str = "Standard",
	payment_kind: str = "",
	permit_stage: str = "",
	required_docs: str = "",
	container_step: str = "",
) -> dict:
	deps = ""
	if depends is not None:
		deps = str(depends)
	# Infer role from legacy flags when caller did not set an explicit role.
	task_role = (role or "Standard").strip() or "Standard"
	if task_role == "Standard":
		if auto:
			task_role = "Auto Complete"
		elif permit and finance:
			task_role = "Permit Finance"
		elif permit:
			task_role = "Permit Application"
		elif finance and payment_kind:
			task_role = "Finance Payment"
		elif finance:
			task_role = "Finance Payment"
		elif doc:
			task_role = "Document"
	return {
		"sequence_no": seq,
		"subject": subject,
		"department_role": dept,
		"depends_on_sequences": deps,
		"task_role": task_role,
		"payment_kind": payment_kind or "",
		"permit_stage": permit_stage or "",
		"requires_finance_action": finance,
		"requires_document_upload": doc or (1 if required_docs else 0),
		"requires_permit_action": permit,
		"is_auto_completable": auto,
		"completion_condition": condition,
		"description": description,
		"required_document_types": required_docs or "",
		"container_step": container_step or "",
	}


def sea_import_tasks() -> list[dict]:
	"""25-step sea import plan (matches legacy Settings template and automation seqs).

	Only application ↔ finance payment pairs keep depends_on links so ops can work
	non-finance steps (inspection, Lodge DO, field clearance, …) independently.
	"""
	return [
		_row(1, "Receive shipment documents from Client", "Operations", auto=1, role="Auto Complete"),
		_row(2, "Share documents with Declarants", "Operations", auto=1, role="Auto Complete"),
		_row(
			3,
			"Create UCR (IDF)",
			"Declaration",
			role="Application",
			payment_kind="UCR",
			required_docs="IDF_CERT",
		),
		_row(
			4,
			"Finance pays UCR",
			"Finance",
			depends=3,
			finance=1,
			role="Finance Payment",
			payment_kind="UCR",
		),
		_row(
			5,
			"Apply for Pre-Clearance Permits (DVS, NBA, VMD, ACA)",
			"Declaration",
			permit=1,
			role="Permit Application",
			permit_stage="Pre-clearance",
		),
		_row(
			6,
			"Finance pays Pre-Clearance Permits",
			"Finance",
			depends=5,
			finance=1,
			permit=1,
			role="Permit Finance",
			permit_stage="Pre-clearance",
			payment_kind="Permit",
		),
		_row(
			8,
			"Receive Final Clearance Documents (B/L, Invoice, PKL, COC)",
			"Documentation",
			doc=1,
			role="Document Checkpoint",
			container_step="ETA Refresh",
		),
		_row(
			10,
			"Attach Shipping Line Invoice",
			"Documentation",
			doc=1,
			role="Application",
			payment_kind="Shipping Line",
		),
		_row(
			11,
			"Finance pays Shipping Line Charges",
			"Finance",
			depends=10,
			finance=1,
			role="Finance Payment",
			payment_kind="Shipping Line",
		),
		_row(
			12,
			"Create Entry",
			"Declaration",
			doc=1,
			role="Application",
			payment_kind="ENTRY_SLIP",
			container_step="Vessel Arrival",
		),
		_row(
			13,
			"Finance Pays Entry Slip",
			"Finance",
			depends=12,
			finance=1,
			role="Finance Payment",
			payment_kind="ENTRY_SLIP",
		),
		_row(14, "Lodge Delivery Order", "Operations", doc=1, role="Document"),
		_row(
			15,
			"Prepare Post-Clearance Permits",
			"Declaration",
			permit=1,
			role="Permit Application",
			permit_stage="Post-clearance",
		),
		_row(
			16,
			"Finance pays for Post-Clearance Permits",
			"Finance",
			depends=15,
			finance=1,
			permit=1,
			role="Permit Finance",
			permit_stage="Post-clearance",
			payment_kind="Permit",
		),
		_row(17, "Field Officers conduct clearance", "Field Operations", container_step="Field Clearance"),
		_row(
			18,
			"Supervisor obtains KPA Invoice",
			"Operations",
			role="Application",
			payment_kind="KPA",
		),
		_row(
			19,
			"Finance pays KPA Invoice",
			"Finance",
			depends=18,
			finance=1,
			role="Finance Payment",
			payment_kind="KPA",
			container_step="KPA Paid",
		),
		_row(20, "Book trucks and notify warehouse", "Transport", container_step="Book Trucks"),
		_row(21, "Load trucks and exit port", "Transport", container_step="Gate Out"),
		_row(22, "Monitor delivery to destination", "Transport", container_step="Monitor Delivery"),
		_row(23, "Offload cargo", "Transport", container_step="Offload"),
		_row(24, "Return empty container to depot", "Transport", container_step="Empty Return"),
		_row(25, "Receive interchange confirmation", "Transport", container_step="Interchange"),
	]


def sea_export_tasks() -> list[dict]:
	return [
		_row(1, "Receive booking from shipping line", "Operations", doc=1),
		_row(2, "Receive invoice and packing list from client", "Documentation", depends=1, doc=1),
		_row(3, "Collect empty container from depot", "Transport", depends=1),
		_row(4, "Weigh truck with empty container", "Transport", depends=3),
		_row(5, "Loading and stuffing at warehouse", "Field Operations", depends=4),
		_row(6, "Lodge mother entry (customs export entry)", "Declaration", depends=5),
		_row(7, "Capture child entry", "Declaration", depends=6),
		_row(8, "Container armed by KRA and shipping line", "Field Operations", depends=7),
		_row(9, "Lodge stuffing report with KRA", "Declaration", depends=8),
		_row(10, "KRA grants pre-advice permission", "Field Operations", depends=9),
		_row(11, "Finance pays KPA charges - truck enters port", "Finance", depends=10, finance=1),
		_row(12, "Entry settled", "Declaration", depends=11),
		_row(13, "Container scheduled for vessel sailing", "Operations", depends=12),
		_row(14, "Receive Certificate of Export (COE)", "Operations", depends=13, doc=1),
	]


def air_import_tasks() -> list[dict]:
	return [
		_row(1, "Receive proforma invoice packing list COA", "Documentation", doc=1, role="Document"),
		_row(
			2,
			"IDF application (UCR)",
			"Declaration",
			depends=1,
			role="Application",
			payment_kind="UCR",
			required_docs="IDF_CERT",
		),
		_row(
			3,
			"Finance pays UCR",
			"Finance",
			depends=2,
			finance=1,
			role="Finance Payment",
			payment_kind="UCR",
		),
		_row(
			4,
			"Apply for pre-clearance permits",
			"Declaration",
			depends=3,
			permit=1,
			role="Permit Application",
			permit_stage="Pre-clearance",
		),
		_row(
			5,
			"Finance pays permit invoices",
			"Finance",
			depends=4,
			finance=1,
			permit=1,
			role="Permit Finance",
			permit_stage="Pre-clearance",
			payment_kind="Permit",
		),
		_row(
			6,
			"IDF approved - share with client",
			"Operations",
			depends=3,
			auto=1,
			condition="project.custom_entry_no",
			role="Auto Complete",
		),
		_row(7, "Client inspects and shares draft COC", "Operations", depends=6),
		_row(8, "Client shares airwaybill", "Documentation", depends=7, doc=1, role="Document"),
		_row(
			9,
			"Shipment arrival - manifest issued",
			"Operations",
			depends=8,
			doc=1,
			auto=1,
			condition="project.custom_actual_time_of_arrival_ata",
			role="Auto Complete",
		),
		_row(10, "Lodge draft entry - share with client", "Declaration", depends=9, role="Document"),
		_row(
			11,
			"Register entry - share e-slip for tax payment",
			"Declaration",
			depends=10,
			role="Application",
			payment_kind="ENTRY_SLIP",
		),
		_row(
			12,
			"Confirm entry taxes paid",
			"Finance",
			depends=11,
			finance=1,
			role="Finance Payment",
			payment_kind="ENTRY_SLIP",
		),
		_row(
			13,
			"Apply for post-clearance permits",
			"Declaration",
			depends=12,
			permit=1,
			role="Permit Application",
			permit_stage="Post-clearance",
		),
		_row(14, "Share documents to ground handling team", "Field Operations", depends=13, doc=1, role="Document"),
		_row(15, "Clearance - verification and permit removal", "Field Operations", depends=14),
		_row(16, "Release and entry settlement", "Operations", depends=15),
	]


def air_export_tasks() -> list[dict]:
	return [
		_row(1, "Receive documents from client", "Documentation", doc=1),
		_row(2, "Get origin and destination address", "Operations", depends=1),
		_row(3, "Check rates from airlines and select route", "Operations", depends=2),
		_row(4, "Generate airwaybill number", "Declaration", depends=3, doc=1),
		_row(5, "Do customs export entry", "Declaration", depends=4),
		_row(6, "Take package to airport and export processes", "Field Operations", depends=5),
		_row(7, "Weigh package and confirm dimensions", "Field Operations", depends=6),
		_row(8, "Book and pay freight and handling charges", "Finance", depends=7, finance=1),
		_row(9, "Hand over shipment to airline", "Field Operations", depends=8),
		_row(10, "Monitor flight departure", "Operations", depends=9),
		_row(11, "Obtain manifest and apply for COE", "Declaration", depends=10, doc=1),
	]


def sea_transit_import_tasks() -> list[dict]:
	"""Sea transit import from B/L through transit-country taxes to border delivery.

	Application ↔ Finance Payment pairs mirror Sea Import (shipping line + entry slip).
	Only finance rows use depends_on so ops can work other steps in parallel.
	"""
	return [
		_row(
			1,
			"Receive B/L and import documents",
			"Documentation",
			doc=1,
			role="Document Checkpoint",
			description="Collect the bill of lading and supporting import documents.",
		),
		_row(
			2,
			"Request shipping line charges from B/L",
			"Documentation",
			doc=1,
			role="Document",
			description="Use the B/L to obtain manifest, local charges, and the shipping line invoice.",
		),
		_row(
			3,
			"Attach shipping line invoice",
			"Documentation",
			doc=1,
			role="Application",
			payment_kind="Shipping Line",
			description="Attach the shipping line invoice for Finance verification and payment.",
		),
		_row(
			4,
			"Finance pays shipping line charges",
			"Finance",
			depends=3,
			finance=1,
			role="Finance Payment",
			payment_kind="Shipping Line",
		),
		_row(
			5,
			"Request delivery order",
			"Operations",
			doc=1,
			role="Document",
			description="Lodge and obtain the delivery order after shipping line charges are settled.",
		),
		_row(
			6,
			"Coordinate transit country tax assessment (Uganda/Tanzania)",
			"Declaration",
			description=(
				"Engage the destination-country team (Uganda, Tanzania, etc.) to assess "
				"transit taxes and share amounts for payment."
			),
		),
		_row(
			7,
			"Create transit entry - destination country team",
			"Declaration",
			doc=1,
			role="Application",
			payment_kind="ENTRY_SLIP",
			description=(
				"Destination-country team lodges the entry and shares the tax / entry slip "
				"for Finance payment."
			),
		),
		_row(
			8,
			"Finance pays transit entry taxes",
			"Finance",
			depends=7,
			finance=1,
			role="Finance Payment",
			payment_kind="ENTRY_SLIP",
		),
		_row(
			9,
			"Clear with transit customs (URA or destination country)",
			"Field Operations",
			description="Complete customs clearance with URA or the relevant destination-country authority.",
		),
		_row(10, "Obtain C2 and exit note", "Declaration", doc=1, role="Document"),
		_row(11, "Obtain KPA release order", "Field Operations"),
		_row(12, "Book trucks", "Transport"),
		_row(13, "Create delivery note", "Documentation", doc=1, role="Document"),
		_row(14, "Fit ECMD devices and dispatch trucks", "Transport"),
		_row(
			15,
			"Monitor to border and destination warehouse",
			"Transport",
		),
	]


def sea_transit_export_tasks() -> list[dict]:
	return [
		_row(1, "Receive booking and documents from client", "Operations", doc=1),
		_row(2, "Uganda side prepare entry and UBS permit", "Operations", depends=1),
		_row(3, "Kenya side prepare COC and EAC certificate", "Operations", depends=1, doc=1),
		_row(4, "Uganda side facilitates entry release", "Operations", depends=2),
		_row(5, "Goods depart Uganda toward Mombasa", "Transport", depends=4),
		_row(6, "Border crossing and Kenya entry", "Field Operations", depends=5),
		_row(7, "Goods arrive Mombasa stuffed into container", "Field Operations", depends=6),
		_row(8, "Lodge Kenya export entry", "Declaration", depends=7),
		_row(9, "KPA pre-advice and vessel sailing", "Finance", depends=8, finance=1),
		_row(10, "Receive Certificate of Export", "Operations", depends=9, doc=1),
	]


def road_transit_outbound_tasks() -> list[dict]:
	return [
		_row(1, "Receive invoice and packing list from client", "Documentation", doc=1),
		_row(2, "Apply for COC and EAC certificate", "Operations", depends=1),
		_row(3, "Finance pays COC and EAC fees", "Finance", depends=2, finance=1),
		_row(4, "Process destination country entry", "Declaration", depends=3, finance=1),
		_row(5, "Destination country releases entry", "Operations", depends=4),
		_row(6, "Transporter shares truck details", "Transport", depends=5),
		_row(7, "Generate exit note", "Declaration", depends=6),
		_row(8, "Obtain C2 document", "Declaration", depends=7),
		_row(9, "Fit ECMD devices and load trucks", "Transport", depends=8),
		_row(10, "Track Kenya to border to destination", "Transport", depends=9),
	]


def road_transit_inbound_tasks() -> list[dict]:
	"""Road transit inbound: Declaration applies → Finance pays (Sea/Air pattern).

	Book trucks and Obtain C2 are separate Transport / Declaration steps.
	"""
	return [
		_row(1, "Receive shipment documents", "Documentation", doc=1, role="Document"),
		_row(
			2,
			"IDF application (UCR)",
			"Declaration",
			depends=1,
			role="Application",
			payment_kind="UCR",
			required_docs="IDF_CERT",
		),
		_row(
			3,
			"Finance pays UCR",
			"Finance",
			depends=2,
			finance=1,
			role="Finance Payment",
			payment_kind="UCR",
		),
		_row(
			4,
			"Apply for pre-clearance permits",
			"Declaration",
			depends=3,
			permit=1,
			role="Permit Application",
			permit_stage="Pre-clearance",
		),
		_row(
			5,
			"Finance pays pre-clearance permits",
			"Finance",
			depends=4,
			finance=1,
			permit=1,
			role="Permit Finance",
			permit_stage="Pre-clearance",
			payment_kind="Permit",
		),
		_row(
			6,
			"Lodge border or ICD entry",
			"Declaration",
			depends=5,
			role="Application",
			payment_kind="ENTRY_SLIP",
		),
		_row(
			7,
			"Finance pays entry / taxes",
			"Finance",
			depends=6,
			finance=1,
			role="Finance Payment",
			payment_kind="ENTRY_SLIP",
		),
		_row(
			8,
			"Apply for post-clearance permits",
			"Declaration",
			depends=7,
			permit=1,
			role="Permit Application",
			permit_stage="Post-clearance",
		),
		_row(
			9,
			"Finance pays post-clearance permits",
			"Finance",
			depends=8,
			finance=1,
			permit=1,
			role="Permit Finance",
			permit_stage="Post-clearance",
			payment_kind="Permit",
		),
		_row(10, "Border and ICD clearance", "Field Operations", depends=9),
		_row(11, "Book trucks", "Transport", depends=10),
		_row(12, "Obtain C2", "Declaration", depends=11, doc=1, role="Document"),
		_row(13, "Monitor delivery to Kenya destination", "Transport", depends=12),
	]


def _gate(state: str, seq: int, rule: str = "Standard") -> dict:
	return {"shipment_workflow_state": state, "min_completed_task_seq": seq, "gate_rule": rule}


# Shipment Status Gates: the task whose completion reaches each status, in status
# chart order. Sea Import's are DEFAULT_SEA_WORKFLOW_TASK_GATES, next to its
# workflow states. Seeds only - sites edit them on the template.

# Air Import: proforma → UCR → permits → AWB/arrival → entry → release.
AIR_IMPORT_GATES: list[dict] = [
	_gate("Documents Received", 1),
	_gate("UCR Applied", 2),
	_gate("UCR Paid", 3),
	_gate("Pre-clearance", 5),
	_gate("Client Inspection", 7),
	_gate("Final Docs Received", 8),
	_gate("Entry Lodged", 10),
	_gate("Entry Paid", 12),
	_gate("Post-clearance", 13),
	_gate("Field Clearance", 15),
	_gate("Completed", 16),
]

# Air Export: client docs → AWB → export entry → airport → flight → COE.
AIR_EXPORT_GATES: list[dict] = [
	_gate("Documents Received", 1),
	_gate("Final Docs Received", 4),
	_gate("Entry Lodged", 5),
	_gate("Entry Paid", 8),
	_gate("In Transit", 10),
	_gate("Completed", 11),
]

# Sea Transit Import leaves out the Sea Import-only statuses (UCR, permits,
# client inspection).
SEA_TRANSIT_IMPORT_GATES: list[dict] = [
	_gate("Documents Received", 1),
	_gate("Line Paid & DO Lodged", 5),
	_gate("Entry Lodged", 7),
	_gate("Entry Paid", 8, "Entry Finance Complete"),
	_gate("Field Clearance", 9),
	_gate("Post-clearance", 10),
	_gate("KPA Paid", 11),
	_gate("In Delivery", 14),
	_gate("Completed", 15),
]

ROAD_TRANSIT_INBOUND_GATES: list[dict] = [
	_gate("Documents Received", 1),
	_gate("UCR Applied", 2),
	_gate("UCR Paid", 3),
	_gate("Pre-clearance", 5),
	_gate("Entry Lodged", 6),
	_gate("Entry Paid", 7),
	_gate("Post-clearance", 9),
	_gate("Field Clearance", 10),
	_gate("In Delivery", 12),
	_gate("Completed", 13),
]


TEMPLATE_DEFINITIONS: list[dict] = [
	{
		"template_name": SEA_IMPORT_TEMPLATE,
		"description": "Standard sea import clearance from document intake through container return.",
		"extends_template": None,
		"tasks": sea_import_tasks(),
		"gates": DEFAULT_SEA_WORKFLOW_TASK_GATES,
	},
	{
		"template_name": SEA_EXPORT_TEMPLATE,
		"description": "Sea export from booking through COE.",
		"extends_template": None,
		"tasks": sea_export_tasks(),
	},
	{
		"template_name": AIR_IMPORT_TEMPLATE,
		"description": "Air import from proforma through release.",
		"extends_template": None,
		"tasks": air_import_tasks(),
		"gates": AIR_IMPORT_GATES,
	},
	{
		"template_name": AIR_EXPORT_TEMPLATE,
		"description": "Air export from client documents through COE.",
		"extends_template": None,
		"tasks": air_export_tasks(),
		"gates": AIR_EXPORT_GATES,
	},
	{
		"template_name": SEA_TRANSIT_IMPORT_TEMPLATE,
		"description": (
			"Sea transit import: B/L and shipping line charges, transit-country entry "
			"and taxes, KPA release, then truck dispatch to border/warehouse."
		),
		"extends_template": None,
		"tasks": sea_transit_import_tasks(),
		"gates": SEA_TRANSIT_IMPORT_GATES,
	},
	{
		"template_name": SEA_TRANSIT_EXPORT_TEMPLATE,
		"description": "Uganda/Kenya transit export to Mombasa sailing.",
		"extends_template": None,
		"tasks": sea_transit_export_tasks(),
	},
	{
		"template_name": ROAD_TRANSIT_OUTBOUND_TEMPLATE,
		"description": "Road transit export from Kenya to destination.",
		"extends_template": None,
		"tasks": road_transit_outbound_tasks(),
	},
	{
		"template_name": ROAD_TRANSIT_INBOUND_TEMPLATE,
		"description": "Road transit import into Kenya.",
		"extends_template": None,
		"tasks": road_transit_inbound_tasks(),
		"gates": ROAD_TRANSIT_INBOUND_GATES,
	},
]

CONTAINER_TRACKER_MODES: list[dict] = [
	{"mode_name": "Mombasa Port", "description": "Import containers cleared and delivered from Mombasa port."},
	{"mode_name": "ICD Nairobi", "description": "Inland container depot clearance and delivery."},
	{"mode_name": "Transit Import", "description": "Import with transit legs after port clearance."},
	{"mode_name": "Transit Export", "description": "Export with transit legs before port sailing."},
	{"mode_name": "Export", "description": "Outbound export container tracking."},
]


def seed_container_tracker_modes() -> None:
	import frappe

	if not frappe.db.exists("DocType", "Container Tracker Mode"):
		return
	for row in CONTAINER_TRACKER_MODES:
		name = row["mode_name"]
		if frappe.db.exists("Container Tracker Mode", name):
			continue
		frappe.get_doc({"doctype": "Container Tracker Mode", **row}).insert(
			ignore_permissions=True
		)


def ensure_project_type(name: str) -> None:
	"""Create ERPNext Project Type when missing (Project.project_type is a Link field)."""
	import frappe

	if not name or not frappe.db.exists("DocType", "Project Type"):
		return
	if frappe.db.exists("Project Type", name):
		return
	frappe.get_doc({"doctype": "Project Type", "project_type": name}).insert(
		ignore_permissions=True
	)


def seed_project_types_from_tracker_modes() -> None:
	"""Align Project Type master with container tracker mode names used on Project."""
	for row in CONTAINER_TRACKER_MODES:
		ensure_project_type(row["mode_name"])


def seed_cgm_task_templates() -> None:
	"""Insert default templates when missing only — never overwrite site edits."""
	import frappe

	if not frappe.db.exists("DocType", "CGM Task Template"):
		return

	for definition in TEMPLATE_DEFINITIONS:
		name = definition["template_name"]
		if frappe.db.exists("CGM Task Template", name):
			continue

		doc = frappe.get_doc(
			{
				"doctype": "CGM Task Template",
				"template_name": name,
				"description": definition.get("description") or "",
				"is_active": 1,
				"extends_template": definition.get("extends_template"),
			}
		)
		for task in definition.get("tasks") or []:
			doc.append("tasks", task)
		for gate in definition.get("gates") or []:
			doc.append("gates", gate)
		doc.insert(ignore_permissions=True)


_BEHAVIOUR_FIELDS = (
	"task_role",
	"payment_kind",
	"permit_stage",
	"requires_finance_action",
	"requires_document_upload",
	"requires_permit_action",
	"is_auto_completable",
	"required_document_types",
)


def sync_template_behaviour_fields() -> int:
	"""Stamp Task Role / Payment Kind / Permit Stage onto existing template rows.

	Matches by sequence_no within each template's own tasks table (not the
	flattened extends plan). Does not change subjects or dependencies.
	"""
	import frappe

	if not frappe.db.exists("DocType", "CGM Task Template"):
		return 0
	meta = frappe.get_meta("CGM Task Template Item")
	if not meta.has_field("task_role"):
		return 0

	updated = 0
	for definition in TEMPLATE_DEFINITIONS:
		name = definition["template_name"]
		if not frappe.db.exists("CGM Task Template", name):
			continue
		seed_by_seq = {
			int(t["sequence_no"]): t for t in (definition.get("tasks") or []) if t.get("sequence_no")
		}
		if not seed_by_seq:
			continue
		doc = frappe.get_doc("CGM Task Template", name)
		changed = False
		for row in doc.get("tasks") or []:
			seed = seed_by_seq.get(int(row.sequence_no or 0))
			if not seed:
				continue
			for field in _BEHAVIOUR_FIELDS:
				if not meta.has_field(field):
					continue
				new_val = seed.get(field)
				if new_val is None or new_val == "":
					continue
				if row.get(field) != new_val:
					row.set(field, new_val)
					changed = True
		if changed:
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			updated += 1
		from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
			coerce_legacy_document_type_tokens,
			set_template_row_required_document_types_from_string,
		)

		docs_changed = False
		# Sync required docs from seed defaults (legacy labels coerced to master names).
		for row in doc.get("tasks") or []:
			seed = seed_by_seq.get(int(row.sequence_no or 0))
			want_raw = (seed or {}).get("required_document_types") or ""
			want_names = coerce_legacy_document_type_tokens(
				[t.strip() for t in want_raw.split(",") if t.strip()]
			)
			if not want_names:
				continue
			from cgm_shipping.cgm_worldwide_shipping.customizations.template_required_documents import (
				document_type_names_from_template_row,
			)

			if document_type_names_from_template_row(row) == want_names:
				continue
			set_template_row_required_document_types_from_string(row, want_raw)
			docs_changed = True
		if docs_changed:
			doc.flags.ignore_permissions = True
			doc.save(ignore_permissions=True)
			updated += 1
	return updated


def backfill_open_task_behaviour_from_templates() -> int:
	"""Copy template behaviour onto existing Tasks by flow_key + sequence_no."""
	import frappe

	from cgm_shipping.cgm_worldwide_shipping.customizations.task_behaviour import (
		ensure_task_behaviour_fields,
	)

	ensure_task_behaviour_fields()
	if not frappe.db.exists("DocType", "CGM Task Template"):
		return 0
	if not frappe.get_meta("Task").has_field("custom_task_role"):
		return 0

	flow_keys = frappe.get_all(
		"Task",
		filters={"custom_task_flow_key": ["!=", ""], "status": ["!=", "Cancelled"]},
		pluck="custom_task_flow_key",
		distinct=True,
	)
	updated = 0
	for flow_key in flow_keys:
		updated += sync_tasks_for_template(flow_key)
	return updated


def _subject_key(value) -> str:
	return " ".join((value or "").split()).lower()


def template_item_for_task(task_row, items: list[dict]) -> dict | None:
	"""The template row an existing Task came from, or None.

	Matched by subject when it is unique in the template, else by step number -
	but only if that row still has the task's subject. Matching by step alone
	re-stamped tasks with a neighbour's role whenever rows moved: PROJ-0035's
	"Taxes paid" became Permit Finance when the Road template grew from 9 to 13
	steps.
	"""
	key = _subject_key(task_row.get("subject"))
	if not key:
		return None
	same_subject = [item for item in items if _subject_key(item.get("subject")) == key]
	if len(same_subject) == 1:
		return same_subject[0]
	seq = int(task_row.get("custom_sequence_no") or 0)
	return next((item for item in same_subject if int(item.get("sequence_no") or 0) == seq), None)


def sync_tasks_for_template(template_name: str) -> int:
	"""Push template behaviour + required Task Documents onto open Tasks for one template."""
	import frappe

	from cgm_shipping.cgm_worldwide_shipping.customizations.task import (
		ensure_stamped_required_documents_saved,
		purge_unrequired_task_document_rows,
		seed_stamped_required_document_rows,
		sync_task_required_document_stamp,
	)
	from cgm_shipping.cgm_worldwide_shipping.task_engine import _collect_items

	if not template_name or not frappe.db.exists("CGM Task Template", template_name):
		return 0
	if not frappe.get_meta("Task").has_field("custom_task_role"):
		return 0

	template = frappe.get_doc("CGM Task Template", template_name)
	items = _collect_items(template)
	if not items:
		return 0

	tasks = frappe.get_all(
		"Task",
		filters={
			"custom_task_flow_key": template_name,
			"status": ["!=", "Cancelled"],
		},
		fields=["name", "subject", "custom_sequence_no", "custom_task_role"],
	)
	updated = 0
	has_container_step = frappe.get_meta("Task").has_field("custom_container_step")
	for task_row in tasks:
		item = template_item_for_task(task_row, items)
		if not item:
			continue
		role = (item.get("task_role") or "Standard").strip() or "Standard"
		want_kind = (item.get("payment_kind") or "").strip()
		want_doc_names = item.get("required_document_type_names") or []
		want_docs = ", ".join(want_doc_names)
		current = frappe.db.get_value(
			"Task",
			task_row.name,
			["custom_task_role", "custom_payment_kind", "custom_permit_stage", "custom_required_document_types"]
			+ (["custom_container_step"] if has_container_step else []),
			as_dict=True,
		) or {}
		want_stage = (item.get("permit_stage") or "").strip()
		want_step = (item.get("container_step") or "").strip() if has_container_step else ""
		current_role = (current.get("custom_task_role") or "").strip()
		current_kind = (current.get("custom_payment_kind") or "").strip()
		current_stage = (current.get("custom_permit_stage") or "").strip()
		current_docs = (current.get("custom_required_document_types") or "").strip()
		behaviour_changed = not (
			current_role
			and current_role == role
			and current_kind == want_kind
			and current_stage == want_stage
			and current_docs == want_docs
			and (current.get("custom_container_step") or "").strip() == want_step
		)
		if behaviour_changed:
			values = {
				"custom_task_role": role,
				"custom_requires_finance_action": 1 if item.get("requires_finance_action") else 0,
				"custom_requires_document_upload": 1 if item.get("requires_document_upload") else 0,
				"custom_requires_permit_action": 1 if item.get("requires_permit_action") else 0,
				"custom_is_auto_completable": 1 if item.get("is_auto_completable") else 0,
			}
			# Write blanks too: a kind or stage the row no longer carries must not
			# stay behind on a re-stamped task.
			values["custom_payment_kind"] = want_kind
			values["custom_permit_stage"] = want_stage
			if has_container_step:
				values["custom_container_step"] = want_step
			if frappe.get_meta("Task").has_field("custom_required_document_types"):
				values["custom_required_document_types"] = want_docs
			frappe.db.set_value("Task", task_row.name, values, update_modified=False)
			updated += 1

		task = frappe.get_doc("Task", task_row.name)
		sync_task_required_document_stamp(task)
		purge_unrequired_task_document_rows(task)
		if ensure_stamped_required_documents_saved(task):
			updated += 1
		elif seed_stamped_required_document_rows(task):
			updated += 1
	return updated


def link_shipment_types_to_templates() -> None:
	import frappe

	if not frappe.db.exists("DocType", "Shipment Type"):
		return

	st_meta = frappe.get_meta("Shipment Type")
	has_template = st_meta.has_field("task_template")
	has_mode = st_meta.has_field("container_tracker_mode")

	for st_name, template_name in SHIPMENT_TYPE_TEMPLATE_MAP.items():
		if not frappe.db.exists("Shipment Type", st_name):
			continue

		updates: dict = {}
		if has_template and template_name and frappe.db.exists("CGM Task Template", template_name):
			current = frappe.db.get_value("Shipment Type", st_name, "task_template")
			if not current:
				updates["task_template"] = template_name

		mode_name = SHIPMENT_TYPE_TRACKER_MODE_MAP.get(st_name)
		if has_mode and mode_name and frappe.db.exists("Container Tracker Mode", mode_name):
			current_mode = frappe.db.get_value("Shipment Type", st_name, "container_tracker_mode")
			if not current_mode or frappe.db.exists("Project Type", current_mode):
				updates["container_tracker_mode"] = mode_name

		if updates:
			frappe.db.set_value("Shipment Type", st_name, updates, update_modified=False)


def seed_task_workflow_masters() -> None:
	seed_container_tracker_modes()
	seed_project_types_from_tracker_modes()
	seed_cgm_task_templates()
	link_shipment_types_to_templates()
