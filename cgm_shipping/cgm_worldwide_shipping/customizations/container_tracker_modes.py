"""Seed the container tracking modes once, then leave them to the business.

These five were shipped as a Frappe *fixture*, and `sync_fixtures` does what its
own docstring says: "Import, **overwrite** fixtures". Every deploy rewrote all
five records. Measured on production, all five carried the same `modified`
timestamp to the millisecond - the moment of the last deploy - which is the
fingerprint of a fixture import rather than of anyone using the system.

Nothing visible had been lost, because nobody had edited them yet. But the first
time somebody deactivated a mode or corrected a description, the next deploy would
have put it back with no warning and no record of why.

A mode is reference data the business owns: which ones are in use is their call,
not the app's. So the app seeds what is missing and never touches what exists.
`docs/guides/patches.md` already states this preference - a fixture only when code
should own the whole record - and that is not the case here.

Called from `install.after_migrate`, so a fresh site still gets all five.
"""

import frappe

MODES = [
	{"mode_name": "Mombasa Port", "description": "Import containers cleared and delivered from Mombasa port."},
	{"mode_name": "ICD Nairobi", "description": "Inland container depot clearance and delivery."},
	{"mode_name": "Transit Import", "description": "Import with transit legs after port clearance."},
	{"mode_name": "Transit Export", "description": "Export with transit legs before port sailing."},
	{"mode_name": "Export", "description": "Outbound export container tracking."},
]


def ensure_container_tracker_modes() -> None:
	if not frappe.db.exists("DocType", "Container Tracker Mode"):
		return

	created = []
	for mode in MODES:
		if frappe.db.exists("Container Tracker Mode", mode["mode_name"]):
			# Already there. Whatever the business has done to it since - renamed
			# the description, switched it off - is theirs to keep.
			continue
		doc = frappe.new_doc("Container Tracker Mode")
		doc.update(mode)
		doc.is_active = 1
		doc.insert(ignore_permissions=True)
		created.append(mode["mode_name"])

	if created:
		frappe.db.commit()
		print(f"Created container tracking mode(s): {', '.join(created)}")
