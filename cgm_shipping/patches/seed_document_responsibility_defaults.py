"""One-time seed of CGM Role Groups + document responsibility defaults.

Editable site config — not re-applied on every migrate. Fresh installs also get
these via ``after_install`` → ``seed_document_responsibility_defaults``.

Safe to remove from patches.txt after all environments show this patch in
Patch Log (defaults already present; later Settings edits must stick).
"""

from __future__ import annotations


def execute():
	from cgm_shipping.default_seed_data import seed_document_responsibility_defaults

	seed_document_responsibility_defaults()
